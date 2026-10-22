from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
from pathlib import Path

from .planner import Opening

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersistedState:
    # The plan day the slots below belong to (the date of its wake-up time).
    plan_day: date | None = None
    sent_slots: tuple[str, ...] = ()
    # Openings recommended over the last few days, assumed to have been followed.
    openings: tuple[Opening, ...] = ()


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> PersistedState:
        if not self.path.exists():
            return PersistedState()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if "plan_day" not in raw:
                LOGGER.info("State file %s is from an older version; starting fresh.", self.path)
                return PersistedState()
            plan_day = raw["plan_day"]
            return PersistedState(
                plan_day=date.fromisoformat(plan_day) if plan_day else None,
                sent_slots=tuple(str(slot) for slot in raw.get("sent_slots", [])),
                openings=tuple(
                    Opening(
                        start=datetime.fromisoformat(item["start"]),
                        end=datetime.fromisoformat(item["end"]),
                    )
                    for item in raw.get("openings", [])
                ),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            LOGGER.warning("Could not read state file %s (%s); starting fresh.", self.path, exc)
            return PersistedState()

    def save(self, state: PersistedState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "plan_day": state.plan_day.isoformat() if state.plan_day else None,
            "sent_slots": list(state.sent_slots),
            "openings": [
                {"start": opening.start.isoformat(), "end": opening.end.isoformat()}
                for opening in state.openings
            ],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temporary.replace(self.path)
