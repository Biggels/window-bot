from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import time

from .config import Config
from .decision import WindowState, decide_window_state, describe_active_thresholds
from .notifier import DiscordNotifier, build_transition_notification
from .state import PersistedState, StateStore
from .weather import OpenMeteoClient

LOGGER = logging.getLogger(__name__)


@dataclass
class ServiceDependencies:
    weather_client: OpenMeteoClient
    notifier: DiscordNotifier
    state_store: StateStore


class WindowBotService:
    def __init__(self, config: Config, dependencies: ServiceDependencies) -> None:
        self.config = config
        self.dependencies = dependencies

    def run_forever(self) -> None:
        while True:
            started_at = time.monotonic()
            self.run_once()
            elapsed = time.monotonic() - started_at
            sleep_seconds = max(self.config.poll_interval_seconds - elapsed, 1)
            LOGGER.debug("Sleeping for %.1f seconds before the next poll", sleep_seconds)
            time.sleep(sleep_seconds)

    def run_once(self) -> None:
        state = self.dependencies.state_store.load()
        previous_state = state.current_state

        try:
            weather = self.dependencies.weather_client.fetch_current_weather(
                latitude=self.config.latitude,
                longitude=self.config.longitude,
                temperature_unit=self.config.temperature_unit,
            )
        except Exception:
            LOGGER.exception("Weather fetch failed; keeping prior window state.")
            return
        LOGGER.info(
            "Fetched weather for %s: %s, %.0f%% humidity at %s",
            self.config.location_label,
            weather.formatted_temperature(self.config.temperature_unit),
            weather.humidity,
            weather.observed_at.isoformat(),
        )

        decision = decide_window_state(weather, self.config, previous_state)
        LOGGER.debug("%s", describe_active_thresholds(self.config, previous_state))
        LOGGER.info("Current window state decision: %s (%s)", decision.state.value, decision.reason)

        if previous_state is None:
            LOGGER.info("No prior state found. Initializing to '%s' without notification.", decision.state.value)
            self.dependencies.state_store.save(
                PersistedState(
                    current_state=decision.state,
                    last_notified_state=None,
                    last_observed_at=weather.observed_at,
                    updated_at=_now_utc(),
                )
            )
            return

        if decision.state is previous_state:
            self.dependencies.state_store.save(
                PersistedState(
                    current_state=decision.state,
                    last_notified_state=state.last_notified_state,
                    last_observed_at=weather.observed_at,
                    updated_at=_now_utc(),
                )
            )
            return

        notification = build_transition_notification(decision, weather, self.config)
        try:
            self.dependencies.notifier.send(notification)
        except Exception:
            LOGGER.exception(
                "Notification send failed for transition %s -> %s; keeping prior state for retry.",
                previous_state.value,
                decision.state.value,
            )
            return
        LOGGER.info("Sent Discord notification for transition %s -> %s", previous_state.value, decision.state.value)
        self.dependencies.state_store.save(
            PersistedState(
                current_state=decision.state,
                last_notified_state=decision.state,
                last_observed_at=weather.observed_at,
                updated_at=_now_utc(),
            )
        )


def build_default_service(config: Config) -> WindowBotService:
    dependencies = ServiceDependencies(
        weather_client=OpenMeteoClient(timeout_seconds=config.request_timeout_seconds),
        notifier=DiscordNotifier(
            webhook_url=config.discord_webhook_url,
            timeout_seconds=config.request_timeout_seconds,
        ),
        state_store=StateStore(config.state_file),
    )
    return WindowBotService(config, dependencies)


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)
