"""The bot remembers each thumbnail it set and checks YouTube shows it.

Run: python -m unittest discover -s tests
No network: YouTube's picture is faked.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from src import thumbnail_memory as memory

CHANNEL = SimpleNamespace(id="quasorynth_space", client_secret_path=Path("cs.json"), token_path=Path("t.json"))


class Memory(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "bot.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, channel TEXT, video_url TEXT)")
        conn.execute("INSERT INTO videos (channel, video_url) VALUES ('quasorynth_space', 'https://www.youtube.com/watch?v=VID1')")
        conn.commit()
        conn.close()
        self.card = self.dir / "card.jpg"
        Image.new("RGB", (1080, 1920), (40, 10, 90)).save(self.card)
        self.patch = mock.patch.object(memory, "settings", SimpleNamespace(db_path=self.db))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _row(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT state, card IS NOT NULL, sets FROM thumb_memory WHERE video_id='VID1'").fetchone()

    def test_card_of_another_channel_is_not_remembered(self):
        note = memory.remember("VID1", self.card, channel_id="veylora_earth")
        self.assertIn("not remembered", note)
        self.assertFalse(memory.known("VID1"))

    def test_shown_card_is_verified_and_its_picture_dropped(self):
        memory.remember("VID1", self.card, channel_id="quasorynth_space")
        with mock.patch("src.pending_uploads.youtube_shows_card", return_value=True):
            self.assertEqual(memory.check("VID1", CHANNEL)[0], "verified")
        self.assertEqual(self._row()[:2], ("verified", 0))

    def test_private_video_waits(self):
        memory.remember("VID1", self.card, channel_id="quasorynth_space")
        with mock.patch("src.pending_uploads.youtube_shows_card", return_value=None):
            self.assertEqual(memory.check("VID1", CHANNEL)[0], "not_public")

    def test_other_picture_gets_the_stored_card_again(self):
        memory.remember("VID1", self.card, channel_id="quasorynth_space")
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE thumb_memory SET set_at = '2026-01-01T00:00:00+00:00'")
        with mock.patch("src.pending_uploads.youtube_shows_card", return_value=False), \
                mock.patch("src.youtube_upload.set_thumbnail") as set_again:
            self.assertEqual(memory.check("VID1", CHANNEL)[0], "fixed")
        self.assertEqual(set_again.call_args.kwargs["channel_id"], "quasorynth_space")

    def test_listed_under_another_channel_is_left_alone(self):
        memory.remember("VID1", self.card, channel_id="quasorynth_space")
        other = SimpleNamespace(**{**vars(CHANNEL), "id": "veylora_earth"})
        with mock.patch("src.youtube_upload.set_thumbnail") as set_again:
            self.assertEqual(memory.check("VID1", other)[0], "error")
        set_again.assert_not_called()


if __name__ == "__main__":
    unittest.main()
