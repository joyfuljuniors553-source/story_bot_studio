"""Style check of designed thumbnails against the channel's own examples (style_match.py).

Run: python -m unittest discover -s tests -t .
Cards are drawn by the real composer (future_thumbnail.compose_long) with no AI
and no photo, into a temporary brand folder.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import brand, future_thumbnail
from src.style_match import compare

PLAN = {"top": "LIFE IN", "big": "2050", "sub": "A realistic look at *possible tomorrows*",
        "labels": ["BIOTECH", "AI"], "visual": ""}
CHANNEL = SimpleNamespace(id="styletest", brand="TESTCO", name="Test Co")


class StyleMatchTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

        def brand_dir(channel_id):
            path = self.dir / str(channel_id)
            path.mkdir(parents=True, exist_ok=True)
            return path

        patch = mock.patch.object(brand, "brand_dir", brand_dir)
        patch.start()
        self.addCleanup(patch.stop)

    def _card(self, name, **changes) -> Path:
        spec = copy.deepcopy(future_thumbnail.SPEC["long"]) | changes
        return future_thumbnail.compose_long(PLAN, None, self.dir / name, CHANNEL, spec)

    def _example(self):
        folder = brand.brand_dir(CHANNEL.id) / "examples"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(self._card("example.jpg"), folder / "example.jpg")

    def test_no_examples_passes_without_a_score(self):
        check = compare(self._card("card.jpg"), CHANNEL.id)
        self.assertTrue(check["ok"])
        self.assertIsNone(check["score"])

    def test_card_like_the_examples_passes(self):
        self._example()
        check = compare(self._card("card.jpg"), CHANNEL.id)
        self.assertTrue(check["ok"], check["issues"])
        self.assertGreaterEqual(check["score"], 90)

    def test_small_headline_and_thin_bar_fail_with_reasons(self):
        self._example()
        check = compare(self._card("small.jpg", top_size=80, big_size=100, bar_pad=8, bar_min_w=380),
                        CHANNEL.id)
        self.assertFalse(check["ok"])
        self.assertTrue(any("smaller" in issue for issue in check["issues"]), check["issues"])
        self.assertLess(check["score"], 75)

    def test_composer_corrects_toward_the_examples(self):
        self._example()
        first = compare(self._card("small.jpg", top_size=95, big_size=120, bar_pad=12), CHANNEL.id)
        small = copy.deepcopy(future_thumbnail.SPEC)
        small["long"].update(top_size=95, big_size=120, bar_pad=12)
        out = self.dir / "fixed.jpg"
        with mock.patch.object(future_thumbnail, "SPEC", small):
            future_thumbnail._compose_checked(future_thumbnail.compose_long, PLAN, None, out, CHANNEL, "long")
        saved = json.loads(out.with_suffix(".style.json").read_text(encoding="utf-8"))
        self.assertTrue(out.is_file())
        self.assertGreater(saved["score"], first["score"])


if __name__ == "__main__":
    unittest.main()
