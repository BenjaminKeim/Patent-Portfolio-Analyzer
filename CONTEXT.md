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
