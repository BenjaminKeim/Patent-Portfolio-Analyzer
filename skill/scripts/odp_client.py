"""USPTO Open Data Portal client for the patent-portfolio-analyzer skill.

Covers what the local PatEx corpus cannot: anything filed or decided after the
June 2023 snapshot. Use the corpus for baselines (it has volume); use this for the
specific case in front of you (it has currency).

Credentials follow the house pattern already used by patent-filing-qc:
  1. Windows Credential Manager generic credential USPTO_ODP_API_KEY
  2. USPTO_ODP_API_KEY environment variable
The key value is never printed. Check presence with:
    python ~/.claude/scripts/wincred.py USPTO_ODP_API_KEY

Rate limiting is deliberately conservative and serial. This runs against Ben's
personal, ID.me-verified key; a burst that trips USPTO's limiter is attributable to
him, so throughput is not worth optimising for.

Usage:
    python odp_client.py doctor
    python odp_client.py app 18123456
    python odp_client.py search "applicationMetaData.firstApplicantName:Microsoft*" --limit 25
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("requests is not installed. Run:  pip install requests")

# Credential Manager helper. The vendored copy alongside this file is tried first so
# the skill works for anyone who clones the repo; Ben's ~/.claude/scripts copy is the
# fallback. On non-Windows both are absent and the environment variable is used instead.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path.home() / ".claude" / "scripts"))
try:
    from wincred import read_generic  # type: ignore
except Exception:  # pragma: no cover - non-Windows or helper missing
    def read_generic(_target):  # type: ignore
        return None

BASE = "https://api.uspto.gov/api/v1"
CRED_NAME = "USPTO_ODP_API_KEY"

# USPTO documents 60 req/min for the trademark APIs; the patent endpoints are not
# separately documented, so pace well under that and stay serial.
MIN_INTERVAL_S = 1.2
_last_call = 0.0


class ODPError(RuntimeError):
    pass


def load_api_key() -> str:
    key = read_generic(CRED_NAME) or os.environ.get(CRED_NAME)
    if not key:
        raise ODPError(
            f"No {CRED_NAME} found. Store it in Windows Credential Manager as a generic "
            f"credential named {CRED_NAME}, or set the environment variable. "
            "Get a key at https://data.uspto.gov/myodp (requires ID.me verification)."
        )
    return key.strip()


def _throttle() -> None:
    global _last_call
    delta = time.monotonic() - _last_call
    if delta < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - delta)
    _last_call = time.monotonic()


def request(path: str, params: dict | None = None, *, retries: int = 3) -> dict:
    """GET an ODP endpoint with throttling and retry on 429/5xx.

    Raises ODPError with the status code rather than returning a partial result,
    so callers never silently treat an error page as data.
    """
    key = load_api_key()
    url = f"{BASE}{path}"
    for attempt in range(retries):
        _throttle()
        resp = requests.get(
            url,
            params=params or {},
            headers={"X-API-KEY": key, "Accept": "application/json"},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 2)))
            time.sleep(min(wait, 60))
            continue
        if 500 <= resp.status_code < 600 and attempt < retries - 1:
            time.sleep(2 ** (attempt + 1))
            continue
        if resp.status_code in (401, 403):
            raise ODPError(
                f"ODP returned {resp.status_code} (unauthorised). The key may be invalid, "
                "or the ODP account may need the additional profile fields USPTO began "
                "requiring on 18 August 2026."
            )
        raise ODPError(f"ODP {resp.status_code} for {path}: {resp.text[:300]}")
    raise ODPError(f"ODP still rate-limited after {retries} attempts for {path}")


# --------------------------------------------------------------------- endpoints
def application(app_number: str) -> dict:
    """Bibliographic + status data for one application."""
    return request(f"/patent/applications/{app_number}")


def transactions(app_number: str) -> dict:
    """Prosecution event history - the live equivalent of the corpus transactions table."""
    return request(f"/patent/applications/{app_number}/transactions")


def continuity(app_number: str) -> dict:
    """Parent/child continuity. Needed for the A1/B1 'was a child filed' question."""
    return request(f"/patent/applications/{app_number}/continuity")


def search(query: str, limit: int = 25, offset: int = 0) -> dict:
    """Search the patent file wrapper. `query` uses ODP's field:value syntax."""
    return request(
        "/patent/applications/search",
        {"q": query, "limit": limit, "offset": offset},
    )


def doctor() -> dict:
    """Confirm the key resolves and the API answers, without printing the key."""
    out: dict = {"credential": CRED_NAME}
    try:
        key = load_api_key()
        out["key"] = f"found (length {len(key)})"
    except ODPError as exc:
        return {**out, "key": "MISSING", "detail": str(exc)}
    try:
        # Cheapest real call: one-record search.
        data = search("applicationMetaData.filingDate:[2020-01-01 TO 2020-01-02]", limit=1)
        out["api"] = "reachable"
        out["sample_count_field"] = next(
            (k for k in data if "count" in k.lower() or "total" in k.lower()), None
        )
        out["top_level_keys"] = sorted(data.keys())[:10]
    except ODPError as exc:
        out["api"] = "ERROR"
        out["detail"] = str(exc)
    return out


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
