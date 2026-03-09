from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .config import Config
from .weather import WeatherSnapshot


class WindowState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class Decision:
    state: WindowState
    reason: str


def decide_window_state(
    weather: WeatherSnapshot,
    config: Config,
    previous_state: WindowState | None,
) -> Decision:
    if previous_state is WindowState.OPEN:
        if _within_open_band(weather, config):
            return Decision(
                state=WindowState.OPEN,
                reason=_build_open_hold_reason(weather, config),
            )
        if _within_retention_band(weather, config):
            return Decision(
                state=WindowState.OPEN,
                reason=_build_retention_reason(weather, config),
            )
        return Decision(
            state=WindowState.CLOSED,
            reason=_build_close_reason(weather, config),
        )

    if _within_open_band(weather, config):
        return Decision(
            state=WindowState.OPEN,
            reason=_build_open_band_reason(weather, config, entered=True),
        )

    return Decision(
        state=WindowState.CLOSED,
        reason=_build_closed_hold_reason(weather, config),
    )


def _within_open_band(weather: WeatherSnapshot, config: Config) -> bool:
    return (
        config.temp_open_min <= weather.temperature <= config.temp_open_max
        and config.humidity_open_min <= weather.humidity <= config.humidity_open_max
    )


def _within_retention_band(weather: WeatherSnapshot, config: Config) -> bool:
    return (
        (config.temp_open_min - config.temp_hysteresis_margin)
        <= weather.temperature
        <= (config.temp_open_max + config.temp_hysteresis_margin)
        and (config.humidity_open_min - config.humidity_hysteresis_margin)
        <= weather.humidity
        <= (config.humidity_open_max + config.humidity_hysteresis_margin)
    )


def describe_threshold_bands(config: Config) -> str:
    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin
    return (
        f"Configured open band: {_format_temperature(config.temp_open_min, config)} to "
        f"{_format_temperature(config.temp_open_max, config)} and "
        f"{config.humidity_open_min:.0f}% to {config.humidity_open_max:.0f}% humidity. "
        f"Hysteresis close band while already open: {_format_temperature(temp_low, config)} to "
        f"{_format_temperature(temp_high, config)} and "
        f"{humidity_low:.0f}% to {humidity_high:.0f}% humidity."
    )


def describe_active_thresholds(config: Config, previous_state: WindowState | None) -> str:
    open_band = (
        f"Configured open band: {_format_temperature(config.temp_open_min, config)} to "
        f"{_format_temperature(config.temp_open_max, config)} and "
        f"{config.humidity_open_min:.0f}% to {config.humidity_open_max:.0f}% humidity."
    )
    if previous_state is not WindowState.OPEN:
        return open_band

    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin
    return (
        f"{open_band} Active hysteresis close band for the current open state: "
        f"{_format_temperature(temp_low, config)} to {_format_temperature(temp_high, config)} and "
        f"{humidity_low:.0f}% to {humidity_high:.0f}% humidity."
    )


def _build_open_band_reason(weather: WeatherSnapshot, config: Config, *, entered: bool) -> str:
    prefix = "Conditions entered the configured open band" if entered else "Conditions remain inside the configured open band"
    return (
        f"{prefix}: temperature {weather.formatted_temperature(config.temperature_unit)} is within "
        f"{_format_temperature(config.temp_open_min, config)} to {_format_temperature(config.temp_open_max, config)} "
        f"and humidity {weather.humidity:.0f}% is within "
        f"{config.humidity_open_min:.0f}% to {config.humidity_open_max:.0f}%."
    )


def _build_open_hold_reason(weather: WeatherSnapshot, config: Config) -> str:
    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin
    return (
        f"Conditions remain open: temperature {weather.formatted_temperature(config.temperature_unit)} and "
        f"humidity {weather.humidity:.0f}% are inside the configured open band, and because the state is already open "
        f"it would not close unless temperature leaves {_format_temperature(temp_low, config)} to "
        f"{_format_temperature(temp_high, config)} or humidity leaves {humidity_low:.0f}% to {humidity_high:.0f}%."
    )


def _build_retention_reason(weather: WeatherSnapshot, config: Config) -> str:
    reasons = []
    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin

    if weather.temperature < config.temp_open_min:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is below the configured open minimum "
            f"of {_format_temperature(config.temp_open_min, config)}, but hysteresis keeps the state open until "
            f"{_format_temperature(temp_low, config)}"
        )
    elif weather.temperature > config.temp_open_max:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is above the configured open maximum "
            f"of {_format_temperature(config.temp_open_max, config)}, but hysteresis keeps the state open until "
            f"{_format_temperature(temp_high, config)}"
        )

    if weather.humidity < config.humidity_open_min:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is below the configured open minimum of "
            f"{config.humidity_open_min:.0f}%, but hysteresis keeps the state open until {humidity_low:.0f}%"
        )
    elif weather.humidity > config.humidity_open_max:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is above the configured open maximum of "
            f"{config.humidity_open_max:.0f}%, but hysteresis keeps the state open until {humidity_high:.0f}%"
        )

    if not reasons:
        return "Conditions remain open because hysteresis is active."

    return _sentence("Conditions remain open because hysteresis is active: " + "; ".join(reasons))


def _build_close_reason(weather: WeatherSnapshot, config: Config) -> str:
    reasons = []
    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin

    if weather.temperature < temp_low:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} fell below the hysteresis-adjusted close minimum "
            f"of {_format_temperature(temp_low, config)} (configured open minimum "
            f"{_format_temperature(config.temp_open_min, config)} - "
            f"{_format_temperature(config.temp_hysteresis_margin, config)} margin)"
        )
    elif weather.temperature > temp_high:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} exceeded the hysteresis-adjusted close maximum "
            f"of {_format_temperature(temp_high, config)} (configured open maximum "
            f"{_format_temperature(config.temp_open_max, config)} + "
            f"{_format_temperature(config.temp_hysteresis_margin, config)} margin)"
        )

    if weather.humidity < humidity_low:
        reasons.append(
            f"humidity {weather.humidity:.0f}% fell below the hysteresis-adjusted close minimum of "
            f"{humidity_low:.0f}% (configured open minimum {config.humidity_open_min:.0f}% - "
            f"{config.humidity_hysteresis_margin:.0f}% margin)"
        )
    elif weather.humidity > humidity_high:
        reasons.append(
            f"humidity {weather.humidity:.0f}% exceeded the hysteresis-adjusted close maximum of "
            f"{humidity_high:.0f}% (configured open maximum {config.humidity_open_max:.0f}% + "
            f"{config.humidity_hysteresis_margin:.0f}% margin)"
        )

    if not reasons:
        reasons.append("conditions left the open retention band")

    return _sentence("; ".join(reasons))


def _build_closed_hold_reason(weather: WeatherSnapshot, config: Config) -> str:
    reasons = []

    if weather.temperature < config.temp_open_min:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is below the configured open minimum of "
            f"{_format_temperature(config.temp_open_min, config)}"
        )
    elif weather.temperature > config.temp_open_max:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is above the configured open maximum of "
            f"{_format_temperature(config.temp_open_max, config)}"
        )

    if weather.humidity < config.humidity_open_min:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is below the configured open minimum of {config.humidity_open_min:.0f}%"
        )
    elif weather.humidity > config.humidity_open_max:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is above the configured open maximum of {config.humidity_open_max:.0f}%"
        )

    if not reasons:
        reasons.append("conditions are outside the configured open band")

    return _sentence("; ".join(reasons))


def _format_temperature(temperature: float, config: Config) -> str:
    suffix = "F" if config.temperature_unit == "fahrenheit" else "C"
    return f"{temperature:.1f}°{suffix}"


def _sentence(message: str) -> str:
    if not message:
        return "."
    return message[0].upper() + message[1:] + "."
