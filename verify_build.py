"""运行打包后的 EXE 自检，使用隔离设置、临时结果文件及精简 PATH。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify(executable):
    executable = Path(executable).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="bst-build-test-") as directory:
        env = os.environ.copy()
        windows_dir = env.get("SystemRoot", r"C:\Windows")
        env["PATH"] = os.pathsep.join([
            str(executable.parent), os.path.join(windows_dir, "System32"), windows_dir,
        ])
        # 自检不会覆盖用户设置，也不能误读上一次运行留下的 PASS。
        env.update(APPDATA=directory, TEMP=directory, TMP=directory)
        for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM",
                     "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            env.pop(name, None)
        result = subprocess.run(
            [str(executable), "--selftest"], cwd=directory, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=45,
        )
        marker = Path(directory, "bst_selftest_result.txt")
        if result.returncode != 0 or not marker.is_file():
            raise RuntimeError(f"EXE self-test failed: exit={result.returncode}, marker={marker.is_file()}")
        if marker.read_text(encoding="utf-8") != "PASS":
            raise RuntimeError("EXE self-test reported FAIL")
    print(f"PASS: packaged EXE self-test (isolated settings and PATH): {executable}")


if __name__ == "__main__":
    verify(sys.argv[1] if len(sys.argv) > 1 else "dist/BigScreenTerminal/BigScreenTerminal.exe")
