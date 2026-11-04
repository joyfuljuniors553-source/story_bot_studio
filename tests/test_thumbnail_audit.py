"""The daily YouTube thumbnail audit (thumbnail_audit.py) with a mocked thumbnails.set.

Run: python -m unittest discover -s tests -t .
Nothing reaches YouTube: the channel list, the pictures and thumbnails.set are fakes.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src import pending_uploads, thumbnail_audit, youtube_accounts
from src import channels as channels_module
from src import youtube_upload


REAL_STATE = thumbnail_audit.thumbnail_state  # setUp replaces it with a fake


def _video(n, short=False):
    return {"id": f"vid{n:02d}", "title": f"Video {n}", "privacy": "public", "publish_at": None, "short": short}


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.states: dict[str, str] = {}
        self.videos: list[dict] = []
        self.set_calls: list[str] = []
        self.set_error: str | None = None
        self.allowed = True
        thumb = self.dir / "card.jpg"
        thumb.write_bytes(b"x")
        channel = SimpleNamespace(id="space", client_secret_path=Path("cs"), token_path=Path("tok"))

        def fake_set(video_id, path, **kwargs):
            if self.set_error:
                raise RuntimeError(self.set_error)
            self.set_calls.append(video_id)

        patches = [
            mock.patch.object(thumbnail_audit, "settings",
                              SimpleNamespace(db_path=self.dir / "bot.sqlite3", root=self.dir)),
            mock.patch.object(channels_module, "load_channels", lambda: [SimpleNamespace(id="space")]),
            mock.patch.object(youtube_accounts, "connected_accounts", lambda cid: [SimpleNamespace(id="main")]),
            mock.patch.object(youtube_accounts, "channel_for_account", lambda cid, aid: channel),
            mock.patch.object(thumbnail_audit, "recent_uploads", lambda ch, days: self.videos),
            mock.patch.object(thumbnail_audit, "thumbnail_state", lambda vid: self.states.get(vid, "custom")),
            mock.patch.object(thumbnail_audit, "thumbnail_for", lambda ch, video: thumb),
            mock.patch.object(youtube_upload, "set_thumbnail", fake_set),
            mock.patch.object(pending_uploads, "thumbnail_upload_allowed", lambda cid: self.allowed),
            mock.patch.object(pending_uploads, "disable_thumbnail_upload", lambda cid: setattr(self, "allowed", False)),
            mock.patch.object(pending_uploads, "enable_thumbnail_upload", lambda cid: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _row(self, video_id):
        conn = sqlite3.connect(thumbnail_audit.settings.db_path)
        try:
            return conn.execute("SELECT state, tries, note FROM thumbnail_audit WHERE video_id = ?",
                                (video_id,)).fetchone()
        finally:
            conn.close()

    # ---------------------------------------------------------------- detection

    def test_detection_by_picture_difference(self):
        frame = np.full((36, 48), 100.0)
        custom = np.full((36, 48), 160.0)
        with mock.patch.object(thumbnail_audit, "_picture",
                               lambda vid, name: frame if name != "hqdefault" else frame + 2):
            self.assertEqual(REAL_STATE("a"), "missing")
        with mock.patch.object(thumbnail_audit, "_picture",
                               lambda vid, name: custom if name == "hqdefault" else frame):
            self.assertEqual(REAL_STATE("a"), "custom")
        with mock.patch.object(thumbnail_audit, "_picture", lambda vid, name: None):
            self.assertEqual(REAL_STATE("a"), "unknown")

    # ---------------------------------------------------------------- fixing

    def test_custom_and_unknown_are_never_touched(self):
        self.videos = [_video(1), _video(2, short=True)]
        self.states = {"vid01": "custom", "vid02": "unknown"}
        thumbnail_audit.audit()
        self.assertEqual(self.set_calls, [])
        self.assertEqual(self._row("vid01")[0], "custom")
        self.assertEqual(self._row("vid02")[0], "unknown")

    def test_missing_is_set_once_then_waits_12_hours(self):
        self.videos = [_video(1)]
        self.states = {"vid01": "missing"}
        thumbnail_audit.audit()
        self.assertEqual(self.set_calls, ["vid01"])
        self.assertEqual(self._row("vid01")[:2], ("fixed", 1))
        thumbnail_audit.audit()  # YouTube still shows its own frame (cache lag)
        self.assertEqual(self.set_calls, ["vid01"])
        self.assertEqual(self._row("vid01")[0], "fix_waiting")

    def test_check_only_sets_nothing(self):
        self.videos = [_video(1)]
        self.states = {"vid01": "missing"}
        thumbnail_audit.audit(fix=False)
        self.assertEqual(self.set_calls, [])
        self.assertEqual(self._row("vid01")[0], "missing")

    def test_gives_up_after_five_tries(self):
        self.videos = [_video(1)]
        self.states = {"vid01": "missing"}
        old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn = thumbnail_audit._conn()
        conn.execute("INSERT INTO thumbnail_audit VALUES ('vid01','space','Video 1','missing',?,?,5,'')",
                     (old, old))
        conn.commit()
        conn.close()
        thumbnail_audit.audit()
        self.assertEqual(self.set_calls, [])
        self.assertIn("gave up", self._row("vid01")[2])

    def test_at_most_ten_fixes_per_channel_per_run(self):
        self.videos = [_video(n) for n in range(14)]
        self.states = {v["id"]: "missing" for v in self.videos}
        thumbnail_audit.audit()
        self.assertEqual(len(self.set_calls), 10)

    def test_permission_error_stops_the_channel(self):
        self.videos = [_video(1), _video(2)]
        self.states = {"vid01": "missing", "vid02": "missing"}
        self.set_error = "The user doesn't have permissions to upload and set custom video thumbnails"
        messages = thumbnail_audit.audit()
        self.assertEqual(self._row("vid01")[0], "fix_failed")
        self.assertIsNone(self._row("vid02"))  # never reached
        self.assertFalse(self.allowed)
        self.assertTrue(any("FAILED" in m for m in messages))

    def test_rate_limit_stops_the_channel(self):
        self.videos = [_video(1), _video(2)]
        self.states = {"vid01": "missing", "vid02": "missing"}
        self.set_error = "uploadRateLimitExceeded"
        thumbnail_audit.audit()
        self.assertIsNone(self._row("vid02"))

    def test_unverified_channel_is_not_fixed(self):
        self.allowed = False
        self.videos = [_video(1)]
        self.states = {"vid01": "missing"}
        thumbnail_audit.audit()
        self.assertEqual(self.set_calls, [])
        self.assertIn("verify", self._row("vid01")[2])


if __name__ == "__main__":
    unittest.main()
