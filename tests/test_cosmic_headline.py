"""Quasorynth headline: a question title must stay a question in the title's own words.

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from unittest import mock

from src import cosmic_thumbnail, genre_topics


class CosmicHeadlineTest(unittest.TestCase):
    def _plan(self, title, answer):
        with mock.patch.object(genre_topics, "_script_json", lambda prompt: answer):
            return cosmic_thumbnail.plan_for(title)

    def test_question_turned_into_a_claim_is_replaced_by_the_title(self):
        plan = self._plan("What If a Magnetar Hit Earth?",
                          {"white": "MAGNETAR STRIKE:", "gold": "EARTH VAPORIZED", "scene": "magnetar"})
        self.assertEqual((plan["white"], plan["gold"]), ("WHAT IF A", "MAGNETAR HIT EARTH?"))

    def test_question_in_the_titles_words_is_kept(self):
        plan = self._plan("Black Holes: Gates of Time?",
                          {"white": "BLACK HOLES:", "gold": "GATES OF TIME?", "scene": "black hole"})
        self.assertEqual((plan["white"], plan["gold"]), ("BLACK HOLES:", "GATES OF TIME?"))

    def test_statement_title_may_be_reworded(self):
        plan = self._plan("The Biggest Star Ever Found",
                          {"white": "THE BIGGEST", "gold": "STAR IN THE COSMOS", "scene": "red hypergiant"})
        self.assertEqual(plan["gold"], "STAR IN THE COSMOS")

    def test_no_ai_answer_splits_the_title(self):
        plan = self._plan("Do Galaxies Have an End?", {})
        self.assertEqual((plan["white"], plan["gold"]), ("DO GALAXIES", "HAVE AN END?"))


if __name__ == "__main__":
    unittest.main()
