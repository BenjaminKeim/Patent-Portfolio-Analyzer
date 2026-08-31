"""Terminal bar charts for the portfolio report, and the structured tallies behind them.

One bar per rule: how many cases the rule fired on, out of the cases where the rule
could fire at all. The denominator is the whole point. The restriction-with-no-divisional
rule flagged 837 of Example Corporation's 2,000 applications, but it can only fire on an
application that drew a restriction AND has closed - 1,151 of them. Charting 837/2,000
would understate it by nearly half, and charting it against a denominator the reader
cannot see would be worse.

summary() returns the same tallies as structured rows, named by description rather than
by internal key, so a widget or a JSON consumer cannot drift from what the bars show.

So each bar states its own denominator in words. rules.RULES defines, per rule,
both that wording and the set an application must belong to before its state counts.

Colour follows Ben's spec - blue for the clear cases, red for the flagged ones. There
is a third state: INDETERMINATE, meaning the case was disposed too near the data
horizon to tell. The skill is emphatic that it must never be folded into FLAG, so it
gets its own muted amber segment rather than being coloured as either.
"""
from __future__ import annotations

import os
import sys

import rules as _rules

BAR_WIDTH = 54

# Below this many evaluable cases a percentage is noise and the bar should not be read
# as a rate. The skill applies the same reasoning to examiner statistics.
SMALL_SAMPLE = 50

# 24-bit colour. Blue and red are picked for contrast on both light and dark
# terminals; amber is deliberately muted so it never competes with the red.
BLUE = "\033[38;2;56;132;255m"
RED = "\033[38;2;235;64;52m"
AMBER = "\033[38;2;180;140;40m"
BOLD = "\033[1m"
DIM = "\033[2m"
OFF = "\033[0m"

# Block glyphs where the console can encode them, ASCII where it cannot. Ben's
# PowerShell defaults to cp1252, which cannot encode these at all - printing them
# there raises UnicodeEncodeError and takes the whole report down with it. A plainer
# bar is a far better outcome than a crash on first fire.
_BLOCKS = ("█", "▓", "░")
_ASCII = ("#", "=", "-")


def glyphs(stream=None):
    """(flagged, indeterminate, clear) fill characters this console can actually print."""
    stream = stream or sys.stdout
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        "".join(_BLOCKS).encode(enc)
        return _BLOCKS
    except (LookupError, UnicodeEncodeError):
        return _ASCII


FULL, MEDIUM, LIGHT = _BLOCKS


def _enable_vt() -> bool:
    """Windows conhost needs VT processing turned on before it honours ANSI."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        return False


def use_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return _enable_vt()


# Eligible sets and denominator wording both live in rules.RULES - see the registry
# there for why a rule is charted against the set it is charted against.


def tally(results: list[dict], rule: str) -> dict:
    """Flagged / clear / indeterminate within the set where the rule can fire."""
    eligible = (_rules.RULES.get(rule) or {}).get("eligible") or _rules.FROM_STATES
    flagged = clear = indet = 0
    for r in results:
        state = ((r.get("flags") or {}).get(rule) or {}).get("state")
        if eligible is _rules.FROM_STATES:
            if state in (None, "N/A"):
                continue
        elif not eligible(r):
            continue
        if state == "FLAG":
            flagged += 1
        elif state == "INDETERMINATE":
            indet += 1
        else:
            clear += 1
    return {"flagged": flagged, "clear": clear, "indeterminate": indet,
            "total": flagged + clear + indet}


def summary(results: list[dict], sections: list[tuple[str, str]]) -> list[dict]:
    """The at-a-glance rows as data: one per rule, named, with its own denominator.

    Rules that no application in the portfolio is eligible for are dropped, exactly as
    the bars drop them - a bar with a zero denominator states nothing.
    """
    rows = []
    for rule, _title in sections:
        t = tally(results, rule)
        if not t["total"]:
            continue
        rows.append({
            "rule": _rules.name(rule),
            "flagged": t["flagged"],
            "indeterminate": t["indeterminate"],
            "clear": t["clear"],
            "evaluable": t["total"],
            "denominator": _rules.RULES[rule]["denominator"],
            "rate": round(100.0 * t["flagged"] / t["total"], 1),
            "small_sample": t["total"] < SMALL_SAMPLE,
        })
    return rows


def _segments(t: dict, width: int) -> tuple[int, int, int]:
    """Split the bar, never letting a non-zero count render as zero width."""
    total = t["total"]
    if total <= 0:
        return 0, 0, 0
    raw = [(t["flagged"] * width) / total, (t["indeterminate"] * width) / total,
           (t["clear"] * width) / total]
    seg = [int(x) for x in raw]
    for i, key in enumerate(("flagged", "indeterminate", "clear")):
        if t[key] > 0 and seg[i] == 0:
            seg[i] = 1
    # Trim from the widest segment if rounding pushed it over.
    while sum(seg) > width:
        seg[seg.index(max(seg))] -= 1
    while sum(seg) < width:
        seg[seg.index(max(seg))] += 1
    return seg[0], seg[1], seg[2]


def bar(t: dict, colour: bool, width: int = BAR_WIDTH, g=None) -> str:
    full, medium, light = g or glyphs()
    f, i, c = _segments(t, width)
    if not colour:
        return full * f + medium * i + light * c
    out = ""
    if f:
        out += BOLD + RED + full * f + OFF
    if i:
        out += AMBER + medium * i + OFF
    if c:
        out += BLUE + light * c + OFF
    return out


def render(results: list[dict], sections: list[tuple[str, str]], colour: bool | None = None) -> list[str]:
    """One labelled bar per rule, widest label padded so the bars line up."""
    if colour is None:
        colour = use_colour()
    g = glyphs()
    full, medium, light = g
    rows = [(rule, title, tally(results, rule)) for rule, title in sections]
    rows = [r for r in rows if r[2]["total"] > 0]
    if not rows:
        return []

    L = ["## At a glance", ""]
    key = (f"{BOLD}{RED}{full*3}{OFF} flagged   {AMBER}{medium*3}{OFF} indeterminate   "
           f"{BLUE}{light*3}{OFF} no finding" if colour else
           f"{full*3} flagged   {medium*3} indeterminate   {light*3} no finding")
    L += [key, ""]

    for rule, title, t in rows:
        pct = 100.0 * t["flagged"] / t["total"]
        head = f"{title}" if not colour else f"{BOLD}{title}{OFF}"
        L.append(head)
        count = f"{t['flagged']:,} of {t['total']:,}"
        if colour:
            count = f"{BOLD}{RED}{t['flagged']:,}{OFF} of {t['total']:,}"
        tail = f"  {count} {_rules.RULES[rule]['denominator']}  ({pct:.1f}%)"
        if t["total"] < SMALL_SAMPLE:
            small = "  small sample - read the count, not the rate"
            tail += (f"{DIM}{small}{OFF}" if colour else small)
        if t["indeterminate"]:
            extra = f"  +{t['indeterminate']:,} indeterminate"
            tail += (f"{DIM}{extra}{OFF}" if colour else extra)
        L.append("  " + bar(t, colour, g=g) + tail)
        L.append("")

    L += ["Each bar is measured against the cases where that rule could fire at all, "
          "not against the whole portfolio - the denominator is named on every row.",
          "Indeterminate is shown separately and is never counted as a finding.", ""]
    return L
