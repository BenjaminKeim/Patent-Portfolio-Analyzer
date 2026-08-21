"""Prosecution audit CLI for the patent-portfolio-analyzer skill.

Routes each request to whichever source is right for it:

  --source corpus   local PatEx DuckDB. Free, instant, no key, but frozen at June 2023.
                    Use for portfolio sweeps and anything historical.
  --source odp      live USPTO ODP with Ben's key. Current, but rate-limited.
                    Use for specific cases, recent filings, anything post-2023.
  --source auto     (default) corpus first; fall back to ODP when the application is
                    absent from the snapshot, which usually means it is newer.

Usage:
    python audit.py app 14973095
    python audit.py app 18759963 --source odp
    python audit.py apps 14973095 15162264 16039495
    python audit.py search "applicationMetaData.firstApplicantName:Microsoft*" --limit 50
    python audit.py doctor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rules  # noqa: E402

# Application-type codes with no prosecution history to audit. Provisionals are never
# examined; designs, plants and reissues follow different procedures and would distort
# allowance-rate and office-action statistics.
EXCLUDED_APP_TYPES = {"PROVSNL", "DESIGN", "PLANT", "REISSUE", "SIR", "PCT"}


def _corpus_facts(app_number: str):
    import corpus
    con = corpus.connect()
    try:
        row = corpus.application_facts(con, app_number)
    finally:
        con.close()
    if not row.get("found"):
        return None
    return rules.from_corpus(row)


def _odp_facts(app_number: str, with_children: bool = True):
    import odp_client
    data = odp_client.application(app_number)
    bag = data.get("patentFileWrapperDataBag") or []
    if not bag:
        return None
    children = None
    if with_children:
        try:
            cont = odp_client.continuity(app_number)
            cbag = (cont.get("patentFileWrapperDataBag") or [{}])[0]
            children = cbag.get("childContinuityBag") or []
        except odp_client.ODPError:
            children = None
    return rules.from_odp(bag[0], children)


def audit_one(app_number: str, source: str = "auto") -> dict:
    facts = None
    if source in ("corpus", "auto"):
        try:
            facts = _corpus_facts(app_number)
        except Exception as exc:  # corpus missing or unreadable
            if source == "corpus":
                return {"application": app_number, "error": str(exc)}
    if facts is None and source in ("odp", "auto"):
        try:
            facts = _odp_facts(app_number)
        except Exception as exc:
            return {"application": app_number, "error": str(exc)}
    if facts is None:
        return {"application": app_number, "error": "not found in corpus or ODP"}
    return rules.summarise(facts, rules.evaluate(facts))


def _norm_name(s: str | None) -> str:
    """Uppercase, strip punctuation, collapse whitespace - same normalisation the
    corpus disambiguation uses, so applicant names compare consistently."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())).strip()


def audit_search(query: str, limit: int, confirm_children: bool,
                 applicant: str | None = None, utility_only: bool = True) -> dict:
    """Screen a set of applications with one search call, then confirm candidates.

    Search results carry events but not children, so absence-based rules come back
    INDETERMINATE. Only applications that could still flag get a follow-up continuity
    call - screening in bulk and confirming selectively keeps the call count low.

    POST-FILTERING IS NOT OPTIONAL FOR PORTFOLIO WORK. ODP tokenises the applicant
    query, so `firstApplicantName:Taiwan Semiconductor*` also returns Micron, Sony
    and every other applicant whose name contains "Semiconductor". Pass --applicant
    to keep only records whose applicant name actually contains that phrase. Search
    also returns provisionals and other non-utility types, which have no prosecution
    to audit; utility_only drops them.
    """
    import odp_client
    data = odp_client.search(query, limit=limit)
    wrappers = data.get("patentFileWrapperDataBag") or []
    total = data.get("count")

    dropped = {"applicant_mismatch": [], "not_utility": []}
    kept = []
    want = _norm_name(applicant) if applicant else None
    for w in wrappers:
        meta = w.get("applicationMetaData") or {}
        app_no = str(w.get("applicationNumberText"))
        if utility_only:
            # ODP codes utility applications as REGULAR, not "Utility". Exclude the
            # types that have no examination history worth auditing rather than
            # allow-listing, so an unfamiliar code is kept and visible rather than
            # silently dropped.
            cat = (meta.get("applicationTypeCategory") or "").strip().upper()
            if cat in EXCLUDED_APP_TYPES:
                label = meta.get("applicationTypeLabelName") or cat
                dropped["not_utility"].append({"application": app_no, "type": label})
                continue
        if want:
            got = _norm_name(meta.get("firstApplicantName"))
            if want not in got:
                dropped["applicant_mismatch"].append(
                    {"application": app_no, "applicant": meta.get("firstApplicantName")})
                continue
        kept.append(w)
    wrappers = kept

    results, confirmed = [], 0
    for w in wrappers:
        facts = rules.from_odp(w, children=None)
        flags = rules.evaluate(facts)
        needs_children = any(
            flags[r]["state"] == "INDETERMINATE" and flags[r]["detail"] == "children not fetched"
            for r in ("A1", "B1", "B2")
        )
        if confirm_children and needs_children:
            try:
                cont = odp_client.continuity(facts.application)
                cbag = (cont.get("patentFileWrapperDataBag") or [{}])[0]
                facts = rules.from_odp(w, cbag.get("childContinuityBag") or [])
                flags = rules.evaluate(facts)
                confirmed += 1
            except odp_client.ODPError:
                pass
        results.append(rules.summarise(facts, flags))

    tallies: dict[str, dict[str, int]] = {}
    for r in results:
        for rule, v in r["flags"].items():
            tallies.setdefault(rule, {}).setdefault(v["state"], 0)
            tallies[rule][v["state"]] += 1

    return {
        "query": query,
        "applicant_filter": applicant,
        "matching_total": total,
        "returned_by_search": len(wrappers) + len(dropped["applicant_mismatch"]) + len(dropped["not_utility"]),
        "dropped_applicant_mismatch": len(dropped["applicant_mismatch"]),
        "dropped_not_utility": len(dropped["not_utility"]),
        "examined": len(results),
        "continuity_calls": confirmed,
        "tallies": tallies,
        "dropped_detail": dropped,
        "flagged": [r for r in results if r["flagged"]],
        "results": results,
    }


def doctor() -> dict:
    out: dict = {}
    try:
        import corpus
        out["corpus"] = corpus.doctor()
    except Exception as exc:
        out["corpus"] = {"error": str(exc)}
    try:
        import odp_client
        out["odp"] = odp_client.doctor()
    except Exception as exc:
        out["odp"] = {"error": str(exc)}
    return out


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(description="Audit patent prosecution for unexercised options.")
    sub = p.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("app", help="audit a single application")
    one.add_argument("application_number")
    one.add_argument("--source", choices=["auto", "corpus", "odp"], default="auto")

    many = sub.add_parser("apps", help="audit several applications")
    many.add_argument("application_numbers", nargs="+")
    many.add_argument("--source", choices=["auto", "corpus", "odp"], default="auto")

    srch = sub.add_parser("search", help="screen an ODP search result set")
    srch.add_argument("query")
    srch.add_argument("--limit", type=int, default=25)
    srch.add_argument("--applicant",
                      help="post-filter to records whose applicant name contains this. "
                           "Strongly recommended: ODP tokenises the query, so searching "
                           "'Taiwan Semiconductor*' also returns Micron and Sony.")
    srch.add_argument("--include-non-utility", action="store_true",
                      help="keep provisionals and other non-utility types (dropped by default)")
    srch.add_argument("--no-confirm", action="store_true",
                      help="skip per-candidate continuity calls (faster, leaves rules INDETERMINATE)")

    sub.add_parser("doctor", help="check corpus and ODP availability")
    args = p.parse_args()

    if args.cmd == "doctor":
        _print(doctor())
    elif args.cmd == "app":
        _print(audit_one(args.application_number, args.source))
    elif args.cmd == "apps":
        _print([audit_one(a, args.source) for a in args.application_numbers])
    else:
        _print(audit_search(args.query, args.limit, not args.no_confirm,
                            applicant=args.applicant,
                            utility_only=not args.include_non_utility))


if __name__ == "__main__":
    main()
