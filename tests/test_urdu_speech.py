"""Urdu narration made ready for the ur-PK voice (urdu_speech.prepare).

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest

from src.urdu_speech import number_words, prepare, year_words


class UrduSpeechTest(unittest.TestCase):
    def test_numbers_in_words(self):
        self.assertEqual(number_words(0), "صفر")
        self.assertEqual(number_words(47), "سینتالیس")
        self.assertEqual(number_words(125), "ایک سو پچیس")
        self.assertEqual(number_words(1_500_000), "پندرہ لاکھ")
        self.assertEqual(number_words(24_000_000), "دو کروڑ چالیس لاکھ")

    def test_years_said_the_spoken_way(self):
        self.assertEqual(year_words(1947), "انیس سو سینتالیس")
        self.assertEqual(year_words(1900), "انیس سو")
        self.assertEqual(year_words(2026), "دو ہزار چھبیس")

    def test_prepare(self):
        self.assertEqual(prepare("پاکستان 1947 میں بنا."), "پاکستان انیس سو سینتالیس میں بنا۔")
        self.assertEqual(prepare("۱۹۴۷ء میں"), "انیس سو سینتالیس میں")
        self.assertEqual(prepare("35% لوگ, جوان ہیں?"), "پینتیس فیصد لوگ، جوان ہیں؟")
        self.assertEqual(prepare("قیمت 3.5 لاکھ"), "قیمت تین اعشاریہ پانچ لاکھ")
        self.assertEqual(prepare("آبادی 24,000,000 ہے"), "آبادی دو کروڑ چالیس لاکھ ہے")

    def test_pronunciation_list_whole_words_only(self):
        self.assertEqual(prepare("NASA اور AI"), "ناسا اور اے آئی")
        self.assertEqual(prepare("NASAS"), "NASAS")  # not part of a longer word


if __name__ == "__main__":
    unittest.main()
