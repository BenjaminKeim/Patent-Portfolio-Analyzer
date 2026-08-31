"""USPTO ODP access for the patent-portfolio-analyzer skill.

Thin adapter over the shared client in the ``uspto-odp`` skill. The implementation
that used to live here — credential resolution, throttling, retry — moved there so
one fix serves every skill that queries ODP. This file now only preserves the local
import name (``import odp_client``) and this skill's calling conventions.

Covers what the local PatEx corpus cannot: anything filed or decided after the
June 2023 snapshot. Use the corpus for baselines (it has volume); use this for the
specific case in front of you (it has currency).

Credentials, endpoints, and troubleshooting: ~/.claude/skills/uspto-odp/SKILL.md
Check the key without printing it:
    python ~/.claude/skills/uspto-odp/scripts/uspto_odp.py doctor

"""
from __future__ import annotations

import sys
from pathlib import Path

def _import_uspto_odp():
    """Return the shared ODP client module, or None if it cannot be found.

    Resolution order matters: the installed skill wins, so updating it updates every
    consumer; the vendored copy under scripts/_vendor/ exists only so this skill still
    works when downloaded on its own.
    """
    here = Path(__file__).resolve().parent
    for directory in (
        Path.home() / ".claude" / "skills" / "uspto-odp" / "scripts",  # installed skill
        here / "_vendor",                                              # bundled fallback
        here,
    ):
        if (directory / "uspto_odp.py").exists():
            sys.path.insert(0, str(directory))
            try:
                import uspto_odp  # type: ignore
                return uspto_odp
            except ImportError:
                continue
    return None


uspto_odp = _import_uspto_odp()
if uspto_odp is None:  # pragma: no cover
    sys.exit(
        "The shared uspto-odp client could not be found. Install the uspto-odp skill "
        "to ~/.claude/skills/uspto-odp/, or place uspto_odp.py in scripts/_vendor/ "
        "next to this file."
    )

ODPError = uspto_odp.ODPError
BASE = uspto_odp.DEFAULT_BASE
CRED_NAME = uspto_odp.CRED_NAME

# Caching is wrapped HERE, at this skill's adapter, and deliberately not inside the
# shared uspto_odp module. Other skills import that module and must not silently
# inherit this skill's caching policy - a filing-receipt check wants live data every
# time. Each exported entry point is wrapped once; the shared module's own internal
# calls to its request() are untouched, so nothing double-caches.
import odp_cache

request = odp_cache.wrap("request", uspto_odp.request)
application = odp_cache.wrap("application", uspto_odp.application)
transactions = odp_cache.wrap("transactions", uspto_odp.transactions)
continuity = odp_cache.wrap("continuity", uspto_odp.continuity)
search = odp_cache.wrap("search", uspto_odp.search)

# doctor() reports whether the API answers RIGHT NOW. Caching it would make it lie.
doctor = uspto_odp.doctor

# This skill's callers treat a missing key as fatal and catch ODPError to skip live
# tests, so bind the raising variant — not the shared module's ''-returning default.
load_api_key = uspto_odp.require_api_key


# No CLI here. `python ~/.claude/skills/uspto-odp/scripts/uspto_odp.py` already exposes
# doctor / app / transactions / continuity / search, and a second copy of the same
# commands only creates somewhere for the two to disagree. This module is an import
# target: the adapter that adds this skill's response cache to the shared client.
