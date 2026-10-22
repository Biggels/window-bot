from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, tzinfo
import logging
import os
from pathlib import Path
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .house import HouseParameters
from .planner import PlanSettings, is_quiet
from .psychrometrics import fahrenheit_to_celsius

LOGGER = logging.getLogger(__name__)

WEBHOOK_ENV_VAR = "WINDOW_BOT_DISCORD_WEBHOOK_URL"

CUBIC_METERS_PER_CUBIC_FOOT = 0.0283168

# Keys from the original threshold-based bot that no longer do anything.
LEGACY_KEYS = (
    "poll_interval_minutes",
    "temp_open_min",
    "temp_open_max",
    "humidity_open_min",
    "humidity_open_max",
    "temp_hysteresis_margin",
    "humidity_hysteresis_margin",
)


@dataclass(frozen=True)
class Schedule:
    morning: time
    midday: time
    evening: time


@dataclass(frozen=True)
class Config:
    latitude: float
    longitude: float
    location_label: str
    temperature_unit: str
    timezone: tzinfo | None
    schedule: Schedule
    plan: PlanSettings
    house: HouseParameters
    discord_webhook_url: str | None
    state_file: Path
    request_timeout_seconds: float
    discord_mention: str | None = None


def load_config(path: Path) -> Config:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    legacy = [key for key in LEGACY_KEYS if key in raw]
    if legacy:
        LOGGER.warning("Ignoring config keys from the old threshold-based bot: %s", ", ".join(legacy))

    schedule_raw = _section(raw, "schedule")
    comfort_raw = _section(raw, "comfort")
    plan_raw = _section(raw, "plan")
    house_raw = _section(raw, "house")

    temperature_unit = str(raw.get("temperature_unit", "fahrenheit")).lower()
    if temperature_unit not in {"celsius", "fahrenheit"}:
        raise ValueError("temperature_unit must be 'celsius' or 'fahrenheit'")
    fahrenheit = temperature_unit == "fahrenheit"

    def temperature(section: dict[str, object], key: str, default_f: float) -> float:
        default = default_f if fahrenheit else round(fahrenheit_to_celsius(default_f), 1)
        value = _number(section, key, default)
        return fahrenheit_to_celsius(value) if fahrenheit else value

    quiet_start = _clock(schedule_raw, "quiet_start", "21:00")
    quiet_end = _clock(schedule_raw, "quiet_end", "05:00")
    plan = PlanSettings(
        humidity_limit=_number(comfort_raw, "humidity_limit", 60.0),
        max_extra_hours_above_limit=_number(comfort_raw, "max_extra_hours_above_limit", 3.0),
        peak_humidity_limit=_number(comfort_raw, "peak_humidity_limit", 75.0),
        open_min_indoor_temp_c=temperature(comfort_raw, "open_min_indoor_temp", 65.0),
        open_max_indoor_temp_c=temperature(comfort_raw, "open_max_indoor_temp", 77.0),
        max_openings=_integer(plan_raw, "max_openings_per_day", 2),
        min_opening_minutes=_integer(plan_raw, "min_opening_minutes", 30),
        rain_probability_limit=_number(plan_raw, "rain_probability_limit", 40.0),
        quiet_start=quiet_start,
        quiet_end=quiet_end,
    )
    house = HouseParameters(
        heat_setpoint_c=temperature(comfort_raw, "heat_setpoint", 68.0),
        cool_setpoint_c=temperature(comfort_raw, "cool_setpoint", 75.0),
        volume_m3=_number(house_raw, "floor_area_sq_ft", 2000.0)
        * _number(house_raw, "ceiling_height_ft", 8.5)
        * CUBIC_METERS_PER_CUBIC_FOOT,
        open_air_changes_per_hour=_number(house_raw, "open_air_changes_per_hour", 5.0),
        closed_air_changes_per_hour=_number(house_raw, "closed_air_changes_per_hour", 0.3),
        moisture_generation_kg_per_day=_number(house_raw, "moisture_generation_kg_per_day", 8.0),
        ac_moisture_removal_kg_per_hour=_number(house_raw, "ac_moisture_removal_kg_per_hour", 2.5),
    )
    config = Config(
        latitude=_number(raw, "latitude"),
        longitude=_number(raw, "longitude"),
        location_label=str(raw.get("location_label", "Home")),
        temperature_unit=temperature_unit,
        timezone=_timezone(raw),
        schedule=Schedule(
            morning=_clock(schedule_raw, "morning", "05:00"),
            midday=_clock(schedule_raw, "midday", "12:30"),
            evening=_clock(schedule_raw, "evening", "17:30"),
        ),
        plan=plan,
        house=house,
        discord_webhook_url=_load_secret_string(raw, "discord_webhook_url", env_var=WEBHOOK_ENV_VAR),
        discord_mention=_optional_string(raw, "discord_mention"),
        state_file=_resolve_path(path.parent, raw.get("state_file", "state/window-bot-state.json")),
        request_timeout_seconds=_number(raw, "request_timeout_seconds", 10.0),
    )
    _validate_config(config)
    return config


def _section(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{key}] must be a table")
    return value


def _number(raw: dict[str, object], key: str, default: float | None = None) -> float:
    value = raw.get(key, default)
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Config key '{key}' must be a number")
    return float(value)


def _integer(raw: dict[str, object], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Config key '{key}' must be an integer")
    return value


def _clock(raw: dict[str, object], key: str, default: str) -> time:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"Config key '{key}' must be a time like \"05:00\"")
    try:
        return time.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"Config key '{key}' must be a time like \"05:00\" (got {value!r})") from exc


def _timezone(raw: dict[str, object]) -> tzinfo | None:
    name = _optional_string(raw, "timezone")
    if name is None:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone {name!r}") from exc


def _load_secret_string(raw: dict[str, object], key: str, *, env_var: str) -> str | None:
    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        return env_value

    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Config key '{key}' must be a non-empty string when {env_var} is not set"
        )
    return value.strip()


def _optional_string(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config key '{key}' must be a non-empty string when provided")
    return value.strip()


def _resolve_path(base: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Config key 'state_file' must be a non-empty string")
    path = Path(raw_path)
    return path if path.is_absolute() else (base / path).resolve()


def _validate_config(config: Config) -> None:
    plan = config.plan
    house = config.house
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be greater than zero")
    if house.heat_setpoint_c >= house.cool_setpoint_c:
        raise ValueError("heat_setpoint must be below cool_setpoint")
    if plan.open_min_indoor_temp_c > house.heat_setpoint_c:
        raise ValueError("open_min_indoor_temp must not be above heat_setpoint")
    if plan.open_max_indoor_temp_c < house.cool_setpoint_c:
        raise ValueError("open_max_indoor_temp must not be below cool_setpoint")
    for name, value in {
        "humidity_limit": plan.humidity_limit,
        "peak_humidity_limit": plan.peak_humidity_limit,
        "rain_probability_limit": plan.rain_probability_limit,
    }.items():
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
    if plan.peak_humidity_limit < plan.humidity_limit:
        raise ValueError("peak_humidity_limit must not be below humidity_limit")
    if plan.max_extra_hours_above_limit < 0:
        raise ValueError("max_extra_hours_above_limit must be non-negative")
    if plan.max_openings < 1:
        raise ValueError("max_openings_per_day must be at least 1")
    if plan.min_opening_minutes < 1:
        raise ValueError("min_opening_minutes must be at least 1")
    for name, value in {
        "open_air_changes_per_hour": house.open_air_changes_per_hour,
        "closed_air_changes_per_hour": house.closed_air_changes_per_hour,
        "floor area and ceiling height": house.volume_m3,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
    if house.closed_air_changes_per_hour >= house.open_air_changes_per_hour:
        raise ValueError("closed_air_changes_per_hour must be below open_air_changes_per_hour")
    if house.moisture_generation_kg_per_day < 0 or house.ac_moisture_removal_kg_per_hour < 0:
        raise ValueError("moisture_generation_kg_per_day and ac_moisture_removal_kg_per_hour must be non-negative")

    for name in ("morning", "midday", "evening"):
        slot = getattr(config.schedule, name)
        if is_quiet(datetime.combine(datetime.min.date(), slot), plan):
            raise ValueError(f"schedule.{name} ({slot:%H:%M}) falls inside quiet hours")
    if not (
        plan.quiet_end <= config.schedule.morning < config.schedule.midday < config.schedule.evening
    ):
        raise ValueError("schedule times must be in order: quiet_end <= morning < midday < evening")
