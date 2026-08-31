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
    python corpus.py app <application_number>
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
    con = duckdb.connect(str(find_corpus()), read_only=read_only)
    # Long portfolio queries otherwise emit an ASCII progress bar onto stdout, which
    # corrupts the JSON this skill is meant to hand back.
    con.execute("SET enable_progress_bar = false")
    return con


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


# ------------------------------------------------------------------------------- applicant
# Company-level work reads applicant_organization directly. It deliberately does NOT
# use app_company / cohort / app_facts: those are site-era derived tables frozen at 20
# companies and filing years 2013-2019, and they look like a general company index
# without being one. The underlying corpus covers every applicant.
#
# Default floor is 2012 because USPTO only began recording applicant organisation
# systematically after the AIA - coverage is ~0% before 2012, 65% in 2013, ~90% from
# 2015. Anything earlier is not a smaller portfolio, it is an unrecorded one.
APPLICANT_FLOOR_YEAR = 2012

# The corpus's last record is dated 2023-06-01, but that is NOT where it stops being
# complete. PatEx carries published applications, so an application filed less than
# ~18 months before the snapshot had not published and is simply absent. Measured
# utility filings per quarter, against a full quarter of ~105,000:
#   2021-Q4 101,430 (full)   2022-Q1 86,384 (79%)   2022-Q3 81,256 (74%)
#   2022-Q4  62,828 (57%)    2023-Q1 14,664 (13%)   2023-Q2    307 (0.3%)
# Quoting a portfolio as current up to June 2023 therefore overstates coverage badly.
# Anything filed after CORPUS_COMPLETE_THROUGH needs an ODP top-up to be trusted.
CORPUS_LAST_RECORD = "2023-06-01"
CORPUS_COMPLETE_THROUGH = "2021-12-31"
CORPUS_NEGLIGIBLE_AFTER = "2022-12-31"

def _rule_event_codes() -> list[str]:
    """Every event code the rules read, taken FROM the rules module.

    The transactions table holds 507M rows, so a portfolio pull has to filter to the
    codes that matter. Deriving the list here rather than restating it means a new rule
    cannot silently go blind: the first version of this list was written before the
    revival rule existed, so E1 could only ever fire on ODP data and read N/A for every
    corpus record - a clean bill of health that had simply never been checked.
    """
    import rules as _r

    codes: set[str] = set()
    for name in dir(_r):
        if name.endswith("_CODES"):
            value = getattr(_r, name)
            if isinstance(value, (set, frozenset, tuple, list)):
                codes |= {c for c in value if isinstance(c, str)}
    return sorted(codes)


RULE_EVENT_CODES = _rule_event_codes()

_NORM_SQL = (
    "trim(regexp_replace(regexp_replace(upper({col}), '[^A-Z0-9 ]', ' ', 'g'), ' +', ' ', 'g'))"
)


def _applicant_scope_cte(utility_only: bool) -> str:
    """Applications belonging to any of a set of normalised applicant names.

    Matched against every applicant on the application, not just the first, so joint
    filings are captured for both filers.
    """
    norm = _NORM_SQL.format(col="ap.applicant_organization")
    return f"""
        SELECT DISTINCT a.application_number, {norm} AS matched_name
        FROM all_applicants ap
        JOIN application_data a USING (application_number)
        WHERE list_contains(?::VARCHAR[], {norm})
          AND EXTRACT(YEAR FROM a.filing_date) >= ?
          {"AND a.application_invention_type = 'Utility'" if utility_only else ""}
    """


SCOPE_TABLE = "entity_scope"


def materialise_scope(con, names: list[str], since: int = APPLICANT_FLOOR_YEAR,
                      utility_only: bool = True) -> int:
    """Resolve an entity's applications into a temp table once, and reuse it.

    Every query below would otherwise re-run the applicant join over all_applicants
    (6.7M rows) against application_data (14.1M). Materialising once takes a
    3,000-application portfolio from 11s to about 4s, and the saving grows with the
    number of questions asked of the same scope.
    """
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {SCOPE_TABLE} AS {_applicant_scope_cte(utility_only)}",
        [names, since],
    )
    return con.execute(f"SELECT COUNT(*) FROM {SCOPE_TABLE}").fetchone()[0]


def applicant_baseline(con, names: list[str], since: int = APPLICANT_FLOOR_YEAR,
                       utility_only: bool = True, scoped: bool = False) -> dict:
    """Allowance rate, pendency and action statistics for one resolved entity.

    Pass scoped=True when materialise_scope() has already been called for these names.
    """
    if not names:
        return {"applications": 0, "names": 0}
    if not scoped:
        materialise_scope(con, names, since, utility_only)

    rows = _rows(
        con,
        f"""
        SELECT {_BASELINE_SELECT}
        FROM application_data
        WHERE application_number IN (SELECT application_number FROM {SCOPE_TABLE})
        """,
    )
    out = rows[0] if rows else {"applications": 0}
    if out.get("applications"):
        out.update(_action_stats(
            con,
            f"a.application_number IN (SELECT application_number FROM {SCOPE_TABLE})",
            [since],
        ))
    out["names"] = len(names)
    out["since"] = since
    return out


def applicant_applications(con, names: list[str], since: int = APPLICANT_FLOOR_YEAR,
                           utility_only: bool = True, scoped: bool = False) -> list[dict]:
    """Every application of a resolved entity, shaped for rules.from_corpus().

    Three bulk queries - applications, rule-relevant events, children - assembled in
    Python, rather than the three-queries-per-application that application_facts()
    does. A 13,000-application portfolio would otherwise be 39,000 round trips.
    """
    if not names:
        return []
    if not scoped:
        materialise_scope(con, names, since, utility_only)

    apps = _rows(
        con,
        f"""
        SELECT a.application_number, a.filing_date, a.patent_number, a.patent_issue_date,
               a.appl_status_desc, a.appl_status_date, a.examiner_full_name,
               a.examiner_art_unit, a.uspc_class, a.invention_title,
               a.application_invention_type,
               ANY_VALUE(s.matched_name) AS matched_applicant_name
        FROM application_data a
        JOIN {SCOPE_TABLE} s USING (application_number)
        GROUP BY ALL
        ORDER BY a.filing_date
        """,
    )
    if not apps:
        return []

    by_app = {r["application_number"]: r for r in apps}
    for r in apps:
        r["events"] = []
        r["children"] = []

    # Both follow-up queries JOIN the materialised scope rather than passing the
    # application numbers back in as a list. A list membership test against the
    # 507M-row transactions table is a linear scan; as a join DuckDB hash-joins
    # against the small scope set. Measured on a 3,000-application portfolio: 45s
    # down to a couple of seconds.
    for ev in _rows(
        con,
        f"""
        SELECT t.application_number, t.event_code, t.recorded_date
        FROM transactions t
        JOIN {SCOPE_TABLE} s USING (application_number)
        WHERE list_contains(?::VARCHAR[], t.event_code)
        """,
        [RULE_EVENT_CODES],
    ):
        by_app[ev["application_number"]]["events"].append(ev)

    # continuation_type lives on the CHILD's row in continuity_parents, pointing at its
    # parent, so children of X are rows WHERE parent_application_number = X. Reversing
    # this returns silently empty results rather than an error.
    for ch in _rows(
        con,
        f"""
        SELECT cp.parent_application_number AS parent,
               cp.application_number        AS child,
               cp.continuation_type,
               cc.child_filing_date
        FROM continuity_parents cp
        JOIN {SCOPE_TABLE} s ON s.application_number = cp.parent_application_number
        LEFT JOIN continuity_children cc
               ON cc.application_number       = cp.parent_application_number
              AND cc.child_application_number = cp.application_number
        """,
    ):
        by_app[ch["parent"]]["children"].append(ch)

    return apps


def applicant_context(con, since: int = APPLICANT_FLOOR_YEAR) -> dict:
    """Confounders needed to read an entity's numbers honestly. Requires a
    materialised scope.

    National-stage share matters because foreign-origin filers use continuations far
    less as a matter of house style, so a high A1 rate for them reflects filing
    culture rather than a lapse. Technology-centre mix matters because restriction
    rate tracks technology, not practice - semiconductor and display filers run
    20-40%, software and communications filers 4-7%.
    """
    ns = _rows(
        con,
        f"""
        SELECT COUNT(*) AS applications,
               COUNT(*) FILTER (WHERE r.is_national_stage) AS national_stage,
               ROUND(100.0 * COUNT(*) FILTER (WHERE r.is_national_stage)
                     / NULLIF(COUNT(*), 0), 1) AS national_stage_share
        FROM {SCOPE_TABLE} s
        LEFT JOIN route r USING (application_number)
        """,
    )
    centres = _rows(
        con,
        f"""
        SELECT left(a.examiner_art_unit, 2) AS tech_center,
               COUNT(*)                     AS applications
        FROM application_data a
        JOIN {SCOPE_TABLE} s USING (application_number)
        -- Numeric art units only. Administrative units such as OPLA truncate to a
        -- meaningless "OP" tech centre and are not a technology signal.
        WHERE a.examiner_art_unit IS NOT NULL
          AND regexp_matches(a.examiner_art_unit, '^[0-9]{{4}}')
        GROUP BY 1 ORDER BY applications DESC LIMIT 6
        """,
    )
    years = _rows(
        con,
        f"""
        SELECT EXTRACT(YEAR FROM a.filing_date)::INT AS filing_year,
               COUNT(*)                              AS applications,
               ROUND(100.0 * COUNT(*) FILTER (WHERE {GRANTED})
                     / NULLIF(COUNT(*) FILTER (WHERE ({GRANTED}) OR ({ABANDONED})), 0), 1)
                                                     AS allowance_rate
        FROM application_data a
        JOIN {SCOPE_TABLE} s USING (application_number)
        GROUP BY 1 ORDER BY 1
        """,
    )
    out = ns[0] if ns else {}
    out["tech_centers"] = centres
    out["by_filing_year"] = years
    return out


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
