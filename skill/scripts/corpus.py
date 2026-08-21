"""Local PatEx corpus access for the patent-portfolio-analyzer skill.

Wraps the DuckDB database built from the USPTO Patent Examination Research Dataset
(PatEx, 2022 release / PEDS pull June 2023): 14.1M applications and 507M prosecution
transactions. Everything here is offline and needs no API key.

The corpus is frozen at June 2023. For anything filed or decided after that, use the
ODP client instead - see odp_client.py. Baselines (examiner behaviour, art-unit norms)
come from here because they need volume, not currency.

Usage:
    python corpus.py examiner "SMITH, JOHN A"
    python corpus.py artunit 2131
    python corpus.py app 14973095
    python corpus.py doctor
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:  # pragma: no cover - dependency guidance
    sys.exit(
        "duckdb is not installed. Run:  pip install duckdb\n"
        "(the skill's requirements.txt pins it)"
    )

# Where the corpus lives, most specific first. The repo-relative path is resolved from
# this file, so it works wherever the repo is cloned - including through the junction
# at ~/.claude/skills/patent-portfolio-analyzer, which the OS resolves before Python
# sees the path. PATEX_DUCKDB overrides everything.
_SKILL_ROOT = Path(__file__).resolve().parent.parent   # <repo>/skill
_REPO_ROOT = _SKILL_ROOT.parent                        # <repo>

DEFAULT_CORPUS_PATHS = [
    Path(os.environ["PATEX_DUCKDB"]) if os.environ.get("PATEX_DUCKDB") else None,
    _REPO_ROOT / "data" / "patex.duckdb",
    Path.home() / "source" / "repos" / "Patent-Portfolio-Analyzer" / "data" / "patex.duckdb",
    Path.home() / ".claude" / "data" / "patex.duckdb",
]

# Prosecution event codes. Verified present in the corpus event_codes table.
EVENTS = {
    "rejection": ("CTNF", "CTFR"),
    "restriction": ("CTRS",),
    "allowance": ("MN/=.",),
    "rce": ("RCEX",),
    "interview": ("EXIN", "EXAC", "EXAT", "EXET"),
    "appeal": ("N/AP",),
    "fai_pilot": ("FAIA", "FAOO"),
}

GRANTED = "appl_status_desc LIKE 'Patented Case%' OR appl_status_desc LIKE 'Patent Expired Due to NonPayment%'"
ABANDONED = "appl_status_desc LIKE '%bandoned%'"


class CorpusUnavailable(RuntimeError):
    """Raised when the local PatEx database cannot be found."""


def find_corpus() -> Path:
    for candidate in DEFAULT_CORPUS_PATHS:
        if candidate and candidate.exists():
            return candidate
    raise CorpusUnavailable(
        "Local PatEx corpus not found. Set PATEX_DUCKDB to the .duckdb path, or see "
        "the skill README for how to build it. Falling back to ODP-only mode is fine "
        "for single-case work but cannot produce baselines."
    )


def connect(read_only: bool = True) -> "duckdb.DuckDBPyConnection":
    return duckdb.connect(str(find_corpus()), read_only=read_only)


def _rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# --------------------------------------------------------------------------- baselines
_BASELINE_SELECT = f"""
    COUNT(*)                                                        AS applications,
    COUNT(*) FILTER (WHERE {GRANTED})                               AS granted,
    COUNT(*) FILTER (WHERE {ABANDONED})                             AS abandoned,
    ROUND(100.0 * COUNT(*) FILTER (WHERE {GRANTED})
          / NULLIF(COUNT(*) FILTER (WHERE ({GRANTED}) OR ({ABANDONED})), 0), 1)
                                                                    AS allowance_rate,
    ROUND(median(CASE WHEN ({GRANTED}) AND patent_issue_date IS NOT NULL
                 THEN datediff('month', filing_date, patent_issue_date) END), 1)
                                                                    AS median_months_to_issue
"""


def examiner_baseline(con, examiner: str, since: int = 2010) -> dict:
    """Allowance rate, pendency and action counts for one examiner, with art-unit context.

    Examiner names in PatEx are stored as 'LAST, FIRST MIDDLE'. Matching is
    case-insensitive and prefix-based so a surname alone still works.
    """
    base = _rows(
        con,
        f"""
        SELECT examiner_full_name AS examiner,
               ANY_VALUE(examiner_art_unit) AS art_unit,
               {_BASELINE_SELECT}
        FROM application_data
        WHERE application_invention_type = 'Utility'
          AND EXTRACT(YEAR FROM filing_date) >= ?
          AND upper(examiner_full_name) LIKE upper(?) || '%'
        GROUP BY examiner_full_name
        ORDER BY applications DESC
        LIMIT 10
        """,
        [since, examiner],
    )
    if not base:
        return {"examiner": examiner, "found": False}

    top = base[0]
    events = _action_stats(con, "upper(a.examiner_full_name) LIKE upper(?) || '%'",
                           [since, top["examiner"]])
    top.update(events)
    top["found"] = True
    top["also_matched"] = [b["examiner"] for b in base[1:]]

    if top.get("art_unit"):
        top["art_unit_context"] = art_unit_baseline(con, top["art_unit"], since=since)
    return top


def art_unit_baseline(con, art_unit: str | int, since: int = 2010) -> dict:
    au = str(art_unit)
    rows = _rows(
        con,
        f"""
        SELECT ? AS art_unit, {_BASELINE_SELECT}
        FROM application_data
        WHERE application_invention_type = 'Utility'
          AND EXTRACT(YEAR FROM filing_date) >= ?
          AND examiner_art_unit = ?
        """,
        [au, since, au],
    )
    out = rows[0] if rows else {"art_unit": au, "applications": 0}
    if out.get("applications"):
        out.update(_action_stats(con, "a.examiner_art_unit = ?", [since, au]))
    return out


def _action_stats(con, where: str, params: list) -> dict:
    """Mean office actions / RCEs, restriction and interview rates for a filtered set.

    Joined against transactions, so this is the expensive half; the caller decides
    whether the filter is narrow enough to be worth it.
    """
    rows = _rows(
        con,
        f"""
        WITH scope AS (
            SELECT a.application_number
            FROM application_data a
            WHERE a.application_invention_type = 'Utility'
              AND EXTRACT(YEAR FROM a.filing_date) >= ?
              AND {where}
        ),
        ev AS (
            SELECT t.application_number,
                   COUNT(*) FILTER (WHERE t.event_code IN ('CTNF','CTFR')) AS office_actions,
                   COUNT(*) FILTER (WHERE t.event_code = 'RCEX')           AS rces,
                   COUNT(*) FILTER (WHERE t.event_code = 'CTRS') > 0       AS restricted,
                   COUNT(*) FILTER (WHERE t.event_code IN ('EXIN','EXAC','EXAT','EXET')) > 0
                                                                           AS interviewed
            FROM transactions t JOIN scope s USING (application_number)
            GROUP BY 1
        )
        SELECT ROUND(AVG(office_actions), 2)                       AS mean_office_actions,
               ROUND(AVG(rces), 2)                                 AS mean_rces,
               ROUND(100.0 * AVG(CASE WHEN restricted THEN 1 ELSE 0 END), 1)  AS restriction_rate,
               ROUND(100.0 * AVG(CASE WHEN interviewed THEN 1 ELSE 0 END), 1) AS interview_rate
        FROM ev
        """,
        params,
    )
    return rows[0] if rows else {}


# --------------------------------------------------------------------------- single application
def application_facts(con, app_number: str) -> dict:
    """Everything the corpus knows about one application, including its children.

    Children are read from continuity_parents (which carries continuation_type on the
    CHILD's row pointing at its parent) joined to continuity_children for the filing
    date. That join direction is easy to get backwards and produces silently empty
    results if reversed.
    """
    app = _rows(
        con,
        """
        SELECT application_number, filing_date, patent_number, patent_issue_date,
               appl_status_desc, appl_status_date, examiner_full_name, examiner_art_unit,
               uspc_class, invention_title, application_invention_type
        FROM application_data WHERE application_number = ?
        """,
        [app_number],
    )
    if not app:
        return {"application_number": app_number, "found": False}
    out = app[0]
    out["found"] = True

    out["events"] = _rows(
        con,
        """
        SELECT t.event_code, t.recorded_date, ANY_VALUE(e.event_desc) AS description
        FROM transactions t
        LEFT JOIN event_codes e ON e.event_cd = t.event_code
        WHERE t.application_number = ?
        GROUP BY t.event_code, t.recorded_date
        ORDER BY t.recorded_date
        """,
        [app_number],
    )

    out["children"] = _rows(
        con,
        """
        SELECT cp.application_number AS child, cp.continuation_type, cc.child_filing_date
        FROM continuity_parents cp
        LEFT JOIN continuity_children cc
               ON cc.application_number       = cp.parent_application_number
              AND cc.child_application_number = cp.application_number
        WHERE cp.parent_application_number = ?
        ORDER BY cc.child_filing_date
        """,
        [app_number],
    )

    out["parents"] = _rows(
        con,
        """
        SELECT parent_application_number AS parent, continuation_type, parent_filing_date
        FROM continuity_parents WHERE application_number = ?
        """,
        [app_number],
    )
    return out


def doctor() -> dict:
    """Report corpus availability and size. Safe to run first."""
    try:
        path = find_corpus()
    except CorpusUnavailable as exc:
        return {"corpus": "unavailable", "detail": str(exc)}
    con = duckdb.connect(str(path), read_only=True)
    counts = _rows(
        con,
        """
        SELECT 'applications' AS table, COUNT(*) AS rows FROM application_data
        UNION ALL SELECT 'transactions', COUNT(*) FROM transactions
        UNION ALL SELECT 'continuity_parents', COUNT(*) FROM continuity_parents
        """,
    )
    con.close()
    return {
        "corpus": str(path),
        "size_gb": round(path.stat().st_size / 1024**3, 2),
        "counts": {c["table"]: c["rows"] for c in counts},
        "frozen_at": "2023-06 (PatEx 2022 release)",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Query the local PatEx corpus.")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("examiner"); e.add_argument("name"); e.add_argument("--since", type=int, default=2010)
    a = sub.add_parser("artunit"); a.add_argument("art_unit"); a.add_argument("--since", type=int, default=2010)
    s = sub.add_parser("app"); s.add_argument("application_number")
    sub.add_parser("doctor")
    args = p.parse_args()

    if args.cmd == "doctor":
        print(json.dumps(doctor(), indent=2, default=str)); return

    con = connect()
    try:
        if args.cmd == "examiner":
            out = examiner_baseline(con, args.name, since=args.since)
        elif args.cmd == "artunit":
            out = art_unit_baseline(con, args.art_unit, since=args.since)
        else:
            out = application_facts(con, args.application_number)
    finally:
        con.close()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
