# -*- coding: utf-8 -*-
"""Manage Windows Run / Startup-folder entries using Explorer's approval state.

Commands and shortcuts stay in place. Services and scheduled tasks are excluded.
"""

import ctypes
import datetime as dt
import os
import struct
import winreg
from dataclasses import dataclass
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def approval_enabled(value):
    if value is None:
        return True
    if not isinstance(value, bytes) or len(value) != 12:
        return None
    state = struct.unpack_from("<I", value)[0]
    if state in (2, 6):
        return True
    if state in (3, 7):
        return False
    return None  # Do not overwrite unrecognized Windows / vendor states.


def approval_value(enabled):
    timestamp = 0 if enabled else int(
        (dt.datetime.now(dt.timezone.utc) - dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc))
        .total_seconds() * 10_000_000)
    return struct.pack("<IQ", 2 if enabled else 3, timestamp)


def startup_folder(common=False):
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 24 if common else 7,
                                                  None, 0, buffer)
    if result:
        raise OSError(f"无法定位启动文件夹（0x{result & 0xffffffff:08x}）")
    return Path(buffer.value)


@dataclass(frozen=True)
class StartupEntry:
    name: str
    command: str
    source: str
    hive: int
    view: int
    approval_group: str
    value_name: str
    enabled: bool | None
    folder: bool = False
    value_type: int = 0

    @property
    def identity(self):
        return self.hive, self.view, self.folder, self.value_name


class StartupManager:
    def __init__(self, registry=winreg, folder_provider=startup_folder, is_64bit=None):
        self.registry = registry
        self.folder_provider = folder_provider
        self.is_64bit = (bool(os.environ.get("PROCESSOR_ARCHITEW6432"))
                         or os.environ.get("PROCESSOR_ARCHITECTURE", "").endswith("64")
                         if is_64bit is None else is_64bit)
        self.native_view = winreg.KEY_WOW64_64KEY if self.is_64bit else 0
        self.errors = []

    def _approval(self, hive, group, name):
        r = self.registry
        try:
            with r.OpenKey(hive, APPROVAL_KEY + "\\" + group, 0,
                           r.KEY_READ | self.native_view) as key:
                value, kind = r.QueryValueEx(key, name)
                return approval_enabled(value) if kind == r.REG_BINARY else None
        except FileNotFoundError:
            return True

    def scan(self):
        r = self.registry
        self.errors = []
        entries = []
        locations = [(r.HKEY_CURRENT_USER, self.native_view, "Run", "当前用户 · 注册表"),
                     (r.HKEY_LOCAL_MACHINE, self.native_view, "Run", "所有用户 · 注册表")]
        if self.is_64bit:
            locations.append((r.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY,
                              "Run32", "所有用户 · 注册表（32 位）"))
        for hive, view, group, source in locations:
            try:
                with r.OpenKey(hive, RUN_KEY, 0, r.KEY_READ | view) as key:
                    count = r.QueryInfoKey(key)[1]
                    for index in range(count):
                        name, command, kind = r.EnumValue(key, index)
                        if kind not in (r.REG_SZ, r.REG_EXPAND_SZ) or not command.strip():
                            continue
                        entries.append(StartupEntry(
                            name or "（默认）", command, source, hive, view, group, name,
                            self._approval(hive, group, name), value_type=kind))
            except FileNotFoundError:
                pass
            except OSError as exc:
                self.errors.append(f"{source}：{exc}")
        for common, hive in ((False, r.HKEY_CURRENT_USER), (True, r.HKEY_LOCAL_MACHINE)):
            source = ("所有用户" if common else "当前用户") + " · 启动文件夹"
            try:
                folder = self.folder_provider(common)
                for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
                    if path.name.lower() == "desktop.ini" or not path.is_file():
                        continue
                    entries.append(StartupEntry(
                        path.stem, str(path), source, hive, self.native_view,
                        "StartupFolder", path.name,
                        self._approval(hive, "StartupFolder", path.name), folder=True))
            except FileNotFoundError:
                pass
            except OSError as exc:
                self.errors.append(f"{source}：{exc}")
        return sorted(entries, key=lambda item: (item.name.casefold(), item.source))

    def set_enabled(self, entry, enabled):
        """Revalidate source, then persist and verify Windows' native approval value."""
        r = self.registry
        if entry.folder:
            if not Path(entry.command).is_file():
                raise FileNotFoundError("启动项已被移动或删除，请刷新列表。")
        else:
            with r.OpenKey(entry.hive, RUN_KEY, 0, r.KEY_READ | entry.view) as key:
                command, kind = r.QueryValueEx(key, entry.value_name)
                if command != entry.command or kind != entry.value_type:
                    raise OSError("启动项已被其他程序修改，请刷新后重试。")
        current = self._approval(entry.hive, entry.approval_group, entry.value_name)
        if current is None:
            raise OSError("无法识别此启动项的状态，请使用 Windows 设置管理。")
        if current == bool(enabled):
            return
        with r.CreateKeyEx(entry.hive, APPROVAL_KEY + "\\" + entry.approval_group,
                           0, r.KEY_SET_VALUE | self.native_view) as key:
            r.SetValueEx(key, entry.value_name, 0, r.REG_BINARY, approval_value(enabled))
        if self._approval(entry.hive, entry.approval_group, entry.value_name) != bool(enabled):
            raise OSError("Windows 未保存启动项状态，请刷新后重试。")

    def app_enabled(self, name):
        r = self.registry
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_READ | self.native_view) as key:
                r.QueryValueEx(key, name)
            return self._approval(r.HKEY_CURRENT_USER, "Run", name) is True
        except FileNotFoundError:
            return False
