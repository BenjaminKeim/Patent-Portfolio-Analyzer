"""Shared USPTO Open Data Portal (ODP) client.

Single source of truth for every skill that talks to ODP. Skills import this module
instead of carrying their own copy of the credential lookup and HTTP plumbing; fix a
bug here and every caller inherits the fix.

Why this exists: three skills each had a private ``_load_odp_api_key()``. They drifted,
and on 2026-08-24 the ``filing_receipt_review`` copy silently returned an empty key on
every run because it predated the Credential Manager tier. Its ODP verification had been
dead for weeks with no warning.

Two call styles are provided, because callers want different things:

  * ``lookup_application()`` never raises. It returns a dict with an ``error`` key,
    suitable for rendering one row of a comparison table where a failed lookup is a
    cell value, not a crash.
  * ``request()`` and the endpoint helpers raise :class:`ODPError`. Use these for
    analysis scripts where a partial result is worse than a stack trace.

Portability is a design constraint, not an afterthought. These skills get shared, and
whoever downloads them runs a different OS, stores secrets differently, and may have no
ODP key at all. So: stdlib only (no ``requests``), every credential backend optional,
and a missing key degrades to a clear message rather than a traceback. See
``resolve_api_key()`` for the full search order and ``KEY_COMMAND_VAR`` for the escape
hatch that supports any password manager.

Author: Benjamin Keim
License: MIT
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = '1.0.0'

__all__ = [
    'ODPError',
    'CRED_NAME',
    'KEY_COMMAND_VAR',
    'load_api_key',
    'require_api_key',
    'resolve_api_key',
    'describe_key_sources',
    'setup_instructions',
    'request',
    'lookup_application',
    'application',
    'transactions',
    'continuity',
    'search',
    'to_iso',
    'normalize_app_number',
    'doctor',
]

CRED_NAME = 'USPTO_ODP_API_KEY'
KEY_COMMAND_VAR = 'USPTO_ODP_KEY_COMMAND'
DEFAULT_BASE = 'https://api.uspto.gov/api/v1'
SIGNUP_URL = 'https://data.uspto.gov/myodp'

# USPTO documents 60 req/min for the trademark APIs; the patent endpoints carry no
# separate published limit, so pace well under it and stay serial. This runs against a
# personal, identity-verified key -- a burst that trips the limiter is attributable to
# the key's owner, so throughput is not worth optimizing for.
MIN_INTERVAL_S = 1.2
_last_call = 0.0


class ODPError(RuntimeError):
    """An ODP request failed. Message is safe to display; it never contains the key."""


# ─────────────────────────────────────────────────────────────────────────────
# Credentials
#
# Every backend below is optional and fails soft. A machine with none of them
# configured simply gets '' from load_api_key(), and callers skip ODP work.
# ─────────────────────────────────────────────────────────────────────────────

# Records why a configured key command produced nothing, so doctor() can say so.
# Silent fallthrough is the exact failure mode this module exists to eliminate.
_KEY_COMMAND_ERROR = ''


def _split_key_command(cmd: str) -> List[str]:
    """Split the user's key command into argv.

    A JSON array is honored verbatim -- the unambiguous form, and the way to express
    a Windows path containing backslashes:
        USPTO_ODP_KEY_COMMAND='["C:\\Program Files\\1Password\\op.exe", "read", "op://v/i/f"]'

    Anything else is split with POSIX rules on every platform, because those are the
    rules that handle quoted arguments correctly. Windows' native rules leave the
    quotes attached, which silently mangles any command with a quoted argument.
    """
    cmd = cmd.strip()
    if cmd.startswith('['):
        try:
            argv = json.loads(cmd)
            if isinstance(argv, list) and all(isinstance(a, str) for a in argv):
                return argv
        except (ValueError, TypeError):
            return []

    argv = shlex.split(cmd, posix=True)

    # POSIX splitting treats a backslash as an escape, so a Windows path arrives as
    # "C:UsersBenop.exe" and the launch fails. When that is what happened -- Windows,
    # backslashes present, and the resulting program does not exist -- re-split with
    # Windows rules and strip the quotes those rules leave attached.
    if (os.name == 'nt' and argv and '\\' in cmd
            and not shutil.which(argv[0]) and not Path(argv[0]).exists()):
        native = [a.strip('"') for a in shlex.split(cmd, posix=False)]
        if native and (shutil.which(native[0]) or Path(native[0]).exists()):
            return native
    return argv


def _from_key_command() -> str:
    """Run the user's own command and take its stdout as the key.

    This is the escape hatch that makes any secret store work without this module
    knowing about it -- 1Password (`op read op://Private/USPTO/key`), pass
    (`pass show uspto/odp`), Bitwarden, `gcloud secrets versions access`, or a
    homemade script. Same idea as a git credential helper.

    Executed without a shell, so no shell metacharacters are interpreted and a stray
    quote cannot become an injection. Pipes and redirection therefore do not work --
    wrap those in a script and point this at the script.
    """
    global _KEY_COMMAND_ERROR
    _KEY_COMMAND_ERROR = ''
    cmd = os.environ.get(KEY_COMMAND_VAR, '').strip()
    if not cmd:
        return ''
    try:
        argv = _split_key_command(cmd)
        if not argv:
            _KEY_COMMAND_ERROR = 'command could not be parsed into arguments'
            return ''
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            detail = (out.stderr or '').strip().splitlines()
            _KEY_COMMAND_ERROR = (
                f'command exited {out.returncode}'
                + (f': {detail[0][:160]}' if detail else '')
            )
            return ''
        # Take the first non-empty line: some CLIs append a trailing newline or a
        # status line after the secret itself.
        for line in out.stdout.splitlines():
            if line.strip():
                return line.strip()
        _KEY_COMMAND_ERROR = 'command produced no output'
    except FileNotFoundError:
        _KEY_COMMAND_ERROR = f'executable not found: {cmd.split()[0][:80]}'
    except subprocess.TimeoutExpired:
        _KEY_COMMAND_ERROR = 'command timed out after 30s'
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _KEY_COMMAND_ERROR = f'{type(exc).__name__}: {str(exc)[:160]}'
    return ''


def _from_windows_credential_manager() -> str:
    """Read a Windows Credential Manager generic credential, or '' if unavailable.

    Uses the wincred.py helper if present (Ben's ~/.claude/scripts copy, or a copy
    vendored beside this file). Absent on other platforms, which is not an error.
    """
    if os.name != 'nt':
        return ''
    for directory in (Path(__file__).resolve().parent, Path.home() / '.claude' / 'scripts'):
        if not (directory / 'wincred.py').exists():
            continue
        try:
            sys.path.insert(0, str(directory))
            from wincred import read_generic  # type: ignore
            return (read_generic(CRED_NAME) or '').strip()
        except Exception:
            continue
    return ''


def _from_macos_keychain() -> str:
    """Read a macOS Keychain generic password named USPTO_ODP_API_KEY, or ''.

    Store one with:
        security add-generic-password -a "$USER" -s USPTO_ODP_API_KEY -w
    """
    if platform.system() != 'Darwin' or not shutil.which('security'):
        return ''
    try:
        out = subprocess.run(
            ['security', 'find-generic-password', '-s', CRED_NAME, '-w'],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _from_secret_service() -> str:
    """Read a freedesktop Secret Service entry via secret-tool (Linux), or ''.

    Store one with:
        secret-tool store --label="USPTO ODP" service USPTO_ODP_API_KEY
    """
    if not shutil.which('secret-tool'):
        return ''
    try:
        out = subprocess.run(
            ['secret-tool', 'lookup', 'service', CRED_NAME],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _key_file_paths() -> List[Path]:
    """Candidate plaintext key files, most-preferred first.

    XDG location first for anyone installing fresh; the two legacy paths are kept so
    existing setups do not break on upgrade.
    """
    xdg = os.environ.get('XDG_CONFIG_HOME', '').strip()
    config_root = Path(xdg) if xdg else Path.home() / '.config'
    return [
        config_root / 'uspto-odp' / 'api_key',
        Path.home() / '.uspto_odp_api_key',
        Path.home() / '.patent_qc_api_key',          # legacy
        Path.home() / '.claude' / 'patent_qc_api_key',  # legacy
    ]


def _from_key_file() -> Tuple[str, str]:
    """Return (key, path_that_supplied_it) from the first readable key file.

    Files accept a raw key on one line, or ``env:VAR_NAME`` to redirect to a
    differently-named environment variable. Blank lines and ``#`` comments are ignored
    so a file can carry a note about where the key came from.
    """
    for candidate in _key_file_paths():
        try:
            # utf-8-sig: PowerShell-written files carry a BOM.
            raw = candidate.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError):
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.lower().startswith('env:'):
                line = os.environ.get(line[4:].strip(), '').strip()
            if line:
                return line, str(candidate)
    return '', ''


def resolve_api_key() -> Tuple[str, str]:
    """Return (key, source_label). Both are '' when no key is configured.

    Search order, first hit wins:

      1. ``USPTO_ODP_KEY_COMMAND``  -- run any command, use its stdout (password
         managers, cloud secret stores, custom scripts)
      2. ``USPTO_ODP_API_KEY``     -- environment variable
      3. OS secret store           -- Windows Credential Manager, macOS Keychain,
         or Linux Secret Service, whichever this platform has
      4. Key file                  -- ~/.config/uspto-odp/api_key,
         ~/.uspto_odp_api_key, or the two legacy ~/.patent_qc_api_key paths

    Explicit configuration (1 and 2) outranks the OS store deliberately: someone
    testing against a second key, or running in CI, needs to override without
    disturbing their stored credential.

    The source label names *where* the key came from -- never the key itself.
    """
    key = _from_key_command()
    if key:
        return key, f'{KEY_COMMAND_VAR} command'

    key = os.environ.get(CRED_NAME, '').strip()
    if key:
        return key, f'{CRED_NAME} environment variable'

    for reader, label in (
        (_from_windows_credential_manager, 'Windows Credential Manager'),
        (_from_macos_keychain, 'macOS Keychain'),
        (_from_secret_service, 'Linux Secret Service (secret-tool)'),
    ):
        key = reader()
        if key:
            return key, label

    key, path = _from_key_file()
    if key:
        return key, f'key file {path}'

    return '', ''


def load_api_key() -> str:
    """Return the ODP API key, or '' when none is configured.

    Returns '' rather than raising so a caller can degrade gracefully. Callers that
    cannot proceed without a key should use :func:`require_api_key`.
    """
    return resolve_api_key()[0]


def setup_instructions() -> str:
    """Return platform-appropriate instructions for storing a key. Safe to print."""
    system = platform.system()
    if system == 'Windows':
        store = (
            'Windows Credential Manager (recommended):\n'
            '    Control Panel -> Credential Manager -> Windows Credentials\n'
            f'    -> Add a generic credential named {CRED_NAME}\n'
            '    (or: cmdkey /generic:%s /user:odp /pass)' % CRED_NAME
        )
    elif system == 'Darwin':
        store = (
            'macOS Keychain (recommended):\n'
            f'    security add-generic-password -a "$USER" -s {CRED_NAME} -w'
        )
    else:
        store = (
            'Secret Service (recommended, needs libsecret):\n'
            f'    secret-tool store --label="USPTO ODP" service {CRED_NAME}'
        )
    return (
        f'No USPTO ODP API key found. Get one free at {SIGNUP_URL}\n'
        '(identity verification required), then store it any of these ways:\n\n'
        f'  {store}\n\n'
        '  Your own password manager:\n'
        f'    export {KEY_COMMAND_VAR}="op read op://Private/USPTO/credential"\n'
        '    (any command whose stdout is the key -- pass, bw, gcloud, a script)\n\n'
        '  Environment variable:\n'
        f'    export {CRED_NAME}="your-key-here"\n\n'
        '  Plain file (simplest; protect its permissions):\n'
        f'    ~/.config/uspto-odp/api_key\n\n'
        'ODP lookups are optional -- every skill still runs without a key, and simply '
        'reports the checks it could not perform.'
    )


def require_api_key() -> str:
    """Return the ODP API key, raising :class:`ODPError` with setup help if absent."""
    key = load_api_key()
    if not key:
        raise ODPError(setup_instructions())
    return key


def describe_key_sources() -> List[Dict[str, Any]]:
    """Report which credential backends are available and which supplied the key.

    Diagnostics only -- reports presence and length, never a key value.
    """
    key, source = resolve_api_key()
    rows: List[Dict[str, Any]] = [
        {'source': f'{KEY_COMMAND_VAR} command',
         'configured': bool(os.environ.get(KEY_COMMAND_VAR, '').strip())},
        {'source': f'{CRED_NAME} environment variable',
         'configured': bool(os.environ.get(CRED_NAME, '').strip())},
        {'source': 'Windows Credential Manager',
         'configured': bool(_from_windows_credential_manager())},
        {'source': 'macOS Keychain', 'configured': bool(_from_macos_keychain())},
        {'source': 'Linux Secret Service', 'configured': bool(_from_secret_service())},
        {'source': 'key file', 'configured': bool(_from_key_file()[0])},
    ]
    for row in rows:
        row['in_use'] = bool(key) and row['source'].split(' (')[0] in source
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    """Return the API base, honoring the USPTO_ODP_BASE_URL test override.

    https is enforced so a misconfigured override cannot transmit the key in
    plaintext; a localhost mock over http is allowed for offline testing.
    """
    base = os.environ.get('USPTO_ODP_BASE_URL', DEFAULT_BASE).rstrip('/')
    if not base.startswith('https://') and not base.startswith('http://localhost'):
        raise ODPError(f'Refusing to send the API key to a non-https base URL: {base[:60]}')
    return base


def _throttle() -> None:
    global _last_call
    delta = time.monotonic() - _last_call
    if delta < MIN_INTERVAL_S:
        time.sleep(MIN_INTERVAL_S - delta)
    _last_call = time.monotonic()


def normalize_app_number(raw: str) -> str:
    """Strip formatting from a US application number, leaving digits only.

    "18/731,126" -> "18731126". Because only digits survive, the result is safe to
    interpolate into a URL path -- no traversal or injection is possible.
    """
    return re.sub(r'[/,.\s\-]', '', raw or '')


def request(path: str, params: Optional[Dict[str, Any]] = None, *,
            retries: int = 3, timeout: int = 60) -> Dict[str, Any]:
    """GET an ODP endpoint, with throttling and retry on 429/5xx.

    Raises :class:`ODPError` on any non-200 rather than returning a partial result,
    so a caller never mistakes an error page for data.
    """
    key = require_api_key()
    url = f'{_base_url()}{path}'
    if params:
        url = f'{url}?{urllib.parse.urlencode(params)}'

    last_error = ''
    for attempt in range(retries):
        _throttle()
        req_obj = urllib.request.Request(
            url, headers={'Accept': 'application/json', 'X-API-KEY': key}
        )
        try:
            with urllib.request.urlopen(req_obj, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8-sig'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    wait = int(exc.headers.get('Retry-After', 2 ** (attempt + 2)))
                except (ValueError, AttributeError):
                    wait = 2 ** (attempt + 2)
                time.sleep(min(wait, 60))
                last_error = 'rate limited (429)'
                continue
            if 500 <= exc.code < 600 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                last_error = f'server error ({exc.code})'
                continue
            if exc.code in (401, 403):
                raise ODPError(
                    f'ODP returned {exc.code} (unauthorized). The key may be invalid, '
                    'or the ODP account may need the additional profile fields USPTO '
                    'began requiring on 18 August 2026.'
                ) from None
            raise ODPError(f'ODP {exc.code} for {path}') from None
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                last_error = str(exc)
                continue
            raise ODPError(f'ODP request failed for {path}: {exc}') from None
    raise ODPError(f'ODP request failed for {path} after {retries} attempts: {last_error}')


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints (raising)
# ─────────────────────────────────────────────────────────────────────────────

def application(app_number: str) -> Dict[str, Any]:
    """Bibliographic and status data for one application."""
    return request(f'/patent/applications/{normalize_app_number(app_number)}')


def transactions(app_number: str) -> Dict[str, Any]:
    """Prosecution event history for one application."""
    return request(f'/patent/applications/{normalize_app_number(app_number)}/transactions')


def continuity(app_number: str) -> Dict[str, Any]:
    """Parent/child continuity data -- answers "was a child ever filed"."""
    return request(f'/patent/applications/{normalize_app_number(app_number)}/continuity')


def search(query: str, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
    """Search the patent file wrapper. `query` uses ODP's field:value syntax."""
    return request('/patent/applications/search',
                   {'q': query, 'limit': limit, 'offset': offset})


# ─────────────────────────────────────────────────────────────────────────────
# Non-raising lookup (for table-style callers)
# ─────────────────────────────────────────────────────────────────────────────

# Stable error codes returned in the 'error' field of lookup_application().
ERR_NO_KEY = 'no_key'
ERR_BAD_KEY = 'bad_key'
ERR_NOT_FOUND = 'not_found'
ERR_RATE_LIMITED = 'rate_limited'
ERR_PCT = 'pct_not_supported'


def lookup_application(raw_app: str) -> Dict[str, str]:
    """Fetch key metadata for one US application without raising.

    Returns a dict with: error, filing_date, status_desc, patent_number.
    ``error`` is None on success, otherwise one of the ERR_* codes above or a short
    message. Designed for callers rendering one row per application, where a failed
    lookup belongs in the table rather than aborting the run.
    """
    empty = {'error': None, 'filing_date': '', 'status_desc': '', 'patent_number': ''}

    # ODP indexes US national applications only; a PCT number is not an error in the
    # caller's data, it is simply outside this API's scope.
    if (raw_app or '').upper().startswith('PCT'):
        return {**empty, 'error': ERR_PCT}
    if not load_api_key():
        return {**empty, 'error': ERR_NO_KEY}

    clean = normalize_app_number(raw_app)
    try:
        data = request(f'/patent/applications/{clean}/meta-data', retries=2, timeout=12)
    except ODPError as exc:
        msg = str(exc)
        if 'unauthorized' in msg:
            return {**empty, 'error': ERR_BAD_KEY}
        if 'ODP 404' in msg or 'ODP 410' in msg:
            return {**empty, 'error': ERR_NOT_FOUND}
        if 'rate limited' in msg:
            return {**empty, 'error': ERR_RATE_LIMITED}
        return {**empty, 'error': msg}

    bag = data.get('patentFileWrapperDataBag') or []
    meta = (bag[0].get('applicationMetaData') or {}) if bag else {}
    if not meta:
        return {**empty, 'error': ERR_NOT_FOUND}
    return {
        'error': None,
        'filing_date': (meta.get('filingDate') or '').strip(),
        'status_desc': (meta.get('applicationStatusDescriptionText') or '').strip(),
        'patent_number': (meta.get('patentNumber') or '').strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def to_iso(date_str: str) -> str:
    """Normalize a date to YYYY-MM-DD so USPTO and ADS formats compare equal.

    ODP returns YYYY-MM-DD, filing receipts print MM/DD/YYYY, and ADS XFA stores
    YYYY-MM-DD. Anything unrecognized is returned unchanged for the caller to show.
    """
    s = (date_str or '').strip()
    if re.match(r'\d{4}-\d{2}-\d{2}', s):
        return s[:10]
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        return f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
    return s


def doctor() -> Dict[str, Any]:
    """Confirm the key resolves and the API answers. Never prints the key value."""
    key, source = resolve_api_key()
    out: Dict[str, Any] = {
        'client_version': __version__,
        'platform': platform.system(),
        'credential_name': CRED_NAME,
        'sources': describe_key_sources(),
    }
    if _KEY_COMMAND_ERROR:
        # A configured command that fails must be loud: the user believes their
        # password manager is wired up, and a lower tier may be quietly answering
        # with a stale key instead.
        out['key_command_error'] = _KEY_COMMAND_ERROR
    if not key:
        out['key'] = 'MISSING'
        out['setup'] = setup_instructions()
        return out
    out['key'] = f'found (length {len(key)})'
    out['key_source'] = source
    try:
        # Cheapest real call: single-record search.
        data = search('applicationMetaData.filingDate:[2020-01-01 TO 2020-01-02]', limit=1)
        out['api'] = 'reachable'
        out['top_level_keys'] = sorted(data.keys())[:10]
    except ODPError as exc:
        out['api'] = 'ERROR'
        out['detail'] = str(exc)
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description='USPTO ODP shared client',
        epilog='Run "doctor" first if lookups come back empty.',
    )
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('doctor', help='check key + connectivity (never prints the key)')
    sub.add_parser('setup', help='print instructions for storing a key on this platform')
    p_app = sub.add_parser('app', help='fetch one application')
    p_app.add_argument('number')
    p_look = sub.add_parser('lookup', help='non-raising metadata lookup')
    p_look.add_argument('number')
    p_search = sub.add_parser('search', help='search the file wrapper')
    p_search.add_argument('query')
    p_search.add_argument('--limit', type=int, default=25)
    args = ap.parse_args()

    if args.cmd == 'setup':
        print(setup_instructions())
        return
    try:
        if args.cmd == 'doctor':
            result: Any = doctor()
        elif args.cmd == 'app':
            result = application(args.number)
        elif args.cmd == 'lookup':
            result = lookup_application(args.number)
        else:
            result = search(args.query, limit=args.limit)
    except ODPError as exc:
        sys.exit(f'ERROR: {exc}')
    print(json.dumps(result, indent=2)[:8000])


if __name__ == '__main__':
    main()
