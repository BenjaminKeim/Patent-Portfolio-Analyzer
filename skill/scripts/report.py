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

# Ben's five, in his order. B2 is reported separately below - it is not on his list but
# it is a live safe-harbour risk, so it is shown rather than silently dropped.
SECTIONS = [
    ("B1", "Restriction issued, no divisional filed"),
    ("A1", "First-action allowance, no continuation filed"),
    ("E1", "Petition to revive"),
    ("D2", "Three or more office actions, no examiner interview"),
    ("D3", "More than two RCEs"),
]

EXTRA_SECTIONS = [
    ("B2", "Restriction issued, child designated a continuation rather than a divisional"),
]

RULE_WHY = {
    "B1": ("The non-elected claims were never pursued. Whether that was intended is not "
           "in the record."),
    "A1": ("A first-action allowance means the examiner found nothing worth citing "
           "against the claims as presented."),
    "E1": ("Nobody petitions to revive a case they meant to abandon, so the petition is "
           "evidence the lapse was unintentional."),
    "D2": "An interview after two rejections is widely treated as best practice.",
    "D3": "Repeated RCEs without an appeal can indicate the case needed a different route.",
    "B2": ("Section 121's safe harbour attaches to a divisional filed as a result of the "
           "restriction. Courts look to substance and consonance rather than the ADS "
           "label, so this warrants review rather than being a conclusion."),
}


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
    hits = [r for r in results if rule in (r.get("flagged") or [])]
    return sorted(hits, key=lambda r: str(r.get("filed") or ""))


def _table(cases: list[dict], rule: str, limit: int | None) -> list[str]:
    shown = cases if limit is None else cases[:limit]
    width = max((len(str(r.get("title") or "")) for r in shown), default=0)
    width = min(max(width, 20), 62)
    head = f"  {'Application':<12} {'Filed':<12} {'Title':<{width}}"
    if rule == "E1":
        head += "  Outcome"
    lines = [head, "  " + "-" * (len(head) - 2)]
    for r in shown:
        title = str(r.get("title") or "")[:width]
        line = f"  {r['application']:<12} {str(r.get('filed') or ''):<12} {title:<{width}}"
        if rule == "E1":
            line += f"  {_revival_outcome(r)}"
        lines.append(line)
    if limit is not None and len(cases) > limit:
        lines.append(f"  ... and {len(cases) - limit:,} more (use --max-cases 0 for all)")
    return lines


def render(d: dict, max_cases: int | None = None) -> str:
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

    L += ["## Prosecution events", ""]
    any_hits = False
    for rule, title in SECTIONS + EXTRA_SECTIONS:
        cases = _cases(results, rule)
        if rule == "B2" and not cases:
            continue
        n = len(cases)
        any_hits = any_hits or bool(n)
        heading = f"### {title} - {n:,}"
        if rule == "B2":
            heading += "  *(not on the requested list; shown because it is a live risk)*"
        L += [heading, ""]
        if not n:
            L += ["None.", ""]
            continue
        pct = 100 * n / total if total else 0
        if total and n / total > PATTERN_SHARE and n >= PATTERN_MIN_CASES:
            L += [f"**{pct:.1f}% of the portfolio.** At this rate the rule is describing "
                  "filing practice rather than listing individual lapses - read it as a "
                  "pattern, not as a count of errors.", ""]
        L.append(RULE_WHY[rule])
        L.append("")
        L += _table(cases, rule, max_cases)
        L.append("")

    if not any_hits:
        L += ["No prosecution events found across this portfolio.", ""]

    # ---- what the numbers rest on
    L += ["## Coverage and caveats", ""]
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
