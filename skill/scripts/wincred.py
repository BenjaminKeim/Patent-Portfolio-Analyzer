"""Read secrets from the Windows Credential Manager (Credential Locker).

Author: Benjamin Keim

Generic credentials stored via Control Panel -> Credential Manager -> Windows
Credentials -> Add a generic credential are DPAPI-encrypted per-user, which is a
better resting place for API keys than a plaintext file in the profile directory.

Pure ctypes against advapi32 -- no third-party dependency. Returns None on any
non-Windows platform or when the entry does not exist, so callers can fall back.
"""

import ctypes
import sys
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
ERROR_NOT_FOUND = 1168


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def read_generic(target):
    """Return the password of generic credential `target`, or None if absent.

    The GUI and cmdkey store the blob as UTF-16LE; some tools write UTF-8. Try
    UTF-16LE first and fall back, since a wrong guess yields silent mojibake
    rather than an error.
    """
    if not sys.platform.startswith("win"):
        return None

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    pcred = ctypes.POINTER(_CREDENTIAL)()
    if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise OSError(f"CredReadW failed for {target!r} (error {err})")

    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    finally:
        advapi32.CredFree(pcred)

    if not blob:
        return None
    try:
        value = blob.decode("utf-16-le")
    except UnicodeDecodeError:
        value = blob.decode("utf-8", "replace")
    # A UTF-8 blob decoded as UTF-16LE produces interleaved NULs; detect and redo.
    if "\x00" in value:
        value = blob.decode("utf-8", "replace")
    return value.strip() or None


if __name__ == "__main__":
    # Diagnostic only: reports presence and length, never the secret itself.
    for name in sys.argv[1:]:
        got = read_generic(name)
        print(f"{name}: {'found, length ' + str(len(got)) if got else 'NOT FOUND'}")
