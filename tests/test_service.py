from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from window_bot.notifier import Notification
from window_bot.service import ServiceDependencies, WindowBotService
from window_bot.state import StateStore
from window_bot.weather import WeatherSeries

from helpers import TZ, config, diurnal, series

DAY = datetime(2026, 5, 10, 5, 0, tzinfo=TZ)


@dataclass
class FakeWeatherClient:
    weather: WeatherSeries | None = None
    error: Exception | None = None
    calls: int = 0

    def fetch_forecast(self, *, latitude: float, longitude: float) -> WeatherSeries:
        del latitude, longitude
        self.calls += 1
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


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self, tz) -> datetime:
        return self.moment.astimezone(tz)


def mild_weather() -> WeatherSeries:
    return series(DAY - timedelta(days=4), temperature_f=diurnal(58, 74), dew_point_f=45)


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def setUp(self) -> None:
        self.tmpdir = TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = config(Path(self.tmpdir.name) / "state.json")
        self.weather = FakeWeatherClient(weather=mild_weather())
        self.notifier = FakeNotifier()
        self.store = StateStore(self.config.state_file)
        self.clock = Clock(DAY)
        self.service = WindowBotService(
            self.config,
            ServiceDependencies(weather_client=self.weather, notifier=self.notifier, state_store=self.store),
            clock=self.clock,
        )

    def tick_at(self, hour: int, minute: int = 0) -> None:
        self.clock.moment = DAY.replace(hour=hour, minute=minute)
        self.service.tick()

    def test_morning_plan_is_sent_once(self) -> None:
        self.tick_at(5)
        self.tick_at(5, 1)
        self.tick_at(9)

        self.assertEqual(len(self.notifier.notifications), 1)
        self.assertTrue(self.notifier.notifications[0].body.startswith("**Window plan · Sun May 10**"))
        state = self.store.load()
        self.assertEqual(state.sent_slots, ("morning",))
        self.assertTrue(state.openings)

    def test_midday_is_silent_when_plan_is_unchanged(self) -> None:
        self.tick_at(5)
        self.tick_at(12, 30)

        self.assertEqual(len(self.notifier.notifications), 1)
        self.assertIn("midday", self.store.load().sent_slots)

    def test_midday_update_when_forecast_changes(self) -> None:
        self.tick_at(5)
        self.weather.weather = series(
            DAY - timedelta(days=4),
            temperature_f=diurnal(58, 74),
            dew_point_f=45,
            rain_probability=lambda moment: 90 if moment >= DAY.replace(hour=13) else 0,
        )
        self.tick_at(12, 30)

        self.assertEqual(len(self.notifier.notifications), 2)
        self.assertTrue(self.notifier.notifications[1].body.startswith("**Plan update"))

    def test_evening_message_previews_tomorrow(self) -> None:
        self.tick_at(5)
        self.tick_at(17, 30)

        evening = self.notifier.notifications[-1].body
        self.assertTrue(evening.startswith("**Tonight · Sun May 10**"))
        self.assertIn("Tomorrow:", evening)

    def test_late_start_sends_only_the_latest_due_message_as_a_full_plan(self) -> None:
        self.tick_at(13)

        self.assertEqual(len(self.notifier.notifications), 1)
        self.assertTrue(self.notifier.notifications[0].body.startswith("**Window plan"))
        self.assertEqual(set(self.store.load().sent_slots), {"morning", "midday"})

    def test_nothing_is_sent_during_quiet_hours(self) -> None:
        self.clock.moment = DAY.replace(hour=22)
        self.service.tick()

        self.assertEqual(self.notifier.notifications, [])
        self.assertEqual(set(self.store.load().sent_slots), {"morning", "midday", "evening"})

    def test_new_plan_day_resets_slots_and_remembers_openings(self) -> None:
        self.tick_at(5)
        first_openings = self.store.load().openings
        self.clock.moment = DAY + timedelta(days=1)
        self.service.tick()

        state = self.store.load()
        self.assertEqual(state.plan_day, (DAY + timedelta(days=1)).date())
        self.assertEqual(state.sent_slots, ("morning",))
        for opening in first_openings:
            self.assertIn(opening, state.openings)
        self.assertEqual(len(self.notifier.notifications), 2)

    def test_notification_failure_is_retried(self) -> None:
        self.notifier.error = RuntimeError("discord down")
        with self.assertRaises(RuntimeError):
            self.tick_at(5)
        self.assertEqual(self.store.load().sent_slots, ())

        self.notifier.error = None
        self.tick_at(5, 1)
        self.assertEqual(len(self.notifier.notifications), 1)

    def test_weather_failure_is_retried(self) -> None:
        self.weather.error = RuntimeError("weather down")
        with self.assertRaises(RuntimeError):
            self.tick_at(5)

        self.weather.error = None
        self.tick_at(5, 5)
        self.assertEqual(len(self.notifier.notifications), 1)
