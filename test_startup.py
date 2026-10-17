import os
import struct
import tempfile
import unittest
import winreg
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from startup import APPROVAL_KEY, RUN_KEY, StartupManager, approval_enabled, approval_value
from startup_dialog import StartupDialog


class MemoryRegistry:
    HKEY_CURRENT_USER = winreg.HKEY_CURRENT_USER
    HKEY_LOCAL_MACHINE = winreg.HKEY_LOCAL_MACHINE
    KEY_READ = winreg.KEY_READ
    KEY_SET_VALUE = winreg.KEY_SET_VALUE
    REG_BINARY = winreg.REG_BINARY
    REG_SZ = winreg.REG_SZ
    REG_EXPAND_SZ = winreg.REG_EXPAND_SZ

    class Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def __init__(self):
        self.keys = {}
        self.deny_write = False

    def address(self, hive, path, access):
        return hive, path, access & (winreg.KEY_WOW64_64KEY | winreg.KEY_WOW64_32KEY)

    def OpenKey(self, hive, path, reserved=0, access=winreg.KEY_READ):
        address = self.address(hive, path, access)
        if address not in self.keys:
            raise FileNotFoundError(path)
        return self.Key(self.keys[address])

    def CreateKeyEx(self, hive, path, reserved=0, access=winreg.KEY_SET_VALUE):
        if self.deny_write:
            raise PermissionError("access denied")
        return self.Key(self.keys.setdefault(self.address(hive, path, access), {}))

    def QueryInfoKey(self, key):
        return 0, len(key.values), 0

    def EnumValue(self, key, index):
        name, (value, kind) = list(key.values.items())[index]
        return name, value, kind

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        key.values[name] = value, kind


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["test", "--selftest"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.user = self.folder / "user"
        self.common = self.folder / "common"
        self.user.mkdir()
        self.common.mkdir()
        self.registry = MemoryRegistry()
        self.manager = StartupManager(self.registry,
                                      lambda common: self.common if common else self.user,
                                      is_64bit=True)
        self.command = '"C:\\Program Files\\Sample\\软件.exe" --start'
        self.run = self.registry.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY,
                                            access=winreg.KEY_WOW64_64KEY)
        self.registry.SetValueEx(self.run, "Sample", 0, winreg.REG_EXPAND_SZ, self.command)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_is_readonly_and_native_toggle_preserves_command_and_type(self):
        snapshot = dict(self.run.values)
        entry = self.manager.scan()[0]
        self.assertTrue(entry.enabled)
        self.assertEqual(self.run.values, snapshot)
        self.manager.set_enabled(entry, False)
        self.assertFalse(self.manager.scan()[0].enabled)
        self.manager.set_enabled(entry, True)
        self.assertTrue(self.manager.scan()[0].enabled)
        self.assertEqual(self.run.values, snapshot)
        self.assertTrue(self.manager.app_enabled("Sample"))

    def test_startup_folders_preserve_files_and_skip_desktop_ini(self):
        shortcut = self.user / "测试.lnk"
        shortcut.write_bytes(b"shortcut-contents")
        (self.user / "desktop.ini").write_text("hidden")
        (self.common / "Common.exe").write_bytes(b"test")
        entries = self.manager.scan()
        self.assertEqual(len(entries), 3)
        entry = next(item for item in entries if item.value_name == shortcut.name)
        self.manager.set_enabled(entry, False)
        self.assertEqual(shortcut.read_bytes(), b"shortcut-contents")
        self.assertFalse(next(item for item in self.manager.scan() if item.folder
                              and item.value_name == shortcut.name).enabled)
        self.manager.set_enabled(entry, True)
        self.assertEqual(shortcut.read_bytes(), b"shortcut-contents")

    def test_machine_32bit_uses_run32_approval_in_native_view(self):
        with self.registry.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, RUN_KEY,
                                       access=winreg.KEY_WOW64_32KEY) as key:
            self.registry.SetValueEx(key, "Legacy", 0, winreg.REG_SZ, "legacy.exe")
        entry = next(item for item in self.manager.scan() if item.name == "Legacy")
        self.manager.set_enabled(entry, False)
        address = (winreg.HKEY_LOCAL_MACHINE, APPROVAL_KEY + r"\Run32", winreg.KEY_WOW64_64KEY)
        self.assertFalse(approval_enabled(self.registry.keys[address]["Legacy"][0]))

    def test_unknown_states_are_readonly_and_known_states_decode(self):
        for state, expected in ((2, True), (3, False), (6, True), (7, False), (99, None)):
            self.assertIs(approval_enabled(struct.pack("<IQ", state, 0)), expected)
        self.assertIsNone(approval_enabled(b"bad"))
        with self.registry.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVAL_KEY + r"\Run",
                                       access=winreg.KEY_WOW64_64KEY) as key:
            self.registry.SetValueEx(key, "Sample", 0, winreg.REG_BINARY, b"bad")
        entry = self.manager.scan()[0]
        self.assertIsNone(entry.enabled)
        with self.assertRaises(OSError):
            self.manager.set_enabled(entry, True)

    def test_permissions_and_source_changes_do_not_report_success(self):
        entry = self.manager.scan()[0]
        self.registry.deny_write = True
        with self.assertRaises(PermissionError):
            self.manager.set_enabled(entry, False)
        self.assertTrue(self.manager.scan()[0].enabled)
        self.registry.deny_write = False
        self.registry.SetValueEx(self.run, "Sample", 0, winreg.REG_SZ, "changed.exe")
        with self.assertRaises(OSError):
            self.manager.set_enabled(entry, False)

    def test_partial_scan_reports_error_and_keeps_accessible_entries(self):
        def folders(common):
            if common:
                raise PermissionError("test denied")
            return self.user
        self.manager.folder_provider = folders
        self.assertEqual(len(self.manager.scan()), 1)
        self.assertIn("test denied", self.manager.errors[0])

    def test_dialog_selection_filter_toggle_refresh_and_permission_failure(self):
        dialog = StartupDialog(manager=self.manager)
        self.assertFalse(dialog.enable_button.isEnabled())
        self.assertFalse(dialog.disable_button.isEnabled())
        dialog.table.selectRow(0)
        self.assertTrue(dialog.disable_button.isEnabled())
        dialog.disable_button.click()
        self.assertTrue(dialog.enable_button.isEnabled())
        self.assertEqual(dialog.table.item(0, 1).text(), "已禁用")
        dialog.search.setText("no-such-app")
        self.assertFalse(dialog.enable_button.isEnabled())
        dialog.search.clear()
        dialog.table.selectRow(0)
        self.registry.deny_write = True
        with patch.object(QMessageBox, "warning") as warning:
            dialog.enable_button.click()
            warning.assert_called_once()
        self.assertEqual(dialog.table.item(0, 1).text(), "已禁用")
        self.run.values.clear()
        dialog.refresh()
        self.assertEqual(dialog.table.rowCount(), 0)
        self.assertFalse(dialog.enable_button.isEnabled())
        dialog.close()

    def test_own_app_state_tracks_windows_approval(self):
        entry = self.manager.scan()[0]
        self.manager.set_enabled(entry, False)
        self.assertFalse(self.manager.app_enabled("Sample"))
        self.manager.set_enabled(entry, True)
        self.assertTrue(self.manager.app_enabled("Sample"))
        self.run.values.clear()
        self.assertFalse(self.manager.app_enabled("Sample"))


if __name__ == "__main__":
    unittest.main()
