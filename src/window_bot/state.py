from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from .decision import WindowState


@dataclass(frozen=True)
class PersistedState:
    current_state: WindowState | None
    last_notified_state: WindowState | None
    last_observed_at: datetime | None
    updated_at: datetime | None


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> PersistedState:
        if not self.path.exists():
            return PersistedState(
                current_state=None,
                last_notified_state=None,
                last_observed_at=None,
                updated_at=None,
            )

        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        return PersistedState(
            current_state=_parse_state(raw.get("current_state")),
            last_notified_state=_parse_state(raw.get("last_notified_state")),
            last_observed_at=_parse_datetime(raw.get("last_observed_at")),
            updated_at=_parse_datetime(raw.get("updated_at")),
        )

    def save(self, state: PersistedState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_state": state.current_state.value if state.current_state else None,
            "last_notified_state": state.last_notified_state.value if state.last_notified_state else None,
            "last_observed_at": state.last_observed_at.isoformat() if state.last_observed_at else None,
            "updated_at": state.updated_at.isoformat() if state.updated_at else datetime.now(tz=UTC).isoformat(),
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")


def _parse_state(value: object) -> WindowState | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("State file contained an invalid state value")
    return WindowState(value)


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("State file contained an invalid datetime value")
    return datetime.fromisoformat(value)
