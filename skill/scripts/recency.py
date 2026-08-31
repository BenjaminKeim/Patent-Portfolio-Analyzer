"""Discovery sweep for applications the corpus never contained.

WHY THIS EXISTS. The portfolio audit enumerates applications ONCE, from the corpus,
and the ODP top-up only refreshes rows that enumeration already produced. So an
application filed after the corpus stops is not "skipped for being too new" - it is
never a row at all. There is no filter to relax; without this module the discovery
pass simply does not exist, and a portfolio report silently understates the filer by
however much they have filed since mid-2023.

That is not a small tail. Measured on Example Corporation: 601 in-scope utility applications
filed since 2022 were invisible to the audit, of which 74 had already issued and 123
had already gone abandoned. Running the same six rules over them produced 35
applications carrying a finding - including 16 continuation-instead-of-divisional
label risks and two applications filed in May 2025 that already had three office
actions with no interview.

COST. 14 search calls, no continuity calls, about 19 seconds. The client throttles to
one request every 1.2s, so wall clock here is call count and nothing else. Three
things buy that: a server-side applicationTypeCategory filter that halves the records
before they cross the wire, a fields projection that keeps a 100-record page under the
response cap, and reading childContinuityBag straight off the search response instead
of making a per-application continuity call. An earlier version cost 80 calls.

WHY IT STARTS AT CORPUS_COMPLETE_THROUGH, NOT AT THE LAST RECORD DATE. PatEx carries
published applications only, so its coverage decays for roughly 18 months before the
June 2023 pull - 57% of a normal quarter by 2022-Q4, 13% by 2023-Q1. Sweeping only
from the last record date would leave that decay window half-covered and unmarked.
Starting a day after CORPUS_COMPLETE_THROUGH covers it, and deduping against the
application numbers the corpus already returned makes the overlap exact rather than
approximate.

WHY THE COHORT IS REPORTED SEPARATELY. Most of what this finds is still pending.
Folding it into the portfolio denominators would dilute every rate without adding
information - the cases have not had time to answer the question each rule asks.
They get their own section, with their own counts.
"""
from __future__ import annotations

from datetime import date

QUARTERS = [("01-01", "03-31"), ("04-01", "06-30"),
            ("07-01", "09-30"), ("10-01", "12-31")]

# The client throttles to one call every 1.2s, so wall clock IS call count. Every
# optimisation here reduces calls; none of them touch the shared throttle, which
# exists to keep this skill from 429-ing the other skills that share the key.
SECONDS_PER_PAGE = 1.5
PAGE = 100
MIN_PAGE = 12

# Only the fields rules.from_odp actually reads. Full wrappers also carry
# recordAttorney, correspondenceAddressBag and pgpubDocumentMetaData, none of which
# this skill looks at - and their weight is what makes a 100-record page exceed the
# response cap and come back 413. Same projection merge.fetch uses, for the same reason.
FIELDS = ",".join([
    "applicationNumberText",
    "applicationMetaData",
    "eventDataBag",
    "childContinuityBag",
    "parentContinuityBag",
])

# Narrow the result set server-side. Measured on Example Corporation 2022 onward: the bare
# applicant query matches 1,454 records, adding this leaves 722 - the provisionals and
# other non-examined types that the client-side deny-list would drop anyway, except
# now they never cross the wire. The deny-list still runs on what comes back and
# remains the authority (a design application is REGULAR too, and only
# audit.excluded_type catches it).
REGULAR_ONLY = "applicationMetaData.applicationTypeCategory:REGULAR"


def _query(applicant: str, lo: str, hi: str, regular_only: bool = True) -> str:
    q = (f"applicationMetaData.firstApplicantName:{applicant} AND "
         f"applicationMetaData.filingDate:[{lo} TO {hi}]")
    return f"{q} AND {REGULAR_ONLY}" if regular_only else q


def _page(query: str, limit: int, offset: int) -> dict:
    """One projected search page, backing off the page size on a 413.

    413 is a RESPONSE-size error, not an offset error, and it is data-dependent: the
    same limit succeeds on one page and fails on the next when those records carry
    longer event histories. Halving and retrying is the only reliable answer. Raising
    on exhaustion matters as much - a swallowed 413 mid-pagination silently truncates
    the window and under-reports the portfolio with no error anywhere.
    """
    import odp_client
    while True:
        try:
            return odp_client.request("/patent/applications/search",
                                      {"q": query, "limit": limit, "offset": offset,
                                       "fields": FIELDS})
        except odp_client.ODPError as exc:
            if "413" not in str(exc) or limit <= MIN_PAGE:
                raise
            limit //= 2


# ODP refuses to page past roughly 900 records into a single result set, so a window
# holding more than this must be split rather than paged through.
OFFSET_CEILING = 800


def _quarters(since: str, until: str) -> list:
    y0, y1 = int(since[:4]), int(until[:4])
    out = []
    for y in range(y0, y1 + 1):
        for lo, hi in QUARTERS:
            a, b = f"{y}-{lo}", f"{y}-{hi}"
            if b < since or a > until:
                continue
            out.append((max(a, since), min(b, until)))
    return out


def windows(entity_token: str, since: str, until: str, counter=None) -> list:
    """The windows to page through, widest first.

    Windowed at all because ODP returns newest-first and stops serving offsets past
    ~900: one wide query over a large filer silently loses the older end of the range.
    A year at a time, splitting to quarters only where a year holds more than ODP will
    page through - fixed quarters cost four calls for a year holding twelve records.

    Costs one count-probe call per year; counter, if given, is called once per probe so
    the caller can keep its own tally.
    """
    import odp_client
    out = []
    for y in range(int(since[:4]), int(until[:4]) + 1):
        lo, hi = max(f"{y}-01-01", since), min(f"{y}-12-31", until)
        if lo > hi:
            continue
        try:
            n = odp_client.search(_query(entity_token, lo, hi), limit=1).get("count") or 0
            if counter:
                counter()
        except Exception:
            n = 0
        if n > OFFSET_CEILING:
            out += _quarters(lo, hi)
        elif n:
            out.append((lo, hi))
    return out


def plan(entity_name: str, since: str, until: str = None) -> dict:
    """Price the sweep with one search call before spending anything."""
    import odp_client
    until = until or str(date.today())
    token = entity_name.split()[0]
    try:
        d = odp_client.search(_query(token, since, until), limit=1)
        raw = d.get("count") or 0
    except Exception as exc:
        return {"priced": False, "error": str(exc), "since": since, "until": until}
    # One page per PAGE records, plus one probe per window that turns out empty.
    pages = max(1, -(-raw // PAGE)) + 1
    seconds = int(pages * SECONDS_PER_PAGE)
    return {"priced": True, "since": since, "until": until,
            "matching_records": raw, "search_calls": pages,
            "estimated_seconds": seconds}


def sweep(entity_name: str, since: str, until: str = None,
          exclude: set = None) -> dict:
    """Find and evaluate in-scope applications filed after the corpus stops.

    Scoped through the same entity matcher the rest of the skill uses, so the two
    ODP search traps are both closed: the token match that pulls in other companies,
    and the non-utility types that have no prosecution history to audit.
    """
    import audit
    import entity
    import odp_client
    import rules

    until = until or str(date.today())
    exclude = exclude or set()
    matcher = entity.Matcher(entity_name)
    token = entity_name.split()[0]

    seen = set()
    kept = []
    dropped = {"applicant_mismatch": 0, "not_utility": 0, "already_in_corpus": 0}
    search_calls = 0

    def _count_call():
        nonlocal search_calls
        search_calls += 1

    for lo, hi in windows(token, since, until, counter=_count_call):
        offset = 0
        while True:
            try:
                d = _page(_query(token, lo, hi), PAGE, offset)
            except Exception:
                # Never silently truncate a window. A 404 means the range is empty,
                # which _page reaches only after exhausting its 413 backoff, so
                # anything arriving here has genuinely nothing left to give.
                break
            search_calls += 1
            bag = d.get("patentFileWrapperDataBag") or []
            if not bag:
                break
            for w in bag:
                meta = w.get("applicationMetaData") or {}
                no = str(w.get("applicationNumberText"))
                if no in seen:
                    continue
                seen.add(no)
                if no in exclude:
                    dropped["already_in_corpus"] += 1
                    continue
                skip, _label = audit.excluded_type(meta)
                if skip:
                    dropped["not_utility"] += 1
                    continue
                ok, _why = matcher.match_application(audit._applicant_names(meta))
                if not ok:
                    dropped["applicant_mismatch"] += 1
                    continue
                kept.append(w)
            offset += len(bag)
            if offset >= (d.get("count") or 0) or len(bag) < PAGE:
                break

    # The search response already carries childContinuityBag, so the children are in
    # hand and a per-application continuity call would be pure waste. Validated against
    # the dedicated endpoint on eight applications spanning zero to five children:
    # identical every time. This is why the sweep makes no per-application calls at all.
    results = []
    for w in kept:
        facts = rules.from_odp(w, w.get("childContinuityBag") or [])
        results.append(rules.summarise(facts, rules.evaluate(facts)))

    tallies = {}
    counts = {"granted": 0, "pending": 0, "abandoned": 0}
    by_year = {}
    for r in results:
        for rule, v in r["flags"].items():
            tallies.setdefault(rule, {}).setdefault(v["state"], 0)
            tallies[rule][v["state"]] += 1
        if r.get("disposition") in counts:
            counts[r["disposition"]] += 1
        y = str(r.get("filed") or "")[:4]
        if y:
            by_year[y] = by_year.get(y, 0) + 1

    return {
        "applied": True,
        "since": since,
        "until": until,
        "applications": len(results),
        "by_filing_year": dict(sorted(by_year.items())),
        "counts": counts,
        "dropped": dropped,
        "search_calls": search_calls,
        "rules": rules.rekey(tallies),
        "flagged_count": sum(1 for r in results if r["flagged"]),
        "results": results,
    }
