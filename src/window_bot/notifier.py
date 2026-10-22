from __future__ import annotations

from dataclasses import dataclass
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request


@dataclass(frozen=True)
class Notification:
    body: str
    mention: str | None = None


class DiscordNotifier:
    def __init__(self, webhook_url: str | None, timeout_seconds: float) -> None:
        self.webhook_url = _normalize_discord_webhook_url(webhook_url) if webhook_url else None
        self.timeout_seconds = timeout_seconds

    def send(self, notification: Notification) -> None:
        if self.webhook_url is None:
            raise RuntimeError(
                "No Discord webhook configured: set WINDOW_BOT_DISCORD_WEBHOOK_URL or discord_webhook_url"
            )
        content = _build_content(notification)
        payload_dict: dict[str, object] = {"content": content}
        allowed_mentions = _build_allowed_mentions(notification.mention)
        if allowed_mentions is not None:
            payload_dict["allowed_mentions"] = allowed_mentions
        payload = json.dumps(payload_dict).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "window-bot/0.2",
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


def _build_content(notification: Notification) -> str:
    prefix = f"{notification.mention}\n" if notification.mention else ""
    return f"{prefix}{notification.body}"


def _build_allowed_mentions(mention: str | None) -> dict[str, object] | None:
    if not mention:
        return None

    user_match = re.fullmatch(r"<@!?(\d+)>", mention)
    if user_match:
        return {"parse": [], "users": [user_match.group(1)]}

    role_match = re.fullmatch(r"<@&(\d+)>", mention)
    if role_match:
        return {"parse": [], "roles": [role_match.group(1)]}

    if mention in {"@everyone", "@here"}:
        return {"parse": ["everyone"]}

    return None
