from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import unittest

from window_bot.config import Config
from window_bot.decision import WindowState, decide_window_state, describe_active_thresholds
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
    def test_active_thresholds_for_closed_state_only_show_open_band(self) -> None:
        summary = describe_active_thresholds(build_config(), WindowState.CLOSED)

        self.assertIn("Configured open band", summary)
        self.assertNotIn("Active hysteresis close band", summary)

    def test_active_thresholds_for_open_state_include_hysteresis_band(self) -> None:
        summary = describe_active_thresholds(build_config(), WindowState.OPEN)

        self.assertIn("Configured open band", summary)
        self.assertIn("Active hysteresis close band for the current open state", summary)

    def test_closed_state_opens_inside_band(self) -> None:
        decision = decide_window_state(snapshot(68.0, 45.0), build_config(), WindowState.CLOSED)

        self.assertEqual(decision.state, WindowState.OPEN)
        self.assertIn("entered the configured open band", decision.reason)
        self.assertIn("within 60.0°F to 74.0°F", decision.reason)

    def test_open_state_stays_open_within_hysteresis_margin(self) -> None:
        decision = decide_window_state(snapshot(75.5, 63.0), build_config(), WindowState.OPEN)

        self.assertEqual(decision.state, WindowState.OPEN)
        self.assertIn("hysteresis is active", decision.reason)
        self.assertIn("configured open maximum of 74.0°F", decision.reason)
        self.assertIn("until 76.0°F", decision.reason)

    def test_open_state_inside_configured_band_mentions_active_close_thresholds(self) -> None:
        decision = decide_window_state(snapshot(72.0, 45.0), build_config(), WindowState.OPEN)

        self.assertEqual(decision.state, WindowState.OPEN)
        self.assertIn("Conditions remain open", decision.reason)
        self.assertIn("inside the configured open band", decision.reason)
        self.assertIn("would not close unless temperature leaves 58.0°F to 76.0°F", decision.reason)
        self.assertIn("humidity leaves 15% to 65%", decision.reason)

    def test_open_state_closes_past_hysteresis_margin(self) -> None:
        decision = decide_window_state(snapshot(77.0, 45.0), build_config(), WindowState.OPEN)

        self.assertEqual(decision.state, WindowState.CLOSED)
        self.assertIn("hysteresis-adjusted close maximum of 76.0°F", decision.reason)
        self.assertIn("configured open maximum 74.0°F", decision.reason)

    def test_closed_state_stays_closed_until_back_inside_band(self) -> None:
        decision = decide_window_state(snapshot(75.0, 45.0), build_config(), WindowState.CLOSED)

        self.assertEqual(decision.state, WindowState.CLOSED)
        self.assertIn("configured open maximum", decision.reason)
