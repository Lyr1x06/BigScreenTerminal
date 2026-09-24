# -*- coding: utf-8 -*-
"""Windows shutdown command. No action is issued by imports or self-tests."""

import subprocess


def shutdown():
    # Omit /f so open applications can protect unsaved data.
    result = subprocess.run(["shutdown.exe", "/s", "/t", "0"],
                            capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise OSError(result.stderr.strip() or "Windows 未接受关机请求")
