# patent-portfolio-analyzer

A Claude skill for US patent prosecution analysis: portfolio audits, single-application
review, and examiner/art-unit benchmarking.

Author: Benjamin Keim

## Why a skill rather than a website

An earlier version of this project was a public static site. It worked, but it could
only ever answer questions about 20 precomputed companies in a frozen 2013–2019 cohort,
because a public site cannot use a personal, ID.me-verified USPTO API key on behalf of
anonymous visitors.

As a skill it runs on Ben's machine with his credentials, so it can answer about any
company, any application, any examiner, against current data.

## Architecture

```
scripts/
  corpus.py      local PatEx DuckDB  - baselines, historical sweeps, no API key
  odp_client.py  live USPTO ODP API  - current cases, credential from Credential Manager
  rules.py       source-neutral prosecution rules (A1/B1/B2/D2)
  audit.py       CLI that routes between the two and applies the rules
```

`rules.py` normalises both sources into one `AppFacts` shape. Both use the same USPTO
event codes and continuation-type codes, so the rules run unchanged on either — verified
by auditing the same application through both paths and getting identical output.

### The two sources

| | Local PatEx corpus | USPTO ODP API |
|---|---|---|
| Contents | 14.1M applications, 507M events | live file wrapper |
| Currency | frozen June 2023 | current |
| Cost | free, instant | rate-limited, personal key |
| Best for | baselines, benchmarks, sweeps | specific and recent cases |

Building the corpus is a one-time job documented in the
`Patent-Portfolio-Analyzer` repo. The skill works without it in ODP-only mode, but
cannot produce baselines.

## Setup

```powershell
pip install -r requirements.txt
python scripts\audit.py doctor
```

`doctor` reports corpus size and confirms the ODP key resolves and the API answers.
It never prints the key.

The ODP key lives in the Windows Credential Manager as generic credential
`USPTO_ODP_API_KEY`, read via `~/.claude/scripts/wincred.py` — the same mechanism
`patent-filing-qc` uses. Set `PATEX_DUCKDB` to override the corpus location.

## Efficiency notes

ODP's search endpoint returns `eventDataBag` inline, so one call screens many
applications. Only candidates that could still flag get a follow-up `/continuity` call
for their children. A 20-application screen typically costs 1 search + a handful of
continuity calls, not 3 calls per application.

## Cautions

Read the "How to report results" section of `SKILL.md` before writing anything up. In
short: these are **unexercised options, not errors**; the three states must stay
distinct; and restriction rate tracks technology rather than practice, so cross-company
comparison needs that caveat stated.

Two ODP search traps are documented in `SKILL.md` and both are handled in code —
loose applicant tokenisation (`--applicant` post-filter) and newest-first ordering
with provisionals mixed in (date-bound the query; non-utility types dropped by
default).
