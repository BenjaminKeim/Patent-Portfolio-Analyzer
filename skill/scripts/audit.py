"""Prosecution audit CLI for the patent-portfolio-analyzer skill.

Routes each request to whichever source is right for it:

  --source corpus   local PatEx DuckDB. Free, instant, no key, but frozen at June 2023.
                    Use for portfolio sweeps and anything historical.
  --source odp      live USPTO ODP with Ben's key. Current, but rate-limited.
                    Use for specific cases, recent filings, anything post-2023.
  --source auto     (default) corpus first; fall back to ODP when the application is
                    absent from the snapshot, which usually means it is newer.

Portfolio work starts with `resolve`. It turns a company name into an explicit,
inspectable set of applicant names under strict filer identity, and reports what it
left out. Pass the same name to `search --entity` to scope a result set with it.

Usage:
    python audit.py resolve "Microsoft Corporation"
    python audit.py app 14973095
    python audit.py app 18759963 --source odp
    python audit.py apps 14973095 15162264 16039495
    python audit.py search "applicationMetaData.firstApplicantName:Microsoft*" \
        --entity "Microsoft Corporation" --limit 50
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


def _applicant_names(meta: dict) -> list[str | None]:
    """Every applicant on the record, not just the first.

    Joint filings are real and large - Hyundai and Kia co-file 5,879 applications
    (CONTEXT.md). Reading only firstApplicantName drops all of them from the second
    filer's audit.
    """
    bag = meta.get("applicantBag") or []
    names = [a.get("applicantNameText") for a in bag if isinstance(a, dict)]
    first = meta.get("firstApplicantName")
    if first and first not in names:
        names.append(first)
    return names


def audit_search(query: str, limit: int, confirm_children: bool,
                 entity_name: str | None = None, utility_only: bool = True) -> dict:
    """Screen a set of applications with one search call, then confirm candidates.

    Search results carry events but not children, so absence-based rules come back
    INDETERMINATE. Only applications that could still flag get a follow-up continuity
    call - screening in bulk and confirming selectively keeps the call count low.

    SCOPING IS NOT OPTIONAL FOR PORTFOLIO WORK. ODP tokenises the applicant query, so
    `firstApplicantName:Taiwan Semiconductor*` also returns Micron, Sony and every
    other applicant whose name contains "Semiconductor" - 15 of 20 results on a real
    run. Pass --entity to scope the result set with entity.Matcher, which resolves the
    name against the corpus and applies token-boundary rules to every applicant on
    each record. Search also returns provisionals and other non-utility types, which
    have no prosecution to audit; utility_only drops them.
    """
    import odp_client
    data = odp_client.search(query, limit=limit)
    wrappers = data.get("patentFileWrapperDataBag") or []
    total = data.get("count")

    matcher = None
    if entity_name:
        import entity
        matcher = entity.Matcher(entity_name)

    dropped: dict[str, list] = {"applicant_mismatch": [], "not_utility": []}
    kept = []
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
        if matcher:
            ok, why = matcher.match_application(_applicant_names(meta))
            if not ok:
                dropped["applicant_mismatch"].append({
                    "application": app_no,
                    "applicant": meta.get("firstApplicantName"),
                    "reason": why,
                })
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

    scope: dict | None = None
    if matcher is not None:
        m = matcher.manifest
        scope = {
            "entity": matcher.entity,
            "policy": "strict filer identity",
            "resolved_from_corpus": m is not None,
            "in_scope_names": len(matcher.in_scope),
            "uncertain_names_excluded": (m or {}).get("uncertain_names", 0),
            "uncertain_applications_excluded": (m or {}).get("uncertain_applications", 0),
            "related_entity_names_excluded": (m or {}).get("related_entity_names", 0),
            "warnings": (m or {}).get("warnings", []),
        }

    return {
        "query": query,
        "entity": entity_name,
        "scope": scope,
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


def portfolio(entity_name: str, since: int | None = None, flagged_limit: int = 25,
              utility_only: bool = True, topup: str = "auto",
              auto_seconds: int = 15) -> dict:
    """Whole-portfolio prosecution profile for one entity, from the corpus.

    Reads applicant_organization directly, so it works for ANY company - not only the
    20 in the site-era app_company table. Every application is evaluated by the same
    rules used for a single-application audit, so a portfolio figure and a case-level
    figure can never disagree.

    The corpus ends June 2023, and the three-state logic uses a stricter June 2022
    horizon so that a case disposed too recently reports INDETERMINATE rather than
    FLAG. Newer filings need an ODP top-up; the coverage block says exactly where
    this account stops.
    """
    import corpus
    import entity

    since = since or corpus.APPLICANT_FLOOR_YEAR
    con = corpus.connect()
    try:
        manifest = entity.resolve(entity_name, con=con)
        names = sorted(c["name"] for c in manifest["in_scope"])
        if not names:
            return {
                "entity": entity_name,
                "resolved": False,
                "scope": manifest,
                "note": "No applicant name in the corpus resolves to this entity. "
                        "It may post-date the corpus (June 2023) - try ODP.",
            }

        corpus.materialise_scope(con, names, since, utility_only)
        baseline = corpus.applicant_baseline(con, names, since, utility_only, scoped=True)
        context = corpus.applicant_context(con, since)
        apps = corpus.applicant_applications(con, names, since, utility_only, scoped=True)

        # --- decide whether live data can change any answer, before spending anything
        import merge
        topup_plan = merge.plan(apps)
        live: dict = {}
        topup_done = False
        if topup == "yes" or (
            topup == "auto" and topup_plan["estimated_seconds"] <= auto_seconds
            and topup_plan["refresh_needed"]
        ):
            live = merge.fetch(topup_plan["refresh_application_numbers"])
            topup_done = True

        results = []
        for row in apps:
            wrapper = live.get(row["application_number"])
            facts = merge.merge_facts(row, wrapper) if topup_done else rules.from_corpus(row)
            summary = rules.summarise(facts, rules.evaluate(facts))
            summary["matched_applicant_name"] = row.get("matched_applicant_name")
            summary["provenance"] = merge.provenance(row, wrapper)
            results.append(summary)

        tallies: dict[str, dict[str, int]] = {}
        for r in results:
            for rule, v in r["flags"].items():
                tallies.setdefault(rule, {}).setdefault(v["state"], 0)
                tallies[rule][v["state"]] += 1

        flagged = [r for r in results if r["flagged"]]
        return {
            "entity": entity_name,
            "resolved": True,
            "scope": {
                "policy": manifest["policy"],
                "names_in_scope": len(names),
                "names": names,
                "uncertain_names_excluded": manifest["uncertain_names"],
                "uncertain_applications_excluded": manifest["uncertain_applications"],
                "related_entity_names_excluded": manifest["related_entity_names"],
                "near_miss_names_excluded": manifest["near_miss_names"],
                "near_miss_applications_excluded": manifest["near_miss_applications"],
                "near_miss": manifest["near_miss"][:15],
                "warnings": manifest["warnings"],
            },
            "coverage": {
                "source": "corpus only",
                "corpus_last_record": corpus.CORPUS_LAST_RECORD,
                "complete_through": corpus.CORPUS_COMPLETE_THROUGH,
                "partial_between": [corpus.CORPUS_COMPLETE_THROUGH,
                                    corpus.CORPUS_NEGLIGIBLE_AFTER],
                "negligible_after": corpus.CORPUS_NEGLIGIBLE_AFTER,
                "completeness_note": "PatEx carries published applications only, so "
                                     "coverage decays for roughly 18 months before the "
                                     "last record date - 79% of a normal quarter by "
                                     "2022-Q1, 57% by 2022-Q4, 13% by 2023-Q1. Do not "
                                     "quote this portfolio as complete past "
                                     f"{corpus.CORPUS_COMPLETE_THROUGH}.",
                "three_state_horizon": str(rules.CORPUS_HORIZON),
                "filing_floor": since,
                "filing_floor_reason": "applicant organisation is ~0% populated before 2012 "
                                       "(USPTO began recording it after the AIA)",
                "odp_topup_applied": topup_done,
                "odp_records_merged": len(live),
            },
            "topup": {
                "applied": topup_done,
                "settled_no_call_needed": topup_plan["settled_no_call_needed"],
                "refresh_needed": topup_plan["refresh_needed"],
                "odp_calls": topup_plan["odp_calls"],
                "estimated_seconds": topup_plan["estimated_seconds"],
                "records_returned": len(live),
                "not_returned_by_odp": (
                    topup_plan["refresh_needed"] - len(live) if topup_done else None),
                "reasons": topup_plan["reasons"],
                "offer": None if topup_done or not topup_plan["refresh_needed"] else (
                    f"{topup_plan['refresh_needed']:,} application(s) were still live when the "
                    f"corpus froze, so their counts and children may have moved. Refreshing "
                    f"them from ODP takes about {topup_plan['estimated_seconds']}s "
                    f"({topup_plan['odp_calls']} call(s)). Re-run with --topup yes."),
            },
            "baseline": baseline,
            "context": context,
            "rules": tallies,
            "flagged_count": len(flagged),
            "flagged": flagged[:flagged_limit],
            "flagged_truncated": max(0, len(flagged) - flagged_limit),
            "results": results,
            "reporting_notes": _confounders(baseline, context, merged=topup_done),
        }
    finally:
        con.close()


def _confounders(baseline: dict, context: dict, merged: bool = False) -> list[str]:
    """Stated every time, because these numbers are misread without them."""
    import corpus

    notes = [
        "These are unexercised options, not errors. The public record contains no "
        "client instruction, budget, or strategy, so no rule here can distinguish a "
        "deliberate decision from a lapse.",
        "INDETERMINATE means the case was disposed too close to the data horizon to "
        "tell. It is not a finding and must not be added to FLAG.",
    ]
    if not merged:
        notes.append(
            f"Bulk-data-only figures. Coverage is complete through "
            f"{corpus.CORPUS_COMPLETE_THROUGH} and decays sharply after that, so recent "
            "filings are under-counted and statuses may have moved on. Measured on "
            "Neuralink, 10 of 25 shared records had advanced to granted since the "
            "snapshot. Confirm anything recent against live data before reporting."
        )
    else:
        notes.append(
            "Applications still active at the bulk-data freeze were refreshed against "
            "live USPTO data, so their statuses, counts and children are current. "
            "Applications filed after the freeze are still absent - the bulk data is "
            f"complete only through {corpus.CORPUS_COMPLETE_THROUGH}."
        )
    n = baseline.get("applications") or 0
    if n < 50:
        notes.append(
            f"Only {n} applications in scope. Rates on a denominator this small are "
            "noise; report the count alongside every percentage."
        )
    share = context.get("national_stage_share")
    if share is not None and share >= 25:
        notes.append(
            f"{share}% of these applications are Sec. 371 national-stage entries. "
            "Foreign-origin filers use continuations far less as a matter of house "
            "style, so a high A1 rate reflects filing culture, not a lapse."
        )
    rr = baseline.get("restriction_rate")
    if rr is not None:
        notes.append(
            f"Restriction rate ({rr}%) tracks technology, not practice - semiconductor "
            "and display filers run 20-40%, software and communications filers 4-7%. "
            "Do not compare across technology centres without saying so."
        )
    return notes


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
    srch.add_argument("--entity", "--applicant", dest="entity",
                      help="scope the result set to this company. Strongly recommended: "
                           "ODP tokenises the query, so searching 'Taiwan Semiconductor*' "
                           "also returns Micron and Sony. Resolves the name against the "
                           "corpus and matches every applicant on each record.")
    srch.add_argument("--include-non-utility", action="store_true",
                      help="keep provisionals and other non-utility types (dropped by default)")
    srch.add_argument("--no-confirm", action="store_true",
                      help="skip per-candidate continuity calls (faster, leaves rules INDETERMINATE)")

    res = sub.add_parser("resolve",
                         help="step 1: resolve a company name to an auditable scope")
    res.add_argument("entity")
    res.add_argument("--json", action="store_true")
    res.add_argument("--save", metavar="PATH")

    pf = sub.add_parser("portfolio",
                        help="whole-portfolio prosecution profile for one entity (corpus)")
    pf.add_argument("entity")
    pf.add_argument("--since", type=int, default=None,
                    help="filing-year floor (default 2012; earlier is unrecorded, not absent)")
    pf.add_argument("--flagged-limit", type=int, default=25)
    pf.add_argument("--include-non-utility", action="store_true")
    pf.add_argument("--topup", choices=["auto", "yes", "no"], default="auto",
                    help="merge live ODP data for applications still live at the corpus "
                         "freeze. auto (default) does it when it costs under --auto-seconds "
                         "and otherwise reports the price without spending")
    pf.add_argument("--auto-seconds", type=int, default=15,
                    help="cost ceiling below which --topup auto proceeds without asking")
    pf.add_argument("--json", action="store_true",
                    help="emit the raw result instead of the readable report")
    pf.add_argument("--full", action="store_true",
                    help="with --json, include every application record")
    pf.add_argument("--save", metavar="PATH", help="write the full result to JSON")

    sub.add_parser("doctor", help="check corpus and ODP availability")
    args = p.parse_args()

    if args.cmd == "doctor":
        _print(doctor())
    elif args.cmd == "resolve":
        import entity
        manifest = entity.resolve(args.entity)
        print(json.dumps(manifest, indent=2, default=str) if args.json
              else entity.render(manifest))
        if args.save:
            Path(args.save).write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            print(f"\nmanifest written to {args.save}", file=sys.stderr)
    elif args.cmd == "portfolio":
        out = portfolio(args.entity, since=args.since,
                        flagged_limit=args.flagged_limit,
                        utility_only=not args.include_non_utility,
                        topup=args.topup, auto_seconds=args.auto_seconds)
        if args.save:
            Path(args.save).write_text(
                json.dumps(out, indent=2, default=str), encoding="utf-8")
        if args.json:
            if not args.full:
                out.pop("results", None)
            _print(out)
        else:
            import report
            print(report.render(out))
        if args.save:
            print(f"\nfull result written to {args.save}", file=sys.stderr)
    elif args.cmd == "app":
        _print(audit_one(args.application_number, args.source))
    elif args.cmd == "apps":
        _print([audit_one(a, args.source) for a in args.application_numbers])
    else:
        _print(audit_search(args.query, args.limit, not args.no_confirm,
                            entity_name=args.entity,
                            utility_only=not args.include_non_utility))


if __name__ == "__main__":
    main()
