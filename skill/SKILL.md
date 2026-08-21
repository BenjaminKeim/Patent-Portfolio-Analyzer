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
| Contents | 14.1M applications, 507M prosecution events | live file wrapper |
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

# One application - full prosecution audit
python $S\audit.py app 14973095

# Several at once
python $S\audit.py apps 14973095 15162264 16039495

# Screen a set from ODP. ALWAYS pass --applicant (see warning below).
python $S\audit.py search `
  "applicationMetaData.firstApplicantName:Microsoft* AND applicationMetaData.filingDate:[2018-01-01 TO 2018-12-31]" `
  --applicant "Microsoft" --limit 50

# Benchmarks - corpus only, no API calls
python $S\corpus.py examiner "NGUYEN, KHIEM"
python $S\corpus.py artunit 2131
```

## Two traps in ODP search — both will silently corrupt a portfolio audit

**1. Applicant search matches on any word in the name.** ODP tokenises the query, so
`firstApplicantName:Taiwan Semiconductor*` returns anything containing "Semiconductor".
Measured on a real run: **15 of 20 results were other companies** — SK hynix, Micron,
Denso, Renesas, Dialog Semiconductor, GlobalWafers. Only 2 were genuinely TSMC.

Always pass `--applicant "<phrase>"`. It post-filters on the actual applicant name and
reports how many records it dropped. If `dropped_applicant_mismatch` is large, the
query was too loose — say so when reporting, and never present the raw search count as
a portfolio size.

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
