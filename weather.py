# -*- coding: utf-8 -*-
"""Open-Meteo weather lookup and the one-minute shutdown reminder worker."""

import datetime as dt
import json
import subprocess
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_LOCATION_URL = "https://ipapi.co/json/"


def native_location(timeout=8):
    """Read Windows' location service through the built-in WinRT API."""
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise OSError("找不到 Windows PowerShell")
    script = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Devices.Geolocation.Geolocator,Windows,ContentType=WindowsRuntime]
$locator = New-Object Windows.Devices.Geolocation.Geolocator
$operation = $locator.GetGeopositionAsync()
$method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq "AsTask" -and $_.IsGenericMethodDefinition -and
  $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -like "IAsyncOperation*"
}
$task = $method.MakeGenericMethod([Windows.Devices.Geolocation.Geoposition]).Invoke($null, @($operation))
$position = $task.GetAwaiter().GetResult().Coordinate.Point.Position
ConvertTo-Json @{ latitude = $position.Latitude; longitude = $position.Longitude } -Compress
'''
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        detail = (result.stderr or "").strip().splitlines()
        raise OSError(detail[-1] if detail else "Windows 定位服务不可用")
    try:
        value = json.loads(result.stdout)
        return float(value["latitude"]), float(value["longitude"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise OSError("Windows 定位服务返回的数据无效")


WEATHER_LABELS = {
    0: "晴", 1: "大部晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "冻雾", 51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨", 71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒", 80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪", 95: "雷雨", 96: "雷雨伴冰雹", 99: "雷雨伴强冰雹",
}
RAIN_CODES = set(range(51, 68)) | {80, 81, 82, 95, 96, 99}
SNOW_CODES = set(range(71, 78)) | {85, 86}


def weather_symbol(code):
    if code in {95, 96, 99}:
        return "ϟ"
    if code in SNOW_CODES:
        return "❄"
    if code in RAIN_CODES:
        return "☂"
    if code in {45, 48}:
        return "≋"
    if code in {1, 2}:
        return "◐"
    if code == 3:
        return "☁"
    return "☀"


@dataclass(frozen=True)
class WeatherReport:
    location: str
    today_date: dt.date
    tomorrow_date: dt.date
    today_min: float
    today_max: float
    tomorrow_min: float
    tomorrow_max: float
    tomorrow_code: int
    tomorrow_precipitation: float
    tomorrow_snowfall: float
    today_code: int = 0

    @property
    def today_average(self):
        return (self.today_min + self.today_max) / 2

    @property
    def tomorrow_average(self):
        return (self.tomorrow_min + self.tomorrow_max) / 2

    @property
    def temperature_change(self):
        return abs(self.tomorrow_average - self.today_average)

    @property
    def tomorrow_label(self):
        return WEATHER_LABELS.get(self.tomorrow_code, "天气变化")

    @property
    def today_label(self):
        return WEATHER_LABELS.get(self.today_code, "天气变化")

    @property
    def has_rain_or_snow(self):
        return (self.tomorrow_code in RAIN_CODES or self.tomorrow_code in SNOW_CODES
                or self.tomorrow_precipitation >= 0.1 or self.tomorrow_snowfall >= 0.1)

    def needs_reminder(self, threshold=5.0):
        return self.temperature_change >= threshold or self.has_rain_or_snow

    def message(self, threshold=5.0):
        reasons = []
        if self.temperature_change >= threshold:
            reasons.append(f"日均温差约 {self.temperature_change:.1f}°C")
        if self.has_rain_or_snow:
            reasons.append("明天有雨雪或明显降水")
        reason = "、".join(reasons) or "未来两天天气变化不大"
        precipitation = f"，降水 {self.tomorrow_precipitation:.1f} mm" \
            if self.tomorrow_precipitation > 0 else ""
        snowfall = f"，降雪 {self.tomorrow_snowfall:.1f} cm" \
            if self.tomorrow_snowfall > 0 else ""
        return (f"{self.location} 明天（{self.tomorrow_date:%m月%d日}）天气提醒\n"
                f"{self.tomorrow_label}，{self.tomorrow_min:.1f}～{self.tomorrow_max:.1f}°C"
                f"{precipitation}{snowfall}\n"
                f"今天 {self.today_min:.1f}～{self.today_max:.1f}°C；{reason}。")


class WeatherClient:
    """Small stdlib-only client so the packaged app has no extra network dependency."""

    def __init__(self, opener=None, timeout=8, locator=native_location):
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.locator = locator

    def _json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "BigScreenTerminal/2.0"})
        with self.opener(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve(self, location):
        if location.strip():
            query = urllib.parse.urlencode({
                "name": location.strip(), "count": 1, "language": "zh", "format": "json",
            })
            data = self._json(f"{GEOCODING_URL}?{query}")
            result = (data.get("results") or [None])[0]
            if not result:
                raise ValueError(f"找不到城市“{location.strip()}”，请检查名称。")
            return result["latitude"], result["longitude"], result.get("name", location.strip())
        # Prefer the local Windows location permission, then use IP as a fallback.
        try:
            latitude, longitude = self.locator(timeout=self.timeout)
            return latitude, longitude, "本机位置"
        except Exception:
            data = self._json(IP_LOCATION_URL)
            if not data.get("latitude") or not data.get("longitude"):
                raise ValueError("无法自动定位，请在天气提醒中填写城市名称。")
            return data["latitude"], data["longitude"], data.get("city") or "当前位置"

    def fetch(self, location, today=None):
        today = today or dt.date.today()
        latitude, longitude, display_name = self._resolve(location)
        query = urllib.parse.urlencode({
            "latitude": latitude, "longitude": longitude, "daily":
            "temperature_2m_min,temperature_2m_max,weather_code,precipitation_sum,snowfall_sum",
            "forecast_days": 2, "timezone": "auto",
        })
        data = self._json(f"{FORECAST_URL}?{query}")
        daily = data.get("daily") or {}
        dates = [dt.date.fromisoformat(value) for value in daily.get("time", [])]
        if today not in dates or today + dt.timedelta(days=1) not in dates:
            raise ValueError("天气接口暂未返回完整的今明两天预报。")
        today_index = dates.index(today)
        tomorrow_index = dates.index(today + dt.timedelta(days=1))

        def number(name, index):
            values = daily.get(name) or []
            try:
                return float(values[index])
            except (IndexError, TypeError, ValueError):
                raise ValueError("天气接口返回的数据不完整。")

        try:
            codes = daily["weather_code"]
            tomorrow_code = int(codes[tomorrow_index])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("天气接口返回的天气类型无效。")
        return WeatherReport(
            display_name, today, today + dt.timedelta(days=1),
            number("temperature_2m_min", today_index), number("temperature_2m_max", today_index),
            number("temperature_2m_min", tomorrow_index), number("temperature_2m_max", tomorrow_index),
            tomorrow_code, number("precipitation_sum", tomorrow_index),
            number("snowfall_sum", tomorrow_index), int(codes[today_index]),
        )


class WeatherWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, location, client=None, parent=None):
        super().__init__(parent)
        self.location = location
        self.client = client or WeatherClient()

    def run(self):
        try:
            self.completed.emit(self.client.fetch(self.location))
        except Exception as exc:
            self.failed.emit(str(exc))
