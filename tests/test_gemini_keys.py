"""Second Gemini key: used when the first key's quota is full, not when Gemini is busy.

Run: python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from src import genre_topics


def fake_settings(**extra):
    base = dict(gemini_api_key="k1", gemini_api_key_2="k2", gemini_model="m1",
                gemini_fallback_model="m2", groq_api_key="", enable_pollinations_text=False,
                openai_api_key="")
    base.update(extra)
    return SimpleNamespace(**base)


class GeminiKeysTest(unittest.TestCase):
    def _run(self, fail):
        calls = []

        def gemini(prompt, model=None, key=None):
            calls.append((key, model))
            reason = fail(key)
            if reason:
                raise RuntimeError(reason)
            return {"ok": key}

        with mock.patch.object(genre_topics, "settings", fake_settings()), \
                mock.patch.object(genre_topics, "_gemini", gemini):
            try:
                return genre_topics._script_json("x"), calls
            except RuntimeError as exc:
                return str(exc), calls

    def test_second_key_after_quota_is_full(self):
        result, calls = self._run(lambda key: "HTTP Error 429: Too Many Requests" if key == "k1" else None)
        self.assertEqual(result, {"ok": "k2"})
        self.assertEqual(calls, [("k1", "m1"), ("k1", "m2"), ("k2", "m1")])

    def test_second_key_skipped_when_gemini_is_busy(self):
        result, calls = self._run(lambda key: "HTTP Error 503: Service Unavailable")
        self.assertIn("Script providers failed", result)
        self.assertEqual([k for k, _ in calls], ["k1", "k1"])

    def test_first_key_answers(self):
        result, calls = self._run(lambda key: None)
        self.assertEqual(result, {"ok": "k1"})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
