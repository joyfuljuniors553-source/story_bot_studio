"""Competitor ideas on fact-checked channels: only the subject is taken (verified_facts).

Run: python -m unittest discover -s tests -t .
The AI, Wikipedia and the script writer are fakes.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from src import genre_topics, verified_facts
from src.competitors import too_similar

CHANNEL = SimpleNamespace(id="space", genre="space documentaries", topic="space science",
                          thumbnail_style="space", builtin=False)


def _article(title):
    return SimpleNamespace(title=title, url="https://en.wikipedia.org/wiki/" + title, text="")


class CompetitorSubjectTest(unittest.TestCase):
    def setUp(self):
        self.ai_answer = {"wikipedia": "TON 618"}
        self.used: set[str] = set()
        self.written: list[str] = []
        self.title = "TON 618: The Monster Quasar"

        def write_lesson(channel, article, scenes, long_form):
            self.written.append(article.title)
            return "key", {"title": self.title if article.title == "TON 618" else article.title,
                           "source_title": article.title}

        patches = [
            mock.patch.object(genre_topics, "_script_json", lambda prompt: self.ai_answer),
            mock.patch.object(verified_facts, "fetch_article", lambda name, *a: _article(name)),
            mock.patch.object(verified_facts, "_used_subjects", lambda ch, lf: self.used),
            mock.patch.object(verified_facts, "write_lesson", write_lesson),
            mock.patch.object(verified_facts, "next_article", lambda ch, lf: _article("Sirius")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_their_subject_is_written_from_its_article(self):
        outcome = {}
        _, lesson = verified_facts.write_next_lesson(
            CHANNEL, 8, False, inspiration_title="What TON 618 Would Look Like at Different Distances",
            outcome=outcome)
        self.assertEqual(self.written, ["TON 618"])
        self.assertEqual(lesson["title"], "TON 618: The Monster Quasar")
        self.assertIn("competitor", outcome)

    def test_brief_in_the_daily_long_prompt_is_understood(self):
        prompt = ("Create a complete, original space documentaries documentary for today.\n"
                  'TOPIC INSPIRATION: another channel has a video titled "What TON 618 Would Look '
                  'Like at Different Distances" that is getting 4.7x its usual views')
        verified_facts.write_next_lesson(CHANNEL, 70, True, user_prompt=prompt)
        self.assertEqual(self.written, ["TON 618"])

    def test_a_title_like_theirs_is_replaced(self):
        self.title = "What TON 618 Would Look Like Up Close"
        theirs = "What TON 618 Would Look Like at Different Distances"
        self.assertTrue(too_similar(self.title, theirs))
        _, lesson = verified_facts.write_next_lesson(CHANNEL, 8, False, inspiration_title=theirs)
        self.assertEqual(lesson["title"], "TON 618 Explained")

    def test_covered_subject_falls_back_to_the_list(self):
        self.used = {"ton 618"}
        outcome = {}
        _, lesson = verified_facts.write_next_lesson(CHANNEL, 8, False, inspiration_title="TON 618 again",
                                                     outcome=outcome)
        self.assertEqual(self.written, ["Sirius"])
        self.assertEqual(outcome, {})

    def test_subject_that_does_not_fit_falls_back_to_the_list(self):
        self.ai_answer = {"wikipedia": ""}
        _, lesson = verified_facts.write_next_lesson(CHANNEL, 8, False,
                                                     inspiration_title="Americans Are Delusional About Food")
        self.assertEqual(self.written, ["Sirius"])

    def test_similarity_rule(self):
        self.assertTrue(too_similar("Why Lucille Ball Is Not Buried Next to Desi",
                                    "Why Desi Arnaz & Lucille Ball Aren't Buried Next to Each Other"))
        self.assertFalse(too_similar("Lucille Ball: The True Story",
                                     "Why Desi Arnaz & Lucille Ball Aren't Buried Next to Each Other"))


if __name__ == "__main__":
    unittest.main()
