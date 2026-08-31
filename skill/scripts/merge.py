"""Merge the frozen local corpus with live ODP data.

The corpus is complete and free but stops in 2021. ODP is current but costs API calls.
Neither alone answers the question this skill exists for - identifying prosecution
issues - so this module combines them, spending calls only where they can change an
answer.

Why a merge rather than a choice of source
------------------------------------------
Every rule reads a COUNT or an ABSENCE over an application's event and child history,
and both can straddle the freeze:

  - Two RCEs before June 2023 and a third after it is a D3 finding that neither source
    shows on its own. The same is true of D2's office actions.
  - An interview after the freeze RETRACTS a D2 finding the corpus would report.
  - A divisional filed in 2024 RETRACTS a B1 finding, and a continuation filed before
    a 2022 issuance retracts A1. Absence is the one thing a later filing can disprove.

So events and children are UNIONED across the two sources, not chosen between. Status
and dates come from ODP, which is current by construction.

What does NOT need a call
-------------------------
An application that was already settled well before the freeze is finished: prosecution
is over, no further events can accrue, and its copendency and revival windows have
closed. The corpus is authoritative for it and asking ODP would only confirm what is
already known. That is roughly 80% of a typical portfolio, answered for free.

Cost
----
ODP accepts a batched `applicationNumberText:(A OR B OR ...)` query. Measured: 100
applications per request in 1.8s WITH the `fields=` selector; without it a 100-batch
fails with HTTP 413 (the 6MB response cap), because the default payload carries
recordAttorney and patentTermAdjustmentData, which together are ~75% of the bytes and
nothing here reads them. Verified that eventDataBag, childContinuityBag and
parentContinuityBag all survive both the batching and the field selection.
"""
from __future__ import annotations

from datetime import date, timedelta

import rules

# Applications per batched ODP request. 100 verified working with FIELDS; a 100-batch
# without FIELDS returns HTTP 413.
BATCH_SIZE = 100

# Only what rules.from_odp reads. Dropping recordAttorney (~53% of payload bytes) and
# patentTermAdjustmentData (~22%) is what keeps a 100-batch under the 6MB cap.
FIELDS = ",".join([
    "applicationNumberText",
    "applicationMetaData",
    "eventDataBag",
    "childContinuityBag",
    "parentContinuityBag",
])

# Measured wall clock per batched request, including the client's own throttle.
SECONDS_PER_BATCH = 3.0

# How far back ODP's continuity data can be trusted to be complete.
#
# NOT the 18 months that publication implies. childContinuityBag comes from PALM, not
# from publication, so it lists children that have not published yet - verified against
# a parent whose divisional, filed roughly seven months ago, is already visible. 90 days
# is a deliberately conservative placeholder for the PALM recording lag and is the
# weakest assumption in this module: it decides when an absence becomes reportable, so
# it should be measured against known recent parent/child pairs before being relied on.
ODP_CHILD_LAG_DAYS = 90

# Slack beyond the corpus freeze within which a settled application is still treated as
# live. A child filed just before issuance, or a revival petition, can be recorded after
# the fact; and a revival is generally available for two years after abandonment.
SETTLED_SLACK_DAYS = 730


def odp_horizon() -> date:
    """The date before which an absence in ODP data can be believed."""
    return date.today() - timedelta(days=ODP_CHILD_LAG_DAYS)


# --------------------------------------------------------------------------- planning
def needs_refresh(row: dict, freeze: date) -> tuple[bool, str]:
    """Could live ODP data change any rule's answer for this application?

    Returns (needed, reason). The reason is carried into the report so that a
    corpus-only answer can always say why it was safe not to look.
    """
    status = (row.get("appl_status_desc") or "").lower()
    if "patented case" in status or "patent expired due to nonpayment" in status:
        settled_on = row.get("patent_issue_date") or row.get("appl_status_date")
        kind = "granted"
    elif "abandon" in status:
        settled_on = row.get("appl_status_date")
        kind = "abandoned"
    else:
        return True, "still pending at the corpus freeze - events and status can both have moved"

    if settled_on is None:
        return True, f"{kind} but with no disposal date recorded"
    if settled_on > freeze - timedelta(days=SETTLED_SLACK_DAYS):
        return True, (f"{kind} close to the corpus freeze - a continuing application or a "
                      "revival petition could still have been recorded afterwards")
    return False, f"{kind} well before the corpus freeze; prosecution is closed"


def plan(apps: list[dict], freeze: date | None = None) -> dict:
    """Decide what a top-up would cost, before spending anything.

    Every number here is exact. It is a partition of applications the corpus already
    holds, not a projection of what ODP might return.
    """
    freeze = freeze or rules.CORPUS_HORIZON
    refresh, settled = [], []
    reasons: dict[str, int] = {}
    for row in apps:
        needed, why = needs_refresh(row, freeze)
        (refresh if needed else settled).append(row["application_number"])
        reasons[why] = reasons.get(why, 0) + 1

    calls = -(-len(refresh) // BATCH_SIZE)
    return {
        "applications": len(apps),
        "settled_no_call_needed": len(settled),
        "refresh_needed": len(refresh),
        "refresh_application_numbers": refresh,
        "odp_calls": calls,
        "estimated_seconds": round(calls * SECONDS_PER_BATCH),
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------- fetching
def fetch(app_numbers: list[str], progress=None) -> dict[str, dict]:
    """Retrieve live ODP records for these applications, batched.

    Missing applications are simply absent from the result - ODP not returning a record
    is not evidence of anything, and callers must not read it as absence.
    """
    import odp_client

    out: dict[str, dict] = {}
    batches = [app_numbers[i:i + BATCH_SIZE] for i in range(0, len(app_numbers), BATCH_SIZE)]
    for n, batch in enumerate(batches, 1):
        query = "applicationNumberText:(" + " OR ".join(batch) + ")"
        try:
            data = odp_client.request(
                "/patent/applications/search",
                {"q": query, "limit": BATCH_SIZE, "fields": FIELDS},
            )
        except odp_client.ODPError:
            if len(batch) == 1:
                continue
            # Halve and retry rather than lose the whole batch to one bad record.
            out.update(fetch(batch[:len(batch) // 2]))
            out.update(fetch(batch[len(batch) // 2:]))
            continue
        for wrapper in data.get("patentFileWrapperDataBag") or []:
            out[str(wrapper.get("applicationNumberText"))] = wrapper
        if progress:
            progress(n, len(batches), len(out))
    return out


# ----------------------------------------------------------------------------- merging
def _event_key(d, code):
    return (str(d) if d else None, code)


def merge_facts(corpus_row: dict, wrapper: dict | None) -> rules.AppFacts:
    """One application, both sources, into the shape the rules already read.

    Union the histories; let ODP win on anything that describes the present.
    """
    base = rules.from_corpus(corpus_row)
    if wrapper is None:
        return base

    live = rules.from_odp(wrapper, (wrapper.get("childContinuityBag") or []))

    # Events: union. The corpus reaches back to 1981 and ODP may not; ODP holds
    # everything after the freeze and the corpus cannot. Neither is a superset.
    seen = {_event_key(d, c) for d, c in base.events}
    events = list(base.events) + [
        (d, c) for d, c in live.events if _event_key(d, c) not in seen
    ]

    # Children: union, keyed on the child's application number, ODP winning on type
    # and filing date because a parentage code can be corrected after the fact.
    children = {c.application: c for c in base.children}
    children.update({c.application: c for c in live.children})

    return rules.AppFacts(
        application=base.application,
        source="corpus+odp",
        filing_date=base.filing_date or live.filing_date,
        patent_number=live.patent_number or base.patent_number,
        issue_date=live.issue_date or base.issue_date,
        status=live.status or base.status,
        status_date=live.status_date or base.status_date,
        examiner=live.examiner or base.examiner,
        art_unit=live.art_unit or base.art_unit,
        title=base.title or live.title,
        events=sorted(events, key=lambda e: (e[0] is None, e[0] or date.min)),
        children=sorted(children.values(), key=lambda c: (c.filed is None, c.filed or date.min)),
        children_known=True,
        # Refreshed, so absence is believable up to ODP's own recording lag rather
        # than up to the 2022 corpus horizon.
        horizon=odp_horizon(),
    )


def provenance(corpus_row: dict, wrapper: dict | None) -> dict:
    """What each merged record is built from - recorded per application, so any figure
    can be traced back to the source that produced it."""
    if wrapper is None:
        return {
            "sources": ["corpus"],
            "as_of": str(rules.CORPUS_HORIZON),
            "refreshed": False,
        }
    return {
        "sources": ["corpus", "odp"],
        "as_of": str(date.today()),
        "refreshed": True,
        "odp_last_ingestion": wrapper.get("lastIngestionDateTime"),
    }
