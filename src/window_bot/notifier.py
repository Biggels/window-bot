from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from .config import Config
from .decision import Decision, WindowState
from .weather import WeatherSnapshot


@dataclass(frozen=True)
class Notification:
    title: str
    body: str


class DiscordNotifier:
    def __init__(self, webhook_url: str, timeout_seconds: float) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def send(self, notification: Notification) -> None:
        payload = json.dumps({"content": f"**{notification.title}**\n{notification.body}"}).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status not in {200, 204}:
                    raise RuntimeError(f"Discord webhook returned unexpected status {response.status}")
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
        f"Reason: {decision.reason}"
    )
    return Notification(title=title, body=body)
