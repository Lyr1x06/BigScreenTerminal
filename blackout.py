# -*- coding: utf-8 -*-
"""Opaque cover windows on every display; click or press Esc to exit."""

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cover_desktop import ScreenCoverDesktop


HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000


class TopmostGuard:
    """React to native stacking changes independently of the Qt event loop."""

    def __init__(self, handles):
        self.handles = tuple(handles)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ScreenCoverGuard", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1)

    def _run(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = wintypes.LONG

        callback_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                          wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                          wintypes.DWORD, wintypes.DWORD)
        user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                         wintypes.HMODULE, callback_type,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                       wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p,
                                                    wintypes.BOOL, wintypes.DWORD,
                                                    wintypes.DWORD]
        user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD

        def enforce():
            if self._stop.is_set():
                return
            for handle in self.handles:
                if not user32.IsWindowVisible(handle):
                    continue
                rect = wintypes.RECT()
                if not user32.GetWindowRect(handle, ctypes.byref(rect)):
                    continue
                covered = not user32.GetWindowLongW(handle, -20) & 0x8  # WS_EX_TOPMOST
                above = user32.GetWindow(handle, 3)  # GW_HWNDPREV
                while above and not covered:
                    if above not in self.handles and user32.IsWindowVisible(above):
                        other = wintypes.RECT()
                        if user32.GetWindowRect(above, ctypes.byref(other)):
                            covered = (other.left < rect.right and other.right > rect.left
                                       and other.top < rect.bottom and other.bottom > rect.top)
                    above = user32.GetWindow(above, 3)
                if covered:
                    # Queue to the owning GUI thread; never block it with a cross-thread send.
                    user32.SetWindowPos(handle, HWND_TOPMOST, 0, 0, 0, 0,
                                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                                        | SWP_ASYNCWINDOWPOS)

        def on_event(hook, event, hwnd, object_id, child_id, thread_id, timestamp):
            if hwnd not in self.handles:
                enforce()

        callback = callback_type(on_event)
        hooks = [user32.SetWinEventHook(first, last, None, callback, 0, 0, 2)
                 for first, last in ((3, 3), (0x8000, 0x800B))]
        try:
            message = wintypes.MSG()
            while not self._stop.is_set():
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    pass  # Out-of-context WinEvent callbacks run while pumping messages.
                enforce()
                user32.MsgWaitForMultipleObjects(0, None, False, 8, 0x04FF)
        finally:
            for hook in hooks:
                if hook:
                    user32.UnhookWinEvent(hook)


def keep_on_top(window):
    if sys.platform != "win32" or not window.isVisible():
        return
    set_window_pos = ctypes.windll.user32.SetWindowPos
    set_window_pos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               wintypes.UINT)
    set_window_pos.restype = wintypes.BOOL
    set_window_pos(int(window.winId()), HWND_TOPMOST, 0, 0, 0, 0,
                   SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


class BlackScreen(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.controller = controller
        self.setStyleSheet("background: black;")
        self.setCursor(Qt.BlankCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Space):
            self.controller.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.controller.close()


class BlackoutController(QObject):
    desktop_finished = Signal(object)

    def __init__(self, app=None):
        super().__init__()
        self.app = app or QApplication.instance()
        self.windows = []
        self._desktop = None
        self.desktop_finished.connect(self._desktop_finished)
        self._native_guard = None
        self._topmost_timer = QTimer()
        self._topmost_timer.setTimerType(Qt.PreciseTimer)
        self._topmost_timer.setInterval(8)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self.app.screenAdded.connect(self._screen_changed)
        self.app.screenRemoved.connect(self._screen_changed)

    @property
    def active(self):
        return bool(self.windows) or bool(self._desktop and self._desktop.active)

    def show(self):
        self.close()
        if sys.platform == "win32" and self.app.platformName() != "offscreen":
            desktop = ScreenCoverDesktop(self.desktop_finished.emit)
            self._desktop = desktop
            if desktop.start():
                return
            desktop.close()
            self._desktop = None
        for screen in self.app.screens():
            window = BlackScreen(self)
            window.createWinId()
            window.windowHandle().setScreen(screen)
            window.setGeometry(screen.geometry())
            window.showFullScreen()
            window.raise_()
            self.windows.append(window)
        self._enforce_topmost()
        if self.windows:
            self._topmost_timer.start()
            if sys.platform == "win32" and self.app.platformName() != "offscreen":
                self._native_guard = TopmostGuard([int(window.winId()) for window in self.windows])
                self._native_guard.start()
        if self.windows:
            self.windows[-1].activateWindow()
            self.windows[-1].setFocus()

    def close(self):
        desktop, self._desktop = self._desktop, None
        if desktop is not None:
            desktop.close()
        self._topmost_timer.stop()
        if self._native_guard is not None:
            self._native_guard.stop()
            self._native_guard = None
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.windows = []

    def _desktop_finished(self, desktop):
        if self._desktop is desktop:
            self._desktop = None

    def _enforce_topmost(self):
        for window in self.windows:
            keep_on_top(window)

    def _screen_changed(self, *_):
        if self.windows:
            self.show()
