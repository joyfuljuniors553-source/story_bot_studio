"""A held video comes back from its own run's artifact with one download.

Run: python -m unittest discover -s tests
Every artifact from the newest backwards used to be downloaded whole for each
video; fifteen held Shorts kept a run busy for 5.5 hours. No network here.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src import github_artifacts


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


ARTIFACTS = [  # newest first, as GitHub lists them
    {"id": 3, "name": "videos-300", "created_at": "2026-11-10T15:00:00Z", "archive_download_url": "z3"},
    {"id": 2, "name": "videos-200", "created_at": "2026-11-09T02:40:00Z", "archive_download_url": "z2"},
    {"id": 1, "name": "videos-100", "created_at": "2026-11-08T20:00:00Z", "archive_download_url": "z1"},
]
ZIPS = {
    "z1": _zip({"runs/20261108_190000_1/video.mp4": b"old"}),
    "z2": _zip({"runs/20261109_012009_586822/video.mp4": b"mine",
                "runs/20261109_012009_586822/thumbnail.jpg": b"thumb"}),
    "z3": _zip({"runs/20261110_130000_9/video.mp4": b"new"}),
}


class Restore(unittest.TestCase):
    def setUp(self):
        github_artifacts._LISTING = None
        github_artifacts._BUNDLES.clear()
        self.calls: list[str] = []

        def fake(path: str) -> bytes:
            self.calls.append(path)
            if path.startswith("actions/artifacts"):
                return json.dumps({"artifacts": ARTIFACTS}).encode()
            return ZIPS[path]

        self.patches = [mock.patch.object(github_artifacts, "github", side_effect=fake),
                        mock.patch.object(github_artifacts, "available", return_value=True)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def test_only_the_runs_own_artifact_is_downloaded(self):
        run_dir = Path(tempfile.mkdtemp()) / "20261109_012009_586822"
        self.assertEqual(github_artifacts.restore_run_files(run_dir), ["video.mp4", "thumbnail.jpg"])
        self.assertEqual((run_dir / "video.mp4").read_bytes(), b"mine")
        self.assertEqual([c for c in self.calls if c.startswith("z")], ["z2"])

    def test_one_download_serves_every_video_of_that_run(self):
        base = Path(tempfile.mkdtemp())
        github_artifacts.restore_run_files(base / "20261109_012009_586822")
        github_artifacts.restore_run_files(base / "20261109_012009_586822")
        self.assertEqual([c for c in self.calls if c.startswith("z")], ["z2"])

    def test_expired_run_downloads_nothing(self):
        run_dir = Path(tempfile.mkdtemp()) / "20261101_100000_1"
        self.assertEqual(github_artifacts.restore_run_files(run_dir), [])
        self.assertEqual([c for c in self.calls if c.startswith("z")], [])


if __name__ == "__main__":
    unittest.main()
