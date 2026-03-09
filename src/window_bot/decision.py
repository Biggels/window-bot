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
        if _within_retention_band(weather, config):
            return Decision(
                state=WindowState.OPEN,
                reason=(
                    "Conditions remain within the open retention band "
                    f"({weather.formatted_temperature(config.temperature_unit)} and {weather.humidity:.0f}% humidity)."
                ),
            )
        return Decision(
            state=WindowState.CLOSED,
            reason=_build_close_reason(weather, config),
        )

    if _within_open_band(weather, config):
        return Decision(
            state=WindowState.OPEN,
            reason=(
                "Conditions entered the open band "
                f"({weather.formatted_temperature(config.temperature_unit)} and {weather.humidity:.0f}% humidity)."
            ),
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


def _build_close_reason(weather: WeatherSnapshot, config: Config) -> str:
    reasons = []
    temp_low = config.temp_open_min - config.temp_hysteresis_margin
    temp_high = config.temp_open_max + config.temp_hysteresis_margin
    humidity_low = config.humidity_open_min - config.humidity_hysteresis_margin
    humidity_high = config.humidity_open_max + config.humidity_hysteresis_margin

    if weather.temperature < temp_low:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} fell below the close threshold of {_format_temperature(temp_low, config)}"
        )
    elif weather.temperature > temp_high:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} exceeded the close threshold of {_format_temperature(temp_high, config)}"
        )

    if weather.humidity < humidity_low:
        reasons.append(
            f"humidity {weather.humidity:.0f}% fell below the close threshold of {humidity_low:.0f}%"
        )
    elif weather.humidity > humidity_high:
        reasons.append(
            f"humidity {weather.humidity:.0f}% exceeded the close threshold of {humidity_high:.0f}%"
        )

    if not reasons:
        reasons.append("conditions left the open retention band")

    return _sentence("; ".join(reasons))


def _build_closed_hold_reason(weather: WeatherSnapshot, config: Config) -> str:
    reasons = []

    if weather.temperature < config.temp_open_min:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is below the open minimum of {_format_temperature(config.temp_open_min, config)}"
        )
    elif weather.temperature > config.temp_open_max:
        reasons.append(
            f"temperature {weather.formatted_temperature(config.temperature_unit)} is above the open maximum of {_format_temperature(config.temp_open_max, config)}"
        )

    if weather.humidity < config.humidity_open_min:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is below the open minimum of {config.humidity_open_min:.0f}%"
        )
    elif weather.humidity > config.humidity_open_max:
        reasons.append(
            f"humidity {weather.humidity:.0f}% is above the open maximum of {config.humidity_open_max:.0f}%"
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
