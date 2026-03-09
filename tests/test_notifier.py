from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import patch
import urllib.error

from window_bot.notifier import DiscordNotifier, Notification


class NotifierTests(unittest.TestCase):
    def test_normalizes_legacy_discordapp_host(self) -> None:
        notifier = DiscordNotifier(
            "https://discordapp.com/api/webhooks/123/abc",
            timeout_seconds=10.0,
        )

        self.assertEqual(notifier.webhook_url, "https://discord.com/api/webhooks/123/abc")

    def test_send_sets_user_agent_and_payload(self) -> None:
        notifier = DiscordNotifier(
            "https://discord.com/api/webhooks/123/abc",
            timeout_seconds=10.0,
        )
        notification = Notification(title="Open the windows", body="Now is good.")

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 10.0)
            self.assertEqual(request.full_url, "https://discord.com/api/webhooks/123/abc")
            self.assertEqual(request.headers["User-agent"], "window-bot/0.1")
            payload = json.loads(request.data.decode("utf-8"))
            self.assertIn("Open the windows", payload["content"])
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            notifier.send(notification)

    def test_send_includes_http_error_body(self) -> None:
        notifier = DiscordNotifier(
            "https://discord.com/api/webhooks/123/abc",
            timeout_seconds=10.0,
        )
        notification = Notification(title="Open the windows", body="Now is good.")
        error = urllib.error.HTTPError(
            notifier.webhook_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"message":"Unknown Webhook","code":10015}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Unknown Webhook"):
                notifier.send(notification)


class FakeResponse:
    status = 204

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
