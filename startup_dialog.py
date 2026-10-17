# -*- coding: utf-8 -*-
"""Blue startup manager UI; scanning never changes startup settings."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from startup import StartupManager


class StartupDialog(QDialog):
    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self.manager = manager or StartupManager()
        self.entries = []
        self.setWindowTitle("开机启动项管理")
        self.resize(940, 560)
        self.setMinimumSize(720, 440)
        self.setStyleSheet("""
            QDialog { background: #173b60; }
            QLineEdit, QTableWidget { background: #214b75; color: #f4f9ff;
                border: 1px solid #5681aa; border-radius: 5px; padding: 6px; }
            QTableWidget { gridline-color: #4275a2; selection-background-color: #397fb3; }
            QHeaderView::section { background: #2b5985; color: #ffffff;
                border: 0; padding: 8px; }
            QTableCornerButton::section { background: #2b5985; }
            QPushButton:disabled { color: #86a0b8; background: #264766; border-color: #395a78; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("开机启动项管理")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        note = QLabel("管理登录 Windows 时启动的注册表、启动文件夹项目；不包含系统服务和计划任务。")
        note.setWordWrap(True)
        layout.addWidget(note)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、来源或启动命令")
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["软件 / 启动项", "状态", "来源", "启动命令 / 文件"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((200, 80, 195)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.enable_button = QPushButton("启用所选")
        self.disable_button = QPushButton("禁用所选")
        self.enable_button.clicked.connect(lambda: self._change(True))
        self.disable_button.clicked.connect(lambda: self._change(False))
        actions.addWidget(self.enable_button)
        actions.addWidget(self.disable_button)
        actions.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.refresh()

    def selected_entry(self):
        row = self.table.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) and not self.table.isRowHidden(row) else None

    def refresh(self):
        previous = self.selected_entry()
        self.entries = self.manager.scan()
        self.table.setRowCount(0)
        for row, entry in enumerate(self.entries):
            self.table.insertRow(row)
            state = "已启用" if entry.enabled is True else "已禁用" if entry.enabled is False else "未知"
            for column, value in enumerate((entry.name, state, entry.source, entry.command)):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            if previous and entry.identity == previous.identity:
                self.table.selectRow(row)
        self._filter()
        self.status.setText(f"检测到 {len(self.entries)} 个启动项。更改在下次登录时生效，不会关闭正在运行的软件。"
                            + ("\n部分位置无法读取：" + "；".join(self.manager.errors)
                               if self.manager.errors else ""))

    def _filter(self):
        query = self.search.text().strip().casefold()
        for row, entry in enumerate(self.entries):
            self.table.setRowHidden(row, query not in
                                    f"{entry.name} {entry.source} {entry.command}".casefold())
        self._selection_changed()

    def _selection_changed(self):
        entry = self.selected_entry()
        self.enable_button.setEnabled(entry is not None and entry.enabled is False)
        self.disable_button.setEnabled(entry is not None and entry.enabled is True)

    def _change(self, enabled):
        entry = self.selected_entry()
        if entry is None:
            return
        try:
            self.manager.set_enabled(entry, enabled)
        except PermissionError:
            QMessageBox.warning(self, "权限不足", "无法更改此启动项。所有用户的启动项通常需要以管理员身份运行本软件后管理。")
        except OSError as exc:
            QMessageBox.warning(self, "更改失败", str(exc))
        self.refresh()
