from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from window_bot.config import Config
from window_bot.decision import WindowState
from window_bot.notifier import Notification
from window_bot.service import ServiceDependencies, WindowBotService
from window_bot.state import PersistedState, StateStore
from window_bot.weather import WeatherSnapshot


def build_config(state_file: Path) -> Config:
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
        state_file=state_file,
        request_timeout_seconds=10.0,
    )


def snapshot(temp: float, humidity: float) -> WeatherSnapshot:
    return WeatherSnapshot(
        temperature=temp,
        humidity=humidity,
        observed_at=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    )


@dataclass
class FakeWeatherClient:
    weather: WeatherSnapshot | None = None
    error: Exception | None = None

    def fetch_current_weather(
        self,
        *,
        latitude: float,
        longitude: float,
        temperature_unit: str,
    ) -> WeatherSnapshot:
        del latitude, longitude, temperature_unit
        if self.error is not None:
            raise self.error
        assert self.weather is not None
        return self.weather


@dataclass
class FakeNotifier:
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.notifications: list[Notification] = []

    def send(self, notification: Notification) -> None:
        if self.error is not None:
            raise self.error
        self.notifications.append(notification)


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def test_initial_run_persists_state_without_notification(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            service, notifier, store = self._build_service(
                build_config(state_file),
                FakeWeatherClient(weather=snapshot(68.0, 45.0)),
                FakeNotifier(),
            )

            service.run_once()

            persisted = store.load()
            self.assertEqual(persisted.current_state, WindowState.OPEN)
            self.assertEqual(notifier.notifications, [])

    def test_transition_sends_notification_and_updates_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = StateStore(state_file)
            store.save(
                PersistedState(
                    current_state=WindowState.CLOSED,
                    last_notified_state=WindowState.CLOSED,
                    last_observed_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                    updated_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                )
            )
            notifier = FakeNotifier()
            service, _, store = self._build_service(
                build_config(state_file),
                FakeWeatherClient(weather=snapshot(68.0, 45.0)),
                notifier,
                store=store,
            )

            service.run_once()

            persisted = store.load()
            self.assertEqual(persisted.current_state, WindowState.OPEN)
            self.assertEqual(persisted.last_notified_state, WindowState.OPEN)
            self.assertEqual(len(notifier.notifications), 1)
            self.assertIn("Open the windows", notifier.notifications[0].title)
            self.assertIn("Configured open band:", notifier.notifications[0].body)

    def test_weather_failure_keeps_prior_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = StateStore(state_file)
            store.save(
                PersistedState(
                    current_state=WindowState.OPEN,
                    last_notified_state=WindowState.OPEN,
                    last_observed_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                    updated_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                )
            )
            notifier = FakeNotifier()
            service, _, store = self._build_service(
                build_config(state_file),
                FakeWeatherClient(error=RuntimeError("boom")),
                notifier,
                store=store,
            )

            service.run_once()

            persisted = store.load()
            self.assertEqual(persisted.current_state, WindowState.OPEN)
            self.assertEqual(notifier.notifications, [])

    def test_notification_failure_does_not_advance_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            store = StateStore(state_file)
            store.save(
                PersistedState(
                    current_state=WindowState.CLOSED,
                    last_notified_state=WindowState.CLOSED,
                    last_observed_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                    updated_at=datetime(2026, 3, 9, 11, 50, tzinfo=UTC),
                )
            )
            service, notifier, store = self._build_service(
                build_config(state_file),
                FakeWeatherClient(weather=snapshot(68.0, 45.0)),
                FakeNotifier(error=RuntimeError("discord down")),
                store=store,
            )

            service.run_once()

            persisted = store.load()
            self.assertEqual(persisted.current_state, WindowState.CLOSED)
            self.assertEqual(len(notifier.notifications), 0)

    def _build_service(
        self,
        config: Config,
        weather_client: FakeWeatherClient,
        notifier: FakeNotifier,
        *,
        store: StateStore | None = None,
    ) -> tuple[WindowBotService, FakeNotifier, StateStore]:
        state_store = store or StateStore(config.state_file)
        dependencies = ServiceDependencies(
            weather_client=weather_client,
            notifier=notifier,
            state_store=state_store,
        )
        return WindowBotService(config, dependencies), notifier, state_store
