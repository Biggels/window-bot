from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

from window_bot.config import load_config
from window_bot.psychrometrics import fahrenheit_to_celsius


MINIMAL_CONFIG = """
latitude = 35.79
longitude = -78.78
"""

LEGACY_CONFIG = """
latitude = 40.7128
longitude = -74.0060
location_label = "Home"
poll_interval_minutes = 10
temperature_unit = "fahrenheit"

temp_open_min = 60
temp_open_max = 74
humidity_open_min = 20
humidity_open_max = 60

temp_hysteresis_margin = 2
humidity_hysteresis_margin = 5

state_file = "state/window-bot-state.json"
request_timeout_seconds = 10
"""


class ConfigTests(unittest.TestCase):
    def load(self, text: str, env: dict[str, str] | None = None):
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(textwrap.dedent(text), encoding="utf-8")
            with patch.dict(os.environ, env or {}, clear=True):
                return load_config(config_path)

    def test_defaults_match_the_planned_schedule_and_comfort_band(self) -> None:
        config = self.load(MINIMAL_CONFIG)

        self.assertEqual(config.schedule.morning.isoformat(), "05:00:00")
        self.assertEqual(config.schedule.midday.isoformat(), "12:30:00")
        self.assertEqual(config.schedule.evening.isoformat(), "17:30:00")
        self.assertEqual(config.plan.quiet_start.isoformat(), "21:00:00")
        self.assertEqual(config.plan.humidity_limit, 60.0)
        self.assertEqual(config.plan.max_extra_hours_above_limit, 3.0)
        self.assertAlmostEqual(config.house.heat_setpoint_c, fahrenheit_to_celsius(68))
        self.assertAlmostEqual(config.house.cool_setpoint_c, fahrenheit_to_celsius(75))
        self.assertIsNone(config.discord_webhook_url)

    def test_legacy_config_still_loads_and_warns(self) -> None:
        with self.assertLogs("window_bot.config", level="WARNING") as logs:
            config = self.load(LEGACY_CONFIG)

        self.assertEqual(config.location_label, "Home")
        self.assertIn("temp_open_min", logs.output[0])

    def test_sections_override_defaults(self) -> None:
        config = self.load(
            MINIMAL_CONFIG
            + """
            [schedule]
            morning = "06:15"

            [comfort]
            cool_setpoint = 76
            max_extra_hours_above_limit = 2

            [house]
            floor_area_sq_ft = 1500
            """
        )

        self.assertEqual(config.schedule.morning.isoformat(), "06:15:00")
        self.assertAlmostEqual(config.house.cool_setpoint_c, fahrenheit_to_celsius(76))
        self.assertEqual(config.plan.max_extra_hours_above_limit, 2.0)
        self.assertAlmostEqual(config.house.volume_m3, 1500 * 8.5 * 0.0283168)

    def test_celsius_temperatures_are_used_as_is(self) -> None:
        config = self.load(MINIMAL_CONFIG + 'temperature_unit = "celsius"\n[comfort]\ncool_setpoint = 24\n')

        self.assertEqual(config.house.cool_setpoint_c, 24.0)
        self.assertAlmostEqual(config.house.heat_setpoint_c, 20.0)

    def test_reads_webhook_from_environment(self) -> None:
        config = self.load(MINIMAL_CONFIG, env={"WINDOW_BOT_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc"})

        self.assertEqual(config.discord_webhook_url, "https://discord.com/api/webhooks/123/abc")

    def test_falls_back_to_config_webhook_and_mention(self) -> None:
        config = self.load(
            'discord_webhook_url = "https://discord.com/api/webhooks/456/def"\n'
            'discord_mention = "<@123456789012345678>"\n' + MINIMAL_CONFIG
        )

        self.assertEqual(config.discord_webhook_url, "https://discord.com/api/webhooks/456/def")
        self.assertEqual(config.discord_mention, "<@123456789012345678>")

    def test_rejects_inverted_setpoints(self) -> None:
        with self.assertRaisesRegex(ValueError, "heat_setpoint"):
            self.load(MINIMAL_CONFIG + "[comfort]\nheat_setpoint = 76\ncool_setpoint = 72\n")

    def test_rejects_message_during_quiet_hours(self) -> None:
        with self.assertRaisesRegex(ValueError, "quiet hours"):
            self.load(MINIMAL_CONFIG + '[schedule]\nevening = "21:30"\n')

    def test_rejects_bad_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "morning"):
            self.load(MINIMAL_CONFIG + '[schedule]\nmorning = "5am"\n')
