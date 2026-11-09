"""A thumbnail refusal expires, and held uploads go back to the queue.

Run: python -m unittest discover -s tests
DimeHorizon was refused once on 3 Nov and every later Short stayed held at
'uploading' for good. Nothing here reaches YouTube.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import pending_uploads


class _Temp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.flag = self.dir / "thumbnail_disabled_channels.json"
        self.db = self.dir / "bot.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE videos (id INTEGER PRIMARY KEY, channel TEXT, status TEXT, error TEXT,
                        video_url TEXT, upload_date TEXT, upload_progress INTEGER, is_daily INTEGER)""")
        conn.commit()
        conn.close()
        self.patches = [
            mock.patch.object(pending_uploads, "_THUMBNAIL_DISABLED_PATH", self.flag),
            mock.patch.object(pending_uploads, "_THUMBNAIL_REENABLED_PATH", self.dir / "re.json"),
            mock.patch.object(pending_uploads, "settings", SimpleNamespace(db_path=self.db, root=self.dir)),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()


class RefusalExpires(_Temp):
    def test_old_list_format_is_retested_at_once(self):
        self.flag.write_text(json.dumps(["dime_horizon"]), encoding="utf-8")
        self.assertTrue(pending_uploads.thumbnail_upload_allowed("dime_horizon"))
        self.assertTrue(pending_uploads.thumbnail_marked_disabled("dime_horizon"))

    def test_fresh_refusal_holds_then_expires(self):
        pending_uploads.disable_thumbnail_upload("dime_horizon")
        self.assertFalse(pending_uploads.thumbnail_upload_allowed("dime_horizon"))
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.flag.write_text(json.dumps({"dime_horizon": old}), encoding="utf-8")
        self.assertTrue(pending_uploads.thumbnail_upload_allowed("dime_horizon"))

    def test_enable_clears_the_flag(self):
        pending_uploads.disable_thumbnail_upload("dime_horizon")
        pending_uploads.enable_thumbnail_upload("dime_horizon")
        self.assertFalse(pending_uploads.thumbnail_marked_disabled("dime_horizon"))
        self.assertTrue(pending_uploads.thumbnail_upload_allowed("dime_horizon"))

    def test_old_permission_error_stops_counting(self):
        conn = sqlite3.connect(self.db)
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        conn.execute("INSERT INTO videos (channel, error, upload_date) VALUES (?, ?, ?)",
                     ("dime_horizon", "The authenticated user doesn't have permissions to upload and set "
                                      "custom video thumbnails", old))
        conn.commit()
        conn.close()
        self.assertTrue(pending_uploads.thumbnail_upload_allowed("dime_horizon"))


class HeldGoBack(_Temp):
    def test_stuck_uploading_rows_are_requeued(self):
        conn = sqlite3.connect(self.db)
        conn.executemany("INSERT INTO videos (id, channel, status, error, is_daily) VALUES (?, ?, ?, ?, ?)", [
            (1, "dime_horizon", "uploading", "Held: YouTube does not allow custom thumbnails", 1),
            (2, "dime_horizon", "uploading", "Held: thumbnail failed its check", 0),
            (3, "dime_horizon", "uploading", None, 0),  # a real upload in progress
        ])
        conn.commit()
        conn.close()
        self.assertEqual(pending_uploads.requeue_held_uploads(), 2)
        conn = sqlite3.connect(self.db)
        rows = dict(conn.execute("SELECT id, status FROM videos").fetchall())
        conn.close()
        self.assertEqual(rows, {1: "daily_upload_pending", 2: "rendered", 3: "uploading"})


if __name__ == "__main__":
    unittest.main()
