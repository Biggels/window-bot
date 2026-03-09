from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Config:
    latitude: float
    longitude: float
    location_label: str
    poll_interval_minutes: int
    temperature_unit: str
    temp_open_min: float
    temp_open_max: float
    humidity_open_min: float
    humidity_open_max: float
    temp_hysteresis_margin: float
    humidity_hysteresis_margin: float
    discord_webhook_url: str
    state_file: Path
    request_timeout_seconds: float

    @property
    def poll_interval_seconds(self) -> int:
        return self.poll_interval_minutes * 60


def load_config(path: Path) -> Config:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    latitude = _require_number(raw, "latitude")
    longitude = _require_number(raw, "longitude")
    location_label = str(raw.get("location_label", "Home"))
    poll_interval_minutes = _require_int(raw, "poll_interval_minutes", default=10)
    temperature_unit = str(raw.get("temperature_unit", "fahrenheit")).lower()
    temp_open_min = _require_number(raw, "temp_open_min")
    temp_open_max = _require_number(raw, "temp_open_max")
    humidity_open_min = _require_number(raw, "humidity_open_min")
    humidity_open_max = _require_number(raw, "humidity_open_max")
    temp_hysteresis_margin = _require_number(raw, "temp_hysteresis_margin")
    humidity_hysteresis_margin = _require_number(raw, "humidity_hysteresis_margin")
    discord_webhook_url = _require_string(raw, "discord_webhook_url")
    state_file = _resolve_path(path.parent, raw.get("state_file", "state/window-bot-state.json"))
    request_timeout_seconds = _require_number(raw, "request_timeout_seconds", default=10.0)

    config = Config(
        latitude=latitude,
        longitude=longitude,
        location_label=location_label,
        poll_interval_minutes=poll_interval_minutes,
        temperature_unit=temperature_unit,
        temp_open_min=temp_open_min,
        temp_open_max=temp_open_max,
        humidity_open_min=humidity_open_min,
        humidity_open_max=humidity_open_max,
        temp_hysteresis_margin=temp_hysteresis_margin,
        humidity_hysteresis_margin=humidity_hysteresis_margin,
        discord_webhook_url=discord_webhook_url,
        state_file=state_file,
        request_timeout_seconds=request_timeout_seconds,
    )
    _validate_config(config)
    return config


def _require_number(raw: dict[str, object], key: str, default: float | None = None) -> float:
    value = raw.get(key, default)
    if value is None or not isinstance(value, int | float):
        raise ValueError(f"Config key '{key}' must be a number")
    return float(value)


def _require_int(raw: dict[str, object], key: str, default: int | None = None) -> int:
    value = raw.get(key, default)
    if value is None or not isinstance(value, int):
        raise ValueError(f"Config key '{key}' must be an integer")
    return value


def _require_string(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config key '{key}' must be a non-empty string")
    return value.strip()


def _resolve_path(base: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Config key 'state_file' must be a non-empty string")
    path = Path(raw_path)
    return path if path.is_absolute() else (base / path).resolve()


def _validate_config(config: Config) -> None:
    if config.temperature_unit not in {"celsius", "fahrenheit"}:
        raise ValueError("temperature_unit must be 'celsius' or 'fahrenheit'")
    if config.poll_interval_minutes <= 0:
        raise ValueError("poll_interval_minutes must be greater than zero")
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be greater than zero")
    if config.temp_open_min > config.temp_open_max:
        raise ValueError("temp_open_min must be less than or equal to temp_open_max")
    if config.humidity_open_min > config.humidity_open_max:
        raise ValueError("humidity_open_min must be less than or equal to humidity_open_max")
    if config.temp_hysteresis_margin < 0:
        raise ValueError("temp_hysteresis_margin must be non-negative")
    if config.humidity_hysteresis_margin < 0:
        raise ValueError("humidity_hysteresis_margin must be non-negative")
    for name, value in {
        "humidity_open_min": config.humidity_open_min,
        "humidity_open_max": config.humidity_open_max,
    }.items():
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
