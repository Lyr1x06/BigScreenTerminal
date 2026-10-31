import datetime as dt
import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from weather import WeatherClient, WeatherReport, native_location
from weather_dialog import WeatherDialog


class Response:
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self.value


class WeatherTests(unittest.TestCase):
    def test_report_requires_temperature_change_or_rain_snow(self):
        today = dt.date(2026, 10, 31)
        report = WeatherReport("济南", today, today + dt.timedelta(days=1),
                               15, 20, 7, 13, 61, 2.0, 0.0)
        self.assertTrue(report.needs_reminder(5))
        self.assertIn("小雨", report.message())
        dry = WeatherReport("济南", today, today + dt.timedelta(days=1),
                            15, 20, 16, 21, 0, 0.0, 0.0)
        self.assertFalse(dry.needs_reminder(5))

    def test_weather_dialog_has_large_cards_and_both_days(self):
        today = dt.date(2026, 10, 31)
        report = WeatherReport("济南", today, today + dt.timedelta(days=1),
                               15, 20, 7, 13, 61, 2.0, 0.0, today_code=2)
        dialog = WeatherDialog(report)
        self.assertGreaterEqual(dialog.width(), 700)
        labels = [label.text() for label in dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
        self.assertIn("今天", labels)
        self.assertIn("明天", labels)
        self.assertIn("小雨", labels)
        dialog.close()

    def test_fetch_uses_city_geocoding_and_two_day_daily_values(self):
        responses = [
            {"results": [{"latitude": 36.67, "longitude": 117.12, "name": "济南"}]},
            {"daily": {
                "time": ["2026-10-31", "2026-11-01"],
                "temperature_2m_min": [10, 3], "temperature_2m_max": [20, 12],
                "weather_code": [0, 71], "precipitation_sum": [0, 0],
                "snowfall_sum": [0, 1.2],
            }},
        ]
        def opener(request, timeout):
            self.assertLessEqual(timeout, 8)
            return Response(responses.pop(0))
        report = WeatherClient(opener=opener, locator=lambda **_: (0, 0)).fetch(
            "济南", today=dt.date(2026, 10, 31))
        self.assertEqual(report.location, "济南")
        self.assertEqual(report.tomorrow_label, "小雪")
        self.assertTrue(report.has_rain_or_snow)
        self.assertEqual(len(responses), 0)

    def test_empty_location_prefers_native_device_location(self):
        responses = [{"daily": {
            "time": ["2026-10-31", "2026-11-01"],
            "temperature_2m_min": [10, 10], "temperature_2m_max": [20, 20],
            "weather_code": [0, 0], "precipitation_sum": [0, 0],
            "snowfall_sum": [0, 0],
        }}]
        def opener(request, timeout):
            return Response(responses.pop(0))
        report = WeatherClient(opener=opener, locator=lambda **_: (36.67, 117.12)).fetch(
            "", today=dt.date(2026, 10, 31))
        self.assertEqual(report.location, "本机位置")
        self.assertEqual(len(responses), 0)

    def test_native_location_parses_powershell_json(self):
        completed = type("Completed", (), {
            "returncode": 0, "stdout": '{"latitude":36.6,"longitude":117.1}', "stderr": "",
        })()
        with patch("weather.shutil.which", return_value="powershell.exe"), \
                patch("weather.subprocess.run", return_value=completed) as run:
            self.assertEqual(native_location(), (36.6, 117.1))
            self.assertEqual(run.call_args.args[0][0], "powershell.exe")


if __name__ == "__main__":
    unittest.main()
