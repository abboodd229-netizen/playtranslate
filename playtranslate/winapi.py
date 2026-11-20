"""Small Windows helpers through ctypes (no pywin32 needed).

Every function degrades gracefully on other systems so the rest of the app,
and the tests, can run anywhere.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    # Client area in physical screen pixels.
    left: int
    top: int
    width: int
    height: int
    minimized: bool


_USER32 = None


def _user32():
    """user32 with explicit argument types, so 64-bit handles pass safely."""
    global _USER32
    if _USER32 is not None:
        return _USER32
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    u.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    _USER32 = u
    return u


def enable_dpi_awareness() -> None:
    """Make window coordinates physical pixels, matching what mss captures.

    Qt also sets per-monitor awareness when QApplication starts; calling this
    first is harmless and keeps headless/CLI runs correct too.
    """
    if not IS_WINDOWS:
        return
    import ctypes

    try:
        # PER_MONITOR_AWARE_V2, Windows 10 1703+
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def windows_build() -> int:
    if not IS_WINDOWS:
        return 0
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return 0


def list_windows() -> list[WindowInfo]:
    """Visible top-level windows that have a title."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    results: list[WindowInfo] = []

    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            info = _window_info(hwnd, buf.value)
            if info is not None:
                results.append(info)
        except Exception:  # never let an exception cross the C callback
            log.debug("EnumWindows callback failed", exc_info=True)
        return True

    proc = EnumProc(callback)  # keep a reference while EnumWindows runs
    user32.EnumWindows(ctypes.cast(proc, ctypes.c_void_p), 0)
    return results


def _window_info(hwnd: int, title: str) -> WindowInfo | None:
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return WindowInfo(
        hwnd=int(hwnd),
        title=title,
        left=origin.x,
        top=origin.y,
        width=rect.right - rect.left,
        height=rect.bottom - rect.top,
        minimized=bool(user32.IsIconic(hwnd)),
    )


def find_window(title_part: str, exclude_hwnds: tuple[int, ...] = ()) -> WindowInfo | None:
    """First visible window whose title contains title_part (case-insensitive).

    Prefers an exact title match, then the largest window, so a browser tab
    that happens to mention "PS Remote Play" loses to the real app.
    """
    needle = title_part.strip().lower()
    if not needle:
        return None
    matches = [w for w in list_windows() if needle in w.title.lower() and w.hwnd not in exclude_hwnds]
    if not matches:
        return None
    matches.sort(key=lambda w: (w.title.lower() != needle, -(w.width * w.height)))
    return matches[0]


def refresh_window(hwnd: int) -> WindowInfo | None:
    """Current geometry of a known window, or None if it was closed."""
    if not IS_WINDOWS:
        return None
    import ctypes

    user32 = _user32()
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return _window_info(hwnd, buf.value)


def exclude_from_capture(hwnd: int) -> bool:
    """Hide our overlay from screen capture so we never read our own text.

    WDA_EXCLUDEFROMCAPTURE exists from Windows 10 2004 (build 19041). Returns
    False when unsupported; callers then keep the overlay outside the
    subtitle area instead.
    """
    if not IS_WINDOWS or windows_build() < 19041:
        return False
    import ctypes

    WDA_EXCLUDEFROMCAPTURE = 0x11
    try:
        return bool(_user32().SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError):
        return False


def keep_awake(on: bool) -> bool:
    """Stop Windows sleeping or turning the screen off while we watch the game.

    Nobody touches the laptop while playing, so after the idle timeout Windows
    would sleep or blank the display and the Remote Play picture would stop.
    The request belongs to the calling thread and ends with it, so call it from
    the long-running worker thread.
    """
    if not IS_WINDOWS:
        return False
    import ctypes

    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
        return bool(kernel32.SetThreadExecutionState(flags))
    except (AttributeError, OSError):
        return False


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PlayTranslate"


def can_run_at_login() -> bool:
    """Only the packaged exe has a stable path worth registering."""
    return IS_WINDOWS and bool(getattr(sys, "frozen", False))


def run_at_login() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
        return bool(value)
    except OSError:
        return False


def set_run_at_login(enabled: bool) -> bool:
    """Start the app when the user signs in to Windows (per user, no admin needed)."""
    if not can_run_at_login():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("Could not change the start-with-Windows setting")
        return False
