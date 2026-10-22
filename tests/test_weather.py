from __future__ import annotations

from datetime import date, timedelta
import io
import json
import unittest
from unittest.mock import patch
import urllib.parse

from window_bot.weather import OpenMeteoClient


class FakeResponse(io.StringIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def hourly_payload(**overrides) -> dict[str, object]:
    payload = {
        "timezone": "America/New_York",
        "utc_offset_seconds": -14400,
        "hourly": {
            "time": ["2026-07-15T05:00", "2026-07-15T06:00", "2026-07-15T07:00"],
            "temperature_2m": [22.0, 23.0, None],
            "dew_point_2m": [20.0, 20.5, None],
            "precipitation": [0.0, 1.2, None],
            "precipitation_probability": [10, 80, None],
        },
    }
    payload.update(overrides)
    return payload


class WeatherClientTests(unittest.TestCase):
    def test_fetch_forecast_parses_hourly_series(self) -> None:
        client = OpenMeteoClient(timeout_seconds=1)
        requested = []

        def fake_urlopen(request, timeout):
            requested.append(request.full_url)
            return FakeResponse(json.dumps(hourly_payload()))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            weather = client.fetch_forecast(latitude=35.8, longitude=-78.8)

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(requested[0]).query)
        self.assertIn("dew_point_2m", query["hourly"][0])
        self.assertEqual(query["past_days"], ["3"])
        # The trailing hour with missing data is skipped.
        self.assertEqual(len(weather.hours), 2)
        first = weather.hours[0]
        self.assertEqual(first.time.isoformat(), "2026-07-15T05:00:00-04:00")
        self.assertEqual(first.temperature_c, 22.0)
        self.assertEqual(first.dew_point_c, 20.0)
        self.assertEqual(weather.hours[1].precipitation_probability, 80.0)

    def test_fetch_history_uses_archive_endpoint(self) -> None:
        client = OpenMeteoClient(timeout_seconds=1)
        payload = hourly_payload()
        del payload["hourly"]["precipitation_probability"]
        requested = []

        def fake_urlopen(request, timeout):
            requested.append(request.full_url)
            return FakeResponse(json.dumps(payload))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            weather = client.fetch_history(latitude=35.8, longitude=-78.8, start=date(2026, 7, 1), end=date(2026, 7, 31))

        self.assertTrue(requested[0].startswith("https://archive-api.open-meteo.com/v1/archive?"))
        self.assertIsNone(weather.hours[0].precipitation_probability)
        self.assertEqual(weather.hours[1].precipitation_mm, 1.2)

    def test_falls_back_to_utc_offset_seconds(self) -> None:
        client = OpenMeteoClient(timeout_seconds=1)

        with patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps(hourly_payload(timezone="Invalid/Zone")))):
            weather = client.fetch_forecast(latitude=35.8, longitude=-78.8)

        self.assertEqual(weather.hours[0].time.utcoffset(), timedelta(hours=-4))

    def test_rejects_bad_payload(self) -> None:
        client = OpenMeteoClient(timeout_seconds=1)

        with patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps({"timezone": "UTC"}))):
            with self.assertRaises(RuntimeError):
                client.fetch_forecast(latitude=35.8, longitude=-78.8)
