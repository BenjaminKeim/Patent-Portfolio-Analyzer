"""Turn a portfolio result into a readable prosecution review.

Layout is Ben's specification: portfolio counts up top, then the five prosecution
events, each case identified by application number, title and filing date.

One judgement is preserved from the engine. A rule that fires on a large share of the
portfolio is describing filing strategy, not listing lapses - 153 first-action
allowances without a continuation across 840 applications is how a connector company
prosecutes, not 153 mistakes. Every case is still listed, because that is what was
asked for, but the section carries the rate so the list is not mistaken for a count of
errors.
"""
from __future__ import annotations

# A rule describes practice rather than incidents when it fires on a large share of the
# portfolio AND on enough cases for "share" to mean anything. Three of 25 applications
# is 12% and is still just three cases; 153 of 840 is a house style.
PATTERN_SHARE = 0.10
PATTERN_MIN_CASES = 20

# Sections, their order and their explanatory text all come from rules.RULES - the one
# registry - so a rule reads identically here, in the chart, in the widget and in the
# JSON, and no rule can be described one way in one place and another way elsewhere.
import rules as _rules

SECTIONS = _rules.sections()


def _revival_outcome(r: dict) -> str:
    detail = (r.get("flags", {}).get("E1") or {}).get("detail", "")
    if "was lost" in detail:
        return "DISMISSED - application lost"
    if "dismissed before one was granted" in detail:
        return f"granted after {r.get('revivals_dismissed', 0)} dismissed"
    return "granted - revived"


def _counts(results: list[dict]) -> dict:
    out = {"granted": 0, "pending": 0, "abandoned": 0}
    for r in results:
        d = r.get("disposition")
        if d in out:
            out[d] += 1
    return out


def _cases(results: list[dict], rule: str) -> list[dict]:
    """Cases for one rule, oldest first.

    The application number is part of the sort key, not decoration: filing date alone
    leaves ties broken by fetch order, which differs between a cold run and a cached
    one. Two runs over identical data then produce differently ordered reports and
    cannot be diffed - which is exactly what someone re-running a client every few
    weeks wants to do.
    """
    hits = [r for r in results if rule in (r.get("flagged") or [])]
    return sorted(hits, key=lambda r: (str(r.get("filed") or ""), str(r["application"])))


def _note(r: dict, rule: str) -> str:
    """The per-case column. Carries the revival outcome for E1, and for B1 the section
    121 label risk that used to be its own B2 section."""
    if rule == "E1":
        return _revival_outcome(r)
    if rule == "B1" and "B2" in (r.get("flagged") or []):
        kinds = sorted({c.get("type") for c in (r.get("children") or []) if c.get("type")})
        label = "/".join(kinds) or "continuing application"
        return f"{label} filed, not a divisional - Sec. 121 label risk"
    return ""


def _table(cases: list[dict], rule: str, limit: int | None) -> list[str]:
    shown = cases if limit is None else cases[:limit]
    width = max((len(str(r.get("title") or "")) for r in shown), default=0)
    width = min(max(width, 20), 62)
    notes = {id(r): _note(r, rule) for r in shown}
    has_notes = any(notes.values())

    head = f"  {'Application':<12} {'Filed':<12} {'Title':<{width}}"
    if has_notes:
        head += "  Note"
    lines = [head, "  " + "-" * (len(head) - 2)]
    for r in shown:
        title = str(r.get("title") or "")[:width]
        line = f"  {r['application']:<12} {str(r.get('filed') or ''):<12} {title:<{width}}"
        if has_notes and notes[id(r)]:
            line += f"  {notes[id(r)]}"
        lines.append(line)
    if limit is not None and len(cases) > limit:
        lines.append(f"  ... and {len(cases) - limit:,} more (use --max-cases 0 for all)")
    return lines


def _recent_section(d: dict) -> list[str]:
    """Applications filed after the bulk data stops.

    Reported apart from the portfolio counts on purpose. Most of this cohort is still
    pending, so folding it into the rates above would dilute every denominator without
    answering anything - the cases have not had time to answer the question each rule
    asks. Kept visible because the alternative is a report that stops in 2023 and does
    not say so.
    """
    rec = d.get("recent") or {}
    if not rec:
        return []
    L = ["## Filed since the bulk data stops", ""]
    if not rec.get("applied"):
        L += [rec.get("offer", "Not swept."), ""]
        return L

    n = rec["applications"]
    if not n:
        L += [f"No in-scope applications filed since {rec['since']} were found in ODP.", ""]
        return L

    c = rec["counts"]
    years = ", ".join(f"{y} ({k:,})" for y, k in (rec.get("by_filing_year") or {}).items())
    L += [f"**{n:,} in-scope application(s)** filed since {rec['since']} - absent from "
          "the bulk data entirely, found by sweeping ODP and evaluated by the same "
          "rules. Not included in the counts or rates above.", "",
          f"Filed: {years}." if years else "",
          f"Of these, {c['granted']:,} have already issued and {c['abandoned']:,} have "
          f"already gone abandoned; {c['pending']:,} are still pending.", ""]

    rows = [(rule, v.get("FLAG", 0), v.get("INDETERMINATE", 0))
            for rule, v in (rec.get("rules") or {}).items() if v.get("FLAG")]
    if rows:
        verb = "carries" if rec["flagged_count"] == 1 else "carry"
        L += [f"**{rec['flagged_count']:,} of them {verb} at least one finding.**", ""]
        width = max(len(r[0]) for r in rows)
        L += [f"  {'Rule':<{width}}  Findings", "  " + "-" * (width + 10)]
        for rule, flag, indet in sorted(rows, key=lambda x: -x[1]):
            extra = f"  (+{indet:,} indeterminate)" if indet else ""
            L.append(f"  {rule:<{width}}  {flag:,}{extra}")
        L.append("")
        cases = sorted((r for r in (rec.get("results") or []) if r.get("flagged")),
                       key=lambda r: (str(r.get("filed") or ""), str(r["application"])))
        if cases:
            import rules as _r
            L += ["  " + "-" * 76]
            for r in cases[:25]:
                names = "; ".join(_r.name(k) for k in r["flagged"])
                L.append(f"  {r['application']:<11} {str(r.get('filed') or ''):<12} "
                         f"{str(r.get('title') or '')[:38]:<40} {names}")
            if len(cases) > 25:
                L.append(f"  ... and {len(cases) - 25:,} more")
            L.append("")
    else:
        L += ["No rule fires on this cohort yet - too little prosecution history.", ""]

    L += [f"Cost: {rec['search_calls']} search call(s); the children come back on the "
          "search response, so there are no per-application calls.", ""]
    return L


def render(d: dict, max_cases: int | None = None, charts: bool = True) -> str:
    if not d.get("resolved"):
        return f"# {d['entity']}\n\n{d.get('note', 'Could not resolve this company.')}\n"

    scope, cov, tup = d["scope"], d["coverage"], d["topup"]
    results = d.get("results") or []
    total = len(results)
    c = _counts(results)

    filed = sorted(str(r["filed"]) for r in results if r.get("filed"))
    window = f"{filed[0][:4]}-{filed[-1][:4]}" if filed else str(cov["filing_floor"])

    L = [f"# Prosecution review - {d['entity']}", ""]
    L += [
        f"**{total:,} applications** across {scope['names_in_scope']} applicant name(s), "
        f"filed **{window}**.",
        "",
        # The window matters as much as the counts. Anything filed after the bulk data
        # stops is absent entirely, so "6 pending" means six pending among applications
        # filed in the window - not six pending at this company.
        f"| Within applications filed {window} | |",
        f"|---|---|",
        f"| Issued patents | **{c['granted']:,}** |",
        f"| Still pending | **{c['pending']:,}** |",
        f"| Abandoned | {c['abandoned']:,} |",
        "",
        f"Coverage is complete only through **{cov['complete_through']}** and thins "
        f"sharply after it, so the {filed[-1][:4] if filed else 'recent'} end of this "
        "window is partial and later filings are missing entirely. Treat these as counts "
        "within the window, not as this company's current portfolio.",
        "",
    ]
    if tup["applied"]:
        L += [f"Live USPTO data merged for the {tup['records_returned']:,} application(s) "
              f"still active when the bulk data froze; the other "
              f"{tup['settled_no_call_needed']:,} were already closed.", ""]
    else:
        L += [f"**Bulk data only.** {tup['refresh_needed']:,} application(s) were still "
              f"active at the freeze, so their counts and statuses may have moved. "
              f"Refreshing takes about {tup['estimated_seconds']}s.", ""]

    # Charts before the case lists. A reader who sees "837" without a denominator
    # reads it against the portfolio total; the bars put it against the set the rule
    # could fire on, which is the only honest comparison.
    if charts:
        import chart
        L += chart.render(results, SECTIONS)

    L += ["## Prosecution events", ""]
    any_hits = False
    for rule, title in SECTIONS:
        cases = _cases(results, rule)
        n = len(cases)
        any_hits = any_hits or bool(n)
        heading = f"### {title} - {n:,}"
        L += [heading, ""]
        if not n:
            L += ["None.", ""]
            continue
        pct = 100 * n / total if total else 0
        if total and n / total > PATTERN_SHARE and n >= PATTERN_MIN_CASES:
            L += [f"**{pct:.1f}% of the portfolio.** At this rate the rule is describing "
                  "filing practice rather than listing individual lapses - read it as a "
                  "pattern, not as a count of errors.", ""]
        L.append(_rules.RULES[rule]["why"])
        L.append("")
        L += _table(cases, rule, max_cases)
        L.append("")

    if not any_hits:
        L += ["No prosecution events found across this portfolio.", ""]

    L += _recent_section(d)

    # ---- what the numbers rest on
    L += ["## Coverage and caveats", ""]
    cache = d.get("cache") or {}
    if cache.get("hits"):
        age = cache.get("oldest_response_age_days")
        when = cache.get("oldest_response_used")
        if age is not None and age >= 1:
            L.append(f"- {cache['hits']} USPTO response(s) came from the local cache; "
                     f"the oldest was fetched {when} ({age} day(s) ago). Re-run with "
                     "--cache refresh for current data.")
        else:
            L.append(f"- {cache['hits']} USPTO response(s) came from the local cache, "
                     "all fetched today.")
    if not tup["applied"] and tup["refresh_needed"]:
        L.append(f"- Counts on the {tup['refresh_needed']:,} still-active applications may "
                 "be understated - a third RCE or a later interview would not show here.")
    L.append(f"- Bulk data is complete through {cov['complete_through']}; coverage decays "
             f"after that and is negligible past {cov['negligible_after']}. Applications "
             "filed since are absent from these counts.")
    if scope.get("uncertain_names_excluded"):
        L.append(f"- {scope['uncertain_names_excluded']} applicant name(s) covering "
                 f"{scope['uncertain_applications_excluded']:,} applications were left out "
                 "as possible regional or research arms.")
    if scope.get("near_miss_names_excluded"):
        # Name them rather than quoting a bare total: a short brand has a crowded
        # one-edit neighbourhood - MOLEX's contains ROLEX (172 applications) - so a
        # count alone reads as missing cases when almost none belong to this filer.
        top = ", ".join(x["name"] for x in (scope.get("near_miss") or [])[:4])
        L.append(f"- {scope['near_miss_names_excluded']} applicant name(s) sit one "
                 f"character from this company's name and were excluded"
                 + (f": {top}." if top else ".")
                 + " Most are usually different companies; check if any looks like this "
                   "filer misspelled.")
    for note in d.get("reporting_notes", []):
        L.append(f"- {note}")
    L += ["", "---", "",
          "These are unexercised options and procedural observations drawn from the public "
          "record. The record contains no client instruction, budget, or strategy, so "
          "nothing here distinguishes a deliberate decision from a lapse.", ""]
    return "\n".join(L)
