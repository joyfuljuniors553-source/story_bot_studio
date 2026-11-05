"""Do the competitors' topics work on OUR channel? (competitor topics vs our own)

For every uploaded video of a channel in the last `days` days that is already
public, views per day since it went public. Each video is either "own" (the
bot's own subject list) or came from a competitor's idea (competitors.py
records our title against their video). Per competitor: how many of our
videos came from it, their median views/day, and that median against the
median of our own videos.

  strong     >= 1.3x our own videos (keep it)
  similar    0.7x - 1.3x
  weak       <= 0.7x (replace it with another channel)
  too early  fewer than 2 of our videos so far

Run daily on GitHub after the uploads (views are read first, 1 quota unit
per 50 videos); the result is saved to data/competitor_report.json and shown
on the status page and the dashboard's Competitors card.
"""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
from datetime import datetime, timezone

from .config import settings

REPORT_FILE = settings.root / "data" / "competitor_report.json"
STRONG, WEAK, MIN_VIDEOS = 1.3, 0.7, 2


def _key(title: str | None) -> str:
    """A title without the ' | Channel' suffix, in one plain form for matching."""
    text = str(title or "").split(" | ")[0]
    text = text.translate({0x2010: "-", 0x2011: "-", 0x2013: "-", 0x2014: "-", 0x00A0: " "})
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def channel_report(conn: sqlite3.Connection, channel_id: str, days: int = 14,
                   now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    origin: dict[str, str] = {}
    try:
        for their_name, ours in conn.execute(
                "SELECT competitor_name, our_title FROM competitor_videos "
                "WHERE channel = ? AND our_title IS NOT NULL AND our_title NOT LIKE '(%'", (channel_id,)):
            origin[_key(ours)] = their_name
    except sqlite3.OperationalError:
        pass  # no competitor table on this machine yet
    rows = conn.execute(
        """SELECT title, views, publish_at, upload_date, created_at FROM videos
           WHERE channel = ? AND video_url IS NOT NULL AND video_url != ''
             AND status IN ('uploaded', 'scheduled')""", (channel_id,)).fetchall()
    groups: dict[str, list[float]] = {}
    for title, views, publish_at, upload_date, created_at in rows:
        live = _when(publish_at) or _when(upload_date) or _when(created_at)
        if not live or live > now or (now - live).days > days:
            continue  # not public yet, or too old for this window
        age_days = max((now - live).total_seconds() / 86400, 1.0)
        key = _key(title)
        source = next((name for ours, name in origin.items()
                       if ours and (key == ours or key.startswith(ours[:40]) or ours.startswith(key[:40]))),
                      "own")
        groups.setdefault(source, []).append((views or 0) / age_days)
    own = groups.pop("own", [])
    own_median = statistics.median(own) if own else 0.0
    competitors = []
    for name, values in sorted(groups.items(), key=lambda kv: -statistics.median(kv[1])):
        median = statistics.median(values)
        ratio = median / own_median if own_median else None
        if len(values) < MIN_VIDEOS or ratio is None:
            verdict = "too early"
        elif ratio >= STRONG:
            verdict = "strong"
        elif ratio <= WEAK:
            verdict = "weak"
        else:
            verdict = "similar"
        competitors.append({"name": name, "videos": len(values), "views_per_day": round(median, 1),
                            "vs_own": round(ratio, 2) if ratio is not None else None, "verdict": verdict})
    return {"days": days, "own_videos": len(own), "own_views_per_day": round(own_median, 1),
            "competitor_videos": sum(c["videos"] for c in competitors), "competitors": competitors}


def build(days: int = 14, refresh: bool = True) -> dict:
    """The report for every channel, saved to data/competitor_report.json."""
    from .channels import load_channels

    if refresh:
        try:
            from .view_stats import refresh_views

            for line in refresh_views():
                print(f"[views] {line}")
        except Exception as exc:
            print(f"[competitor-report] views not refreshed ({exc}); using the saved counts")
    conn = sqlite3.connect(settings.db_path)
    try:
        report = {"made_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                  "channels": {ch.id: channel_report(conn, ch.id, days) for ch in load_channels()}}
    finally:
        conn.close()
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def load() -> dict:
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_PUBLISHED: dict = {}


def published(max_age_seconds: int = 3600) -> dict:
    """The report the daily GitHub run published with the status page (GitHub's
    videos live there, not on this PC); this PC's own report when it cannot be read."""
    import time
    import urllib.request

    cached = _PUBLISHED.get("report")
    if cached and time.time() - _PUBLISHED.get("at", 0) < max_age_seconds:
        return cached
    try:
        from .setup_guide import SITE

        request = urllib.request.Request(SITE + "competitor_report.json",
                                         headers={"User-Agent": "StoryBotStudio/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            report = json.loads(response.read())
        _PUBLISHED.update(report=report, at=time.time())
        return report
    except Exception:
        return load()


def lines(report: dict) -> list[str]:
    out = []
    for cid, r in (report.get("channels") or {}).items():
        out.append(f"[{cid}] own videos: {r['own_videos']} at {r['own_views_per_day']} views/day "
                   f"(last {r['days']} days)")
        for c in r["competitors"]:
            vs = f"{c['vs_own']}x own" if c["vs_own"] is not None else "no own videos to compare"
            out.append(f"   {c['name']}: {c['videos']} of our videos, {c['views_per_day']} views/day, "
                       f"{vs} -> {c['verdict']}")
    return out
