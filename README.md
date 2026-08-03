# Patent Portfolio Analyzer

Prosecution-level analysis of US patent portfolios for the 20 largest US patent
recipients, built entirely from USPTO public-domain bulk data. No API key is used at
runtime and none is present in the deployed site.

**Cohort:** 393,587 US utility applications, filing years 2013–2019
**Source:** USPTO Patent Examination Research Dataset (PatEx), 2022 release (PEDS pull June 2023)

## What it reports

Per company: allowance rate, median time to issue, mean office actions, restriction
rate, first-action-allowance rate, §371 national-stage share, interview rate, RCE rate,
filings by year, and technology mix by USPTO technology centre.

Three prosecution rules, reported as **review flags — unexercised options, not errors**:

| Rule | Meaning |
|---|---|
| **A1** | First-action allowance with no continuation filed before issuance |
| **B1** | Restriction requirement issued, no divisional ever filed |
| **B2** | Restriction issued, child filed as a continuation rather than a divisional (§ 121 safe-harbour risk) |

Absence-based rules use three states: `FLAG` (a filing would have been visible and was
not made), `PRESENT`, and `INDETERMINATE` (disposed too close to the data cutoff to tell).

## Rebuilding the data

Requires [DuckDB](https://duckdb.org) and Python 3. The raw CSVs are not in the repo.

1. Download the PatEx **2022 release, CSV** from
   [USPTO Economic Research](https://www.uspto.gov/ip-policy/economic-research/research-datasets/patent-examination-research-dataset-public-pair)
   (requires a signed-in USPTO.gov account). Extract these seven files to `data/raw/`:
   `transactions`, `application_data`, `all_applicants`, `continuity_children`,
   `continuity_parents`, `foreign_priority`, `event_codes`.

2. Run the pipeline:

```bash
duckdb data/patex.duckdb -f sql/01_load.sql          # load CSVs into native tables
duckdb data/patex.duckdb -f sql/10_classify.sql      # applicant-name disambiguation
duckdb data/patex.duckdb -f sql/20_build_site_data.sql  # cohort, events, rules
duckdb data/patex.duckdb -f sql/21_export_json.sql   # export JSON
duckdb data/patex.duckdb -f sql/23_stats_and_check.sql
python scripts/split_details.py                      # per-company files
```

## Disambiguation

`config/canonical_seeds.csv` defines the 20 companies and their brand tokens (a leading
`~` marks a *weak* token — a generic industry word like `SEMICONDUCTOR` that alone is not
evidence of identity). `config/decisions.csv` records human rulings, which always
override the rules; `EXCLUDE` in the `company_id` column vetoes a name.

The classifier is deterministic — no machine learning — so every assignment traces to
either a named rule or an explicit human decision. Rules are documented in the header of
`sql/10_classify.sql`. Typo variants of any decided name are swept up automatically.

## Running the site

```bash
cd site
npm install
npm run dev     # http://localhost:3000
npm run build   # static export to site/out/
```

Next.js 16 with static export — every page is prerendered HTML. Charts are Recharts
(bar, line, pie). Flagged-application lists are fetched at runtime rather than inlined,
which keeps company pages at ~30 KB instead of ~2.8 MB.

## Deploying

```bash
cd site
npx vercel --prod
```

No environment variables and no server are required.

## Known limitations

- **Pre-2013 is unreachable.** USPTO only began recording the applicant organisation
  systematically after the AIA (Sept 2012); coverage is ~0% before 2012.
- **2013–2014 are understated.** Coverage is 65% and 81% respectively, reaching ~90%
  from 2015. Company pages mark these years.
- **Joint filings count for both companies.** Company totals therefore sum to more than
  the number of distinct applications (399,905 memberships across 393,587 applications;
  Hyundai and Kia alone co-file 5,879).
- **Sibling operating companies are rolled up** into the parent brand (LG Chem and LG
  Display into LG Electronics; Chengdu BOE into BOE). This diverges from IFI CLAIMS,
  which ranks LG Display (#30) and Chengdu BOE (#48) as separate entities, so totals for
  those companies are not directly comparable to the published IFI ranking.
- **Restriction rate tracks technology, not practice.** Semiconductor and display filers
  are restricted far more often than software and communications filers; cross-company
  comparison without controlling for technology centre is misleading.
- **US only.** No other patent office publishes prosecution data at this granularity.
