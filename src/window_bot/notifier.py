from __future__ import annotations

from dataclasses import dataclass
import io
import json
import urllib.error
import urllib.parse
import urllib.request

from .config import Config
from .decision import Decision, WindowState, describe_threshold_bands
from .weather import WeatherSnapshot


@dataclass(frozen=True)
class Notification:
    title: str
    body: str


class DiscordNotifier:
    def __init__(self, webhook_url: str, timeout_seconds: float) -> None:
        self.webhook_url = _normalize_discord_webhook_url(webhook_url)
        self.timeout_seconds = timeout_seconds

    def send(self, notification: Notification) -> None:
        payload = json.dumps({"content": f"**{notification.title}**\n{notification.body}"}).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "window-bot/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status not in {200, 204}:
                    raise RuntimeError(f"Discord webhook returned unexpected status {response.status}")
        except urllib.error.HTTPError as exc:
            body = _read_error_body(exc)
            body_suffix = f": {body}" if body else ""
            raise RuntimeError(
                f"Failed to send Discord notification: HTTP {exc.code} {exc.reason}{body_suffix}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to send Discord notification: {exc}") from exc


def build_transition_notification(
    decision: Decision,
    weather: WeatherSnapshot,
    config: Config,
) -> Notification:
    action = "Open the windows" if decision.state is WindowState.OPEN else "Close the windows"
    title = f"{action} at {config.location_label}"
    body = (
        f"Current conditions: {weather.formatted_temperature(config.temperature_unit)}, "
        f"{weather.humidity:.0f}% humidity.\n"
        f"{describe_threshold_bands(config)}\n"
        f"Reason: {decision.reason}"
    )
    return Notification(title=title, body=body)


def _normalize_discord_webhook_url(webhook_url: str) -> str:
    parsed = urllib.parse.urlsplit(webhook_url)
    if parsed.netloc == "discordapp.com":
        parsed = parsed._replace(netloc="discord.com")
    return urllib.parse.urlunsplit(parsed)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    if exc.fp is None:
        return ""
    try:
        body = exc.read()
    except OSError:
        return ""
    finally:
        close = getattr(exc.fp, "close", None)
        if callable(close):
            close()
    if isinstance(body, str):
        text = body
    elif isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    elif isinstance(body, io.StringIO):
        text = body.getvalue()
    else:
        return ""
    compact = " ".join(text.split())
    return compact[:300]
