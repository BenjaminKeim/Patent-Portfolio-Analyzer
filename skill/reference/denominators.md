# Denominators, chart states, and terminal rendering

Why each bar is measured against the set it is measured against. The eligible sets and
their wording live in one place in code — `rules.RULES` — so this file explains the
reasoning rather than restating the table.

## Two ways the eligible set is derived

**From the rule's own states.** The no-divisional and no-continuation rules each have a
state meaning the option *was* exercised — a divisional was filed, a continuation was
filed — so the rule's own `N/A` verdict already defines the eligible set exactly.
Deriving it a second time would let the bar drift out of step with `rules.evaluate`.
These use `FROM_STATES`: everything the rule did not call `N/A`.

**Computed from the facts.** The no-interview, RCE and revival rules are FLAG-or-nothing,
so reading states would make every bar 100% and say nothing. Each carries a predicate:

- no-interview → cases with 3+ office actions
- revival → cases that went abandoned at some point (a case revived back to grant still
  belongs in that denominator)
- RCE → **every application in the portfolio**

## The RCE row is not like the others

Ben's call, and it is right: nothing meaningful separates filing zero RCEs from filing
one, so gating the denominator on "filed at least one" manufactures a set rather than
describing one.

The consequence is worth stating whenever the bars are compared. That row is an
**incidence rate** across the portfolio while every row above it is a **conditional
rate**. The bar heights are not like-for-like, and a reader scanning down the chart will
assume they are unless told otherwise.

## The continuation-instead-of-divisional rule has no section

It is folded into the no-divisional section as a per-case note, because both fire on the
same application. Listing it twice misrepresents both: the no-divisional heading implies
the non-elected claims were dropped, when in these cases they were pursued — just under a
label that may forfeit the § 121 safe harbour. The note reads
`CON filed, not a divisional - Sec. 121 label risk`.

## Terminal rendering

Red is the flagged share, blue the rest, and INDETERMINATE gets its own muted amber
segment because it must never be folded into either. `--no-charts` suppresses the bars.

Colour is dropped when output is piped or `NO_COLOR` is set. The block glyphs fall back
to `#`/`=`/`-` when the console encoding cannot represent them — Ben's PowerShell defaults
to cp1252, where printing them raises `UnicodeEncodeError` and would take the whole
report down.

The widget uses a different palette from the terminal — see `widget-recipe.md`. That is
deliberate, not drift: the terminal has three usable colours, the widget has a full ramp.
