# -*- coding: utf-8 -*-
"""Keep Windows taskbar auto-hide disabled while the application runs."""

import ctypes
from ctypes import wintypes
import winreg


ABM_GETSTATE = 0x00000004
ABM_SETSTATE = 0x0000000A
ABS_AUTOHIDE = 0x00000001
CHECK_INTERVAL_MS = 100
STUCK_RECTS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3"


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", RECT),
        ("lParam", wintypes.LPARAM),
    ]


class TaskbarAutoHideGuard:
    def __init__(self, shell32=None, registry=None, user32=None):
        self._shell32 = shell32 or ctypes.WinDLL("shell32", use_last_error=True)
        self._registry = registry or winreg
        self._user32 = user32 or ctypes.WinDLL("user32", use_last_error=True)
        if shell32 is None:
            self._shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
            self._shell32.SHAppBarMessage.restype = ctypes.c_size_t
        if user32 is None:
            self._user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            self._user32.FindWindowW.restype = wintypes.HWND

    def enforce(self):
        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(data)
        # Resolve each time so Explorer restarts do not leave a stale HWND.
        data.hWnd = self._user32.FindWindowW("Shell_TrayWnd", None)
        if not data.hWnd:
            raise OSError("任务栏尚未就绪，稍后自动重试")
        state = self._shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data))
        changed = bool(state & ABS_AUTOHIDE)
        if changed or self._saved_auto_hide_enabled():
            data.lParam = state & ~ABS_AUTOHIDE
            self._shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(data))
            current = self._shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data))
            if current & ABS_AUTOHIDE:
                raise OSError("Windows 未接受关闭任务栏自动隐藏的请求")
            changed = True
        return self._disable_saved_auto_hide() or changed

    def _saved_auto_hide_enabled(self):
        try:
            with self._registry.OpenKey(
                    self._registry.HKEY_CURRENT_USER, STUCK_RECTS_KEY, 0,
                    self._registry.KEY_QUERY_VALUE) as key:
                value, kind = self._registry.QueryValueEx(key, "Settings")
                return (kind == self._registry.REG_BINARY and len(value) > 8
                        and bool(value[8] & ABS_AUTOHIDE))
        except FileNotFoundError:
            return False

    def _disable_saved_auto_hide(self):
        try:
            with self._registry.OpenKey(
                    self._registry.HKEY_CURRENT_USER, STUCK_RECTS_KEY, 0,
                    self._registry.KEY_QUERY_VALUE | self._registry.KEY_SET_VALUE) as key:
                value, kind = self._registry.QueryValueEx(key, "Settings")
                if kind != self._registry.REG_BINARY or len(value) <= 8:
                    return False
                if not value[8] & ABS_AUTOHIDE:
                    return False
                updated = bytearray(value)
                updated[8] &= ~ABS_AUTOHIDE
                self._registry.SetValueEx(key, "Settings", 0,
                                          self._registry.REG_BINARY, bytes(updated))
                return True
        except FileNotFoundError:
            return False
