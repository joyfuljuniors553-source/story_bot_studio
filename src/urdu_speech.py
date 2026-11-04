"""Urdu text made ready for the Urdu voice (ur-PK), the last step before speech.

The voice reads exactly what it is given, so a few things go wrong on their
own: digits are read oddly ("1947" is not said the way people say a year),
English punctuation gives no proper pauses, and some words are said wrong.
This module fixes those without touching what is shown on screen:

  - numbers become Urdu words (years the spoken way: انیس سو سینتالیس),
    percentages "فیصد", decimals "اعشاریہ";
  - the pronunciation list data/urdu_pronunciation.json swaps words the voice
    gets wrong for a spelling it says right (edit it any time; longest first);
  - . , ? ! become ۔ ، ؟ so the voice pauses where a speaker would.

The speaking rate for Urdu voices is set in tts.py (URDU_RATE).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import settings

PRONUNCIATION_FILE = settings.root / "data" / "urdu_pronunciation.json"

_ONES = (
    "صفر ایک دو تین چار پانچ چھ سات آٹھ نو دس گیارہ بارہ تیرہ چودہ پندرہ سولہ سترہ اٹھارہ انیس "
    "بیس اکیس بائیس تئیس چوبیس پچیس چھبیس ستائیس اٹھائیس انتیس تیس اکتیس بتیس تینتیس چونتیس "
    "پینتیس چھتیس سینتیس اڑتیس انتالیس چالیس اکتالیس بیالیس تینتالیس چوالیس پینتالیس چھیالیس "
    "سینتالیس اڑتالیس انچاس پچاس اکاون باون ترپن چون پچپن چھپن ستاون اٹھاون انسٹھ ساٹھ اکسٹھ "
    "باسٹھ تریسٹھ چونسٹھ پینسٹھ چھیاسٹھ سڑسٹھ اڑسٹھ انہتر ستر اکہتر بہتر تہتر چوہتر پچھتر چھہتر "
    "ستتر اٹھہتر اناسی اسی اکاسی بیاسی تراسی چوراسی پچاسی چھیاسی ستاسی اٹھاسی نواسی نوے اکانوے "
    "بانوے ترانوے چورانوے پچانوے چھیانوے ستانوے اٹھانوے ننانوے"
).split()
assert len(_ONES) == 100

_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def number_words(n: int) -> str:
    """0..999,999,999 in Urdu words, with the South Asian lakh and crore."""
    if n < 100:
        return _ONES[n]
    parts = []
    for size, name in ((10_000_000, "کروڑ"), (100_000, "لاکھ"), (1000, "ہزار"), (100, "سو")):
        if n >= size:
            parts.append(f"{number_words(n // size)} {name}")
            n %= size
    if n:
        parts.append(_ONES[n])
    return " ".join(parts)


def year_words(n: int) -> str:
    """A year the way it is said: 1947 -> انیس سو سینتالیس, 2026 -> دو ہزار چھبیس."""
    if 1100 <= n <= 1999:
        head, tail = divmod(n, 100)
        return f"{_ONES[head]} سو" + (f" {_ONES[tail]}" if tail else "")
    return number_words(n)


def _say_number(match: re.Match) -> str:
    return _say(match.group(0))


def _say(text: str) -> str:
    whole, _, frac = text.replace(",", "").partition(".")
    if not whole.isdigit():
        return text
    value = int(whole)
    if frac:
        return f"{number_words(value)} اعشاریہ {' '.join(_ONES[int(d)] for d in frac if d.isdigit())}"
    # A plain four-digit number between 1100 and 2099 is a year in a story.
    if "," not in text and len(whole) == 4 and 1100 <= value <= 2099:
        return year_words(value)
    if value >= 1_000_000_000:
        return text
    return number_words(value)


@lru_cache(maxsize=1)
def pronunciations() -> list[tuple[str, str]]:
    try:
        table = json.loads(PRONUNCIATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    pairs = [(str(k), str(v)) for k, v in (table.get("replace") or {}).items() if str(k).strip()]
    return sorted(pairs, key=lambda kv: -len(kv[0]))


def prepare(text: str) -> str:
    """The Urdu narration as the voice should read it."""
    text = " ".join(str(text or "").split())
    text = text.translate(_URDU_DIGITS)
    for wrong, right in pronunciations():
        # Whole words only, so a short entry never changes part of a longer word.
        text = re.sub(rf"(?<![\w؀-ۿ]){re.escape(wrong)}(?![\w؀-ۿ])", right, text)
    text = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s*%", lambda m: f"{_say(m.group(1))} فیصد", text)
    # "۱۹۴۷ء": the year sign is written, not said.
    text = re.sub(r"(\d[\d,]*)\s*ء", lambda m: _say(m.group(1)), text)
    text = re.sub(r"\d[\d,]*(?:\.\d+)?", _say_number, text)
    text = text.replace("?", "؟").replace(",", "،").replace(";", "؛")
    text = re.sub(r"\.(?=\s|$)", "۔", text)
    text = re.sub(r"\s+([،۔؟!])", r"\1", text)
    return text
