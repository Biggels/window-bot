from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import unittest

from window_bot.config import Config
from window_bot.decision import WindowState, decide_window_state
from window_bot.weather import WeatherSnapshot


def build_config() -> Config:
    return Config(
        latitude=40.0,
        longitude=-73.0,
        location_label="Home",
        poll_interval_minutes=10,
        temperature_unit="fahrenheit",
        temp_open_min=60.0,
        temp_open_max=74.0,
        humidity_open_min=20.0,
        humidity_open_max=60.0,
        temp_hysteresis_margin=2.0,
        humidity_hysteresis_margin=5.0,
        discord_webhook_url="https://discord.invalid/webhook",
        state_file=Path("/tmp/window-bot-test-state.json"),
        request_timeout_seconds=10.0,
    )


def snapshot(temp: float, humidity: float) -> WeatherSnapshot:
    return WeatherSnapshot(
        temperature=temp,
        humidity=humidity,
        observed_at=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    )


class DecisionTests(unittest.TestCase):
    def test_closed_state_opens_inside_band(self) -> None:
        decision = decide_window_state(snapshot(68.0, 45.0), build_config(), WindowState.CLOSED)

        self.assertEqual(decision.state, WindowState.OPEN)
        self.assertIn("entered the open band", decision.reason)

    def test_open_state_stays_open_within_hysteresis_margin(self) -> None:
        decision = decide_window_state(snapshot(75.5, 63.0), build_config(), WindowState.OPEN)

        self.assertEqual(decision.state, WindowState.OPEN)
        self.assertIn("retention band", decision.reason)

    def test_open_state_closes_past_hysteresis_margin(self) -> None:
        decision = decide_window_state(snapshot(77.0, 45.0), build_config(), WindowState.OPEN)

        self.assertEqual(decision.state, WindowState.CLOSED)
        self.assertIn("close threshold", decision.reason)

    def test_closed_state_stays_closed_until_back_inside_band(self) -> None:
        decision = decide_window_state(snapshot(75.0, 45.0), build_config(), WindowState.CLOSED)

        self.assertEqual(decision.state, WindowState.CLOSED)
        self.assertIn("open maximum", decision.reason)
