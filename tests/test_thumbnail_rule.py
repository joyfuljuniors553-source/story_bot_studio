"""No video goes to YouTube without a verified thumbnail (thumbnail_check + upload_video).

Run: python -m unittest discover -s tests
The YouTube client is a fake that records every API call; nothing reaches YouTube.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from src import youtube_upload

youtube_upload._real_can_update = youtube_upload.can_update  # setUp replaces it
from src.thumbnail_check import ThumbnailNotReady, check_thumbnail, ensure_ready


class _Call:
    def __init__(self, client, name, kwargs):
        self.client, self.name, self.kwargs = client, name, kwargs

    def execute(self):
        self.client.calls.append((self.name, self.kwargs))
        if self.name == "thumbnails.set" and self.client.fail_thumbnail:
            raise RuntimeError("thumbnail rejected")
        return {}

    def next_chunk(self):  # videos.insert is a resumable upload
        self.client.calls.append((self.name, self.kwargs))
        return None, {"id": "VID123"}


class _Resource:
    def __init__(self, client, kind):
        self.client, self.kind = client, kind

    def __getattr__(self, method):
        return lambda **kwargs: _Call(self.client, f"{self.kind}.{method}", kwargs)


class FakeYouTube:
    def __init__(self, fail_thumbnail=False):
        self.calls: list[tuple[str, dict]] = []
        self.fail_thumbnail = fail_thumbnail

    def videos(self):
        return _Resource(self, "videos")

    def thumbnails(self):
        return _Resource(self, "thumbnails")

    def names(self):
        return [name for name, _ in self.calls]


def _image(path: Path, width=1280, height=720, blank=False, quality=85) -> Path:
    if blank:
        picture = np.zeros((height, width, 3), np.uint8)
    else:
        rng = np.random.default_rng(1)
        picture = (rng.random((height, width, 3)) * 255).astype(np.uint8)
    cv2.imwrite(str(path), picture, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return path


CHANNEL = SimpleNamespace(client_secret_path=Path("cs.json"), token_path=Path("tok.json"),
                          category_id="28", made_for_kids=False, privacy="public")
META = {"title": "Test", "description": "d", "tags": []}


class ThumbnailRuleTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.good = _image(self.dir / "good.jpg")
        self.video = self.dir / "video.mp4"
        self.video.write_bytes(b"0")
        self.yt = FakeYouTube()
        patches = [
            mock.patch.object(youtube_upload, "_youtube", lambda *a, **k: self.yt),
            mock.patch.object(youtube_upload, "MediaFileUpload", lambda *a, **k: object()),
            mock.patch.object(youtube_upload.time, "sleep", lambda s: None),
            mock.patch.dict(os.environ, {"REQUIRE_THUMBNAIL": "true"}),
            # A login with the permission to change a video after upload.
            mock.patch.object(youtube_upload, "can_update", lambda token=None: True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _upload(self, thumb, **kwargs):
        return youtube_upload.upload_video(self.video, thumb, META, channel=CHANNEL, **kwargs)

    # ---------------------------------------------------------------- checks

    def test_check_passes_and_fails(self):
        self.assertTrue(check_thumbnail(self.good).ok)
        self.assertTrue(check_thumbnail(_image(self.dir / "tall.jpg", 1080, 1920)).ok)
        self.assertFalse(check_thumbnail(_image(self.dir / "small.jpg", 640, 360)).ok)
        self.assertFalse(check_thumbnail(_image(self.dir / "black.jpg", blank=True)).ok)
        self.assertFalse(check_thumbnail(_image(self.dir / "square.jpg", 1280, 1280)).ok)
        self.assertFalse(check_thumbnail(self.dir / "missing.jpg").ok)

    def test_ensure_ready_remakes_once(self):
        bad = _image(self.dir / "bad.jpg", blank=True)
        self.assertEqual(ensure_ready(bad, regenerate=lambda: self.good), self.good)
        with self.assertRaises(ThumbnailNotReady):
            ensure_ready(bad, regenerate=lambda: bad)
        with self.assertRaises(ThumbnailNotReady):
            ensure_ready(bad)

    def test_oversize_is_recompressed(self):
        # Full noise at quality 100 is ~2.8 MB; re-saved at quality 90 it fits.
        big = _image(self.dir / "big.jpg", 1600, 900, quality=100)
        self.assertGreater(big.stat().st_size, 2 * 1024 * 1024)
        self.assertEqual(ensure_ready(big), big)
        self.assertLessEqual(big.stat().st_size, 2 * 1024 * 1024)

    # ---------------------------------------------------------------- upload

    def test_good_thumbnail_private_then_thumbnail_then_schedule(self):
        when = datetime.now(timezone.utc) + timedelta(days=1)
        url = self._upload(self.good, publish_at=when)
        self.assertTrue(url.endswith("VID123"))
        self.assertEqual(self.yt.names(), ["videos.insert", "thumbnails.set", "videos.update"])
        inserted = self.yt.calls[0][1]["body"]["status"]
        self.assertEqual(inserted["privacyStatus"], "private")
        self.assertNotIn("publishAt", inserted)
        final = self.yt.calls[2][1]["body"]["status"]
        self.assertEqual(final["privacyStatus"], "private")
        self.assertIn("publishAt", final)

    def test_good_thumbnail_without_schedule_goes_public(self):
        self._upload(self.good)
        self.assertEqual(self.yt.names(), ["videos.insert", "thumbnails.set", "videos.update"])
        self.assertEqual(self.yt.calls[2][1]["body"]["status"]["privacyStatus"], "public")

    def test_bad_thumbnail_makes_no_api_call(self):
        with self.assertRaises(ThumbnailNotReady):
            self._upload(_image(self.dir / "black.jpg", blank=True))
        self.assertEqual(self.yt.calls, [])

    def test_no_thumbnail_permission_makes_no_api_call(self):
        with self.assertRaises(ThumbnailNotReady):
            self._upload(self.good, upload_thumbnail=False)
        self.assertEqual(self.yt.calls, [])

    def test_thumbnail_failure_keeps_video_private(self):
        self.yt.fail_thumbnail = True
        with self.assertRaises(youtube_upload.ThumbnailUploadError) as caught:
            self._upload(self.good)
        self.assertIn("kept private", str(caught.exception))
        self.assertNotIn("videos.update", self.yt.names())
        self.assertEqual(self.yt.calls[0][1]["body"]["status"]["privacyStatus"], "private")

    def test_release_later_or_now(self):
        later = datetime.now(timezone.utc) + timedelta(hours=5)
        self.assertEqual(youtube_upload.release_video(
            "https://www.youtube.com/watch?v=VID123", CHANNEL, later.isoformat()), later)
        status = self.yt.calls[-1][1]["body"]["status"]
        self.assertEqual(self.yt.calls[-1][1]["body"]["id"], "VID123")
        self.assertEqual(status["privacyStatus"], "private")
        self.assertIn("publishAt", status)

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertIsNone(youtube_upload.release_video("https://youtu.be/VID123", CHANNEL, past))
        status = self.yt.calls[-1][1]["body"]["status"]
        self.assertEqual(status["privacyStatus"], "public")
        self.assertNotIn("publishAt", status)

    def test_login_without_update_permission_uploads_scheduled(self):
        when = datetime.now(timezone.utc) + timedelta(days=1)
        with mock.patch.object(youtube_upload, "can_update", lambda token=None: False):
            self._upload(self.good, publish_at=when)
            with self.assertRaises(ThumbnailNotReady):  # the check before upload still holds
                self._upload(_image(self.dir / "black.jpg", blank=True))
            with self.assertRaises(RuntimeError):  # a held video cannot be released
                youtube_upload.release_video("https://youtu.be/VID123", CHANNEL, when)
        self.assertEqual(self.yt.names(), ["videos.insert", "thumbnails.set"])
        status = self.yt.calls[0][1]["body"]["status"]
        self.assertEqual(status["privacyStatus"], "private")
        self.assertIn("publishAt", status)  # scheduled straight away, never stuck private

    def test_can_update_reads_the_login_scopes(self):
        import json
        token = self.dir / "token.json"
        token.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/youtube.upload"]}))
        with mock.patch.object(youtube_upload, "can_update", youtube_upload.__dict__["_real_can_update"]):
            self.assertFalse(youtube_upload.can_update(token))
            token.write_text(json.dumps({"scopes": [youtube_upload.UPDATE_SCOPE]}))
            self.assertTrue(youtube_upload.can_update(token))
            self.assertFalse(youtube_upload.can_update(self.dir / "missing.json"))

    def test_switch_off_restores_old_behaviour(self):
        with mock.patch.dict(os.environ, {"REQUIRE_THUMBNAIL": "false"}):
            self._upload(_image(self.dir / "black.jpg", blank=True))
        self.assertEqual(self.yt.names(), ["videos.insert", "thumbnails.set"])
        self.assertEqual(self.yt.calls[0][1]["body"]["status"]["privacyStatus"], "public")


if __name__ == "__main__":
    unittest.main()
