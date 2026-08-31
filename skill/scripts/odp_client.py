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

Usage:
    python odp_client.py doctor
    python odp_client.py app 18123456
    python odp_client.py search "applicationMetaData.firstApplicantName:Microsoft*" --limit 25
"""
from __future__ import annotations

import argparse
import json
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

request = uspto_odp.request
application = uspto_odp.application
transactions = uspto_odp.transactions
continuity = uspto_odp.continuity
search = uspto_odp.search
doctor = uspto_odp.doctor

# This skill's callers treat a missing key as fatal and catch ODPError to skip live
# tests, so bind the raising variant — not the shared module's ''-returning default.
load_api_key = uspto_odp.require_api_key


def main() -> None:
    p = argparse.ArgumentParser(description="Query the USPTO Open Data Portal.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    a = sub.add_parser("app"); a.add_argument("application_number")
    t = sub.add_parser("transactions"); t.add_argument("application_number")
    c = sub.add_parser("continuity"); c.add_argument("application_number")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=25)
    args = p.parse_args()

    try:
        if args.cmd == "doctor":
            out = doctor()
        elif args.cmd == "app":
            out = application(args.application_number)
        elif args.cmd == "transactions":
            out = transactions(args.application_number)
        elif args.cmd == "continuity":
            out = continuity(args.application_number)
        else:
            out = search(args.query, limit=args.limit)
    except ODPError as exc:
        print(json.dumps({"error": str(exc)}, indent=2)); sys.exit(1)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
