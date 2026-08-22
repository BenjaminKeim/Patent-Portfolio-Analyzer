"""Turn a portfolio result into something a person can read and act on.

The engine will happily return 257 findings on an 840-application portfolio. That is
not a to-do list, and presenting it as one would be both unusable and wrong: 153
first-action allowances without a continuation is a house pattern, not 153 mistakes.

So findings are triaged by what they actually support:

  ACT      A specific procedural defect on a specific case. Small in number, concrete,
           and defensible to point at individually.
  REVIEW   A concrete unexercised option on a named case - worth a look, but the record
           cannot tell you whether it was deliberate.
  PATTERN  A rule firing across a large share of the portfolio. Reported as a rate with
           a sample, never as a list, because at that volume it describes filing
           strategy rather than individual lapses.

The ACT/REVIEW/PATTERN split is about what the evidence supports, not severity. A rule
lands in PATTERN when it fires on more than PATTERN_SHARE of the portfolio, because a
finding that applies to a third of everything is a description of how the firm works.
"""
from __future__ import annotations

# Above this share of the scoped portfolio, a rule is a pattern, not a finding list.
PATTERN_SHARE = 0.10

# Rules whose evidence is a procedural defect rather than an unexercised option. These
# are reported individually however many there are.
ALWAYS_ACT = {"E1", "B2"}

RULE_TITLES = {
    "A1": "Allowed on the first action, no continuation filed before issuance",
    "B1": "Restriction issued, no divisional filed",
    "B2": "Restriction issued, child designated a continuation rather than a divisional",
    "D2": "Three or more office actions with no examiner interview",
    "D3": "More than two RCEs",
    "E1": "Unintentional abandonment, evidenced by a petition to revive",
}

RULE_WHY = {
    "A1": ("A first-action allowance means the examiner found nothing worth citing "
           "against the claims as presented - the strongest signal in the public record "
           "that scope was left unclaimed."),
    "B1": ("The non-elected claims were never pursued. Whether that was intended is not "
           "in the record."),
    "B2": ("Section 121's safe harbour attaches to a divisional filed as a result of the "
           "restriction. Courts look to substance and consonance rather than the ADS "
           "label, so this warrants review rather than being a conclusion."),
    "D2": "An interview after two rejections is widely treated as best practice.",
    "D3": "Repeated RCEs without an appeal can indicate the case needed a different route.",
    "E1": ("Nobody petitions to revive a case they meant to abandon, so the petition is "
           "evidence the lapse was unintentional - a docketing failure rather than a "
           "decision."),
}


def _bucket(rule: str, hits: int, total: int) -> str:
    if rule in ALWAYS_ACT:
        return "ACT"
    if total and hits / total > PATTERN_SHARE:
        return "PATTERN"
    return "REVIEW"


def _case_line(r: dict, rule: str) -> str:
    bits = [r["application"]]
    if r.get("filed"):
        bits.append(f"filed {r['filed']}")
    if r.get("patent"):
        bits.append(f"pat {r['patent']}")
    elif r.get("disposition"):
        bits.append(str(r["disposition"]))
    if r.get("art_unit"):
        bits.append(f"AU {r['art_unit']}")
    if r.get("title"):
        bits.append(r["title"][:60])
    line = "  " + "  ".join(bits)
    # E1's detail varies per case (revived, revived after a dismissal, or lost) and is
    # the finding itself. Every other rule's detail just restates the rule heading.
    if rule == "E1":
        detail = (r.get("flags", {}).get(rule) or {}).get("detail", "")
        if "was lost" in detail:
            line += "\n      revival petition DISMISSED - the application was lost"
        elif "dismissed before one was granted" in detail:
            line += "\n      revived, but only after an earlier petition was dismissed"
    return line


def render(d: dict, max_cases: int = 12) -> str:
    if not d.get("resolved"):
        return (f"# {d['entity']}\n\n{d.get('note', 'Could not resolve this company.')}\n")

    scope, cov, tup = d["scope"], d["coverage"], d["topup"]
    total = d["baseline"]["applications"]
    results = d.get("results") or d.get("flagged") or []

    L = [f"# Prosecution review - {d['entity']}", ""]

    # ---- what was looked at
    L += [
        f"**{total:,} applications** in scope across {scope['names_in_scope']} applicant "
        f"name(s), filed {cov['filing_floor']} onward.",
        "",
    ]
    if tup["applied"]:
        L.append(
            f"Live USPTO data merged for the {tup['records_returned']:,} application(s) "
            f"still active when the bulk data froze; the other "
            f"{tup['settled_no_call_needed']:,} were already closed and need no refresh."
        )
    else:
        L.append(
            f"**Bulk data only.** {tup['refresh_needed']:,} application(s) were still "
            f"active when it froze, so their counts and children may have moved since. "
            f"Refreshing them takes about {tup['estimated_seconds']}s."
        )
    L.append("")

    # ---- triage
    buckets: dict[str, list] = {"ACT": [], "REVIEW": [], "PATTERN": []}
    for rule, states in sorted(d["rules"].items()):
        hits = states.get("FLAG", 0)
        if hits:
            buckets[_bucket(rule, hits, total)].append((rule, hits))

    by_rule: dict[str, list] = {}
    for r in results:
        for rule in r.get("flagged", []):
            by_rule.setdefault(rule, []).append(r)

    if not any(buckets.values()):
        L += ["No findings. Every rule returned not-applicable across this portfolio.", ""]

    if buckets["ACT"]:
        L += ["## Act on these", "",
              "Specific procedural defects on specific cases.", ""]
        for rule, hits in buckets["ACT"]:
            L += [f"### {rule} - {RULE_TITLES[rule]} ({hits})", "", RULE_WHY[rule], ""]
            for r in by_rule.get(rule, [])[:max_cases]:
                L.append(_case_line(r, rule))
            if len(by_rule.get(rule, [])) > max_cases:
                L.append(f"  ... and {len(by_rule[rule]) - max_cases} more")
            L.append("")

    if buckets["REVIEW"]:
        L += ["## Worth reviewing", "",
              "Concrete options that were available and not taken. The record contains no "
              "client instruction, budget or strategy, so it cannot tell you whether any "
              "of these was deliberate.", ""]
        for rule, hits in buckets["REVIEW"]:
            pct = 100 * hits / total if total else 0
            L += [f"### {rule} - {RULE_TITLES[rule]} ({hits}, {pct:.1f}%)", "",
                  RULE_WHY[rule], ""]
            for r in by_rule.get(rule, [])[:max_cases]:
                L.append(_case_line(r, rule))
            if len(by_rule.get(rule, [])) > max_cases:
                L.append(f"  ... and {len(by_rule[rule]) - max_cases} more")
            L.append("")

    if buckets["PATTERN"]:
        L += ["## Portfolio patterns", "",
              "These fire on a large share of the portfolio, which makes them a "
              "description of filing practice rather than a list of individual lapses. "
              "Reported as rates, with a sample.", ""]
        for rule, hits in buckets["PATTERN"]:
            pct = 100 * hits / total
            L += [f"### {rule} - {RULE_TITLES[rule]}", "",
                  f"**{hits:,} of {total:,} applications ({pct:.1f}%)**. {RULE_WHY[rule]}",
                  ""]
            for r in by_rule.get(rule, [])[:3]:
                L.append(_case_line(r, rule))
            L += ["", f"  (sample of {hits:,}; full list in the JSON)", ""]

    # ---- what the numbers rest on
    L += ["## Coverage and caveats", ""]
    if not tup["applied"] and tup["refresh_needed"]:
        L.append(f"- Counts on the {tup['refresh_needed']:,} still-active applications may "
                 "be understated - a third RCE or a later interview would not show here.")
    L.append(f"- Bulk data is complete through {cov['complete_through']}; coverage decays "
             f"after that and is negligible past {cov['negligible_after']}.")
    if scope.get("uncertain_names_excluded"):
        L.append(f"- {scope['uncertain_names_excluded']} applicant name(s) covering "
                 f"{scope['uncertain_applications_excluded']:,} applications were left out "
                 "as possible regional or research arms.")
    if scope.get("near_miss_names_excluded"):
        # Deliberately name them rather than quoting a bare total. A short brand has a
        # crowded one-edit neighbourhood - MOLEX's contains ROLEX (172 applications),
        # VOLEX and MILEX - so "240 applications spell the name differently" reads as
        # 240 missing cases when almost none of them belong to this filer.
        top = ", ".join(c["name"] for c in (scope.get("near_miss") or [])[:4])
        L.append(f"- {scope['near_miss_names_excluded']} applicant name(s) sit one "
                 f"character from this company's name and were excluded"
                 + (f": {top}." if top else ".")
                 + " Most are usually different companies; check the list if any looks "
                   "like this filer misspelled.")
    for note in d.get("reporting_notes", []):
        L.append(f"- {note}")
    L.append("")
    L += ["---", "",
          "These are unexercised options and procedural observations drawn from the public "
          "record. The record contains no client instruction, budget, or strategy, so "
          "nothing here distinguishes a deliberate decision from a lapse.", ""]
    return "\n".join(L)
