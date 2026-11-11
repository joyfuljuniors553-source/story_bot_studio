"""A channel does not repeat a subject or a clip.

Run: python -m unittest discover -s tests
DimeHorizon covered net worth and credit scores three times each, Veylora
Earth the fossil record three times, and three of its Shorts opened on one
geode clip. Nothing here reaches YouTube.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import clip_sources
from src.topic_similarity import covered_by, same_subject

DIME = [
    "How Net Worth and Assets Define Personal Wealth | Dime Horizon",
    "Understanding Your Net Worth and Wealth | Dime Horizon",
    "How Credit Scores Measure Financial Risk | Dime Horizon",
    "How Banking Panics and Fractional Reserves Spark Financial Crises | Dime Horizon",
    "Inflation Explained | Dime Horizon",
    "How Compound Interest Quietly Builds Wealth | Dime Horizon",
    "Wall Street crash of 1929 Explained | Dime Horizon",
    "Personal finance Explained | Dime Horizon",
]


class SameSubject(unittest.TestCase):
    def test_repeats_are_caught(self):
        self.assertTrue(covered_by("How Net Worth Quietly Measures Financial Strength | Dime Horizon", DIME))
        self.assertTrue(covered_by("Understanding How Credit Scores Work and Determine Your Options", DIME))
        self.assertTrue(covered_by("Personal finance Explained | Dime Horizon", DIME))
        self.assertTrue(same_subject("Unveiling the Ancient Fossil Record Across Time",
                                     "Unveiling the Ancient Fossil Record Dating Methods"))

    def test_new_subjects_pass(self):
        for title in ("How the Debt Snowball Method Uses Small Wins to Clear Balances",
                      "Time Value of Money: Why a Dollar Today Beats Tomorrow",
                      "FIRE movement Explained | Dime Horizon"):
            self.assertIsNone(covered_by(title, DIME), title)
        self.assertFalse(same_subject("Thylacine Explained | Veylora Earth", "Irish elk Explained | Veylora Earth"))
        self.assertFalse(same_subject("Unveiling Paraceratherium: The 20 Tonne Extinct Giant",
                                      "Unveiling Arsinoitherium: The Enigmatic Horned Beast"))
        self.assertFalse(same_subject("How Billie Eilish and Finneas Created Ocean Eyes",
                                      "How Oprah Gail Winfrey Rose From Poverty to Global Fame"))


class ClipMemory(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(clip_sources, "settings", SimpleNamespace(db_path=self.dir / "bot.sqlite3"))
        self.patch.start()
        clip_sources._CHANNEL_CLIPS.clear()

    def tearDown(self):
        self.patch.stop()
        clip_sources._CHANNEL_CLIPS.clear()
        clip_sources.set_context()

    def test_a_clip_is_kept_from_the_channels_next_video(self):
        clip_sources.set_context(channel="veylora_earth")
        clip_sources.remember_clip("pexels:777")
        clip_sources._CHANNEL_CLIPS.clear()  # a later run reads it back from the database
        run_dir = self.dir / "next_video"
        self.assertIn("pexels:777", clip_sources._used(run_dir))

    def test_other_channels_are_not_affected(self):
        clip_sources.set_context(channel="veylora_earth")
        clip_sources.remember_clip("pexels:777")
        clip_sources.set_context(channel="quasorynth_space")
        self.assertNotIn("pexels:777", clip_sources._used(self.dir / "x"))

    def test_rejected_clips_stay_with_their_own_video(self):
        clip_sources.set_context(channel="veylora_earth")
        run_dir = self.dir / "one"
        run_dir.mkdir()
        clip_sources._mark_used(run_dir, "pixabay:5")  # tried, did not fit this line
        self.assertNotIn("pixabay:5", clip_sources._used(self.dir / "two"))
        with sqlite3.connect(self.dir / "bot.sqlite3") as conn:
            clip_sources._clip_table(conn)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM used_clips").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
