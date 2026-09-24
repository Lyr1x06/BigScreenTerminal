# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（ICO 容器 + PNG 数据），供 PyInstaller --icon 与托盘使用。

用法：python make_icon.py
"""

import os
import struct
import tempfile

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QApplication


def render_icon_pixmap(size=256):
    """绘制应用图标：圆角渐变底 + 白色电源符号。"""
    app = QApplication.instance() or QApplication([])
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    radius = size * 0.22
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#62d6ff"))
    grad.setColorAt(0.55, QColor("#3695e5"))
    grad.setColorAt(1.0, QColor("#165fb9"))
    p.fillPath(path, QBrush(grad))

    pen = QPen(QColor("#ffffff"), max(2.0, size * 0.075))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    cx = cy = size * 0.5
    rad = size * 0.24
    p.drawArc(QRectF(cx - rad, cy - rad, rad * 2, rad * 2), 225 * 16, 270 * 16)
    p.drawLine(int(cx), int(cy - rad * 1.15), int(cx), int(cy + rad * 0.22))
    p.end()
    return pm


def build_ico(sizes=(16, 24, 32, 48, 64, 128, 256), out="icon.ico"):
    """把多个尺寸的 PNG 封装成 Windows ICO 文件（PNG 压缩条目）。"""
    files = []
    for s in sizes:
        pm = render_icon_pixmap(s)
        path = os.path.join(tempfile.gettempdir(), f"_bst_icon_{s}.png")
        pm.save(path, "PNG")
        files.append((s, path))

    entries = []
    data = b""
    offset = 6 + 16 * len(files)
    for s, path in files:
        with open(path, "rb") as f:
            blob = f.read()
        w = s if s < 256 else 0
        entries.append(struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset))
        data += blob
        offset += len(blob)

    with open(out, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(files)))
        f.write(b"".join(entries))
        f.write(data)

    for _, path in files:
        try:
            os.remove(path)
        except OSError:
            pass
    print(f"已生成 {out}（{len(files)} 个尺寸）")


if __name__ == "__main__":
    build_ico()
