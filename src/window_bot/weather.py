from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
import json
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_HOURLY_FIELDS = "temperature_2m,dew_point_2m,precipitation,precipitation_probability"
_ARCHIVE_HOURLY_FIELDS = "temperature_2m,dew_point_2m,precipitation"


@dataclass(frozen=True)
class WeatherHour:
    time: datetime
    temperature_c: float
    dew_point_c: float
    precipitation_mm: float = 0.0
    precipitation_probability: float | None = None


@dataclass(frozen=True)
class WeatherSeries:
    """Hourly outdoor conditions in the location's local time zone, oldest first."""

    timezone: tzinfo
    hours: tuple[WeatherHour, ...]


class OpenMeteoClient:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        past_days: int = 3,
        forecast_days: int = 4,
    ) -> WeatherSeries:
        """Recent observed hours plus the forecast, all at hourly resolution."""
        payload = self._get(
            FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": _HOURLY_FIELDS,
                "timezone": "auto",
                "past_days": past_days,
                "forecast_days": forecast_days,
            },
        )
        return parse_hourly_payload(payload)

    def fetch_history(
        self,
        *,
        latitude: float,
        longitude: float,
        start: date,
        end: date,
    ) -> WeatherSeries:
        payload = self._get(
            ARCHIVE_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": _ARCHIVE_HOURLY_FIELDS,
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        return parse_hourly_payload(payload)

    def _get(self, base_url: str, params: dict[str, object]) -> dict[str, object]:
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "window-bot/0.2"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.load(response)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to fetch weather data: {exc}") from exc


def parse_hourly_payload(payload: dict[str, object]) -> WeatherSeries:
    try:
        tz = _resolve_response_timezone(payload)
        hourly = payload["hourly"]
        times = hourly["time"]
        temperatures = hourly["temperature_2m"]
        dew_points = hourly["dew_point_2m"]
        precipitation = hourly.get("precipitation") or [None] * len(times)
        probabilities = hourly.get("precipitation_probability") or [None] * len(times)
    except (KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError("Weather API response did not contain the expected hourly data") from exc

    hours = []
    for time_text, temperature, dew, rain, probability in zip(
        times, temperatures, dew_points, precipitation, probabilities
    ):
        # The archive leaves the most recent few days empty; skip any gaps.
        if temperature is None or dew is None:
            continue
        observed_at = datetime.fromisoformat(str(time_text))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=tz)
        hours.append(
            WeatherHour(
                time=observed_at,
                temperature_c=float(temperature),
                dew_point_c=float(dew),
                precipitation_mm=float(rain) if rain is not None else 0.0,
                precipitation_probability=float(probability) if probability is not None else None,
            )
        )

    if not hours:
        raise RuntimeError("Weather API response contained no usable hourly data")
    return WeatherSeries(timezone=tz, hours=tuple(hours))


def _resolve_response_timezone(payload: dict[str, object]) -> tzinfo:
    timezone_name = payload.get("timezone")
    if isinstance(timezone_name, str) and timezone_name.strip():
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass

    utc_offset_seconds = payload.get("utc_offset_seconds")
    if isinstance(utc_offset_seconds, int | float):
        return timezone(timedelta(seconds=float(utc_offset_seconds)))

    raise RuntimeError("Weather API response did not include timezone metadata")
