# The at-a-glance widget

How to render the portfolio result as an inline visual panel. Ben asked for this
after reading a terminal report: the bars work, but the first thing he wants to see
is the picture, and he wants to open a rule and look at its cases without another
command.

## Setup

Call `mcp__visualize__read_me` with modules `["data_viz","interactive"]` BEFORE writing
any markup — it loads the CSS-variable palette, colour ramps and layout rules. Do not
skip it and do not narrate the call. Render with `mcp__visualize__show_widget`.
HTML fragments only: no DOCTYPE, `html`, `head` or `body`.

## Where the numbers come from

`at_a_glance` in the portfolio JSON — `chart.summary()`, the same tallies that draw
the terminal bars. Never recount from `results[]` by hand; a widget that disagrees
with the report is worse than no widget.

Each row already carries `rule` (the description — never a code), `flagged`,
`indeterminate`, `clear`, `evaluable`, `denominator`, `rate` and `small_sample`.

**The RCE row is measured against the whole portfolio, not against cases that filed an
RCE.** Ben's reasoning: nothing meaningful separates filing zero RCEs from filing one,
so gating the denominator on "filed at least one" manufactures a set rather than
describing one. That makes this row an incidence rate while the rows above it are
conditional rates — a real difference in what the bar heights mean, worth stating
whenever the panel is discussed.

**Every bar states its own denominator in the row label.** "837 of 1,996 applications"
answers the wrong question; "837 of 1,151 closed cases that drew a restriction" answers
the right one. This is the whole point of the chart — see the denominator discussion in
SKILL.md.

## Colour semantics — decide before drawing

One meaning per colour, held throughout:

- `#E24B4A` red — the option was NOT exercised (the rule fired)
- `#B4B2A9` gray — cannot tell (INDETERMINATE)
- `#378ADD` blue — the option WAS exercised

**Red is Ben's call, made deliberately.** An earlier version used amber on the
reasoning that red reads as an error count and these are unexercised options, not
errors. Ben overrode it: he wants the flagged share to read as the thing to look at,
and blue to read as the practice he would want to see. He decides how his own review
output is coloured. The non-error framing is carried by the words — headings, notes,
and the closing paragraph — not by withholding a colour. Do not quietly revert this
to amber.

**Always show the indeterminate band explicitly.** Letting it vanish into the
background overstates confidence, and this skill is emphatic that INDETERMINATE must
never fold into either neighbour.

## Look

- Flat only. No gradients, shadows, blur, or coloured outer backgrounds.
- Borders `0.5px solid var(--border)`. Radius `var(--radius)` for controls, `12px` for
  cards.
- Every colour from CSS variables (`--surface-1/-2`, `--text-primary/-secondary/-muted`,
  `--bg-accent/-success/-warning/-danger`) except the three semantic hues above. Never
  hardcode `#333` — it dies in dark mode.
- Type: 20px/500 titles, 14px body, 13px secondary, 11–12px captions. Weights 400 and
  500 only. Sentence case everywhere.
- Metric cards: `var(--surface-1)`, no border, 1rem padding, 13px muted label above a
  24px/500 number. Grid of four, 12px gap.
- Badges: tinted background with the darker text colour from the same family, 11px,
  2px 8px padding.
- Icons: Tabler outline webfont (`<i class="ti ti-chevron-down">`). No emoji.

## Data and streaming

- Embed the dataset inline as a JS const so drill-downs cost no round trips. Twelve
  sample cases per rule is enough; the row states the true total, and the full list is
  in the report and the JSON.
- Precompute bar widths as literal inline percentages in the HTML. Anything computed in
  JS flashes or mis-renders while the response streams.
- Order: short style block, then content HTML, then `<script>` LAST.
- No `display:none` sections holding streamed content; no `position:fixed` (it collapses
  the iframe height); no nested scrolling.

## Interactions

- Click a summary row to expand its case table; build the table in JS on first open.
- Sortable headers as a three-state cycle: ascending → descending → back to default.
  Show `ti-arrow-up`/`ti-arrow-down` on the active column and darken its label, so a
  sorted view never looks like the default.
- Call `e.stopPropagation()` in header, link and button handlers, or clicking one also
  collapses the parent row.
- **Do not tint rows.** An earlier version tinted the high-rate rows with
  `var(--bg-accent)` on an unstated threshold the reader could not see. Once red and
  blue carry meaning, that tint is actively wrong: `--bg-accent` is blue, so the
  attention rows were washed in the colour the legend assigns to the option being
  exercised — the opposite of why they were highlighted. Sorting by rate already puts
  the rows that matter at the top, without a second, conflicting encoding. Every
  colour on the panel should mean exactly one thing.
- Plain `<a href>` works and opens the host's link dialog. `sendPrompt('...')` for
  anything needing Claude to think.
- Round every number that reaches the screen (`toFixed` / `toLocaleString`).

## Accessibility

Open with a visually-hidden `h2` (`position:absolute; width:1px; clip:rect(0 0 0 0)`)
summarising the visualisation in one sentence, including the headline count and its
denominator.

## Panel furniture

- **The company name goes at the top, centred, large** (26px/500), with a 13px muted
  caption beneath it. The caption names what is being counted, not a date range:
  "Published utility patent applications since 2012". Published, because both sources
  carry published applications only - which is also why the most recent filings are
  thin. Since 2012, because that is the applicant-organisation floor and it does not go
  stale; an end year in the caption reads as though the analysis stops there, when the
  recency sweep carries it to the present.
- **The window belongs on the numbers it governs, not in the page caption.** The metric
  cards and the rule bars are the corpus cohort, so that block is labelled with its own
  filing window; the recency block carries its own. One caption covering both would be
  wrong for whichever it did not describe.
- **A rule with a time dimension worth seeing gets a strip directly under its own
  bar**, inside the same card — not in a separate section, where the reader has to
  hold two things in their head to connect them. The revival strip is the worked
  example: equal-width year cells across the full span, filled from the red ramp by
  count (`#F7C1C1` / `#F09595` / `#E24B4A` / `#A32D2D`, `var(--surface-1)` for zero),
  with the count and the year beneath each cell. Equal widths keep the time axis
  honest — sizing cells by count would distort it into a bar chart wearing a
  timeline's clothes.
- Say what the strip measures. The revival strip is keyed on the date the petition was
  DECIDED, which is what the event log records; the underlying lapse precedes it,
  usually by months.

## Domain formatting

- Application numbers as the reader reads them: `18/000,000`, not `18000000`. Patent
  numbers `9,999,999`. Years in full — `2019`, not `19`.
- Titles truncate to ~58 characters; the full title is in the report.

## What does NOT go in the widget

All explanatory prose — the confounders, the coverage caveats, the unexercised-options
framing, the reading of what a rate means. Those go in the chat response. The widget
holds the visual only.
