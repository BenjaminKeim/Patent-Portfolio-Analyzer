---
name: patent-portfolio-analyzer
description: Review US patent prosecution for any company or a single application, and benchmark examiners and art units. Surfaces specific prosecution events from the public record - a restriction requirement with no divisional filed, a first-action allowance with no continuation, an unintentional abandonment evidenced by a petition to revive, three or more office actions with no examiner interview, and more than two RCEs - each identified by application number, filing date and title. Resolves a company name to an exact set of applicant names, reads a local 14.1M-application USPTO corpus, and merges live ODP data for applications still active when the corpus froze. Also answers allowance rate, time to issuance, restriction rate, and examiner or art-unit statistics before drafting an office action response or setting prosecution strategy. Use whenever the user names a company and wants its prosecution reviewed, audited, or checked for problems. Triggers include "review X's prosecution", "audit this portfolio", "any docketing failures", "petitions to revive", "unintentional abandonment", "did we miss a continuation", "was a divisional filed", "how many RCEs", "cases with no interview", "section 121 safe harbor", "examiner allowance rate", "how does art unit 2131 compare", "prosecution statistics", "restriction rate", "portfolio analysis".
---

# Patent Portfolio Analyzer

Prosecution-level analysis of US patent data from two complementary sources, with
rules that surface procedural options that were available and not taken.

## Two sources — pick deliberately

| | Local PatEx corpus | USPTO ODP API |
|---|---|---|
| Contents | 14.1M applications, 507M events, **every applicant** | live file wrapper |
| Currency | **frozen June 2023** | current |
| Cost | free, instant, no key | your own API key, rate-limited |
| Use for | baselines, examiner/art-unit benchmarks, historical sweeps | specific cases, anything filed or decided after mid-2023 |

`audit.py` defaults to `--source auto`: corpus first, ODP when the application is
absent from the snapshot (which usually means it is newer).

**Prefer the corpus for anything statistical.** Benchmarks need volume, not currency,
and the corpus costs nothing. Reserve ODP calls for the specific case in hand.

## Setup

Requires `duckdb` and `requests` (`pip install -r requirements.txt`).

ODP access runs through the shared client in the **`uspto-odp`** skill
(`~/.claude/skills/uspto-odp/scripts/uspto_odp.py`); `scripts/odp_client.py` here is a
thin adapter over it. The key is read from the Windows Credential Manager generic
credential `USPTO_ODP_API_KEY`, falling back to an environment variable of the same
name — see that skill's SKILL.md for the full search order and troubleshooting.
**Never print the key.** Verify everything with:

```powershell
python "$env:USERPROFILE\.claude\skills\patent-portfolio-analyzer\scripts\audit.py" doctor
```

`doctor` reports corpus size and confirms the API answers, without revealing the key.

The corpus is located in this order: `PATEX_DUCKDB`, then `../data/patex.duckdb`
relative to this skill (so it works wherever the repo is cloned), then two legacy
paths. If no corpus is found the skill still runs in ODP-only mode, but **cannot
produce examiner or art-unit baselines** — those need the 507M-event table.

## Commands

```powershell
$S = "$env:USERPROFILE\.claude\skills\patent-portfolio-analyzer\scripts"

# STEP 1 for any portfolio work - resolve the company to an auditable scope
python $S\audit.py resolve "Example Corporation"

# STEP 2 - the prosecution review. ANY company. Give it a name, get a report.
# Merges live USPTO data automatically when it costs under 15s; otherwise quotes it.
python $S\audit.py portfolio "Example Corporation"
python $S\audit.py portfolio "Example Corporation" --topup yes --recent yes
python $S\audit.py portfolio "Example Corporation" --json --full --save example.json

# One application - full prosecution audit
python $S\audit.py app <application_number>

# Several at once
python $S\audit.py apps <application_number> <application_number> ...

# Screen a set from ODP. ALWAYS pass --entity (see warning below).
python $S\audit.py search `
  "applicationMetaData.firstApplicantName:Example* AND applicationMetaData.filingDate:[2018-01-01 TO 2018-12-31]" `
  --entity "Example Corporation" --limit 50

# Benchmarks - corpus only, no API calls
python $S\corpus.py examiner "NGUYEN, KHIEM"
python $S\corpus.py artunit 2131
```

## Step 1: resolve the entity before analysing anything

Portfolio work is scoped to exactly one filer. `resolve` turns a company name into an
explicit list of applicant names and reports what it left out. **Run it first and read
the output** - every downstream figure depends on it, and it is the one step where a
silent error contaminates everything after.

**Policy is strict filer identity.** In scope: the named entity, its renamed and
IP-holding vehicles (Microsoft Technology Licensing is Microsoft), and misspellings.
Out of scope: sibling operating companies, regional arms and joint ventures - LG
Display is not LG Electronics. Those are listed under "related entities" so they can be
opted in deliberately.

**Read the three excluded buckets before quoting any total,** and say what was left out
rather than quoting a total as if it were complete:

- **related entities** - different filers sharing the brand. Excluded by policy.
- **UNCERTAIN** - possibly the filer's own regional or research arm, indistinguishable
  from patent data. Excluded, but reported with the application count at stake. If any
  belongs to the filer, the denominator is understated by that much.
- **NEAR MISS** - the company name spelled differently by one character, so exact
  matching puts it out of scope. Usually the filer's own applications with a USPTO typo
  (QUALCOM, SUMSUNG, MICROSFT). Volume is small, but **look at the list** and say so if
  it is material - it is a review list, not a candidate scope.

How names are matched, why short names get no typo budget, and why Jaro-Winkler is
never used: `reference/entity-resolution.md`.

## Step 2: the portfolio profile

`portfolio` reads `applicant_organization` directly, so it works for **any company** —
a global filer, a mid-size manufacturer, a two-application startup. It evaluates every application with
the same rules a single-application audit uses, so the two can never disagree.

**Do not use `app_company`, `cohort`, `app_facts` or `app_flags` for company work.**
They are site-era derived tables frozen at 20 companies and filing years 2013–2019.
They look like a general company index and are not one. The corpus underneath covers
every applicant.

**The filing floor is 2012 and should stay there.** USPTO only began recording
applicant organisation after the AIA — coverage is ~0% before 2012, 65% in 2013, ~90%
from 2015. A pre-2012 portfolio is not small, it is unrecorded, and the 2013–14 ramp
looks like filing growth without being it.

## Step 3: the ODP top-up

`portfolio` merges live ODP data into the corpus result. It is **not** a choice of
source — every rule reads a count or an absence, and both straddle the freeze:

- Two RCEs before June 2023 and a third after it is a more-than-two-RCEs finding that
  neither source shows on its own.
- An interview after the freeze **retracts** a no-interview finding the corpus reports.
- A divisional filed in 2024 **retracts** a no-divisional finding; a continuation before
  a 2022 issuance retracts a no-continuation finding.

So events and children are **unioned**; status and dates come from ODP.

**Only applications that were still live at the freeze need a call.** One settled well
before it is finished — prosecution is over, no further events can accrue, and its
copendency and revival windows have closed. That is ~45% of a typical portfolio
answered for nothing. The split is exact, computed from the corpus, and costs no calls.

`--topup auto` (the default) runs the merge when it costs under 15 seconds and
otherwise reports the price and proceeds corpus-only. `--topup yes` always merges;
`--topup no` never does. Measured: 100 applications per request in ~1.8s, so roughly
2,000 records a minute.

| | Free findings | Needs a call | Cost |
|---|---|---|---|
| 25-application filer | 0 | 25 | 1 call, 3s — runs automatically |
| 2,200-application filer | 552 | 1,650 | 17 calls, ~51s — quotes and asks |
| large filer | — | ~2,900 | ~29 calls, ~1.5 min |
| very large filer | — | ~14,500 | ~145 calls, ~7 min |

A filer whose applications were all still pending at the freeze is the case that
shows why this matters: the corpus alone yields **zero** findings. One call surfaces
six.

## Step 4: the recency sweep - what the top-up cannot reach

**The top-up refreshes; it does not discover.** Enumeration happens once, in the
corpus, and the top-up only revisits rows that enumeration produced. An application
filed after the corpus stops is therefore not "skipped for being too new" - it is
never a row at all. There is no filter to relax. Without the sweep a portfolio report
silently ends at the corpus horizon and does not say so.

That gap is large. Example Corporation: **601 in-scope utility applications** filed since
2022-01-01 that the audit never saw, of which 74 had already issued and 123 had
already gone abandoned. Same six rules, **35 applications carrying a finding** - 16
continuation-instead-of-divisional label risks, and two applications filed in May 2025
that already had three office actions with no interview.

`--recent auto` (the default) sweeps when the price is under 120 seconds and otherwise
quotes it; `--recent yes` always sweeps, `--recent no` never does. Example Corporation costs 14
search calls and about 19 seconds.

**It starts a day after `CORPUS_COMPLETE_THROUGH` (2022-01-01), not at the June 2023
last-record date,** because PatEx coverage decays for ~18 months before the pull. The
overlap is deduped exactly against the application numbers the corpus returned.

**Report the cohort separately, never merged into the rates above.** Most of it is
still pending - 404 of Example Corporation's 601 - so folding it in would dilute every rate
without answering anything. These cases have not had time to answer the question each
rule asks.

Windowing, the 413 trap, the server-side filter and the field projection are all in
`reference/odp-access.md`. Read it before changing anything that builds a query or
pages a result set.

## The response cache

Every ODP response is cached to disk, dated. A full Example Corporation audit is 58 seconds cold
and **16 seconds warm**; what remains is DuckDB, not the network.

```powershell
python $S\audit.py cache                                    # location, size, date range
python $S\audit.py portfolio "Example Corporation"                    # uses cache under 14 days old
python $S\audit.py portfolio "Example Corporation" --cache refresh    # fetch fresh, file a new copy
python $S\audit.py portfolio "Example Corporation" --stale-ok         # proceed on old data, say so
```

**Nothing is ever deleted** - each fetch is filed beside the last, so the cache is also
the record of what USPTO said about a portfolio on a given day. **Stale data is never
served silently**: past 14 days the run stops and asks, and exits 2 rather than guess
when no one is there to answer. Any report that used the cache says so, with the age of
the oldest response.

Wiring, key canonicalisation and the bug that made the top-up miss 100% of the time:
`reference/odp-access.md`.

## Step 5: the report

`portfolio` prints a readable report by default (`--json` for the raw result,
`--max-cases N` to limit each list, `0` for all). Layout: portfolio counts with the
filing window stated, at-a-glance bars, the prosecution events with each case
identified by application number, filing date and title, the recency cohort, then
coverage and caveats.

**Every bar names its own denominator, and that is the whole point.** A rule is charted
against the cases where it *could* fire, never against the portfolio. Example Corporation's
no-divisional rule fired 837 times, but it can only fire on an application that drew a
restriction and has closed - 1,151 of them, not 1,996. Charting 837/1,996 would
understate it by nearly half. How each eligible set is derived, and why the RCE row is
the one incidence rate among conditional rates, is in `reference/denominators.md`.

**Build any visual from `at_a_glance` in the JSON** - the same rows `chart.summary()`
gives the terminal bars - never from a hand-recount, so a chart cannot drift from what
the bars say.

**A rule firing on more than 10% of a portfolio, on 20+ cases, carries a note saying it
describes filing practice rather than individual lapses.** One filer in this corpus had
153 first-action allowances without a continuation - 18% of its portfolio, which is how
that company prosecutes, not 153 mistakes. The cases are still listed; the note stops the
list being read as an error count. Both conditions are needed: three of 25 applications
is 12% and is still just three cases.

Under 50 evaluable cases a row is marked "small sample - read the count, not the rate",
on the same reasoning the skill applies to examiner statistics.

## Step 6: the widget comes first in the reply

**Lead every portfolio reply with a `mcp__visualize__show_widget` panel.** The bars in
the terminal report are for the person running the command; the widget is what Ben
actually reads first, and it is where he opens a rule to see its cases without running
anything else. A portfolio reply that is prose only is incomplete.

Build it from `at_a_glance` in the JSON — the same tallies `chart.summary()` gives the
terminal bars, so the two cannot disagree. Amber means the condition was met, gray means
INDETERMINATE, teal means it was not met; **never red**, because these are unexercised
options and red reads as an error count.

Read `reference/widget-recipe.md` before writing any markup, and call
`mcp__visualize__read_me` with modules `["data_viz","interactive"]` first, as that file
says.

The widget holds the visual only. Every piece of explanation — the confounders, the
coverage caveats, the unexercised-options framing, what a rate actually means — goes in
the chat response around it, never inside the panel.

## ODP search will silently corrupt an audit if you let it

Four traps, all with measured evidence, in `reference/odp-access.md`: the applicant
query matches on any word in the name; results are newest-first with provisionals mixed
in; the application type lives in two fields that disagree; and `413` is a response-size
error that must never be swallowed. Every one of them produces a plausible-looking
report rather than an error.

The operational rule: **always pass `--entity`**, always bound the filing date, and use
`audit.excluded_type(meta)` rather than testing a type field yourself. If
`dropped_applicant_mismatch` is large the query was too loose - say so when reporting,
and never present a raw search count as a portfolio size.

## Rules

Six rules. Each returns one of `PRESENT`, `FLAG`, `INDETERMINATE`, `N/A`.

`rules.RULES` is the single registry - name, report order, explanatory text, eligible
set and denominator wording, all in one table. It used to be five dicts across three
files and they drifted; the table below restates it for reading, but the code is
authoritative.

| Rule | Fires when |
|---|---|
| **Restriction issued, no divisional filed** | A restriction requirement issued and no divisional was ever filed |
| **Restriction issued, child filed as a continuation rather than a divisional** | A restriction issued and a child was filed, but designated a continuation |
| **First-action allowance, no continuation filed** | Allowed on the first action, and no continuing application was filed before issuance |
| **Three or more office actions, no examiner interview** | Three or more office actions with no examiner interview |
| **More than two RCEs** | More than two RCEs |
| **Petition to revive** | The application went abandoned unintentionally, evidenced by a petition to revive |

**NEVER surface a rule's internal code.** The engine keys these rules `A1`, `B1`, `B2`,
`D2`, `D3` and `E1` in `rules.py`, and those keys still appear in per-case `flags` and
`flagged` inside `results[]`. They are dict keys and nothing more — they carry no
meaning to a reader, and a report that says "B1 fired 837 times" has told the reader
nothing. Name a rule by its description, everywhere, in the terminal report, the chat
write-up, the widget and any document. `rules.RULE_NAMES` is the single place the
wording lives; `rules.name(key)` resolves one and `rules.rekey()` renames a whole
tally block. The JSON's top-level `rules`, `tallies` and `at_a_glance` are already
named, and `rule_names` decodes the per-case flags.

**Petition to revive keys on the petition, not the abandonment.** 774,934 modern
utility applications went abandoned for failure to respond — that is simply the normal,
cheap way to drop a case you have decided not to pursue, and flagging it would be
almost entirely false positives. Nobody petitions to revive a case they meant to
abandon, so the petition is what separates a docketing failure from a deliberate
decision. Measured: 42,444 granted, 211 dismissed. A dismissed petition with no later
grant means the application was lost.

**Two of the six can be disproved by a later filing.** The no-continuation and
no-divisional rules are absence findings, and a continuation or divisional filed after
the corpus froze retracts them. That is what the merge below exists to prevent.

**The first-action allowance rule** matters because a first-action allowance means the
examiner found nothing worth citing against the claims as presented — the strongest
signal in the public record that scope was left unclaimed. Only children filed
**before** the parent issued count, since § 120 requires copendency.

**The continuation-instead-of-divisional rule** matters because § 121's safe harbour
against double-patenting rejections attaches to a divisional filed as a result of the
restriction. Courts look to substance and consonance rather than the ADS label, so it
is a risk flag warranting review, never a conclusion.

## How to report results — read this before writing anything up

**Name rules by their description, never by their internal code.** `A1`, `B1`, `D2` and
the rest are dict keys in `rules.py` and mean nothing to a reader — see Rules below.

**These are unexercised options, not errors.** The public record contains no client
instruction, budget, or strategy. No rule here can distinguish a mistake from a
deliberate decision, and reports must not imply otherwise.

This is not just phrasing. A document characterising prosecution decisions as errors
is discoverable, and running this over Ben's own or a client's portfolio produces
exactly such a document. Use "review flag", "unexercised option", "warrants review".
Never "error", "mistake", "missed", or "failure". Never present a portfolio-level
error count.

**Three states, always distinguished.** `FLAG` means enough time passed for a filing
to appear and it did not. `INDETERMINATE` means the case was disposed too close to
the data horizon to tell — for the corpus that horizon is June 2022, for ODP roughly
18 months back. Never fold INDETERMINATE into FLAG, and never count it as a finding.

**Confounders to state when comparing companies or examiners:**

- **Restriction rate tracks technology, not practice.** Semiconductor and display
  filers run 20–40%; software and communications filers 4–7%. Comparing across
  technology centres without saying so is misleading.
- **Foreign-origin filers use continuations far less** as a matter of house style.
  A high first-action-allowance rate for a Japanese or Chinese filer reflects filing
  culture, not a lapse. Check the § 371 national-stage share before drawing conclusions.
- **Examiner samples get small fast.** Under ~50 applications, an allowance rate is
  noise. Report the denominator alongside every rate.
- Always give an examiner's figure next to their art unit's — the absolute number
  means little without it.

## Writing about this skill

**Numbers in the docs carry magnitude or format, never identity.** A measurement
calibrates a decision and belongs here: 1,454 records to 722 after the server-side
filter, 80 calls to 14, 58 seconds to 16, 837 of 1,151. A specific application number
tells a future reader nothing they can act on - the lesson in "a filter reading one
type field let a design application through" is the mechanism, not which design it was.

A placeholder identifier is worse than none. A fake application number in a sentence
that reads like a citation looks like provenance while citing nothing, and invites
someone to go look it up. Drop the identifier and state the mechanism.

Real identifiers belong only where they are INPUT rather than illustration - and even
then, prefer discovering them. The live merge test used to name three applications to
prove a point about batching that had nothing to do with which applications were used;
it now searches for its own fixtures, which also stopped a newly filed continuation
from failing the test. The synthetic numbers left in the offline unit tests are
fabricated inputs, and the two in the widget recipe demonstrate a display format, which
is the one case where the number IS the content.

## Known limits

- Corpus is frozen at June 2023. For a single application `--source odp` covers it;
  for a portfolio the recency sweep (Step 4) is the only thing that finds later
  filings at all, because the top-up cannot discover a row the corpus never held.
- Corpus applicant-organisation coverage is ~0% before 2012 (the AIA changed
  applicant recording), 65% in 2013, ~90% from 2015. Company-level work before 2013
  is not possible from this field.
- US only. No other office publishes prosecution data at this granularity.
- Report ordering is stable: cases sort by filing date AND application number, so two
  runs over the same data diff cleanly. Filing date alone left ties broken by fetch
  order, which differs between a cold run and a cached one.
- The restriction rules detect that a restriction *occurred*, not which groups were
  defined or elected. That needs the office action text, which neither source exposes here.
- Entity resolution enumerates names from the corpus, so a filer that only ever
  appears after June 2023 resolves to nothing. `resolve` says so in its warnings.
  Live ODP names absent from the corpus are still classified by the same rules, so
  scoping a search does not depend on the name being in the snapshot.
- Applicant organisation is ~0% populated before 2012, so entity resolution cannot
  scope a pre-2013 portfolio at all.
