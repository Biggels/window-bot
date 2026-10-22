from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from window_bot.config import Config, Schedule
from window_bot.house import HouseParameters
from window_bot.planner import PlanSettings
from window_bot.psychrometrics import fahrenheit_to_celsius
from window_bot.weather import WeatherHour, WeatherSeries

TZ = ZoneInfo("America/New_York")


def series(
    start: datetime,
    *,
    hours: int = 24 * 8,
    temperature_f: Callable[[datetime], float] | float = 68.0,
    dew_point_f: Callable[[datetime], float] | float = 45.0,
    rain_probability: Callable[[datetime], float] | float = 0.0,
) -> WeatherSeries:
    """Hourly weather from ``start``; each field is a constant or a function of the hour."""

    def value(field, moment: datetime) -> float:
        return field(moment) if callable(field) else field

    rows = []
    for offset in range(hours):
        moment = start + timedelta(hours=offset)
        rows.append(
            WeatherHour(
                time=moment,
                temperature_c=fahrenheit_to_celsius(value(temperature_f, moment)),
                dew_point_c=fahrenheit_to_celsius(value(dew_point_f, moment)),
                precipitation_probability=value(rain_probability, moment),
            )
        )
    return WeatherSeries(timezone=start.tzinfo, hours=tuple(rows))


def diurnal(low: float, high: float) -> Callable[[datetime], float]:
    """Coldest at 5am, warmest at 3pm, linear in between."""

    def temperature(moment: datetime) -> float:
        hour = moment.hour + moment.minute / 60
        if 5 <= hour <= 15:
            return low + (high - low) * (hour - 5) / 10
        since_peak = (hour - 15) % 24
        return high - (high - low) * since_peak / 14

    return temperature


def house() -> HouseParameters:
    return HouseParameters(
        heat_setpoint_c=fahrenheit_to_celsius(68),
        cool_setpoint_c=fahrenheit_to_celsius(75),
        volume_m3=480.0,
        open_air_changes_per_hour=5.0,
        closed_air_changes_per_hour=0.3,
        moisture_generation_kg_per_day=8.0,
        ac_moisture_removal_kg_per_hour=2.5,
    )


def plan_settings(**overrides) -> PlanSettings:
    values = dict(
        humidity_limit=60.0,
        max_extra_hours_above_limit=3.0,
        peak_humidity_limit=75.0,
        open_min_indoor_temp_c=fahrenheit_to_celsius(65),
        open_max_indoor_temp_c=fahrenheit_to_celsius(77),
        max_openings=2,
        min_opening_minutes=30,
        rain_probability_limit=40.0,
        quiet_start=time(21, 0),
        quiet_end=time(5, 0),
    )
    values.update(overrides)
    return PlanSettings(**values)


def config(state_file: Path, **plan_overrides) -> Config:
    return Config(
        latitude=35.8,
        longitude=-78.8,
        location_label="Home",
        temperature_unit="fahrenheit",
        timezone=TZ,
        schedule=Schedule(morning=time(5, 0), midday=time(12, 30), evening=time(17, 30)),
        plan=plan_settings(**plan_overrides),
        house=house(),
        discord_webhook_url="https://discord.invalid/webhook",
        state_file=state_file,
        request_timeout_seconds=10.0,
    )
