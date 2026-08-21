# Patent Portfolio Analyzer

US patent prosecution analysis — portfolio audits, single-application review, and
examiner/art-unit benchmarking — delivered as a **Claude skill** that runs locally with
your own USPTO credentials.

Author: Benjamin Keim

The repository contains two things:

| | |
|---|---|
| **`skill/`** | The product. A Claude skill: rules, ODP client, corpus queries. |
| **`sql/`, `config/`, `scripts/`** | The pipeline that builds the local corpus the skill benchmarks against. |

`site/` holds an earlier static-website version. It is superseded and kept only for
reference — its metric SQL is the origin of the rules now in `skill/scripts/rules.py`.

## Why a skill and not a website

The website worked, but it could only ever answer questions about 20 precomputed
companies in a frozen 2013–2019 cohort. A public site cannot use a personal,
ID.me-verified USPTO API key on behalf of anonymous visitors, so its data had to be
baked in at build time.

As a skill it runs on your machine with your credentials, and can answer about any
company, any application, any examiner, against current data.

## Install (your own machine)

The skill lives in `skill/`. Claude finds skills in `~/.claude/skills/`, so link the two
rather than copying — a copy needs syncing and will drift.

```powershell
# Windows: a junction. No administrator rights needed (a symlink would need them).
cmd /c mklink /J "$env:USERPROFILE\.claude\skills\patent-portfolio-analyzer" "<repo>\skill"
```

```bash
# macOS / Linux
ln -s "<repo>/skill" ~/.claude/skills/patent-portfolio-analyzer
```

Then:

```powershell
pip install -r skill\requirements.txt
python skill\scripts\audit.py doctor
```

`doctor` reports corpus availability and confirms the API key resolves and the API
answers. It never prints the key.

**There is no sync step.** The linked folder *is* the repo folder, so editing the skill
edits the repo, and `git status` shows it immediately.

## Install (someone else's machine)

```bash
git clone https://github.com/BenjaminKeim/Patent-Portfolio-Analyzer.git
ln -s "$PWD/Patent-Portfolio-Analyzer/skill" ~/.claude/skills/patent-portfolio-analyzer
pip install -r Patent-Portfolio-Analyzer/skill/requirements.txt
```

You need **your own USPTO ODP API key** from [data.uspto.gov/myodp](https://data.uspto.gov/myodp)
(free; requires ID.me verification). Provide it either way:

- **Windows** — Credential Manager → Windows Credentials → add a generic credential named
  `USPTO_ODP_API_KEY`
- **Any OS** — set the `USPTO_ODP_API_KEY` environment variable

Without the local corpus you get single-application audits but **no examiner or
art-unit benchmarks** — those need the 507M-event table. Build your own with the
pipeline below, or set `PATEX_DUCKDB` to point at an existing copy.

## Building the corpus (optional, enables benchmarks)

The corpus is ~21 GB locally and is not in git. It is rebuilt from a USPTO bulk download.

1. Download the **PatEx 2022 release, CSV** from
   [USPTO Economic Research](https://www.uspto.gov/ip-policy/economic-research/research-datasets/patent-examination-research-dataset-public-pair).
   Requires a signed-in USPTO.gov account; the link hands back a short-lived
   pre-signed URL, so start the download promptly.
   Extract these seven files to `data/raw/`:
   `transactions`, `application_data`, `all_applicants`, `continuity_children`,
   `continuity_parents`, `foreign_priority`, `event_codes`.

2. Run the pipeline with [DuckDB](https://duckdb.org):

```bash
duckdb data/patex.duckdb -f sql/01_load.sql             # CSVs -> native tables (~12 GB CSV, slowest step)
duckdb data/patex.duckdb -f sql/10_classify.sql         # applicant-name disambiguation
duckdb data/patex.duckdb -f sql/20_build_site_data.sql  # cohort, events, rules
duckdb data/patex.duckdb -f sql/21_export_json.sql      # (site only)
duckdb data/patex.duckdb -f sql/23_stats_and_check.sql  # (site only)
python scripts/split_details.py                         # (site only)
```

Only the first three steps are needed for the skill. The rest feed the superseded site.

## Applicant disambiguation

`config/canonical_seeds.csv` defines the tracked companies and their brand tokens; a
leading `~` marks a **weak** token — a generic industry word such as `SEMICONDUCTOR`
that alone is not evidence of identity.

`config/decisions.csv` records human rulings, which **always** override the rules.
`EXCLUDE` in the `company_id` column vetoes a name outright.

The classifier is deterministic — no machine learning — so every assignment traces to a
named rule or an explicit decision, and you can always answer "why was this entity
excluded." Rules are documented in the header of `sql/10_classify.sql`. Typo variants of
any decided name are swept up automatically.

## Known limits

- **Corpus is frozen at June 2023.** Anything later needs `--source odp`.
- **Company analysis is impossible before 2013.** USPTO only began recording the
  applicant organisation systematically after the AIA (Sept 2012): coverage is ~0%
  before 2012, 65% in 2013, 81% in 2014, ~90% from 2015. The 2013–14 ramp looks like
  filing growth and is not.
- **US only.** No other patent office publishes prosecution events at the granularity
  these rules need. EPO would broaden coverage, not deepen the audit.
- **Sibling operating companies are rolled up** into the parent brand (LG Chem and LG
  Display into LG Electronics; Chengdu BOE into BOE), which diverges from IFI CLAIMS —
  it ranks LG Display (#30) and Chengdu BOE (#48) separately. Totals for those are not
  comparable to the published IFI ranking. Joint ventures are excluded.
- **Restriction rate tracks technology, not practice.** Semiconductor and display filers
  run 20–40%, software and communications filers 4–7%. Cross-company comparison without
  controlling for technology centre is misleading.

## Reporting

Read the "How to report results" section of `skill/SKILL.md` before writing anything up.
In short: these are **unexercised options, not errors** — the public record contains no
client instruction, budget, or strategy, so no rule here can distinguish a mistake from
a deliberate decision, and a document that implies otherwise is discoverable.

## Further context

`CONTEXT.md` records the decisions, dead ends, and hard-won details behind this
repository — the things that would otherwise have to be rediscovered.
