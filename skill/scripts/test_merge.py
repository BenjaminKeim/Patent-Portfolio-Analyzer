"""Tests for the corpus/ODP merge and the two new rules.

Rule tests and merge-semantics tests are offline. The live tests need an ODP key and
are skipped without one; they are cheap (1-2 requests).

    python test_merge.py
"""
from __future__ import annotations

import sys
from datetime import date

import merge
import rules

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{label}\n      got  {got!r}\n      want {want!r}")


def facts(**kw) -> rules.AppFacts:
    base = dict(application="1", source="test", horizon=date(2022, 6, 30))
    base.update(kw)
    return rules.AppFacts(**base)


def ev(*pairs):
    return [(date.fromisoformat(d), c) for d, c in pairs]


# ------------------------------------------------------------------------- new rules
def run_rules() -> None:
    # E1 - abandonment is only a finding when a revival petition proves it was
    # unintentional. Plain failure-to-respond abandonment is the normal way to drop a
    # case: 774,934 modern utility applications did it, and flagging them would be
    # almost entirely false positives.
    plain = facts(status="Abandoned  --  Failure to Respond to an Office Action",
                  status_date=date(2018, 1, 1), events=ev(("2017-06-01", "MABN2")))
    check("plain abandonment is not a finding",
          rules.evaluate(plain)["E1"]["state"], "N/A")

    revived = facts(status="Patented Case", issue_date=date(2019, 5, 1),
                    events=ev(("2017-06-01", "MABN2"), ("2017-11-02", "PREV")))
    check("abandonment plus granted revival flags",
          rules.evaluate(revived)["E1"]["state"], "FLAG")

    lost = facts(status="Abandoned", status_date=date(2018, 6, 1),
                 events=ev(("2017-06-01", "MABN2"), ("2017-11-02", "ODPET4")))
    e1 = rules.evaluate(lost)["E1"]
    check("dismissed revival flags", e1["state"], "FLAG")
    check("dismissed revival says the application was lost",
          "was lost" in e1["detail"], True)

    # A dismissed petition followed by a granted one means the application survived.
    # Reporting it as lost would be plainly wrong to anyone who pulled the file.
    both = facts(status="Patented Case", issue_date=date(2019, 5, 1),
                 events=ev(("2017-11-02", "ODPET4"), ("2018-02-02", "PREV")))
    e1 = rules.evaluate(both)["E1"]
    check("dismissed-then-granted still flags", e1["state"], "FLAG")
    check("dismissed-then-granted must NOT say the application was lost",
          "was lost" in e1["detail"], False)

    # D3 - more than two RCEs.
    for n, want in ((2, "N/A"), (3, "FLAG"), (5, "FLAG")):
        f = facts(status="Patented Case", issue_date=date(2020, 1, 1),
                  events=[(date(2018, 1, 1), "RCEX")] * n)
        check(f"D3 with {n} RCEs", rules.evaluate(f)["D3"]["state"], want)

    # A live application can still accrue events, so a negative count is provisional -
    # two RCEs before the freeze and a third after it is a finding the corpus cannot
    # show. It must be marked, not silently reported as a clean N/A.
    pending = facts(status="Docketed New Case - Ready for Examination",
                    events=[(date(2022, 1, 1), "RCEX")] * 2)
    out = rules.evaluate(pending)["D3"]
    check("pending negative count is marked provisional", out.get("provisional"), True)

    settled = facts(status="Patented Case", issue_date=date(2020, 1, 1),
                    events=[(date(2018, 1, 1), "RCEX")] * 2)
    check("settled negative count is not provisional",
          rules.evaluate(settled)["D3"].get("provisional"), None)


# --------------------------------------------------------------------- merge planning
def run_planning() -> None:
    freeze = rules.CORPUS_HORIZON

    def row(status, disposal=None, issue=None):
        return {"application_number": "1", "appl_status_desc": status,
                "appl_status_date": disposal, "patent_issue_date": issue}

    old = row("Patented Case", issue=date(2015, 1, 1))
    check("a long-settled grant needs no call", merge.needs_refresh(old, freeze)[0], False)

    recent = row("Patented Case", issue=date(2022, 3, 1))
    check("a grant near the freeze needs a call",
          merge.needs_refresh(recent, freeze)[0], True)

    pending = row("Non Final Action Mailed")
    check("a pending application needs a call",
          merge.needs_refresh(pending, freeze)[0], True)

    old_aband = row("Abandoned  --  Failure to Respond", disposal=date(2016, 5, 1))
    check("a long-abandoned application needs no call",
          merge.needs_refresh(old_aband, freeze)[0], False)

    # Revival is generally available for two years, so a recent abandonment can still
    # sprout an E1 finding that the corpus cannot see.
    new_aband = row("Abandoned  --  Failure to Respond", disposal=date(2022, 1, 1))
    check("a recent abandonment needs a call",
          merge.needs_refresh(new_aband, freeze)[0], True)

    no_date = row("Patented Case")
    check("a grant with no disposal date needs a call",
          merge.needs_refresh(no_date, freeze)[0], True)

    p = merge.plan([old, recent, pending, old_aband, new_aband])
    check("plan counts the settled", p["settled_no_call_needed"], 2)
    check("plan counts the refresh set", p["refresh_needed"], 3)
    check("plan batches into calls", p["odp_calls"], 1)


# -------------------------------------------------------------------- merge semantics
def run_merge_semantics() -> None:
    corpus_row = {
        "application_number": "12345678",
        "filing_date": date(2019, 1, 1),
        "appl_status_desc": "Non Final Action Mailed",
        "appl_status_date": date(2023, 1, 1),
        "patent_number": None, "patent_issue_date": None,
        "examiner_full_name": "DOE, JOHN", "examiner_art_unit": "2131",
        "invention_title": "A thing",
        "events": [{"event_code": "RCEX", "recorded_date": date(2022, 1, 1)},
                   {"event_code": "RCEX", "recorded_date": date(2022, 6, 1)}],
        "children": [],
    }
    wrapper = {
        "applicationNumberText": "12345678",
        "applicationMetaData": {
            "filingDate": "2019-01-01",
            "applicationStatusDescriptionText": "Patented Case",
            "patentNumber": "11999999",
            "grantDate": "2025-03-04",
        },
        "eventDataBag": [
            {"eventCode": "RCEX", "eventDate": "2022-06-01"},   # duplicate of corpus
            {"eventCode": "RCEX", "eventDate": "2024-02-01"},   # the third, post-freeze
        ],
        "childContinuityBag": [{
            "childApplicationNumberText": "18000001",
            "claimParentageTypeCode": "DIV",
            "childApplicationFilingDate": "2025-01-02",
        }],
    }

    f = merge.merge_facts(corpus_row, wrapper)
    check("merged source is recorded", f.source, "corpus+odp")
    check("ODP wins on status", f.status, "Patented Case")
    check("ODP supplies the patent number", f.patent_number, "11999999")
    check("corpus keeps the filing date", f.filing_date, date(2019, 1, 1))

    # The whole reason events are unioned: two RCEs before the freeze and one after it
    # is three, and neither source shows three on its own.
    check("events are unioned and deduplicated", f.rce_count, 3)
    check("D3 fires only on the merged history",
          rules.evaluate(f)["D3"]["state"], "FLAG")
    check("corpus alone would not have fired D3",
          rules.evaluate(rules.from_corpus(corpus_row))["D3"]["state"], "N/A")

    # A divisional filed after the freeze must retract a B1 finding, not be ignored.
    check("post-freeze children are merged in",
          [(c.application, c.kind) for c in f.children], [("18000001", "DIV")])

    check("a refreshed record gets a current horizon", f.horizon > rules.CORPUS_HORIZON, True)

    # No live data must leave the record exactly as the corpus had it.
    g = merge.merge_facts(corpus_row, None)
    check("no wrapper leaves the corpus record untouched", g.source, "corpus")
    check("no wrapper keeps the corpus horizon", g.horizon, rules.CORPUS_HORIZON)
    check("provenance records a corpus-only record",
          merge.provenance(corpus_row, None)["refreshed"], False)
    check("provenance records a merged record",
          merge.provenance(corpus_row, wrapper)["sources"], ["corpus", "odp"])


# ------------------------------------------------------------------------- live tests
def run_live() -> None:
    """Two ODP requests. Skipped without a key."""
    try:
        import odp_client

        odp_client.load_api_key()
    except Exception as exc:
        print(f"  (live tests skipped - no ODP key: {str(exc)[:60]})")
        return

    got = merge.fetch(["16354059", "17968610", "17513027"])
    check("batched lookup returns every application asked for", len(got), 3)
    check("events come back inline", bool(got["16354059"].get("eventDataBag")), True)
    # Children must survive both the batching and the fields= selector, or every
    # absence-based rule silently over-flags.
    kids = got["17968610"].get("childContinuityBag") or []
    check("children survive a batched, field-selected query",
          [k.get("claimParentageTypeCode") for k in kids], ["DIV"])


if __name__ == "__main__":
    print("new rules ...")
    run_rules()
    print("merge planning ...")
    run_planning()
    print("merge semantics ...")
    run_merge_semantics()
    print("live ODP ...")
    run_live()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED\n")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nall passed")
