# Project context

Decisions, dead ends, and details that cost real effort to establish. Deliberately does
**not** repeat what `README.md` or `skill/SKILL.md` already cover — read those first.

Written 2026-08-03.

---

## How the project arrived here

The original goal was a public web dashboard for patent portfolio analysis. It was built
and worked locally. It was abandoned not because it failed technically but because of a
ceiling: a public site cannot use a personal ID.me-verified USPTO key for anonymous
visitors, so its data had to be precomputed — 20 companies, one frozen cohort. A skill
running locally with your credentials has no such ceiling.

Worth recording because it was briefly misdiagnosed: **the website did not fail on API
limits.** By the end it made zero runtime API calls — it ran on PatEx bulk data. Its last
failure was a Vercel root-directory misconfiguration, one setting from working.

## Data-source evaluation (don't redo this)

Live APIs were the obvious first idea and are the wrong primary source for portfolio
work. A prosecution audit needs roughly 3 ODP calls per application; at ~60 req/min a
100,000-application portfolio is ~3.5 days. **Bulk data eliminated that entirely.**

Sources considered and rejected:

- **Google Patents / BigQuery** — no transaction history at all. `CTRS`, `CTNF`,
  first-action allowance are USPTO-internal artifacts that do not exist outside USPTO
  systems. Also needs a GCP billing account. The `google/patents-public-data` repo was
  archived April 2026.
- **IFI CLAIMS** — excellent for global breadth, full text, standardised entity names.
  Does **not** carry US prosecution transaction history. Institutional subscription.
  Their standardised assignee names are the one thing worth paying for, and PatentsView
  gives you a free US-only equivalent.
- **Lens.org** — institutional subscription only; cannot be a base layer.
- **EPO OPS / BDDS** — as of 1 Jan 2025 seven EPO datasets are free in the BDDS Public
  Area (DOCDB, INPADOC, EP full text, Register back file, EBD, Boards of Appeal
  decisions, sequence listings). Genuinely useful for families and legal status. But no
  office outside the US publishes prosecution events at the needed granularity.
- **PEDS bulk (PEDSXML/PEDSJSON on ODP)** — a tombstone. PEDS retired 15 Mar 2025 and
  the static dump covers **1900–2000 only**. Not the modern data; easy to mistake for it.

The commercial landscape splits three ways, and nothing occupies the middle: portfolio
valuation (PatentSight, Cipher), search/analytics (PatSnap, Derwent, Orbit, AcclaimIP),
and prosecution analytics (PatentAdvisor, Juristat). **Nobody sells entity-level
prosecution statistics for a third party's portfolio** — PatentAdvisor computes
allowance rates for *examiners*, not companies. That gap is what this project fills.

Vendors avoid the API problem entirely by ingesting licensed bulk data into their own
warehouses and selling seats. Per-user API keys never enter the picture. The credential
problem is a symptom of live-API architecture.

## Schema facts that are easy to get wrong

These were each found by hitting them:

- **`continuation_type` lives on the CHILD's row** in `continuity_parents`, pointing at
  its parent. To find children of X: `WHERE parent_application_number = X`. Reverse it
  and you get silently empty results, not an error. `continuity_children` has the child
  filing date but **no relationship type** — you must join both.
- **`"Patent Expired Due to NonPayment of Maintenance Fees"` is a GRANTED outcome**, not
  an abandonment. 2.5M applications corpus-wide. Counting only `"Patented Case"`
  undercounts grants badly.
- **PatEx has no CPC.** Technology comes from `examiner_art_unit` → technology centre.
  ODP *does* have `cpcClassificationBag`, so live records classify better.
- **ODP codes utility applications as `REGULAR`**, not "Utility". PatEx uses `"Utility"`.
  Filtering ODP for the string "utility" drops everything.
- **DuckDB does not auto-detect the quote character** on the PatEx CSVs — values like
  `"PCT/FR99/02,868"` contain commas inside quotes. Pass `quote='"'` explicitly.
- **Application numbers must stay VARCHAR.** Leading zeros; numeric inference corrupts joins.
- `event_codes` is only ~87% documented — 283 of 2,194 codes have a description equal to
  the code itself. All 28 rule-critical codes are documented.

## ODP API behaviour

- **Search returns `eventDataBag` inline** — the full event history, same codes as the
  corpus. One search call screens many applications. Only `parentContinuityBag` is
  inline; **children require a `/continuity` call**, which returns `childContinuityBag`.
  Screen in bulk, confirm candidates selectively.
- **Applicant search tokenises.** `firstApplicantName:Taiwan Semiconductor*` matches
  anything containing "Semiconductor". Measured: **15 of 20 results were other
  companies** (SK hynix, Micron, Denso, Renesas, Dialog, GlobalWafers). Always
  post-filter. This is the same weak-token problem the corpus classifier solves.
- **Results are newest-first and include provisionals.** A bare applicant search returns
  applications with no prosecution history, so every rule returns `N/A` and an empty
  audit looks like a clean one. Always bound the filing date.
- ODP requires a signed-in USPTO.gov account since 18 Jun 2026, plus four extra profile
  fields since 18 Aug 2026. Bulk download links are short-lived pre-signed CloudFront
  URLs behind an AWS WAF — `curl` gets an error page; use a browser.

## Rule design decisions

- **A1 counts only children filed before the parent issued.** § 120 requires copendency.
  Verified on application `14973095`: six children exist, only one preceded issuance.
- **Restrictions do not disqualify a first-action allowance.** Standard definition — a
  restriction is not a rejection on the merits. Reported separately.
- **FAI pilot cases (`FAIA`/`FAOO`) are excluded** from FAA; their "first action" is a
  different procedure and would inflate the rate.
- **B2 is a risk flag, never a conclusion.** § 121's safe harbour turns on whether the
  divisional was filed *as a result of* the restriction and whether consonance was
  maintained. Courts look to substance, not the ADS label.
- **Three states are non-negotiable.** `INDETERMINATE` must never be folded into `FLAG`
  or counted as a finding. An unpublished continuation is invisible, not absent.
- LexisNexis built ETA specifically because raw allowance rate "fails to account for
  actions taken on pending applications." Worth knowing before over-trusting the metric.

## Disambiguation rulings (2026-08-02)

Policy decisions made by Ben, encoded in `config/decisions.csv`:

| | |
|---|---|
| Renamed / IP-holding entities | **merge** (Microsoft Technology Licensing = Microsoft Corporation) |
| Sibling operating companies | **merge** (LG Chem, LG Display, LG Innotek → LG Electronics) |
| Regional subsidiaries | **merge** (Beijing/Hefei/Chengdu/Chongqing BOE → BOE) |
| Acquisitions | **merge** (Canon Medical, formerly Toshiba Medical) |
| Captive research arms | **merge** (Toyota Research Institute) |
| **Joint ventures** | **exclude** — shared IP ownership is not wholly the parent's |
| Unrelated businesses | **exclude** (Samsung Heavy Industries, Hyundai Steel/Card) |

Consequence accepted: LG and BOE totals no longer match IFI CLAIMS, which ranks LG
Display and Chengdu BOE separately.

Classifier mechanics worth remembering: token-boundary matching (not substring) is the
single biggest precision win — it eliminates TRUDELL/LYONDELL under DELL, PINEAPPLE
under APPLE, INTELLECTUAL VENTURES under INTEL. `SAMSUNG ELECTRO MECHANICS` scored
Jaro-Winkler **0.941** against Samsung Electronics and is a different company, which is
why the auto-merge threshold cannot drop below 0.90. Whole-string similarity fooled the
variant sweep (`HYUNDAI STEEL` vs `HYUNDAI AUTOEVER` cleared 0.90 on a shared prefix);
comparing only the single differing token fixed it.

Review burden was tractable: 2,266 distinct names, but names with ≤2 applications are
0.4% of the data. Reviewing the 327 names with ≥10 applications covers ~99.6%.

## Entity resolution (2026-08-21)

Scoping a portfolio to one company is step 1, and it used to be a substring test on
`firstApplicantName` inside `audit.py`. Substring matching kept INTELLECTUAL VENTURES
under "Intel", PINEAPPLE under "Apple", and TRUDELL and LYONDELLBASELL under "Dell" —
the token-boundary lesson had been learned in `sql/10_classify.sql` at build time and
never reached the runtime path, which also only ever covered the 20 seeded companies.
`skill/scripts/entity.py` now does this for any company, with `test_entity.py` pinning
every trap below.

Ben's policy rulings:

| | |
|---|---|
| Corporate family | **strict filer identity** — renamed and IP-holding vehicles merge (Microsoft Technology Licensing = Microsoft); siblings, regional arms and JVs do not |
| Unclassifiable names | **exclude, report loudly** — left out of scope, reported with the application count at stake so an understated denominator is visible |

This deliberately diverges from `config/decisions.csv`, whose *merge* rulings encode
the family rollup used for IFI-style ranking. Its `EXCLUDE` rulings are still honoured
— those only ever remove names. Consequence: an audit scope is smaller than the
corresponding corpus `company_id`, and the two are not interchangeable.

**The company name is matched exactly; only boilerplate tolerates typos.** Ben's
ruling, 2026-08-21. Identity tokens at or below **10 characters** must match exactly —
no edit budget at all. Above 10, bounded edit distance applies, so MANUFACTURING still
absorbs MANFACTURING / MANUFACTUING / MANUGACTURING. Corporate-form and boilerplate
words (Corp., Ltd., Incorporated, Technology, Licensing, Holdings) keep full typo
tolerance, because they are a small closed vocabulary and a fuzzy match against them
cannot pull in an unrelated brand. Plurals are treated as a variant spelling, not a
typo, at any length (MOTOR/MOTORS, TECHNOLOGY/TECHNOLOGIES).

Measured cost of exactness: about **80 applications out of ~236,000** across Intel,
Microsoft, Samsung, Qualcomm, TSMC and NVIDIA — 0.03%. What it buys is the removal of
a whole risk class and, more importantly, a rule that can be stated in one sentence to
a client. "Edit distance ≤ 2 when the token is ≥ 8 characters and the first letter
matches" is not defensible in a discoverable document; "the company name must match
exactly" is.

Because strict matching would otherwise make a filer's own misspelled filings
*invisible* rather than excluded, `resolve` reports a **near-miss** bucket: names one
edit from the anchor that would resolve if the spelling were corrected — QUALCOM,
SUMSUNG, MICROSFT, MIRCOSOFT, LNTEL, NVIDA. One edit, not two: at two the
neighbourhood of a short brand token fills with real companies, and LINTEC (348
applications) and XINTEC (311) would swamp Intel's list. Enumeration is deliberately
looser than classification so these can be seen at all. Note that a 5-character brand
still has a crowded neighbourhood — Intel's near-miss list contains INTEX, INTEC and
INTER — so it is a review list, never a candidate scope.

**Jaro-Winkler is the wrong function for token matching, and this is not a threshold
you can tune your way out of.** JW awards a large bonus for a shared prefix, so short
tokens match anything starting the same way. Measured: `JW(INTEL, INTELSAT)` and
`JW(INTEL, INTEPLAST)` both clear 0.90; `JW(SAMSIN, SAS) = 0.867` clears the 0.85 used
for suffix-typo tolerance, so SAMSIN was eaten as a corporate suffix and Samsin's
applications joined Samsung's. A first cut using JW put **169 unrelated companies**
into Intel's scope — Intelsat, Inteplast, Intelgenx, Intellon, Intelesol, Interblock.

Replaced with bounded Damerau-Levenshtein, budget scaled to length: under 6 characters
must match exactly, 6–7 allows one edit, 8+ allows two. Adjacent transposition costs
one edit, because that is what a real typo is (HUYNDAI, ELECTORNICS, TECHNOLGOY).
Plurals are handled separately so MOTOR/MOTORS and TECHNOLOGY/TECHNOLOGIES survive.
The cost is no typo tolerance on short brands (INTEL, APPLE, DELL) — worth it: on
Intel the fuzzy version added ~1,000 applications, almost all contamination.

The whole-string JW note from 2026-08-02 still stands and is now a regression test:
`SAMSUNG ELECTRO MECHANICS` scores 0.941 against Samsung Electronics and is a
different company.

Other mechanics worth keeping:

- **Weak tokens are derived from the corpus, not a hand-maintained stoplist.** Document
  frequency across the 369,090 distinct applicant names separates brands from industry
  vocabulary cleanly: MICROSOFT 80, QUALCOMM 80, DELL 30, GOOGLE 23, APPLE 14 versus
  TECHNOLOGY 17,768, SYSTEMS 8,446, INTERNATIONAL 6,312, SEMICONDUCTOR 878. Threshold
  500. A name with no distinctive token at all (all tokens generic) requires the full
  name to match instead.
- **Anchor on the single rarest token, not every distinctive one.** "Hyundai Motor
  Company" anchored on both HYUNDAI and MOTOR drags in Honda (13,946 applications) and
  every other carmaker. Correctly excluded afterwards, but it turns the excluded count
  into something that reads like lost Hyundai volume.
- **Every applicant is tested, not just the first** — Hyundai/Kia co-filings would
  otherwise vanish from the second filer's audit.
- Validation: re-running the TSMC search from the ODP section reproduces the original
  measurement exactly — 15 of 20 dropped as other companies, 2 genuinely TSMC.

## Company-level access is not limited to 20 companies (2026-08-21)

Easy to believe it is, because `app_company` (399,905 rows) *looks* like a company
index. It is not: it, `cohort`, `app_facts` and `app_flags` are all built by
`sql/20_build_site_data.sql` and frozen at **20 companies, filing years 2013–2019** to
serve the superseded website. The corpus underneath covers **516,807 distinct applicant
organisations** across all 14.1M applications. Verified against companies that were
never seeded: NVIDIA 3,697 applications, Molex 2,031, Cisco 12,255, Boeing 13,732,
Genentech 3,998, 3M 17,879 — with full transaction histories (Boeing 668,831 events).

`corpus.applicant_baseline` / `applicant_applications` / `applicant_context` read
`applicant_organization` directly and work for any entity. **No further USPTO download
is needed for arbitrary-company research** — that was the assumption worth killing.
What genuinely needs more data: anything after June 2023 (ODP, or a newer PatEx
release), CPC (ODP only), office action text for rules B3/B4, and firm attribution from
`attorney_agent.csv` — which is already inside the downloaded PatEx zip, just never
extracted.

Two implementation notes that cost time:

- **Materialise the scope once.** The applicant join runs `all_applicants` (6.7M)
  against `application_data` (14.1M); re-running it per query made a 3,000-application
  portfolio take 11s. A temp table takes it to ~3s.
- **Never filter 507M `transactions` rows with `list_contains` on application number.**
  That is a linear scan — 45s for one portfolio. Expressed as a join against the
  materialised scope, DuckDB hash-joins and it drops to about 2s. Also filter to the
  ~12 event codes the rules actually read.
- DuckDB's progress bar writes to stdout and corrupts JSON output; `connect()` now
  disables it.

**The first letter of a short brand token is load-bearing.** `AVIDIA INC` is one edit
from NVIDIA and is a different company; `NIVIDIA` and `NAVIDIA` are also one edit away
and are NVIDIA. Tokens under 8 characters now additionally require a matching first
character. Longer tokens are exempt, so the duplicated-letter typo `LELECTRONICS` still
resolves to `ELECTRONICS`.

## The corpus stops being complete ~18 months before it stops (2026-08-21)

The corpus's last record is dated 2023-06-01 and it is tempting — the README, SKILL.md
and the first version of the `portfolio` coverage block all did it — to describe it as
covering everything up to then. **It does not.** PatEx carries *published*
applications, so anything filed inside the 18-month publication window before the
snapshot is simply absent. Utility filings per quarter, against a normal ~105,000:

| 2021-Q4 | 2022-Q1 | 2022-Q2 | 2022-Q3 | 2022-Q4 | 2023-Q1 | 2023-Q2 |
|---|---|---|---|---|---|---|
| 101,430 | 86,384 | 85,472 | 81,256 | 62,828 | 14,664 | 307 |
| full | 79% | 78% | 74% | 57% | 13% | 0.3% |

So: complete through **end 2021**, partial through 2022, effectively empty in 2023.
`CORPUS_COMPLETE_THROUGH` in `corpus.py` encodes this and the `portfolio` coverage
block reports it. Never quote a corpus portfolio as current past 2021-12-31.

## Neuralink: the corpus/ODP merge, measured (2026-08-21)

Deliberately small filer, used to test combining the two sources. One ODP search call.

- **Corpus:** 25 utility applications, allowance rate 91.7% — but on only 12 disposed.
- **ODP:** 56 matches → 35 REGULAR after dropping 11 provisionals and 10 PCT.
- **Union: 35.** Corpus-only: **0**. ODP-only: **10**.

Three things this settled:

1. **The corpus was a strict subset here** — zero corpus-only records — so deduplicating
   on application number with ODP winning is safe. Do not assume it holds universally,
   but it is the right default.
2. **Status drift is severe for a young filer.** 10 of the 25 shared records had moved
   from pending to granted since the snapshot. Corpus-only allowance rate 91.7% on 12
   disposed; merged, 96.6% on 29 disposed of 35. A corpus-only answer about a recent
   portfolio is not merely stale, it materially misstates the metric.
3. **`17553364` (filed 2021-12-16) is absent from the corpus entirely** — not scoped
   away, not present in `application_data` at all. That is what led to the publication-
   lag finding above.

Also confirmed: ODP returns the applicant as `Neuralink Corp.`, `NEURALINK CORP.` and
`Neuralink Corp` in the same result set; all three normalise to one name, and
`entity.Matcher` handles them. PCT entries arrive with application numbers like
`PCTUS2019050877` and are dropped by `EXCLUDED_APP_TYPES`.

Incidental proof that the near-miss bucket earns its place: asked for "Neurolink", the
resolver returned nothing in scope and pointed at `NEURALINK CORP` (40 applications) as
a near miss, rather than silently answering "no such company".

## Corpus statistics (for sanity-checking future work)

20 companies, 2013–2019, 393,587 distinct applications. Allowance rate spans **75.7%
(Qualcomm) to 98.8% (TSMC)**; median months to issue 21 (Micron) to 33 (Amazon);
restriction rate **4.6% (Google) to 41% (TSMC)**.

National-stage share is a good data-integrity check — Ericsson 79.9%, BOE 63.5%, LG
47.4% versus IBM 0.6%, Dell 0.1%, Amazon 0.1%. That foreign-vs-US-origin split is
exactly right; if it ever inverts, something upstream broke.

**Joint filings are real.** Hyundai and Kia co-file 5,879 applications — essentially
Kia's entire portfolio. An early build collapsed each application to one company and cut
Kia from 5,938 to 59. Applications now belong to multiple companies, so company totals
sum to more than the distinct count (399,905 memberships across 393,587 applications).

## Open threads

- **`attorney_agent.csv` (15 GB) is still unextracted** in the PatEx zip. It maps
  attorney/agent of record to each application, which would enable **firm-level**
  analysis — "which firms most often let a first-action allowance issue without a
  continuation." Substantially more interesting and substantially more fraught: firm
  flag rates mostly reflect client instructions and budgets, not competence. Think hard
  before it becomes anything shareable.
- **B1/B2 detect that a restriction occurred, not which groups were defined or
  elected.** That needs office action text. USPTO's Office Action Research Dataset is
  also free bulk and would enable rules B3 (traversal) and B4 (missed rejoinder after
  species election — the most expensive miss on the original rule list).
- `atty_docket_number` reflects the **outside firm's** format, not the applicant's
  (Sughrue's `Q`-prefix is visible throughout). Useless for entity matching; potentially
  useful for firm attribution.
- EPO OPS credentials already exist in Credential Manager under the same mechanism; see
  `~/.claude/reference/epo-ops-api.md`. An `epo_client.py` would slot in beside
  `odp_client.py`.
