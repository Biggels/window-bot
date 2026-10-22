from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
import logging
import time
from typing import Callable

from .config import Config
from .notifier import DiscordNotifier, Notification
from .planner import Opening, Plan, add_local_days, estimate_indoor_state, is_quiet, plan_day, plan_day_start
from .report import Formatter, evening_message, midday_message, morning_message, plans_differ
from .state import PersistedState, StateStore
from .weather import OpenMeteoClient

LOGGER = logging.getLogger(__name__)

SLOTS = ("morning", "midday", "evening")
TICK_SECONDS = 60
RETRY_SECONDS = 300
OPENING_MEMORY = timedelta(days=3)


@dataclass
class ServiceDependencies:
    weather_client: OpenMeteoClient
    notifier: DiscordNotifier
    state_store: StateStore


@dataclass(frozen=True)
class SlotResult:
    message: str | None
    plan: Plan
    openings: tuple[Opening, ...]


def _system_clock(tz: tzinfo) -> datetime:
    return datetime.now(tz=UTC).astimezone(tz)


class WindowBotService:
    def __init__(
        self,
        config: Config,
        dependencies: ServiceDependencies,
        clock: Callable[[tzinfo], datetime] = _system_clock,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.clock = clock
        self._timezone: tzinfo | None = config.timezone
        self.formatter = Formatter(config.temperature_unit, config.plan)

    def run_forever(self) -> None:
        while True:
            try:
                self.tick()
                delay = TICK_SECONDS
            except Exception:
                LOGGER.exception("Window bot tick failed; retrying in %d seconds.", RETRY_SECONDS)
                delay = RETRY_SECONDS
            time.sleep(delay)

    def tick(self) -> None:
        """Send whichever scheduled message is due, if any."""
        now = self.now()
        day_start = plan_day_start(now, self.config.plan)
        state = self._state_for(day_start)
        due = [
            slot
            for slot in SLOTS
            if slot not in state.sent_slots and self._slot_time(day_start, slot) <= now
        ]
        if not due:
            return
        if is_quiet(now, self.config.plan):
            LOGGER.info("Skipping %s: inside quiet hours.", ", ".join(due))
            self._save(state, sent=due)
            return

        # If the bot was down, only the most recent due message is worth sending.
        slot = due[-1]
        result = self.prepare(slot, now, state)
        if result.message is not None:
            self.dependencies.notifier.send(Notification(body=result.message, mention=self.config.discord_mention))
            LOGGER.info("Sent %s message.", slot)
        else:
            LOGGER.info("No %s message needed; the plan has not changed.", slot)
        self._save(state, sent=due, openings=result.openings)

    def prepare(self, slot: str, now: datetime, state: PersistedState) -> SlotResult:
        """Build the plan and message for ``slot`` at ``now`` without sending or saving anything."""
        config = self.config
        series = self.dependencies.weather_client.fetch_forecast(
            latitude=config.latitude,
            longitude=config.longitude,
        )
        self._timezone = self._timezone or series.timezone
        now = now.astimezone(series.timezone)
        day_start = plan_day_start(now, config.plan)
        day_end = add_local_days(day_start, 1)
        remembered = [
            Opening(start=opening.start.astimezone(series.timezone), end=opening.end.astimezone(series.timezone))
            for opening in state.openings
        ]
        earlier_days = [opening for opening in remembered if opening.start < day_start]
        has_plan_today = state.plan_day == day_start.date() and bool(state.sent_slots)
        today = [opening for opening in remembered if day_start <= opening.start < day_end] if has_plan_today else []

        initial = estimate_indoor_state(
            config.house,
            series,
            day_start,
            config.plan.rain_probability_limit,
            assumed_openings=earlier_days,
        )
        plan = plan_day(
            config.house,
            config.plan,
            series,
            initial_state=initial,
            window_start=day_start,
            decide_from=now,
            earlier_openings=today,
        )

        openings = plan.openings
        if slot == "morning" or not has_plan_today:
            message: str | None = morning_message(plan, self.formatter)
        elif slot == "midday":
            remaining_before = tuple(opening for opening in today if opening.end > now)
            if plans_differ(remaining_before, plan.openings_after(now)):
                message = midday_message(plan, now, self.formatter)
            else:
                message = None
                openings = tuple(today)
        else:
            message = evening_message(plan, now, self._tomorrow(series, plan), self.formatter)

        keep = tuple(opening for opening in earlier_days if opening.end > day_start - OPENING_MEMORY)
        return SlotResult(message=message, plan=plan, openings=keep + tuple(openings))

    def _tomorrow(self, series, plan: Plan) -> Plan | None:
        try:
            return plan_day(
                self.config.house,
                self.config.plan,
                series,
                initial_state=plan.end_state,
                window_start=plan.window_end,
            )
        except ValueError:
            LOGGER.warning("Forecast does not reach far enough to preview tomorrow.")
            return None

    def now(self) -> datetime:
        return self.clock(self._location_timezone())

    def _location_timezone(self) -> tzinfo:
        if self._timezone is None:
            series = self.dependencies.weather_client.fetch_forecast(
                latitude=self.config.latitude,
                longitude=self.config.longitude,
            )
            self._timezone = series.timezone
        return self._timezone

    def _slot_time(self, day_start: datetime, slot: str) -> datetime:
        clock = getattr(self.config.schedule, slot)
        return day_start.replace(hour=clock.hour, minute=clock.minute)

    def _state_for(self, day_start: datetime) -> PersistedState:
        state = self.dependencies.state_store.load()
        if state.plan_day != day_start.date():
            state = PersistedState(plan_day=day_start.date(), sent_slots=(), openings=state.openings)
        return state

    def _save(self, state: PersistedState, *, sent: list[str], openings: tuple[Opening, ...] | None = None) -> None:
        self.dependencies.state_store.save(
            PersistedState(
                plan_day=state.plan_day,
                sent_slots=tuple(dict.fromkeys([*state.sent_slots, *sent])),
                openings=state.openings if openings is None else openings,
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
