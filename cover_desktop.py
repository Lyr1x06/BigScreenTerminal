# -*- coding: utf-8 -*-
"""Display the screen cover on its own Windows desktop, isolated from other HWNDs."""

import ctypes
import threading
import uuid
from ctypes import wintypes


class ScreenCoverDesktop:
    def __init__(self, finished):
        self._finished = finished
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ScreenCoverDesktop", daemon=True)
        self.active = False
        self.error = None

    def start(self):
        self._thread.start()
        if not self._ready.wait(timeout=5):
            self.close()
            return False
        return self.active

    def close(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        def bind(library, name, arguments, result):
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result
            return function

        handle = wintypes.HANDLE
        open_input = bind(user32, "OpenInputDesktop", [wintypes.DWORD, wintypes.BOOL,
                                                      wintypes.DWORD], handle)
        create_desktop = bind(user32, "CreateDesktopW", [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                        ctypes.c_void_p, wintypes.DWORD,
                                                        wintypes.DWORD, ctypes.c_void_p], handle)
        set_desktop = bind(user32, "SetThreadDesktop", [handle], wintypes.BOOL)
        switch_desktop = bind(user32, "SwitchDesktop", [handle], wintypes.BOOL)
        close_desktop = bind(user32, "CloseDesktop", [handle], wintypes.BOOL)
        get_thread_desktop = bind(user32, "GetThreadDesktop", [wintypes.DWORD], handle)
        get_thread_id = bind(kernel32, "GetCurrentThreadId", [], wintypes.DWORD)
        get_module = bind(kernel32, "GetModuleHandleW", [wintypes.LPCWSTR], wintypes.HMODULE)
        get_stock = bind(gdi32, "GetStockObject", [ctypes.c_int], handle)
        wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", wndproc_type),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", handle),
                        ("hCursor", handle), ("hbrBackground", handle),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        register = bind(user32, "RegisterClassW", [ctypes.POINTER(WNDCLASS)], wintypes.WORD)
        unregister = bind(user32, "UnregisterClassW", [wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL)
        create_window = bind(user32, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR,
                                                       wintypes.LPCWSTR, wintypes.DWORD,
                                                       ctypes.c_int, ctypes.c_int,
                                                       ctypes.c_int, ctypes.c_int,
                                                       wintypes.HWND, handle,
                                                       wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND)
        destroy = bind(user32, "DestroyWindow", [wintypes.HWND], wintypes.BOOL)
        def_window = bind(user32, "DefWindowProcW", [wintypes.HWND, wintypes.UINT,
                                                   wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t)
        show = bind(user32, "ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
        update = bind(user32, "UpdateWindow", [wintypes.HWND], wintypes.BOOL)
        foreground = bind(user32, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL)
        focus = bind(user32, "SetFocus", [wintypes.HWND], wintypes.HWND)
        set_cursor = bind(user32, "SetCursor", [handle], handle)
        peek = bind(user32, "PeekMessageW", [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                             wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL)
        translate = bind(user32, "TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL)
        dispatch = bind(user32, "DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t)
        metrics = bind(user32, "GetSystemMetrics", [ctypes.c_int], ctypes.c_int)
        move = bind(user32, "MoveWindow", [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.BOOL], wintypes.BOOL)
        wait_messages = bind(user32, "MsgWaitForMultipleObjects", [wintypes.DWORD, ctypes.c_void_p,
                                                                  wintypes.BOOL, wintypes.DWORD,
                                                                  wintypes.DWORD], wintypes.DWORD)

        def virtual_rect():
            return [metrics(index) for index in (76, 77, 78, 79)]

        def on_message(hwnd, message, wparam, lparam):
            if message == 0x20:  # WM_SETCURSOR
                set_cursor(None)
                return 1
            if message == 0x100 and wparam in (0x1B, 0x0D, 0x20):  # WM_KEYDOWN
                self._stop.set()
                return 0
            if message in (0x201, 0x204, 0x207, 0x10):  # Mouse button down / WM_CLOSE
                self._stop.set()
                return 0
            if message == 0x7E:  # WM_DISPLAYCHANGE
                move(hwnd, *virtual_rect(), True)
                return 0
            return def_window(hwnd, message, wparam, lparam)

        original_thread_desktop = get_thread_desktop(get_thread_id())
        original_input = desktop = hwnd = None
        instance = get_module(None)
        class_name = "BigScreenCover_" + uuid.uuid4().hex
        registered = switched = False
        callback = wndproc_type(on_message)
        try:
            original_input = open_input(0, False, 0x0101)  # SWITCHDESKTOP | READOBJECTS
            if not original_input:
                raise ctypes.WinError(ctypes.get_last_error())
            desktop = create_desktop(class_name, None, None, 0, 0x01FF, None)
            if not desktop or not set_desktop(desktop):
                raise ctypes.WinError(ctypes.get_last_error())
            window_class = WNDCLASS()
            window_class.lpfnWndProc = callback
            window_class.hInstance = instance
            window_class.hbrBackground = get_stock(4)  # BLACK_BRUSH
            window_class.lpszClassName = class_name
            if not register(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            hwnd = create_window(0x8 | 0x80, class_name, "关屏", 0x80000000,
                                 *virtual_rect(), None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            show(hwnd, 5)
            update(hwnd)
            if self._stop.is_set():
                return
            if not switch_desktop(desktop):
                raise ctypes.WinError(ctypes.get_last_error())
            switched = True
            foreground(hwnd)
            focus(hwnd)
            self.active = True
            self._ready.set()
            message = wintypes.MSG()
            while not self._stop.is_set():
                while peek(ctypes.byref(message), None, 0, 0, 1):
                    translate(ctypes.byref(message))
                    dispatch(ctypes.byref(message))
                wait_messages(0, None, False, 20, 0x04FF)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if switched:
                switch_desktop(original_input)
            if hwnd:
                destroy(hwnd)
            if registered:
                unregister(class_name, instance)
            set_desktop(original_thread_desktop)
            if desktop:
                close_desktop(desktop)
            if original_input:
                close_desktop(original_input)
            self.active = False
            self._ready.set()
            self._finished(self)
