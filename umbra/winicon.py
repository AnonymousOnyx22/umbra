"""Put the ghost on the console window instead of Python's icon.

`umbra.exe` is a setuptools console-script wrapper, so Windows shows the
Python icon for it in the taskbar and title bar. A shortcut's icon only
covers the shortcut, not the window that opens - so the icon is set on the
live console window at startup, via WM_SETICON. No dependencies: ctypes only.

Every call is best-effort. On a non-Windows machine, inside Windows Terminal
(which draws its own profile icon), or with no console at all, this quietly
does nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ID = "umbra.localcodingagent"

_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_LR_DEFAULTSIZE = 0x0040


def icon_path() -> Path | None:
    """The packaged .ico, falling back to the one in a source checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "assets" / "umbra.ico",
                      here.parent / "assets" / "umbra.ico"):
        if candidate.is_file():
            return candidate
    return None


def set_app_id(app_id: str = APP_ID) -> None:
    """Stop the taskbar from filing umbra under python.exe."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:  # noqa: BLE001
        pass


def apply_window_icon(path: Path | None = None) -> bool:
    """Set the console window's large and small icons. True if it took."""
    if not sys.platform.startswith("win"):
        return False
    path = path or icon_path()
    if path is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32.GetConsoleWindow.restype = wintypes.HWND
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return False

        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]

        target = str(path)
        # 32px for the alt-tab/taskbar icon, 16px for the title bar.
        big = user32.LoadImageW(None, target, _IMAGE_ICON, 32, 32, _LR_LOADFROMFILE)
        small = user32.LoadImageW(None, target, _IMAGE_ICON, 16, 16, _LR_LOADFROMFILE)
        if not big and not small:
            return False
        if big:
            user32.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, small)
        return bool(big or small)
    except Exception:  # noqa: BLE001
        return False


def brand_console() -> None:
    """Everything the console needs to stop looking like a Python script."""
    set_app_id()
    apply_window_icon()
