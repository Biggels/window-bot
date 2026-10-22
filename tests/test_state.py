from __future__ import annotations

from datetime import date, datetime
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from window_bot.planner import Opening
from window_bot.state import PersistedState, StateStore

from helpers import TZ


class StateStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def test_load_returns_empty_state_when_file_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            self.assertEqual(StateStore(Path(tmpdir) / "missing.json").load(), PersistedState())

    def test_save_and_load_round_trip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            state = PersistedState(
                plan_day=date(2026, 7, 15),
                sent_slots=("morning", "midday"),
                openings=(
                    Opening(datetime(2026, 7, 15, 9, 30, tzinfo=TZ), datetime(2026, 7, 15, 10, 15, tzinfo=TZ)),
                ),
            )

            store.save(state)
            reloaded = store.load()

        self.assertEqual(reloaded.plan_day, state.plan_day)
        self.assertEqual(reloaded.sent_slots, state.sent_slots)
        self.assertEqual(reloaded.openings, state.openings)

    def test_state_from_old_version_is_ignored(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(json.dumps({"current_state": "open", "last_notified_state": "open"}), encoding="utf-8")

            self.assertEqual(StateStore(path).load(), PersistedState())

    def test_corrupt_state_is_ignored(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text("{not json", encoding="utf-8")

            self.assertEqual(StateStore(path).load(), PersistedState())
