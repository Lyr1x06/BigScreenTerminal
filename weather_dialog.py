# -*- coding: utf-8 -*-
"""Large, compact weather result dialog used by manual and scheduled checks."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from weather import weather_symbol


class WeatherDialog(QDialog):
    def __init__(self, report, title="天气查询结果", threshold=5.0, parent=None):
        super().__init__(parent)
        self.report = report
        self.threshold = threshold
        self.setWindowTitle(title)
        self.setMinimumSize(700, 420)
        self.resize(760, 470)
        self.setModal(False)
        self.setStyleSheet("""
            QDialog { background: #173b60; color: #f4f9ff; }
            QLabel#eyebrow { color: #9fc9eb; font-size: 12px; }
            QLabel#dialogTitle { color: #ffffff; font-size: 23px; font-weight: 700; }
            QLabel#location { color: #c8e2f5; font-size: 13px; }
            QFrame#dayCard { background: #214b75; border: 1px solid #5681aa;
                border-radius: 10px; }
            QFrame#tomorrowCard { background: #285983; border: 1px solid #78b5df;
                border-radius: 10px; }
            QLabel#dayName { color: #b6d9f2; font-size: 13px; font-weight: 600; }
            QLabel#date { color: #8fb5d3; font-size: 12px; }
            QLabel#weatherIcon { color: #86d6ff; font-size: 54px; font-weight: 700; }
            QLabel#condition { color: #ffffff; font-size: 17px; font-weight: 600; }
            QLabel#temperature { color: #ffffff; font-size: 26px; font-weight: 700; }
            QLabel#metric { color: #c9e0f2; font-size: 12px; }
            QFrame#notice { background: #1c4269; border: 1px solid #4d83ae;
                border-radius: 7px; }
            QLabel#noticeText { color: #d9efff; font-size: 13px; }
            QPushButton { background: #73c5ff; color: #103754; border: 0;
                border-radius: 6px; padding: 7px 22px; font-weight: 700; }
            QPushButton:hover { background: #9adaff; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(15)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        eyebrow = QLabel("今明两天天气")
        eyebrow.setObjectName("eyebrow")
        heading.addWidget(eyebrow)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        heading.addWidget(title_label)
        header.addLayout(heading)
        header.addStretch()
        location = QLabel(f"⌖  {report.location}")
        location.setObjectName("location")
        location.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(location, 0, Qt.AlignBottom)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(13)
        cards.addWidget(self._day_card(
            "今天", report.today_date, report.today_code, report.today_label,
            report.today_min, report.today_max, False,
            report.today_average, None, None), 1)
        cards.addWidget(self._day_card(
            "明天", report.tomorrow_date, report.tomorrow_code, report.tomorrow_label,
            report.tomorrow_min, report.tomorrow_max, True,
            report.tomorrow_average, report.tomorrow_precipitation,
            report.tomorrow_snowfall), 1)
        root.addLayout(cards, 1)

        notice = QFrame()
        notice.setObjectName("notice")
        notice_row = QHBoxLayout(notice)
        notice_row.setContentsMargins(13, 9, 13, 9)
        notice_text = QLabel(self._notice_text())
        notice_text.setObjectName("noticeText")
        notice_text.setWordWrap(True)
        notice_row.addWidget(notice_text, 1)
        root.addWidget(notice)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("数据来源：Open-Meteo"))
        footer.itemAt(0).widget().setObjectName("eyebrow")
        footer.addStretch()
        close = QPushButton("知道了")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _day_card(self, name, date, code, label, low, high, tomorrow,
                  average, precipitation, snowfall):
        card = QFrame()
        card.setObjectName("tomorrowCard" if tomorrow else "dayCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(4)
        top = QHBoxLayout()
        day_name = QLabel(name)
        day_name.setObjectName("dayName")
        top.addWidget(day_name)
        top.addStretch()
        date_label = QLabel(date.strftime("%m月%d日"))
        date_label.setObjectName("date")
        top.addWidget(date_label)
        layout.addLayout(top)
        middle = QHBoxLayout()
        icon = QLabel(weather_symbol(code))
        icon.setObjectName("weatherIcon")
        icon.setAlignment(Qt.AlignCenter)
        middle.addWidget(icon, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        condition = QLabel(label)
        condition.setObjectName("condition")
        text.addWidget(condition)
        temperature = QLabel(f"{low:.1f}°  /  {high:.1f}°C")
        temperature.setObjectName("temperature")
        text.addWidget(temperature)
        average_label = QLabel(f"平均 {average:.1f}°C")
        average_label.setObjectName("metric")
        text.addWidget(average_label)
        middle.addLayout(text, 1)
        layout.addLayout(middle)
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(2)
        metrics.addWidget(QLabel("降水"), 0, 0)
        metrics.addWidget(QLabel("--" if precipitation is None else f"{precipitation:.1f} mm"), 0, 1)
        metrics.addWidget(QLabel("降雪"), 1, 0)
        metrics.addWidget(QLabel("--" if snowfall is None else f"{snowfall:.1f} cm"), 1, 1)
        for row in range(2):
            for column in range(2):
                metrics.itemAtPosition(row, column).widget().setObjectName("metric")
        layout.addLayout(metrics)
        return card

    def _notice_text(self):
        reasons = []
        if self.report.temperature_change >= self.threshold:
            reasons.append(f"今明平均温度变化 {self.report.temperature_change:.1f}°C")
        if self.report.has_rain_or_snow:
            reasons.append("明天有雨雪或明显降水")
        if reasons:
            return "天气提醒：" + "，".join(reasons)
        return "天气提醒：今明两天天气变化不大"
