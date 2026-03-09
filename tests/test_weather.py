from __future__ import annotations

from datetime import UTC
import io
import json
import unittest
from unittest.mock import patch

from window_bot.weather import OpenMeteoClient


class FakeResponse(io.StringIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class WeatherClientTests(unittest.TestCase):
    def test_fetch_current_weather_parses_snapshot(self) -> None:
        payload = {
            "current": {
                "time": "2026-03-09T12:00",
                "temperature_2m": 68.5,
                "relative_humidity_2m": 44,
            }
        }
        client = OpenMeteoClient(timeout_seconds=1)

        with patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps(payload))):
            weather = client.fetch_current_weather(
                latitude=40.0,
                longitude=-73.0,
                temperature_unit="fahrenheit",
            )

        self.assertEqual(weather.temperature, 68.5)
        self.assertEqual(weather.humidity, 44.0)
        self.assertEqual(weather.observed_at.tzinfo, UTC)

    def test_fetch_current_weather_rejects_bad_payload(self) -> None:
        client = OpenMeteoClient(timeout_seconds=1)

        with patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps({"current": {}}))):
            with self.assertRaises(RuntimeError):
                client.fetch_current_weather(
                    latitude=40.0,
                    longitude=-73.0,
                    temperature_unit="fahrenheit",
                )
