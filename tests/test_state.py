from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from window_bot.decision import WindowState
from window_bot.state import PersistedState, StateStore


class StateStoreTests(unittest.TestCase):
    def test_load_returns_empty_state_when_file_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "missing.json")

            persisted = store.load()

            self.assertIsNone(persisted.current_state)
            self.assertIsNone(persisted.last_notified_state)

    def test_save_and_load_round_trip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.json")
            state = PersistedState(
                current_state=WindowState.OPEN,
                last_notified_state=WindowState.OPEN,
                last_observed_at=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 9, 12, 1, tzinfo=UTC),
            )

            store.save(state)
            reloaded = store.load()

            self.assertEqual(reloaded, state)
