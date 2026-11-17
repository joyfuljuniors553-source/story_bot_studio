"""The bot's memory of the thumbnail it gave every video, and the check that YouTube shows it.

Every time a thumbnail is set on YouTube (youtube_upload.set_thumbnail) the
card is stored here with the video and its channel: a JPEG in the database,
which every GitHub run saves with its state. A private or scheduled video has
no public picture, so the check happens once the video is public: YouTube's
own picture is compared with the stored card.

    same card            -> verified; the stored picture is dropped (the database stays small)
    another picture      -> the stored card is set again, and checked again later
    not public yet       -> checked on a later run

This replaces guessing from YouTube's own frames: since every Short opens on
its thumbnail (video.add_cover_frame), YouTube's first frame looks like the
card, and the old check called five good thumbnails missing and set them
again five times each.

A card is only remembered for a video of the channel it was made for: the
database row of the video and the login that set it must name the same one.
"""
from __future__ import annotations

import io
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

RECHECK_AFTER = timedelta(hours=2)   # YouTube's picture cache can lag behind a fresh set
MAX_SETS = 4                         # stored card set again at most this often
KEEP_DAYS = 21                       # unverified rows (and their pictures) are dropped after this


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS thumb_memory (
        video_id TEXT PRIMARY KEY, channel TEXT NOT NULL, card BLOB, made_at TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'set', checked_at TEXT, set_at TEXT, sets INTEGER NOT NULL DEFAULT 1,
        note TEXT)""")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jpeg(card: Path) -> bytes:
    """The card small enough to keep (YouTube still takes it: at least 640 wide)."""
    from PIL import Image

    image = Image.open(card).convert("RGB")
    longest = 1280 if image.width >= image.height else 1280
    if max(image.size) > longest:
        image.thumbnail((longest, longest))
    if image.width < 640:
        image = image.resize((640, round(image.height * 640 / image.width)))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=86, optimize=True)
    return out.getvalue()


def channel_for_token(token_file: Path | None) -> str:
    """The channel whose login this is: 'token_veylora_earth.json' -> 'veylora_earth'."""
    from .channels import load_channels

    name = Path(str(token_file or "")).name
    best = ""
    for channel in load_channels():
        own = Path(str(channel.token)).name
        if name == own or name.startswith(f"token_{channel.id}"):
            if len(channel.id) > len(best):
                best = channel.id
    return best


def _video_channel(video_id: str) -> str:
    """The channel the bot's database says this video belongs to ('' when it is not the bot's)."""
    if not settings.db_path.exists():
        return ""
    conn = sqlite3.connect(settings.db_path)
    try:
        row = conn.execute("SELECT channel FROM videos WHERE video_url LIKE ? ORDER BY id DESC LIMIT 1",
                           (f"%{video_id}%",)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    return str(row[0]) if row else ""


def remember(video_id: str, card: Path, token_file: Path | None = None, channel_id: str = "") -> str:
    """Store the card just set on `video_id`. Returns '' or why it was not stored."""
    channel_id = channel_id or channel_for_token(token_file)
    owner = _video_channel(video_id)
    if owner and channel_id and owner != channel_id:
        note = f"card set with {channel_id}'s login on a video the database gives to {owner}; not remembered"
        print(f"[thumb-memory] {video_id}: {note}")
        return note
    channel_id = channel_id or owner
    if not channel_id:
        return "no channel known"
    try:
        data = _jpeg(card)
    except Exception as exc:
        return f"card could not be read ({exc})"
    with _conn() as conn:
        old = conn.execute("SELECT sets FROM thumb_memory WHERE video_id = ?", (video_id,)).fetchone()
        conn.execute(
            """INSERT INTO thumb_memory (video_id, channel, card, made_at, state, set_at, sets)
               VALUES (?, ?, ?, ?, 'set', ?, 1)
               ON CONFLICT(video_id) DO UPDATE SET card = excluded.card, channel = excluded.channel,
                   state = 'set', set_at = excluded.set_at, sets = thumb_memory.sets + 1, note = NULL""",
            (video_id, channel_id, data, _now(), _now()))
    return ""


def known(video_id: str) -> bool:
    with _conn() as conn:
        return conn.execute("SELECT 1 FROM thumb_memory WHERE video_id = ?", (video_id,)).fetchone() is not None


def _card_file(data: bytes, video_id: str) -> Path:
    path = Path(tempfile.gettempdir()) / f"thumb_memory_{video_id}.jpg"
    path.write_bytes(data)
    return path


def check(video_id: str, channel, fix: bool = True) -> tuple[str, str]:
    """('verified'|'fixed'|'waiting'|'not_public'|'gave_up'|'error'|'unknown_video', note) for one video."""
    from .pending_uploads import youtube_shows_card

    with _conn() as conn:
        row = conn.execute("SELECT channel, card, state, set_at, sets FROM thumb_memory WHERE video_id = ?",
                           (video_id,)).fetchone()
    if row is None:
        return "unknown_video", "not in memory"
    owner, card, state, set_at, sets = row
    if state == "verified":
        return "verified", "checked before"
    if owner != channel.id:
        return "error", f"remembered for {owner}, listed under {channel.id}; left alone"
    if not card:
        return "error", "no stored picture"
    path = _card_file(card, video_id)
    try:
        shows = youtube_shows_card(video_id, path)
        if shows is None:
            with _conn() as conn:
                conn.execute("UPDATE thumb_memory SET checked_at = ? WHERE video_id = ?", (_now(), video_id))
            return "not_public", "no public picture yet"
        if shows:
            with _conn() as conn:
                # The picture is not needed any more: keep the database small.
                conn.execute("UPDATE thumb_memory SET state = 'verified', checked_at = ?, card = NULL, note = NULL "
                             "WHERE video_id = ?", (_now(), video_id))
            return "verified", "YouTube shows our card"
        if set_at and datetime.now(timezone.utc) - datetime.fromisoformat(set_at) < RECHECK_AFTER:
            return "waiting", "set recently; YouTube may still show the old picture"
        if sets >= MAX_SETS:
            with _conn() as conn:
                conn.execute("UPDATE thumb_memory SET state = 'gave_up', checked_at = ?, note = ? WHERE video_id = ?",
                             (_now(), f"still another picture after {sets} sets", video_id))
            return "gave_up", f"still another picture after {sets} sets"
        if not fix:
            return "waiting", "another picture shown (check only)"
        from .youtube_upload import set_thumbnail

        set_thumbnail(video_id, path, attempts=2, client_secret_file=channel.client_secret_path,
                      token_file=channel.token_path, channel_id=channel.id)
        return "fixed", "another picture was shown; our stored card set again"
    except Exception as exc:
        with _conn() as conn:
            conn.execute("UPDATE thumb_memory SET checked_at = ?, note = ? WHERE video_id = ?",
                         (_now(), str(exc)[:300], video_id))
        return "error", str(exc)[:200]
    finally:
        path.unlink(missing_ok=True)


def prune() -> int:
    """Drop rows older than KEEP_DAYS days (their pictures with them)."""
    since = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    with _conn() as conn:
        return conn.execute("DELETE FROM thumb_memory WHERE made_at < ?", (since,)).rowcount or 0
