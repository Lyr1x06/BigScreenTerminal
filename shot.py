# -*- coding: utf-8 -*-
"""开发用：离屏渲染主窗口并截图保存为 ui_preview.png（不弹出真实窗口）。"""

import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from main import MainWindow, QSS  # noqa: E402
from settings import Settings  # noqa: E402

sys.argv.append("--selftest")
app = QApplication(sys.argv)
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyhbd.ttc")
app.setStyleSheet(QSS)
tmp = tempfile.TemporaryDirectory(prefix="bst-preview-")
win = MainWindow(settings=Settings(path=os.path.join(tmp.name, "settings.json")))
win._add_default_rule()
win.schedule_rows[0].enabled_toggle.setChecked(False)
win.resize(960, 600)
win.show()
app.processEvents()
QTest.qWait(100)
win.grab().save("ui_preview.png", "PNG")
print("saved ui_preview.png")
app.quit()
tmp.cleanup()
