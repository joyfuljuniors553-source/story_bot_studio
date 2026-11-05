"""Competitor ideas are not wasted: outages and crashes give them back.

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import competitors, genre_topics, verified_facts

CHANNEL = SimpleNamespace(id="ocean", competitors=("x",), builtin=False, genre="deep ocean")


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


class CompetitorIdeasTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for patch in (mock.patch.object(competitors, "settings", SimpleNamespace(db_path=self.dir / "b.sqlite3")),
                      mock.patch.object(competitors, "refresh", lambda ch, force=False: [])):
            patch.start()
            self.addCleanup(patch.stop)

    def _add(self, vid, ratio, used_at=None, our_title=None, published_hours=24):
        conn = competitors._conn()
        conn.execute("""INSERT INTO competitor_videos (channel, video_id, competitor_id, competitor_name, title,
                        views, published_at, short, ratio, fetched_at, used_at, our_title)
                        VALUES ('ocean', ?, 'c', 'MBARI', ?, 1000, ?, 1, ?, ?, ?, ?)""",
                     (vid, f"title {vid}", ago(published_hours), ratio, ago(1), used_at, our_title))
        conn.commit()
        conn.close()

    def _row(self, vid):
        conn = competitors._conn()
        try:
            return tuple(conn.execute("SELECT used_at, our_title FROM competitor_videos WHERE video_id = ?",
                                      (vid,)).fetchone())
        finally:
            conn.close()

    def test_stale_reservation_comes_back_fresh_one_stays(self):
        self._add("old", 50.0, used_at=ago(7))
        self._add("new", 40.0, used_at=ago(1))
        idea = competitors.next_idea(CHANNEL, "short")
        self.assertEqual(idea["video_id"], "old")
        self.assertIsNotNone(self._row("new")[0])

    def test_outage_marked_did_not_fit_before_the_fix_comes_back(self):
        self._add("barreleye", 50.7, used_at="2026-11-05T14:02:00+00:00", our_title=competitors.DID_NOT_FIT)
        self.assertEqual(competitors.next_idea(CHANNEL, "short")["video_id"], "barreleye")

    def test_a_real_did_not_fit_stays_closed(self):
        self._add("food", 9.0, used_at=max(ago(0), "2026-11-05T17:30:00+00:00"), our_title=competitors.DID_NOT_FIT)
        self.assertIsNone(competitors.next_idea(CHANNEL, "short"))

    def _write_short(self, behaviour):
        def write(channel, scenes, long_form, inspiration_title=None, outcome=None, **kw):
            return behaviour(outcome)

        with mock.patch.object(verified_facts, "is_verified_channel", lambda ch: True), \
                mock.patch.object(verified_facts, "write_next_lesson", write):
            return genre_topics._generate_one(CHANNEL, [])

    def test_ai_outage_gives_the_idea_back(self):
        self._add("v1", 20.0)

        def failed(outcome):
            outcome["failed"] = "HTTP Error 503"
            return "k", {"title": "Our own fallback subject"}

        self._write_short(failed)
        self.assertEqual(self._row("v1"), (None, None))

    def test_no_script_at_all_gives_the_idea_back(self):
        self._add("v1", 20.0)

        def crash(outcome):
            raise RuntimeError("Script providers failed")

        with self.assertRaises(RuntimeError):
            self._write_short(crash)
        self.assertEqual(self._row("v1"), (None, None))

    def test_used_idea_records_our_title(self):
        self._add("v1", 20.0)

        def used(outcome):
            outcome["competitor"] = "title v1"
            return "k", {"title": "Barreleye: The Fish With a See-Through Head"}

        self._write_short(used)
        self.assertEqual(self._row("v1")[1], "Barreleye: The Fish With a See-Through Head")


if __name__ == "__main__":
    unittest.main()
