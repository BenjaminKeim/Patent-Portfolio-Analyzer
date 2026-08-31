# Entity resolution — how names are matched

The rules behind `resolve`. SKILL.md carries the policy; this is the mechanism and the
evidence for it.

## Token boundaries, never substrings

A substring match on a short brand pulls in everything that contains it. Matching is
always on token boundaries.

## Two standards, depending on the kind of word

**The company name itself must match EXACTLY at or below 10 characters — no typo
budget.** At that length a single edit is as likely to be a different company as a
misspelling: NVIDIA/AVIDIA, INTEL/INTEC, SAMSUNG/SAMSIN. Above 10 characters a bounded
edit distance applies, so MANUFACTURING still matches MANFACTURING.

**Corporate-form and boilerplate words tolerate typos** — Corp., Ltd., Incorporated,
Technology, Licensing, Holdings. These are a small closed vocabulary, so fuzzy matching
cannot pull in an unrelated brand, and USPTO's own records genuinely contain COPORATION,
INCORPORTED, TECHNOLGOY and LICESNING.

## Never Jaro-Winkler, at any length

It merged 169 unrelated companies into Intel. See "Entity resolution" in `CONTEXT.md`
for the full post-mortem.

## Why the near-miss list is a review list, not a scope

A short brand token has a crowded one-edit neighbourhood. Intel's near-miss list contains
INTEX and INTEC, which are real and unrelated companies; Molex's contains ROLEX with 172
applications. Present the list for a human to read; never fold it into scope
automatically.

## decisions.csv

Its EXCLUDE rulings bind here. Its *merge* rulings deliberately do not: those encode the
corporate-family rollup used for IFI-style ranking, which is the opposite of strict filer
identity.

## Limits

Resolution enumerates names from the corpus, so a filer that only ever appears after
June 2023 resolves to nothing — `resolve` says so in its warnings. Live ODP names absent
from the corpus are still classified by the same rules, so scoping a search does not
depend on the name being in the snapshot. Applicant organisation is ~0% populated before
2012, so a pre-2013 portfolio cannot be scoped at all.
