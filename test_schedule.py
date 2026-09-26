import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import main
import blackout
import power
from schedule import ALL_DAYS, due_occurrence, next_occurrence
from settings import Settings
from taskbar import ABM_GETSTATE, ABM_SETSTATE, ABS_AUTOHIDE, TaskbarAutoHideGuard


class ScheduleTests(unittest.TestCase):
    def test_weekday_and_once_per_day(self):
        rule = {"id": "one", "time": "22:00", "days": [0, 2], "action": "blackout",
                "enabled": True}
        monday = dt.datetime(2026, 9, 28, 22, 0, 15)
        key = due_occurrence(rule, monday, set())
        self.assertEqual(key, "one:2026-09-28")
        self.assertIsNone(due_occurrence(rule, monday, {key}))
        self.assertIsNone(due_occurrence(rule, monday + dt.timedelta(minutes=1), set()))
        self.assertIsNone(due_occurrence(rule, monday + dt.timedelta(days=1), set()))
        self.assertEqual(next_occurrence(rule, monday), dt.datetime(2026, 9, 30, 22))

    def test_legacy_alarm_migration_does_not_repeat_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            import json
            with open(path, "w", encoding="utf-8") as file:
                json.dump({"alarms": [
                    {"time": "22:00", "repeat": True, "enabled": True},
                    {"time": "23:00", "repeat": False, "enabled": True},
                ]}, file)
            settings = Settings(path=path)
            self.assertEqual(settings.schedule[0]["days"], ALL_DAYS)
            self.assertTrue(settings.schedule[0]["enabled"])
            self.assertFalse(settings.schedule[1]["enabled"])
            self.assertTrue(settings.save())
            self.assertEqual(Settings(path=path).schedule, settings.schedule)

    def test_shutdown_command_does_not_force_close_apps(self):
        with patch.object(power.subprocess, "run") as run:
            run.return_value.returncode = 0
            power.shutdown()
            self.assertEqual(run.call_args.args[0],
                             ["shutdown.exe", "/s", "/t", "0"])


class FakeShell:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def SHAppBarMessage(self, message, data):
        if not data._obj.hWnd:
            raise AssertionError("ABM_SETSTATE requires the taskbar HWND")
        self.calls.append(message)
        if message == ABM_SETSTATE:
            self.state = data._obj.lParam
        return self.state


class FakeUser32:
    hwnd = 123

    def FindWindowW(self, class_name, title):
        if class_name != "Shell_TrayWnd" or title is not None:
            raise AssertionError("Expected the Windows taskbar window")
        return self.hwnd


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_BINARY = 3

    def __init__(self):
        self.value = bytes([0] * 8 + [3] + [42] * 20)

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def OpenKey(self, *_):
        return self.Key()

    def QueryValueEx(self, *_):
        return self.value, self.REG_BINARY

    def SetValueEx(self, key, name, reserved, kind, value):
        self.value = value


class TaskbarTests(unittest.TestCase):
    def test_clears_only_auto_hide_and_detects_reenable(self):
        shell = FakeShell(ABS_AUTOHIDE | 2)
        registry = FakeRegistry()
        guard = TaskbarAutoHideGuard(shell, registry, FakeUser32())
        self.assertTrue(guard.enforce())
        self.assertEqual(shell.state, 2)
        self.assertEqual(registry.value[8], 2)
        self.assertEqual(registry.value[9:], bytes([42] * 20))
        self.assertFalse(guard.enforce())
        shell.state |= ABS_AUTOHIDE
        registry.value = registry.value[:8] + bytes([3]) + registry.value[9:]
        self.assertTrue(guard.enforce())
        self.assertEqual(shell.calls.count(ABM_SETSTATE), 2)

    def test_saved_setting_also_dispatches_windows_update(self):
        shell = FakeShell(2)
        registry = FakeRegistry()
        guard = TaskbarAutoHideGuard(shell, registry, FakeUser32())
        self.assertTrue(guard.enforce())
        self.assertIn(ABM_SETSTATE, shell.calls)
        self.assertEqual(registry.value[8], 2)

    def test_recovers_after_explorer_restarts(self):
        shell = FakeShell(3)
        user32 = FakeUser32()
        guard = TaskbarAutoHideGuard(shell, FakeRegistry(), user32)
        user32.hwnd = 0
        with self.assertRaises(OSError):
            guard.enforce()
        self.assertEqual(shell.calls, [])
        user32.hwnd = 456
        self.assertTrue(guard.enforce())
        self.assertEqual(shell.state, 2)

    def test_failed_windows_update_keeps_saved_setting_for_retry(self):
        shell = FakeShell(3)
        registry = FakeRegistry()
        guard = TaskbarAutoHideGuard(shell, registry, FakeUser32())
        original = shell.SHAppBarMessage
        with patch.object(shell, "SHAppBarMessage", side_effect=lambda message, data:
                          0 if message == ABM_SETSTATE else original(message, data)):
            with self.assertRaises(OSError):
                guard.enforce()
        self.assertEqual(registry.value[8], 3)
        self.assertTrue(guard.enforce())


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["test", "--selftest"])
        cls.app.setStyleSheet(main.QSS)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        settings = Settings(path=os.path.join(self.directory.name, "settings.json"))
        self.window = main.MainWindow(settings=settings, selftest=True)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window._quitting = True
        self.window.close()
        self.directory.cleanup()

    def test_weekday_chips_and_shutdown_dispatch(self):
        self.window._add_default_rule()
        row = self.window.schedule_rows[0]
        self.assertEqual(row.to_rule()["days"], ALL_DAYS)
        QTest.mouseClick(row.day_buttons[0], Qt.LeftButton)
        self.assertEqual(row.to_rule()["days"], [1, 2, 3, 4, 5, 6])
        row.action_combo.setCurrentIndex(row.action_combo.findData("shutdown"))
        with patch.object(main, "shutdown") as command:
            self.window._run_rule(row.to_rule())
            command.assert_called_once()
        with patch.object(main, "shutdown") as command:
            monday = dt.datetime(2026, 9, 28, 22, 0, 10)
            row.day_buttons[0].click()
            self.window._selftest = False
            with patch.object(self.window, "_update_next"), \
                    patch.object(main.datetime, "datetime") as datetime_mock:
                datetime_mock.now.return_value = monday
                self.window._on_tick()
                self.window._on_tick()
            command.assert_called_once()
            self.window._selftest = True

    def test_selftest_never_dispatches_scheduled_shutdown(self):
        self.window._add_default_rule()
        row = self.window.schedule_rows[0]
        row.action_combo.setCurrentIndex(row.action_combo.findData("shutdown"))
        due = dt.datetime(2026, 9, 28, 22, 0, 10)
        with patch.object(main, "shutdown") as command, \
                patch.object(self.window, "_update_next"), \
                patch.object(main.datetime, "datetime") as datetime_mock:
            datetime_mock.now.return_value = due
            self.window._on_tick()
            command.assert_not_called()

    def test_blackout_covers_and_dismisses_screen(self):
        with patch.object(blackout, "keep_on_top") as enforce:
            self.window._show_blackout()
            self.assertTrue(self.window.blackout.active)
            screen = self.app.primaryScreen()
            overlay = self.window.blackout.windows[0]
            self.assertEqual(overlay.geometry(), screen.geometry())
            self.assertTrue(overlay.windowFlags() & Qt.WindowStaysOnTopHint)
            enforce.assert_called_with(overlay)
            self.assertTrue(self.window.blackout._topmost_timer.isActive())
            enforce.reset_mock()
            self.window.blackout._enforce_topmost()
            enforce.assert_called_with(overlay)
            QTest.keyClick(overlay, Qt.Key_Escape)
            self.assertFalse(self.window.blackout.active)
            self.assertFalse(self.window.blackout._topmost_timer.isActive())

    def test_titlebar_and_tray_toggle(self):
        self.assertTrue(self.window.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(self.window.size().width(), 960)
        self.assertEqual(len(self.window.title_bar.findChildren(main.QToolButton)), 3)
        self.window.tray_toggle.setChecked(False)
        self.assertFalse(self.window.settings.minimize_to_tray)
        self.window.tray_toggle.setChecked(True)
        self.assertTrue(self.window.settings.minimize_to_tray)
        self.window.tray_toggle.blockSignals(True)
        self.window.tray_toggle.setChecked(False)
        self.window.tray_toggle.blockSignals(False)
        self.assertFalse(self.window.tray_toggle.isChecked())
        self.window._toggle_maximize()
        self.assertTrue(self.window._custom_maximized)
        available = self.window.screen().availableGeometry()
        self.assertEqual(self.window.geometry().topLeft(), available.topLeft())
        self.assertEqual(self.window.geometry().height(), available.height())
        self.assertEqual(self.window.geometry().width(),
                         max(self.window.minimumWidth(), available.width()))
        self.window._toggle_maximize()
        self.assertFalse(self.window._custom_maximized)
        self.window.tray_toggle.setChecked(True)
        from unittest.mock import Mock
        self.window.tray = Mock()
        self.window.tray.isVisible.return_value = True
        self.window._minimize()
        self.assertFalse(self.window.isVisible())
        self.window._show_main()
        self.assertTrue(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
