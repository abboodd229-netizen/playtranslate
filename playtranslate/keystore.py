"""Keep the DeepL key out of plain text on Windows.

On Windows the key is encrypted with DPAPI (tied to the Windows user account),
so copying config.json to another PC or sharing it with a friend does not leak
the key. Elsewhere the key is stored as-is. Stored values carry a prefix so
either form loads correctly.
"""

from __future__ import annotations

import base64
import logging
import sys

log = logging.getLogger(__name__)

_DPAPI_PREFIX = "dpapi:"
_PLAIN_PREFIX = "plain:"


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    fn.restype = wintypes.BOOL
    ok = fn(ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(value: str) -> str:
    if sys.platform == "win32":
        try:
            enc = _dpapi(value.encode("utf-8"), encrypt=True)
            return _DPAPI_PREFIX + base64.b64encode(enc).decode("ascii")
        except Exception as exc:  # pragma: no cover - Windows only
            log.warning("DPAPI unavailable (%s); storing key unencrypted", exc)
    return _PLAIN_PREFIX + value


def unprotect(stored: str) -> str:
    if stored.startswith(_DPAPI_PREFIX):
        if sys.platform != "win32":
            log.warning("Encrypted key from Windows cannot be read here; please re-enter it")
            return ""
        try:
            return _dpapi(base64.b64decode(stored[len(_DPAPI_PREFIX):]), encrypt=False).decode("utf-8")
        except Exception as exc:  # pragma: no cover - Windows only
            log.warning("Could not decrypt saved key (%s); please re-enter it", exc)
            return ""
    if stored.startswith(_PLAIN_PREFIX):
        return stored[len(_PLAIN_PREFIX):]
    return stored  # value written by hand
