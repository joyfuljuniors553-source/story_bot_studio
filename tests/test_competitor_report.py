"""Competitor topics vs our own videos (competitor_report.channel_report).

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from src.competitor_report import channel_report

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def day(n):
    return (NOW - timedelta(days=n)).isoformat()


class CompetitorReportTest(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.execute("""CREATE TABLE videos (title TEXT, views INT, publish_at TEXT, upload_date TEXT,
                          created_at TEXT, video_url TEXT, status TEXT, channel TEXT)""")
        self.c.execute("CREATE TABLE competitor_videos (channel TEXT, competitor_name TEXT, our_title TEXT)")

    def video(self, title, views, days_ago, status="scheduled"):
        self.c.execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?, 'space')",
                       (title, views, day(days_ago), day(days_ago), day(days_ago), "https://youtu.be/x", status))

    def idea(self, name, our_title):
        self.c.execute("INSERT INTO competitor_videos VALUES ('space', ?, ?)", (name, our_title))

    def test_strong_weak_and_too_early(self):
        for i in range(4):
            self.video(f"Own video {i} | Quasorynth", 100, 2)         # 50 views/day each
        self.idea("Astrum", "TON 618: The Quasar Hosting a 66‑Billion‑Solar‑Mass Black Hole")
        self.idea("Astrum", "Where Is Everybody in the Fermi Paradox?")
        self.video("TON 618: The Quasar Hosting a 66-Billion-Solar-Mass Black Hole | Quasorynth", 400, 2)
        self.video("Where Is Everybody in the Fermi Paradox? | Quasorynth", 300, 2)
        self.idea("Insane Curiosity", "Mars Olympus Mons")
        self.idea("Insane Curiosity", "Magnetars Explained")
        self.video("Mars Olympus Mons | Quasorynth", 40, 2)
        self.video("Magnetars Explained | Quasorynth", 20, 2)
        self.idea("SEA", "Saturn's Moons")
        self.video("Saturn's Moons | Quasorynth", 900, 2)
        r = channel_report(self.c, "space", 14, now=NOW)
        by = {c["name"]: c for c in r["competitors"]}
        self.assertEqual(r["own_videos"], 4)
        self.assertEqual(by["Astrum"]["verdict"], "strong")          # 175/day vs 50
        self.assertEqual(by["Insane Curiosity"]["verdict"], "weak")  # 15/day vs 50
        self.assertEqual(by["SEA"]["verdict"], "too early")          # only one video

    def test_not_public_yet_and_too_old_are_left_out(self):
        self.video("Tomorrow's video", 0, -1)
        self.video("Old video", 5000, 40)
        self.video("Failed video", 10, 2, status="upload_failed")
        r = channel_report(self.c, "space", 14, now=NOW)
        self.assertEqual(r["own_videos"], 0)


if __name__ == "__main__":
    unittest.main()
