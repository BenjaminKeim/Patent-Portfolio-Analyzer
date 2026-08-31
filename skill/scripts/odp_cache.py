"""A dated, append-only cache for ODP responses.

WHY. The shared client throttles to one request every 1.2s, so an audit's wall clock
is its call count. Iterating on one client - which is the normal way this skill gets
used - pays that price again on every run for data that has not moved. A full
Example Corporation audit costs 58 seconds cold and 16 seconds warm; every second of what is
left is DuckDB, not the network.

WHAT IT IS NOT. It is not a speed hack layered over a currency-critical tool without
telling anyone. Two rules keep it honest:

  1. NOTHING IS EVER DELETED. Every fetch writes a new dated entry beside the old one.
     A cache read takes the newest. The history is the point: it is the only record of
     what USPTO was saying about a portfolio on a given day, and for a prosecution
     audit that provenance can matter more than the speed.

  2. STALE DATA IS NEVER SERVED SILENTLY. Past MAX_AGE_DAYS the run stops and asks.
     On a terminal it prompts; anywhere else it raises StaleCacheError so the caller
     surfaces the question to a person. Answering once settles the whole run.

Every result that touched the cache reports how many responses came from it and how
old the oldest one was, so a report can always say how fresh it is.

Layout, under PPA_ODP_CACHE or the platform cache directory:

    <cache>/<sha256 of the request>/<UTC ISO timestamp>.json.gz

Each file holds the request that produced it alongside the response, so the cache is
auditable on its own without this module.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ben's number. Two weeks is long enough that iterating on one client all week costs
# nothing, and short enough that a portfolio never quietly drifts a month out of date.
MAX_AGE_DAYS = 14

_STAMP = "%Y%m%dT%H%M%SZ"

_state = {
    "mode": "auto",          # auto | refresh | off
    "max_age_days": MAX_AGE_DAYS,
    "stale_choice": None,    # None = not yet asked; True = use stale; False = refetch
    "hits": 0,
    "misses": 0,
    "writes": 0,
    "oldest_used": None,     # datetime of the oldest cached response actually served
}


class StaleCacheError(RuntimeError):
    """Raised when cached data is past its age limit and no person is present to ask."""

    def __init__(self, age_days: float, fetched: datetime):
        self.age_days = age_days
        self.fetched = fetched
        super().__init__(
            f"Cached USPTO responses for this run are {age_days:.0f} days old "
            f"(fetched {fetched:%Y-%m-%d}), past the {_state['max_age_days']}-day limit. "
            "Re-run with --cache refresh to fetch current data, or --stale-ok to use "
            "what is cached and have the report say how old it is."
        )


def root() -> Path:
    env = os.environ.get("PPA_ODP_CACHE")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "patent-portfolio-analyzer" / "odp-cache"


def configure(mode: str = "auto", max_age_days: int = MAX_AGE_DAYS,
              stale_ok: bool = False) -> None:
    """Set the policy for this run and reset its counters."""
    _state.update(mode=mode, max_age_days=max_age_days,
                  stale_choice=True if stale_ok else None,
                  hits=0, misses=0, writes=0, oldest_used=None)


def stats() -> dict:
    """What the cache did this run, for the report to quote."""
    oldest = _state["oldest_used"]
    age = (datetime.now(timezone.utc) - oldest).days if oldest else None
    return {
        "mode": _state["mode"],
        "hits": _state["hits"],
        "misses": _state["misses"],
        "writes": _state["writes"],
        "oldest_response_used": oldest.strftime("%Y-%m-%d") if oldest else None,
        "oldest_response_age_days": age,
        "location": str(root()),
    }


def _key(fn: str, args: tuple, kwargs: dict) -> str:
    payload = json.dumps({"fn": fn, "args": args, "kwargs": kwargs},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entries(key: str) -> list:
    d = root() / key
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json.gz"))


def _read(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _write(key: str, fn: str, args: tuple, kwargs: dict, response) -> None:
    now = datetime.now(timezone.utc)
    d = root() / key
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.strftime(_STAMP)}.json.gz"
    body = {"fetched": now.isoformat(), "fn": fn,
            "args": list(args), "kwargs": kwargs, "response": response}
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(body, fh, default=str)
    tmp.replace(path)
    _state["writes"] += 1


def _ask_stale(age_days: float, fetched: datetime) -> bool:
    """Ask once per run whether stale data is acceptable. True means use it."""
    if _state["stale_choice"] is not None:
        return _state["stale_choice"]
    if not (sys.stdin and sys.stdin.isatty()):
        raise StaleCacheError(age_days, fetched)
    print(f"\nCached USPTO data for this run is {age_days:.0f} days old "
          f"(fetched {fetched:%Y-%m-%d}), past the {_state['max_age_days']}-day limit.",
          file=sys.stderr)
    try:
        answer = input("Refresh from USPTO now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # isatty() is not a reliable promise that someone is there to answer - it
        # reports true under some shells and agent harnesses with nothing on stdin.
        # If the question cannot actually be asked, raise rather than guess: quietly
        # serving stale prosecution data because a prompt fell on the floor is the one
        # outcome worth failing to avoid.
        raise StaleCacheError(age_days, fetched) from None
    _state["stale_choice"] = answer in ("n", "no")
    return _state["stale_choice"]


def wrap(fn_name: str, fn):
    """Return fn with caching applied, per the configured policy."""
    def cached(*args, **kwargs):
        if _state["mode"] == "off":
            return fn(*args, **kwargs)

        key = _key(fn_name, args, kwargs)
        entries = _entries(key)

        if entries and _state["mode"] != "refresh":
            newest = entries[-1]
            try:
                body = _read(newest)
                fetched = datetime.fromisoformat(body["fetched"])
            except Exception:
                body, fetched = None, None
            if body is not None and fetched is not None:
                age = (datetime.now(timezone.utc) - fetched).total_seconds() / 86400
                fresh = age <= _state["max_age_days"]
                # Past the limit, a person decides - once, for the whole run.
                if fresh or _ask_stale(age, fetched):
                    _state["hits"] += 1
                    if _state["oldest_used"] is None or fetched < _state["oldest_used"]:
                        _state["oldest_used"] = fetched
                    return body["response"]

        _state["misses"] += 1
        response = fn(*args, **kwargs)
        try:
            _write(key, fn_name, args, kwargs, response)
        except OSError:
            # A cache that cannot be written must never break the audit.
            pass
        return response

    cached.__name__ = getattr(fn, "__name__", fn_name)
    cached.__doc__ = getattr(fn, "__doc__", None)
    return cached


def summary() -> dict:
    """Everything on disk: entry count, versions kept, size, date range."""
    r = root()
    keys = size = versions = 0
    oldest = newest = None
    if r.is_dir():
        for d in r.iterdir():
            if not d.is_dir():
                continue
            files = sorted(d.glob("*.json.gz"))
            if not files:
                continue
            keys += 1
            versions += len(files)
            for f in files:
                size += f.stat().st_size
                stamp = f.name.split(".")[0]
                oldest = min(oldest or stamp, stamp)
                newest = max(newest or stamp, stamp)

    def show(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if s else None

    return {"location": str(r), "requests_cached": keys, "responses_kept": versions,
            "megabytes": round(size / 1048576, 1),
            "oldest": show(oldest), "newest": show(newest),
            "max_age_days": _state["max_age_days"]}
