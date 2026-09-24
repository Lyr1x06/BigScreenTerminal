# -*- coding: utf-8 -*-
"""JSON settings stored under %APPDATA%/BigScreenTerminal."""

import json
import os
import sys

from schedule import migrate_alarms, normalize_rule


DEFAULTS = {
    "schedule": [],
    "autostart": False,
    "minimize_to_tray": True,
    "geometry": None,
}


def _default_config_dir():
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "BigScreenTerminal")


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(_default_config_dir(), "settings.json")
        self.data = dict(DEFAULTS)
        self.data["schedule"] = []
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, ValueError):
            return
        if not isinstance(loaded, dict):
            return
        for key in ("autostart", "minimize_to_tray", "geometry"):
            if key in loaded:
                self.data[key] = loaded[key]
        source = loaded.get("schedule")
        if source is None:
            self.data["schedule"] = migrate_alarms(loaded.get("alarms"))
        elif isinstance(source, list):
            self.data["schedule"] = [
                rule for item in source if (rule := normalize_rule(item))
            ]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(self.data, file, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    @property
    def schedule(self):
        return self.data["schedule"]

    @property
    def minimize_to_tray(self):
        return bool(self.data.get("minimize_to_tray", True))
