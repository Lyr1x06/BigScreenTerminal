#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大屏控制终端：按星期定时关屏/关机、任务栏自动隐藏监测。"""

import ctypes
import datetime
import os
import sys
import tempfile
import uuid
import winreg
from ctypes import wintypes

from PySide6.QtCore import Qt, QTime, QTimer, Signal, QPoint, QRect
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QAbstractSpinBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSystemTrayIcon, QTimeEdit, QToolButton, QVBoxLayout, QWidget, QCheckBox,
)

from blackout import BlackoutController
from make_icon import render_icon_pixmap
from power import shutdown
from schedule import ALL_DAYS, due_occurrence, next_occurrence, normalize_rule
from settings import Settings
from taskbar import CHECK_INTERVAL_MS, TaskbarAutoHideGuard
from window_effects import disable_native_border, set_window_rounding


APP_NAME = "大屏控制终端"
VERSION = "2.0.7"
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_VALUE = "BigScreenTerminal"
WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")
ACTION_LABELS = {"blackout": "关屏", "shutdown": "关机"}


QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px; color: #f4f9ff; }
QMainWindow { background: transparent; }
QWidget#root { background: #173b60; border: 0;
    border-radius: 10px; }
QWidget#root[maximized="true"] { border-radius: 0; }
QWidget#titleBar { background: #204e79; border-top-left-radius: 10px;
    border-top-right-radius: 10px; }
QWidget#titleBar[maximized="true"] { border-top-left-radius: 0;
    border-top-right-radius: 0; }
QLabel#appTitle { font-size: 18px; font-weight: 700; color: #ffffff; }
QLabel#appAuthor { font-size: 11px; color: #c2ddf7; }
QLabel#appSub, QLabel#field { color: #c4dbef; font-size: 12px; }
QLabel#clock { font-size: 25px; font-weight: 600; font-family: Consolas, monospace; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; }
QLabel#statusOk { color: #8de5ff; }
QLabel#statusErr { color: #ff9292; }
QFrame#panel { background: #214b75;
    border: 1px solid #4275a2; border-radius: 7px; }
QFrame#scheduleRow { background: #2b5985;
    border: 1px solid #5681aa; border-radius: 6px; }
QFrame#scheduleRow[dimmed="true"] QLabel { color: #95b2ce; }
QPushButton, QTimeEdit, QComboBox {
    background: #32628d; border: 1px solid #6593bc;
    border-radius: 6px; padding: 6px 10px; }
QPushButton:hover, QTimeEdit:hover, QComboBox:hover {
    background: #3c78ac; border-color: #92c7ed; }
QPushButton:pressed { background: #24557f; }
QPushButton#primary { background: #73c5ff; color: #103754;
    border: 0; font-weight: 700; padding: 10px; }
QPushButton#primary:hover { background: #9adaff; }
QPushButton#danger { background: #613f59;
    color: #ffd7d2; border-color: #ba7586; }
QPushButton#danger:hover { background: #80506a; }
QPushButton#dayChip { min-width: 25px; max-width: 25px;
    min-height: 23px; max-height: 23px; padding: 0; }
QPushButton#dayChip:checked { background: #73c5ff; color: #103754; border: 0; }
QToolButton#windowButton { border: 0; background: transparent;
    border-radius: 4px; min-width: 32px; min-height: 27px; font-size: 18px; }
QToolButton#windowButton:hover { background: #3b6892; }
QToolButton#closeButton { border: 0; background: transparent;
    border-radius: 4px; min-width: 32px; min-height: 27px; font-size: 18px; }
QToolButton#closeButton:hover { background: #cf5c57; }
QToolButton#removeButton { border: 0; background: transparent;
    min-width: 25px; font-size: 17px; color: #c0d6ea; }
QToolButton#removeButton:hover { color: #ffada8; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #1c4269; selection-background-color: #3985c0; }
QTimeEdit::up-button, QTimeEdit::down-button { width: 0; border: 0; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 7px; background: transparent; }
QScrollBar::handle:vertical { background: #5e91bc; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #1c4269; color: #f5faff; border: 1px solid #77aede; }
"""


class Toggle(QCheckBox):
    """Compact switch with a full-size click target."""

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setChecked(checked)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#73c5ff") if self.isChecked() else QColor("#7895b2"))
        painter.drawRoundedRect(0, 0, 42, 24, 12, 12)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(22 if self.isChecked() else 3, 3, 18, 18)


class ScheduleRow(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, rule, parent=None):
        super().__init__(parent)
        self.rule = rule
        self.setObjectName("scheduleRow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 9, 9, 9)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        hour, minute = map(int, rule["time"].split(":"))
        self.time_edit.setTime(QTime(hour, minute))
        self.time_edit.setFixedWidth(82)
        top.addWidget(self.time_edit)

        self.action_combo = QComboBox()
        for value, label in ACTION_LABELS.items():
            self.action_combo.addItem(label, value)
        self.action_combo.setCurrentIndex(self.action_combo.findData(rule["action"]))
        self.action_combo.setFixedWidth(105)
        top.addWidget(self.action_combo)
        top.addStretch()
        top.addWidget(QLabel("启用"))
        self.enabled_toggle = Toggle(checked=rule["enabled"])
        self.enabled_toggle.setAccessibleName("启用定时规则")
        top.addWidget(self.enabled_toggle)
        remove = QToolButton()
        remove.setObjectName("removeButton")
        remove.setText("×")
        remove.setToolTip("删除规则")
        remove.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(remove)
        outer.addLayout(top)

        days_row = QHBoxLayout()
        days_row.setSpacing(5)
        days_row.addWidget(QLabel("星期"))
        self.day_buttons = []
        for index, label in enumerate(WEEKDAYS):
            button = QPushButton(label)
            button.setObjectName("dayChip")
            button.setCheckable(True)
            button.setChecked(index in rule["days"])
            button.setAccessibleName(f"星期{label}")
            button.clicked.connect(self._on_day_changed)
            self.day_buttons.append(button)
            days_row.addWidget(button)
        days_row.addStretch()
        outer.addLayout(days_row)

        self.once_checkbox = QCheckBox("仅执行一次")
        self.once_checkbox.setChecked(rule.get("once", False))
        self.once_checkbox.setToolTip("在下一次符合时间和星期的时刻执行，触发后自动停用。")
        outer.addWidget(self.once_checkbox)

        self.time_edit.timeChanged.connect(self._changed)
        self.action_combo.currentIndexChanged.connect(self._changed)
        self.enabled_toggle.toggled.connect(self._changed)
        self.once_checkbox.toggled.connect(self._changed)
        self._apply_dim()

    def _on_day_changed(self):
        if not any(button.isChecked() for button in self.day_buttons):
            self.sender().setChecked(True)
        self._changed()

    def _changed(self, *_):
        self.rule.update(self.to_rule())
        self._apply_dim()
        self.changed.emit()

    def _apply_dim(self):
        self.setProperty("dimmed", not self.enabled_toggle.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)

    def to_rule(self):
        return {
            "id": self.rule["id"],
            "time": self.time_edit.time().toString("HH:mm"),
            "action": self.action_combo.currentData(),
            "days": [index for index, button in enumerate(self.day_buttons)
                     if button.isChecked()],
            "enabled": self.enabled_toggle.isChecked(),
            "once": self.once_checkbox.isChecked(),
        }


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(49)
        self._drag_origin = None
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 5, 10, 5)
        row.setSpacing(9)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        row.addWidget(title, 0, Qt.AlignVCenter)
        author = QLabel("by Lyr1x")
        author.setObjectName("appAuthor")
        row.addWidget(author, 0, Qt.AlignVCenter)
        row.addStretch()
        for text, tip, callback, name in (
            ("−", "最小化", window._minimize, "windowButton"),
            ("□", "最大化或还原", window._toggle_maximize, "windowButton"),
            ("×", "关闭", window.close, "closeButton"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setObjectName(name)
            button.clicked.connect(callback)
            row.addWidget(button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.window._custom_maximized:
                return
            self._drag_origin = event.globalPosition().toPoint() - self.window.pos()
            handle = self.window.windowHandle()
            if handle and handle.startSystemMove():
                self._drag_origin = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.window.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window._toggle_maximize()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, start_minimized=False, settings=None, selftest=None):
        super().__init__()
        self._selftest = ("--selftest" in sys.argv) if selftest is None else bool(selftest)
        self._quitting = False
        self._custom_maximized = False
        self._restore_geometry = None
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(840, 530)
        self.resize(960, 600)
        self.settings = settings or Settings()
        self.schedule_rows = []
        self._fired = set()
        self.tray = None
        self.blackout = BlackoutController()
        self.taskbar_guard = TaskbarAutoHideGuard()
        self._pending_save = QTimer(self)
        self._pending_save.setSingleShot(True)
        self._pending_save.setInterval(400)
        self._pending_save.timeout.connect(self._save_settings)

        self._init_ui()
        self._init_tray()
        self._apply_saved()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._on_tick)
        self._clock_timer.start(1000)
        self._on_tick()
        if not self._selftest:
            self._taskbar_timer = QTimer(self)
            self._taskbar_timer.timeout.connect(self._check_taskbar)
            self._taskbar_timer.setTimerType(Qt.PreciseTimer)
            self._taskbar_timer.start(CHECK_INTERVAL_MS)
            self._check_taskbar()
        if start_minimized and not self._selftest:
            QTimer.singleShot(0, self._show_tray_only)

    def _init_ui(self):
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(18, 13, 18, 15)
        body.setSpacing(13)
        header = QHBoxLayout()
        sub = QLabel("按星期定时 · 关屏 · 自动关机")
        sub.setObjectName("appSub")
        header.addWidget(sub)
        header.addStretch()
        self.clock_label = QLabel()
        self.clock_label.setObjectName("clock")
        header.addWidget(self.clock_label)
        body.addLayout(header)

        panels = QHBoxLayout()
        panels.setSpacing(14)
        panels.addWidget(self._build_schedule_panel(), 3)
        panels.addWidget(self._build_control_panel(), 2)
        body.addLayout(panels, 1)

        footer = QHBoxLayout()
        footer.setSpacing(9)
        footer.addWidget(QLabel("开机自启动"))
        self.autostart_toggle = Toggle()
        self.autostart_toggle.setAccessibleName("开机自启动")
        self.autostart_toggle.toggled.connect(self._on_autostart_toggled)
        footer.addWidget(self.autostart_toggle)
        footer.addSpacing(14)
        footer.addWidget(QLabel("最小化到托盘"))
        self.tray_toggle = Toggle()
        self.tray_toggle.setAccessibleName("最小化到托盘")
        self.tray_toggle.setToolTip("开启后，最小化或关闭窗口会收起到系统托盘。")
        self.tray_toggle.toggled.connect(self._on_tray_toggled)
        footer.addWidget(self.tray_toggle)
        footer.addStretch()
        version = QLabel(f"v{VERSION} · Windows 10/11")
        version.setObjectName("field")
        footer.addWidget(version)
        body.addLayout(footer)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)

    def _build_schedule_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 14, 15, 14)
        layout.setSpacing(10)
        title = QLabel("定时规则")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.schedule_scroll = QScrollArea()
        self.schedule_scroll.setWidgetResizable(True)
        list_box = QWidget()
        self.schedule_layout = QVBoxLayout(list_box)
        self.schedule_layout.setContentsMargins(2, 2, 2, 2)
        self.schedule_layout.setSpacing(8)
        self.schedule_layout.addStretch()
        self.schedule_scroll.setWidget(list_box)
        layout.addWidget(self.schedule_scroll, 1)
        add = QPushButton("添加规则")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._add_default_rule)
        layout.addWidget(add)
        self.next_label = QLabel("暂无定时规则")
        self.next_label.setObjectName("statusOk")
        layout.addWidget(self.next_label)
        return panel

    def _build_control_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(11)
        title = QLabel("屏幕与电源")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        description = QLabel("关屏时覆盖所有显示器，电脑保持运行。")
        description.setObjectName("field")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addSpacing(8)
        black = QPushButton("立即关屏")
        black.setObjectName("primary")
        black.clicked.connect(self._show_blackout)
        layout.addWidget(black)
        layout.addStretch()
        shut = QPushButton("立即关机")
        shut.setObjectName("danger")
        shut.clicked.connect(self._confirm_shutdown)
        layout.addWidget(shut)
        self.taskbar_status = QLabel("任务栏自动隐藏监测中")
        self.taskbar_status.setObjectName("field")
        self.taskbar_status.setWordWrap(True)
        layout.addWidget(self.taskbar_status)
        self.action_status = QLabel("")
        self.action_status.setWordWrap(True)
        layout.addWidget(self.action_status)
        return panel

    def _init_tray(self):
        from PySide6.QtGui import QIcon
        icon = QIcon(render_icon_pixmap(64))
        self.setWindowIcon(icon)
        if self._selftest or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        for label, callback in (
            ("显示主窗口", self._show_main),
            ("立即关屏", self._show_blackout),
            ("退出程序", self._quit),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_main() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_main(self):
        self.showNormal()
        if self._custom_maximized:
            self.setGeometry(self.screen().availableGeometry())
        self.raise_()
        self.activateWindow()

    def _show_tray_only(self):
        if self.tray is not None and self.tray.isVisible():
            self.hide()

    def _minimize(self):
        if self.tray_toggle.isChecked() and self.tray is not None and self.tray.isVisible():
            self.hide()
        else:
            self.showMinimized()

    def _toggle_maximize(self):
        if self._custom_maximized:
            self._custom_maximized = False
            if self._restore_geometry is not None:
                self.setGeometry(self._restore_geometry)
        else:
            self._restore_geometry = self.geometry()
            self._custom_maximized = True
            self.setGeometry(self.screen().availableGeometry())
        for widget in (self.centralWidget(), self.title_bar):
            widget.setProperty("maximized", self._custom_maximized)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._update_window_shape()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            disable_native_border(int(self.winId()))
            self._update_window_shape()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_shape()

    def _update_window_shape(self):
        if sys.platform == "win32" and self.isVisible() and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            set_window_rounding(int(self.winId()), not self._custom_maximized)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and not self._custom_maximized:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == 0x0084:  # WM_NCHITTEST
                rect = wintypes.RECT()
                get_rect = ctypes.windll.user32.GetWindowRect
                get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                get_rect.restype = wintypes.BOOL
                get_rect(int(self.winId()), ctypes.byref(rect))
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                left, right = x < rect.left + 6, x >= rect.right - 6
                top, bottom = y < rect.top + 6, y >= rect.bottom - 6
                hits = {(True, False, True, False): 13,
                        (False, True, True, False): 14,
                        (True, False, False, True): 16,
                        (False, True, False, True): 17}
                for edges, code in hits.items():
                    if edges == (left, right, top, bottom):
                        return True, code
                if left or right or top or bottom:
                    return True, 10 if left else 11 if right else 12 if top else 15
        return super().nativeEvent(event_type, message)

    def _apply_saved(self):
        for rule in self.settings.schedule:
            self._add_rule(rule, save=False)
        for control, checked in (
            (self.autostart_toggle, self.is_autostart()),
            (self.tray_toggle, self.settings.minimize_to_tray),
        ):
            control.blockSignals(True)
            control.setChecked(checked)
            control.blockSignals(False)
        geometry = self.settings.data.get("geometry")
        if isinstance(geometry, list) and len(geometry) == 4:
            try:
                position = QPoint(int(geometry[0]), int(geometry[1]))
                candidate = QRect(position, self.size())
                if any(candidate.intersects(screen.availableGeometry())
                       for screen in QApplication.instance().screens()):
                    self.move(position)
            except (TypeError, ValueError):
                pass

    def _add_default_rule(self):
        self._add_rule({
            "id": uuid.uuid4().hex, "time": "22:00",
            "action": "blackout", "days": ALL_DAYS, "enabled": True,
        })

    def _add_rule(self, value, save=True):
        rule = normalize_rule(value)
        if rule is None:
            return
        row = ScheduleRow(rule)
        row.changed.connect(self._on_rule_changed)
        row.removed.connect(self._remove_rule)
        self.schedule_layout.insertWidget(self.schedule_layout.count() - 1, row)
        self.schedule_rows.append(row)
        if save:
            self._save_settings()
        self._update_next(datetime.datetime.now())

    def _remove_rule(self, row):
        self.schedule_rows.remove(row)
        self.schedule_layout.removeWidget(row)
        row.deleteLater()
        self._save_settings()
        self._update_next(datetime.datetime.now())

    def _on_rule_changed(self):
        self._save_settings()
        self._update_next(datetime.datetime.now())

    def _on_tick(self):
        now = datetime.datetime.now()
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        for row in tuple(self.schedule_rows):
            rule = row.to_rule()
            key = due_occurrence(rule, now, self._fired)
            if key and not self._selftest:
                self._fired.add(key)
                if rule["once"]:
                    row.enabled_toggle.blockSignals(True)
                    row.enabled_toggle.setChecked(False)
                    row.enabled_toggle.blockSignals(False)
                    row.rule.update(row.to_rule())
                    row._apply_dim()
                    if not self._save_settings():
                        self.action_status.setText("仅执行一次规则保存失败，本次未执行，请检查设置目录。")
                        continue
                self._run_rule(rule)
        self._update_next(now)

    def _update_next(self, now):
        upcoming = []
        for row in self.schedule_rows:
            rule = row.to_rule()
            due = next_occurrence(rule, now)
            if due is not None:
                upcoming.append((due, rule["action"]))
        if upcoming:
            due, action = min(upcoming)
            self.next_label.setText(
                f"下次：{due:%m月%d日 %H:%M} · {ACTION_LABELS[action]}")
        else:
            self.next_label.setText("暂无启用的定时规则")

    def _run_rule(self, rule):
        try:
            if rule["action"] == "blackout":
                self._show_blackout()
            else:
                shutdown()
                self._notify("已发出定时关机请求")
        except Exception as exc:
            self.action_status.setText(f"定时任务失败：{exc}")
            self.action_status.setObjectName("statusErr")
            self.action_status.style().unpolish(self.action_status)
            self.action_status.style().polish(self.action_status)
            self._notify(self.action_status.text())

    def _show_blackout(self):
        self.blackout.show()

    def _confirm_shutdown(self):
        choice = QMessageBox.question(
            self, APP_NAME, "现在关机？未保存的工作可能被其他程序阻止关机。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if choice == QMessageBox.Yes:
            try:
                shutdown()
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f"关机失败：{exc}")

    def _check_taskbar(self):
        try:
            changed = self.taskbar_guard.enforce()
            self.taskbar_status.setText(
                "已关闭任务栏自动隐藏" if changed else "任务栏自动隐藏：关闭")
        except OSError as exc:
            self.taskbar_status.setText(f"任务栏设置检查失败：{exc}")

    def _notify(self, text):
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.Information, 3000)

    @staticmethod
    def _startup_command(target, arguments):
        return f'"{target}" {arguments}'.strip()

    def _launcher(self):
        if getattr(sys, "frozen", False):
            return sys.executable, "--minimized"
        return sys.executable, f'"{os.path.abspath(__file__)}" --minimized'

    def _set_autostart(self, enabled):
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY) as key:
                if enabled:
                    target, arguments = self._launcher()
                    winreg.SetValueEx(key, STARTUP_REG_VALUE, 0, winreg.REG_SZ,
                                      self._startup_command(target, arguments))
                else:
                    try:
                        winreg.DeleteValue(key, STARTUP_REG_VALUE)
                    except FileNotFoundError:
                        pass
            return True
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"设置开机自启动失败：{exc}")
            return False

    @staticmethod
    def is_autostart():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY) as key:
                winreg.QueryValueEx(key, STARTUP_REG_VALUE)
            return True
        except FileNotFoundError:
            return False

    def _on_autostart_toggled(self, enabled):
        if not self._set_autostart(enabled):
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(not enabled)
            self.autostart_toggle.blockSignals(False)
        self._save_settings()

    def _on_tray_toggled(self, *_):
        self._save_settings()

    def _save_settings(self):
        self.settings.data["schedule"] = [row.to_rule() for row in self.schedule_rows]
        self.settings.data["autostart"] = self.autostart_toggle.isChecked()
        self.settings.data["minimize_to_tray"] = self.tray_toggle.isChecked()
        if self._custom_maximized and self._restore_geometry is not None:
            geo = self._restore_geometry
            self.settings.data["geometry"] = [geo.x(), geo.y(), geo.width(), geo.height()]
        elif not self.isMinimized():
            self.settings.data["geometry"] = [self.x(), self.y(), self.width(), self.height()]
        return self.settings.save()

    def _quit(self):
        self._quitting = True
        self.blackout.close()
        self._save_settings()
        if self.tray is not None:
            self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if (not self._quitting and self.tray_toggle.isChecked()
                and self.tray is not None and self.tray.isVisible()
                and not self._selftest):
            self.hide()
            event.ignore()
        else:
            self._quit()
            event.accept()


def run_selftest():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    with tempfile.TemporaryDirectory(prefix="bst-selftest-") as directory:
        settings = Settings(path=os.path.join(directory, "settings.json"))
        settings.data["schedule"] = [{
            "id": "test", "time": "22:00", "days": ALL_DAYS,
            "action": "blackout", "enabled": True, "once": False,
        }]
        assert settings.save()
        assert Settings(path=settings.path).schedule == settings.schedule
        app = QApplication.instance() or QApplication([sys.argv[0]])
        app.setStyleSheet(QSS)
        window = MainWindow(settings=settings)
        app.processEvents()
        assert window.schedule_rows[0].to_rule()["days"] == ALL_DAYS
        assert window.title_bar.findChildren(QToolButton)
        print("[selftest] 设置、定时规则和界面构建 OK")
    marker = os.path.join(tempfile.gettempdir(), "bst_selftest_result.txt")
    with open(marker, "w", encoding="utf-8") as file:
        file.write("PASS")
    return True


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if run_selftest() else 1)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    window = MainWindow(start_minimized="--minimized" in sys.argv)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
