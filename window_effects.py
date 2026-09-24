# -*- coding: utf-8 -*-
"""Native rounding for the frameless application window."""

import ctypes
from ctypes import wintypes


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWA_COLOR_NONE = 0xFFFFFFFE


def disable_native_border(hwnd):
    """Prevent DWM from drawing its own outline over the rounded window."""
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    set_attribute = dwmapi.DwmSetWindowAttribute
    set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD]
    set_attribute.restype = ctypes.c_long
    color = wintypes.DWORD(DWMWA_COLOR_NONE)
    set_attribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(color),
                  ctypes.sizeof(color))


def set_window_rounding(hwnd, rounded):
    """Clip the window to the same corners as the Qt content."""
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    set_attribute = dwmapi.DwmSetWindowAttribute
    set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD]
    set_attribute.restype = ctypes.c_long
    preference = wintypes.DWORD(DWMWCP_ROUND if rounded else DWMWCP_DONOTROUND)
    set_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                  ctypes.byref(preference), ctypes.sizeof(preference))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_region = user32.SetWindowRgn
    set_region.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    set_region.restype = ctypes.c_int
    if not rounded:
        return bool(set_region(hwnd, None, True))

    rect = wintypes.RECT()
    get_rect = user32.GetWindowRect
    get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    get_rect.restype = wintypes.BOOL
    if not get_rect(hwnd, ctypes.byref(rect)):
        return False

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    create_region = gdi32.CreateRoundRectRgn
    create_region.argtypes = [ctypes.c_int] * 6
    create_region.restype = wintypes.HANDLE
    region = create_region(0, 0, rect.right - rect.left,
                           rect.bottom - rect.top, 20, 20)
    if not region:
        return False
    if set_region(hwnd, region, True):
        return True  # Windows owns the region after a successful call.
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject(region)
    return False
