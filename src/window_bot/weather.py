from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class WeatherSnapshot:
    temperature: float
    humidity: float
    observed_at: datetime

    def formatted_temperature(self, temperature_unit: str) -> str:
        suffix = "F" if temperature_unit == "fahrenheit" else "C"
        return f"{self.temperature:.1f}°{suffix}"


class OpenMeteoClient:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_current_weather(
        self,
        *,
        latitude: float,
        longitude: float,
        temperature_unit: str,
    ) -> WeatherSnapshot:
        query = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m",
                "temperature_unit": temperature_unit,
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "window-bot/0.1"},
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to fetch weather data: {exc}") from exc

        try:
            current = payload["current"]
            observed_at = _parse_observed_at(payload, current)
            return WeatherSnapshot(
                temperature=float(current["temperature_2m"]),
                humidity=float(current["relative_humidity_2m"]),
                observed_at=observed_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Weather API response did not contain the expected current conditions") from exc


def _parse_observed_at(payload: dict[str, object], current: dict[str, object]) -> datetime:
    observed_at = datetime.fromisoformat(str(current["time"]))
    if observed_at.tzinfo is not None:
        return observed_at

    tzinfo = _resolve_response_timezone(payload)
    return observed_at.replace(tzinfo=tzinfo)


def _resolve_response_timezone(payload: dict[str, object]) -> timezone | ZoneInfo:
    timezone_name = payload.get("timezone")
    if isinstance(timezone_name, str) and timezone_name.strip():
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass

    utc_offset_seconds = payload.get("utc_offset_seconds")
    if isinstance(utc_offset_seconds, int | float):
        return timezone(timedelta(seconds=float(utc_offset_seconds)))

    raise RuntimeError("Weather API response did not include timezone metadata for the current observation")
