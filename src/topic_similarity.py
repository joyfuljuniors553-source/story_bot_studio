"""Is a new video's subject one this channel already covered?

Titles are compared by their subject words: the words left after dropping
filler ("How", "Explained", "Unveiling", "Quietly") and the words that run
through most of the channel's titles ("financial" on a money channel), with
plurals and -ing folded. Two titles sharing at least two subject words that
make up half or more of the shorter one are the same subject:

    "How Net Worth Quietly Measures Financial Strength"
    "Understanding Your Net Worth and Wealth"            -> same (net, worth)

DimeHorizon put out net worth and credit scores three times each and Veylora
Earth the fossil record three times in a week; the scene-label check in
daily_runner never saw it, because each script was written in new words.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .config import settings

WINDOW_DAYS = 45

_FILLER = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for", "from", "with", "into",
    "over", "under", "about", "as", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "you", "your", "our", "we", "they", "their", "his", "her", "he", "she", "them",
    "how", "why", "what", "when", "where", "who", "which", "can", "could", "will", "would", "did", "does",
    "do", "has", "have", "had", "than", "then", "more", "most", "very", "really", "just", "all", "any",
    "explained", "explain", "explaining", "understanding", "understand", "unveiling", "unveil", "revealed",
    "reveal", "secret", "secrets", "secretly", "quietly", "mystery", "mysteries", "truth", "untold", "story",
    "stories", "life", "became", "become", "becomes", "behind", "inside", "really", "actually", "ever",
    "true", "real", "facts", "fact", "everything", "know", "need", "guide", "simple", "simply", "way",
    "ways", "work", "works", "make", "makes", "made", "one", "new", "big", "great", "shape", "shapes",
    "define", "defines", "matter", "matters", "really", "here", "there", "s",
}


def _fold(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(title: object) -> set[str]:
    text = str(title or "").split(" | ")[0].lower()
    return {_fold(w) for w in re.findall(r"[a-z0-9]+", text) if w not in _FILLER and (len(w) > 2 or w.isdigit())}


def common_words(titles: list[str], share: float = 0.25) -> set[str]:
    """Words in more than `share` of the titles: the channel's own vocabulary, not a subject."""
    if len(titles) < 8:
        return set()
    counts: dict[str, int] = {}
    for title in titles:
        for word in _words(title):
            counts[word] = counts.get(word, 0) + 1
    return {word for word, n in counts.items() if n / len(titles) > share}


def subject(title: object, common: set[str] = frozenset()) -> set[str]:
    return _words(title) - set(common)


def same_subject(left: object, right: object, common: set[str] = frozenset()) -> bool:
    a, b = subject(left, common), subject(right, common)
    if not a or not b:
        return False
    if a == b:
        return True
    shared = a & b
    return len(shared) >= 2 and len(shared) / min(len(a), len(b)) >= 0.5


def recent_titles(channel, days: int = WINDOW_DAYS, youtube: bool = True) -> list[str]:
    """This channel's titles of the last `days` days: the database's and YouTube's own."""
    titles: list[str] = []
    if settings.db_path.exists():
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(settings.db_path)
        try:
            titles += [str(row[0]) for row in conn.execute(
                """SELECT title FROM videos
                   WHERE channel = ? AND created_at >= ? AND title IS NOT NULL
                     AND status NOT IN ('quality_failed', 'duplicate_blocked', 'files_lost')""",
                (channel.id, since)).fetchall()]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
    if youtube and getattr(channel, "token_path", None) is not None and channel.token_path.exists():
        from .pending_uploads import youtube_titles

        titles += list(youtube_titles(channel))  # normalized titles; their words are what counts
    return titles


def covered_by(title: object, titles: list[str]) -> str | None:
    """The earlier title with the same subject as `title`, if any."""
    common = common_words(titles)
    for other in titles:
        if same_subject(title, other, common):
            return other
    return None
