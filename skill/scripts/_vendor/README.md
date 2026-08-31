# Vendored dependency — do not edit

`uspto_odp.py` here is a copy of the shared USPTO ODP client, canonically at
`~/.claude/skills/uspto-odp/scripts/uspto_odp.py`.

This skill imports the installed `uspto-odp` skill when it is available and only falls
back to this copy when it is not — which is the case when this skill was downloaded on
its own. Edit the canonical file, then run:

    python ~/.claude/skills/uspto-odp/scripts/sync_vendor.py

Credential setup and troubleshooting:

    python uspto_odp.py setup
    python uspto_odp.py doctor
