# -*- coding: utf-8 -*-
"""Opaque cover windows on every display; click or press Esc to exit."""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget


HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


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


class BlackoutController:
    def __init__(self, app=None):
        self.app = app or QApplication.instance()
        self.windows = []
        self._topmost_timer = QTimer()
        self._topmost_timer.setInterval(150)
        self._topmost_timer.timeout.connect(self._enforce_topmost)
        self.app.screenAdded.connect(self._screen_changed)
        self.app.screenRemoved.connect(self._screen_changed)

    @property
    def active(self):
        return bool(self.windows)

    def show(self):
        self.close()
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
        if self.windows:
            self.windows[-1].activateWindow()
            self.windows[-1].setFocus()

    def close(self):
        self._topmost_timer.stop()
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.windows = []

    def _enforce_topmost(self):
        for window in self.windows:
            keep_on_top(window)

    def _screen_changed(self, *_):
        if self.active:
            self.show()
