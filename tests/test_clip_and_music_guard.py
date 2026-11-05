"""Off-topic stock clips and dance music stay out of the space Shorts.

Run: python -m unittest discover -s tests
No network: Gemini and the clip sources are never called.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src import clip_sources, music_moods
from src.models import Scene
from src.stock_video import _relevant, has_people, off_topic_words

SPACE = SimpleNamespace(
    id="space_test", genre="space documentaries", tone="", name="Test", builtin=False,
    clip_subject="space and astronomy", clip_check_required=True,
    clip_off_topic=("hospital", "surgery", "operating", "medical"), music_mood="",
)


def _scene() -> Scene:
    return Scene(label="spectra", line="She obtained optical spectra at McDonald Observatory.",
                 image="x.jpg", image_prompt="observatory")


class PeopleWords(unittest.TestCase):
    def test_plurals_count_as_people(self):
        self.assertTrue(has_people({"doctors", "operating", "room"}))
        self.assertTrue(has_people({"surgeons"}))
        self.assertTrue(has_people({"nurses"}))
        self.assertFalse(has_people({"galaxy", "nebula", "telescope"}))

    def test_pexels_clip_of_doctors_rejected_without_people(self):
        video = {"url": "https://www.pexels.com/video/doctors-in-an-operating-room-123/"}
        self.assertFalse(_relevant(video, {"room"}, strict_people=True))


class OffTopic(unittest.TestCase):
    def tearDown(self):
        clip_sources.set_context()

    def test_channel_banned_settings(self):
        clip_sources.set_context(banned=off_topic_words(SPACE))
        self.assertTrue(clip_sources.off_topic({"hospital", "corridor"}))
        self.assertTrue(clip_sources.off_topic({"surgerys"}))
        self.assertFalse(clip_sources.off_topic({"observatory", "dome"}))

    def test_no_list_bans_nothing(self):
        clip_sources.set_context()
        self.assertFalse(clip_sources.off_topic({"hospital"}))


class FrameCheckOff(unittest.TestCase):
    """With Gemini unavailable, a strict channel refuses unchecked generic stock only."""

    def tearDown(self):
        clip_sources.set_context()

    def test_strict_channel(self):
        clip_sources.set_context(topic="space", strict=True)
        with mock.patch.object(clip_sources, "_checks_off", True):
            self.assertFalse(clip_sources.frame_matches(Path("c.mp4"), _scene(), generic=True))
            # NASA footage is on-topic by where it comes from.
            self.assertTrue(clip_sources.frame_matches(Path("c.mp4"), _scene(), generic=False))

    def test_other_channels_keep_failing_open(self):
        clip_sources.set_context()
        with mock.patch.object(clip_sources, "_checks_off", True):
            self.assertTrue(clip_sources.frame_matches(Path("c.mp4"), _scene(), generic=True))


class Music(unittest.TestCase):
    def test_space_channel_gets_ambient(self):
        with mock.patch("src.video.is_cinematic", return_value=False):
            self.assertEqual(music_moods.mood_for(SPACE), "ambient")

    def test_channel_mood_wins(self):
        channel = SimpleNamespace(**{**vars(SPACE), "genre": "celebrity", "music_mood": "epic"})
        with mock.patch("src.video.is_cinematic", return_value=False):
            self.assertEqual(music_moods.mood_for(channel), "epic")

    def test_dance_beat_kept_out_of_quiet_moods(self):
        track = Path("Friendly Dance.mp3")
        with mock.patch.object(music_moods, "beat_strength", return_value=0.59):
            self.assertFalse(music_moods.fits_mood(track, "ambient"))
            self.assertFalse(music_moods.fits_mood(track, "warm"))
            self.assertTrue(music_moods.fits_mood(track, "uplift"))
        with mock.patch.object(music_moods, "beat_strength", return_value=0.14):
            self.assertTrue(music_moods.fits_mood(track, "ambient"))

    def test_unmeasurable_track_is_kept(self):
        with mock.patch.object(music_moods, "beat_strength", return_value=None):
            self.assertTrue(music_moods.fits_mood(Path("x.mp3"), "ambient"))


if __name__ == "__main__":
    unittest.main()
