from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

from window_bot.config import load_config


CONFIG_TEMPLATE = """
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
    def test_load_config_reads_webhook_from_environment(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(textwrap.dedent(CONFIG_TEMPLATE), encoding="utf-8")

            with patch.dict(
                os.environ,
                {"WINDOW_BOT_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc"},
                clear=False,
            ):
                config = load_config(config_path)

        self.assertEqual(config.discord_webhook_url, "https://discord.com/api/webhooks/123/abc")

    def test_load_config_falls_back_to_config_value(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                textwrap.dedent(
                    CONFIG_TEMPLATE + 'discord_webhook_url = "https://discord.com/api/webhooks/456/def"\n'
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(config_path)

        self.assertEqual(config.discord_webhook_url, "https://discord.com/api/webhooks/456/def")

    def test_load_config_requires_webhook_from_env_or_config(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(textwrap.dedent(CONFIG_TEMPLATE), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "WINDOW_BOT_DISCORD_WEBHOOK_URL"):
                    load_config(config_path)
