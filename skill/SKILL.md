---
name: patent-portfolio-analyzer
description: Analyze US patent prosecution at the portfolio or single-application level, and benchmark examiners and art units. Use when the user asks about allowance rate, time to issuance, office action counts, restriction practice, first-action allowances, missed continuations or divisionals, or wants a prosecution audit of a company's portfolio or specific applications. Also use for examiner statistics ("what's this examiner's allowance rate", "how does art unit 2131 compare") before drafting an office action response or setting prosecution strategy. Triggers include "audit this portfolio", "prosecution statistics", "examiner allowance rate", "did we miss a continuation", "was a divisional filed", "how does this examiner compare", "portfolio analysis", "restriction rate".
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

The ODP key is read from the Windows Credential Manager generic credential
`USPTO_ODP_API_KEY`, falling back to an environment variable of the same name (the
mechanism `patent-filing-qc` uses). **Never print the key.** Verify everything with:

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
python $S\audit.py resolve "Microsoft Corporation"

# STEP 2 - the prosecution review. ANY company. Give it a name, get a report.
# Merges live USPTO data automatically when it costs under 15s; otherwise quotes it.
python $S\audit.py portfolio "Molex, LLC"
python $S\audit.py portfolio "NVIDIA Corporation" --topup yes
python $S\audit.py portfolio "Molex, LLC" --json --full --save molex.json

# One application - full prosecution audit
python $S\audit.py app 14973095

# Several at once
python $S\audit.py apps 14973095 15162264 16039495

# Screen a set from ODP. ALWAYS pass --entity (see warning below).
python $S\audit.py search `
  "applicationMetaData.firstApplicantName:Microsoft* AND applicationMetaData.filingDate:[2018-01-01 TO 2018-12-31]" `
  --entity "Microsoft Corporation" --limit 50

# Benchmarks - corpus only, no API calls
python $S\corpus.py examiner "NGUYEN, KHIEM"
python $S\corpus.py artunit 2131
```

## Step 1: resolve the entity before analysing anything

Portfolio work is scoped to exactly one filer. `resolve` turns a company name into an
explicit list of applicant names, and reports what it left out and how much volume that
represents. **Run it first and read the output** — every downstream figure depends on
it, and it is the one step where a silent error contaminates everything after.

**Policy is strict filer identity.** In scope: the named entity, its renamed and
IP-holding vehicles (Microsoft Technology Licensing is Microsoft), and misspellings.
Out of scope: sibling operating companies, regional arms, and joint ventures — LG
Display is not LG Electronics, Samsung Display is not Samsung Electronics. Those are
listed under "related entities" so they can be opted in deliberately.

**How names are matched.** Token boundaries, never substrings. Then two different
standards depending on what kind of word it is:

- **The company name itself must match EXACTLY** at or below 10 characters — no typo
  budget. At that length a single edit is as likely to be a different company as a
  misspelling (NVIDIA/AVIDIA, INTEL/INTEC, SAMSUNG/SAMSIN). Above 10 characters a
  bounded edit distance applies, so MANUFACTURING still matches MANFACTURING.
- **Corporate-form and boilerplate words tolerate typos** — Corp., Ltd., Incorporated,
  Technology, Licensing, Holdings. These are a small closed vocabulary, so fuzzy
  matching cannot pull in an unrelated brand, and USPTO's own records contain
  COPORATION, INCORPORTED, TECHNOLGOY and LICESNING.

Never Jaro-Winkler at any length — it merged 169 unrelated companies into Intel. See
"Entity resolution" in `CONTEXT.md`.

**Read the three excluded buckets before quoting any total:**

- **related entities** — different filers that share the brand. Excluded by policy.
- **UNCERTAIN** — names that may be the filer's own regional or research arm and cannot
  be told apart from patent data. Excluded, but reported with the application count at
  stake. If any belongs to the filer, the denominator is understated by that amount.
- **NEAR MISS** — the company name is spelled differently by one character, so exact
  matching puts it out of scope. These are usually the filer's own applications with a
  USPTO typo (QUALCOM, SUMSUNG, MICROSFT, LNTEL). Volume is small — tens of
  applications on a portfolio of tens of thousands — but **look at the list** and say
  so if it is material. A short brand token has a crowded neighbourhood, so Intel's
  near-miss list also contains real companies such as INTEX and INTEC; it is a review
  list, not a candidate scope.

**Say so when reporting** rather than quoting a total as if it were complete.

`decisions.csv` EXCLUDE rulings bind here. Its *merge* rulings deliberately do not:
they encode the corporate-family rollup used for IFI-style ranking, which is the
opposite of strict filer identity.

## Step 2: the portfolio profile

`portfolio` reads `applicant_organization` directly, so it works for **any company** —
NVIDIA, Molex, Boeing, a two-application startup. It evaluates every application with
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

- Two RCEs before June 2023 and a third after it is a D3 finding neither source shows.
- An interview after the freeze **retracts** a D2 finding the corpus would report.
- A divisional filed in 2024 **retracts** B1; a continuation before a 2022 issuance
  retracts A1.

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
| Neuralink | 0 | 25 | 1 call, 3s — runs automatically |
| NVIDIA | 552 | 1,650 | 17 calls, ~51s — quotes and asks |
| Microsoft | — | ~2,900 | ~29 calls, ~1.5 min |
| Samsung | — | ~14,500 | ~145 calls, ~7 min |

Neuralink is the case that shows why this matters: the corpus alone yields **zero**
findings because everything was still pending when it froze. One call surfaces six.

## Step 4: the report

`portfolio` prints a readable report by default (`--json` for the raw result). Findings
are triaged, because the engine will return 257 findings on an 840-application portfolio
and that is not a to-do list:

- **Act on these** — E1 and B2. Specific procedural defects on specific cases.
- **Worth reviewing** — a rule firing on under 10% of the portfolio. Listed individually.
- **Portfolio patterns** — a rule firing on more than 10%. Reported as a rate with a
  small sample, never as a list, because at that volume it describes filing strategy
  rather than individual lapses. Molex's 153 first-action allowances without a
  continuation is a house pattern, not 153 mistakes.

**Do not present a pattern as a finding count.** That is the distinction the triage
exists to preserve, and it is also what keeps the report defensible.

When the top-up is declined, say so — the report is corpus-only and counts on live
applications may be understated. `topup.offer` carries the exact wording and price.

**Read the `coverage` block before quoting anything.** The corpus stops at June 2023,
and the three-state logic uses a stricter June 2022 horizon so a recently disposed case
reports INDETERMINATE rather than FLAG. `incomplete_after` says where this account
stops; anything later needs an ODP top-up, and `odp_topup_applied` records whether one
was done. Never present a corpus-only portfolio as current.

`reporting_notes` comes back populated with the confounders that apply to that specific
entity — small denominator, national-stage share, restriction rate. Use them; they are
generated because these numbers are routinely misread without them.

## Two traps in ODP search — both will silently corrupt a portfolio audit

**1. Applicant search matches on any word in the name.** ODP tokenises the query, so
`firstApplicantName:Taiwan Semiconductor*` returns anything containing "Semiconductor".
Measured on a real run: **15 of 20 results were other companies** — SK hynix, Micron,
Denso, Renesas, Dialog Semiconductor, GlobalWafers. Only 2 were genuinely TSMC.

Always pass `--entity "<company>"`. It scopes the result set through the resolver above,
tests **every** applicant on each record rather than just the first (joint filings are
real — Hyundai and Kia co-file 5,879 applications), and reports each dropped record with
the reason. If `dropped_applicant_mismatch` is large the query was too loose — say so
when reporting, and never present the raw search count as a portfolio size.

**2. Results are newest-first, and provisionals are included.** A bare applicant search
returns applications filed weeks ago with no prosecution history, so every rule comes
back `N/A` and the audit looks clean when it is simply empty. Bound the filing date to
a cohort old enough to be disposed. Provisionals, designs, plants and reissues are
dropped automatically (`--include-non-utility` to keep them).

## Rules

Each returns one of `PRESENT`, `FLAG`, `INDETERMINATE`, `N/A`.

| Rule | Fires when |
|---|---|
| **A1** | Allowed on the first action, and no continuing application was filed before issuance |
| **B1** | A restriction requirement issued and no divisional was ever filed |
| **B2** | A restriction issued and a child was filed, but designated a continuation rather than a divisional |
| **D2** | Three or more office actions with no examiner interview |
| **D3** | More than two RCEs |
| **E1** | The application went abandoned unintentionally, evidenced by a petition to revive |

**E1 keys on the petition, not the abandonment.** 774,934 modern utility applications
went abandoned for failure to respond — that is simply the normal, cheap way to drop a
case you have decided not to pursue, and flagging it would be almost entirely false
positives. Nobody petitions to revive a case they meant to abandon, so the petition is
what separates a docketing failure from a deliberate decision. Measured: 42,444 granted,
211 dismissed. A dismissed petition with no later grant means the application was lost.

**Two of the six can be disproved by a later filing.** A1 and B1 are absence findings —
"no continuation", "no divisional" — and a continuation or divisional filed after the
corpus froze retracts them. That is what the merge below exists to prevent.

**A1** matters because a first-action allowance means the examiner found nothing
worth citing against the claims as presented — the strongest signal in the public
record that scope was left unclaimed. Only children filed **before** the parent
issued count, since § 120 requires copendency.

**B2** matters because § 121's safe harbour against double-patenting rejections
attaches to a divisional filed as a result of the restriction. Courts look to
substance and consonance rather than the ADS label, so B2 is a risk flag warranting
review, never a conclusion.

## How to report results — read this before writing anything up

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
  A high A1 rate for a Japanese or Chinese filer reflects filing culture, not a
  lapse. Check the § 371 national-stage share before drawing conclusions.
- **Examiner samples get small fast.** Under ~50 applications, an allowance rate is
  noise. Report the denominator alongside every rate.
- Always give an examiner's figure next to their art unit's — the absolute number
  means little without it.

## Known limits

- Corpus is frozen at June 2023; anything later needs `--source odp`.
- Corpus applicant-organisation coverage is ~0% before 2012 (the AIA changed
  applicant recording), 65% in 2013, ~90% from 2015. Company-level work before 2013
  is not possible from this field.
- US only. No other office publishes prosecution data at this granularity.
- B1/B2 detect that a restriction *occurred*, not which groups were defined or
  elected. That needs the office action text, which neither source exposes here.
- Entity resolution enumerates names from the corpus, so a filer that only ever
  appears after June 2023 resolves to nothing. `resolve` says so in its warnings.
  Live ODP names absent from the corpus are still classified by the same rules, so
  scoping a search does not depend on the name being in the snapshot.
- Applicant organisation is ~0% populated before 2012, so entity resolution cannot
  scope a pre-2013 portfolio at all.
