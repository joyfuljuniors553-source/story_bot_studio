"""A late build slot lost to a cancelled run is caught up by the next morning run.

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from src.slots import missed_late_slot

LATE = SimpleNamespace(slot=8)    # 20:30 UTC (Quasorynth)
EARLY = SimpleNamespace(slot=4)   # 12:30 UTC


def at(h, m=0):
    return datetime(2026, 11, 5, h, m, tzinfo=timezone.utc)


class MissedSlotTest(unittest.TestCase):
    def test_morning_run_catches_up_a_lost_late_slot(self):
        self.assertTrue(missed_late_slot(LATE, 30.0, at(1, 42)))
        self.assertTrue(missed_late_slot(LATE, None, at(1, 42)))  # never built

    def test_not_when_the_channel_built_recently(self):
        self.assertFalse(missed_late_slot(LATE, 5.0, at(1, 42)))

    def test_not_after_the_first_daytime_slot(self):
        self.assertFalse(missed_late_slot(LATE, 30.0, at(11, 24)))

    def test_not_for_a_slot_that_already_came_today(self):
        self.assertFalse(missed_late_slot(SimpleNamespace(slot=0), 30.0, at(1, 42)))


if __name__ == "__main__":
    unittest.main()
