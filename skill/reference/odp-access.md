# ODP access — the traps, the costs, and the cache

Everything learned the hard way about talking to the Open Data Portal from this skill.
SKILL.md carries the rules; this file carries the evidence behind them. Read it before
changing anything that builds a query, pages a result set, or touches the cache.

## Wall clock is call count

The shared client throttles to one request every 1.2 s. Nothing else in the network path
matters at this scale, so every optimisation below is a call-count reduction and nothing
is gained by parallelism.

**Do not "optimise" by loosening that throttle.** It lives in the shared `uspto-odp`
skill and it is what stops this skill 429-ing every other skill using the same key.

## Four traps, each of which silently corrupts an audit

**1. Applicant search matches on any word in the name.** ODP tokenises the query, so
`firstApplicantName:Taiwan Semiconductor*` returns anything containing "Semiconductor".
Measured on a real run: 15 of 20 results were other companies — SK hynix, Micron, Denso,
Renesas, Dialog Semiconductor, GlobalWafers. Only 2 were genuinely TSMC. Always scope
through `--entity`, which tests every applicant on each record, not just the first
(joint filings are real — Hyundai and Kia co-file 5,879 applications).

**2. Results are newest-first, and provisionals are included.** A bare applicant search
returns applications filed weeks ago with no prosecution history, so every rule comes
back `N/A` and the audit looks clean when it is simply empty. Bound the filing date to a
cohort old enough to be disposed.

**3. The application type lives in two fields that disagree.** A design application comes
back as `applicationTypeCategory: "REGULAR"` with the real type only in
`applicationTypeCode: "DES"`. A filter reading the category alone lets every design
through, and one was scored as a first-action allowance with no continuation before this
was caught — a design patent cannot have a continuation, so the finding was nonsense on
its face and still shipped. Use
`audit.excluded_type(meta)`, which checks both. It stays a deny-list rather than an
allow-list so an unfamiliar code is kept and visible rather than silently dropped.

**4. `413` is a response-size error, not an offset error, and it must never be
swallowed.** It is data-dependent: the same page limit succeeds on one page and fails on
the next when those records carry longer event histories. `recency._page` halves the page
size and retries, and raises once it cannot. An earlier version caught it and `break`-ed,
which silently truncated the window — that one bug under-reported Example Corporation by 31
applications and 4 findings, with no error anywhere in the output.

## Three things that keep the call count down

- **Filter server-side.** `applicationMetaData.applicationTypeCategory:REGULAR` halves the
  result set before it crosses the wire — 1,454 records to 722 on Example Corporation. Verified
  against an unfiltered pull: it removes only provisionals, PCT and reissues, exactly what
  the deny-list drops anyway, and it keeps § 371 national-stage applications. The
  deny-list still runs and remains the authority, because a design application is REGULAR
  too.
- **Project the fields.** Full wrappers carry `recordAttorney`, `correspondenceAddressBag`
  and `pgpubDocumentMetaData`, none of which this skill reads, and their weight is what
  pushes a 100-record page over the response cap.
- **Read `childContinuityBag` off the search response.** It is already there. Validated
  against the dedicated continuity endpoint on eight applications spanning zero to five
  children — identical every time. This removed 58 per-application calls from a single
  Example Corporation sweep, and is why the sweep makes no per-application calls at all.

## Windowing

ODP stops serving offsets past roughly 900 records into one result set, so a wide query
over a large filer silently loses the older end of the range. `recency.windows()` probes
one year at a time and splits to quarters only where a year exceeds `OFFSET_CEILING`.
Fixed quarters were the first attempt and cost four calls for a year holding twelve
records.

## The response cache

Wired at this skill's `odp_client` adapter, never inside the shared `uspto_odp` module —
other skills import that and must not inherit this policy; a filing-receipt check wants
live data every time. `doctor` is deliberately uncached, because its whole job is
reporting whether the API answers right now.

**Nothing is ever deleted.** Each fetch writes a new dated entry beside the previous one
and reads take the newest. The cache is the only record of what USPTO was saying about a
portfolio on a given day, and for a prosecution audit that provenance can matter more
than the speed. About 4.5 MB per full company audit.

**Stale data is never served silently.** Past `--cache-days` (14) the run stops. On a
terminal it prompts once and the answer settles the whole run; anywhere else it exits 2
with a message naming the age. `isatty()` is not trusted as proof someone is there to
answer — if the prompt raises EOF, that is treated as "cannot ask" and the run stops.

**Cache keys must be canonical.** The key is a hash of the request, so any instability in
how a request is built defeats the cache while appearing to work. This bit once already:
`merge.fetch` batched application numbers in whatever order DuckDB returned them, which
differs between processes, so the batch query text changed every run and the top-up missed
100% of the time while the sweep's hits made the cache look healthy. `merge.fetch` now
sorts before batching. **Anything that builds a query from a corpus result set must do the
same** — DuckDB gives no order guarantee without `ORDER BY`.

The same instability produced unstable report ordering, which is why `report._cases` sorts
by filing date *and* application number: two runs over identical data have to diff cleanly.

## Measured costs

| | Cold | Warm |
|---|---|---|
| Example Corporation, full audit (top-up + sweep) | 58 s | 16 s |
| — of which the recency sweep | 14 calls, 19 s | ~3 s |
| — of which DuckDB | 12 s | 12 s |

Everything left in the warm run is DuckDB against the 507M-event table, not the network.
