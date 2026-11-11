"""More places to find a scene's clip: NASA's library and Pixabay, and a look at the frame.

Pexels alone often has nothing that fits a space or prehistory line, so a
channel can list its own sources in order (channels.json "clip_sources"):
"nasa" (NASA Image and Video Library: real missions, planets and telescopes,
public domain, no key), "commons" (Wikimedia Commons film, stock_video.py),
"pexels", "pixabay" (free key, PIXABAY_API_KEY) and "smithsonian" (the Natural
History museum's CC0 photos of fossils and specimens, shown with a slow zoom;
free api.data.gov key, DATA_GOV_API_KEY), "coverr" (COVERR_API_KEY; clips made
by AI are skipped) and "nps" (National Park Service b-roll of parks, fossil
beds and glaciers, public domain; NPS_API_KEY). Every source is searched
with the same AI-planned phrases and must-have noun (stock_video.plan_clip_shots).

Before a clip is kept, one frame of it is shown to Gemini with the narrated
line ("does this picture show it?"), so a search hit that only shares a word
is thrown out. When Gemini cannot answer (no key, daily quota) the check is
skipped and the clip kept, so a video is never lost to the check.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .config import settings
from .models import Scene

_USER_AGENT = "StoryBotStudio/1.0 (https://joyfuljuniors553-source.github.io/story-bot-studio/)"
_USED_FILE = "clips_used.json"
_CACHE: dict[tuple, list[dict]] = {}
# NASA's library is mostly briefings and interviews; their titles say so.
_TALK_WORDS = {
    "briefing", "conference", "interview", "news", "update", "live", "talk", "panel", "webinar",
    "podcast", "lecture", "q&a", "remarks", "speech", "town", "hall", "meeting", "ceremony",
    "show", "episode", "minute", "chat", "explains", "discusses", "testimony", "hearing",
}
_checks_off = False  # set once every Gemini key and model refuses (quota), for the rest of the run
_dead_pairs: set[tuple[str, str]] = set()  # (key, model) pairs that hit their quota this run
# What the channel is about, set per clip search by stock_video.fetch_scene_clip:
#   topic   - the channel's subject, so a frame from an unrelated setting fails
#   strict  - generic stock (Pexels, Pixabay, Coverr) is only kept after the
#             frame check said yes; with the check unavailable it is refused
#   loose   - the frame only has to show the channel's subject, not this line
#             (the last-resort space/ocean footage of stock_video)
_context: dict = {"topic": "", "strict": False, "loose": False, "banned": set(), "channel": ""}


#   banned  - words naming settings the channel never shows (clip_off_topic)
#   channel - whose videos may not repeat a clip (remember_clip)
def set_context(topic: str = "", strict: bool = False, loose: bool = False,
                banned: set[str] | None = None, channel: str = "") -> None:
    _context.update(topic=" ".join(str(topic or "").split())[:200], strict=strict, loose=loose,
                    banned=set(banned or ()), channel=str(channel or ""))


# ------------------------------------------------------------ across videos
# The clips used list lived in each video's own run folder, so the next video
# could open on the same footage: three Veylora Earth Shorts in a row began on
# one geode clip. A clip a channel used is now kept from its videos for a month.
CLIP_MEMORY_DAYS = 30
_CHANNEL_CLIPS: dict[str, set[str]] = {}


def _clip_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS used_clips (
        channel TEXT NOT NULL, clip TEXT NOT NULL, used_at TEXT NOT NULL,
        PRIMARY KEY (channel, clip))""")


def channel_clips(channel_id: str | None = None) -> set[str]:
    """Clips this channel used in the last CLIP_MEMORY_DAYS days ('pexels:123', 'nasa:...')."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    channel_id = str(channel_id if channel_id is not None else _context["channel"])
    if not channel_id:
        return set()
    if channel_id not in _CHANNEL_CLIPS:
        since = (datetime.now(timezone.utc) - timedelta(days=CLIP_MEMORY_DAYS)).isoformat()
        found: set[str] = set()
        try:
            conn = sqlite3.connect(settings.db_path)
            try:
                _clip_table(conn)
                found = {row[0] for row in conn.execute(
                    "SELECT clip FROM used_clips WHERE channel = ? AND used_at >= ?", (channel_id, since))}
            finally:
                conn.close()
        except Exception as exc:
            print(f"[clips] could not read the channel's used clips ({exc})")
        _CHANNEL_CLIPS[channel_id] = found
    return _CHANNEL_CLIPS[channel_id]


def remember_clip(key: str) -> None:
    """Record a clip the channel just used, so its other videos leave it out."""
    import sqlite3
    from datetime import datetime, timezone

    channel_id = _context["channel"]
    if not channel_id or not key:
        return
    channel_clips(channel_id).add(key)
    try:
        conn = sqlite3.connect(settings.db_path)
        try:
            _clip_table(conn)
            conn.execute("INSERT OR REPLACE INTO used_clips (channel, clip, used_at) VALUES (?, ?, ?)",
                         (channel_id, key, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[clips] could not record clip {key} ({exc})")


def off_topic(words: set[str]) -> bool:
    """True when a clip's title or tags name a setting this channel never shows."""
    banned = _context["banned"]
    return bool(banned) and any(word in banned or word.rstrip("s") in banned for word in words)
# Clips a source may have rejected by the frame check before it gives up on a
# scene, so one hopeless search does not burn the Gemini quota.
_MAX_MISSES = 3


def default_sources(channel=None) -> list[str]:
    """This channel's clip sources in order; Pexels then Pixabay unless it lists its own."""
    listed = [str(s).strip().lower() for s in (getattr(channel, "clip_sources", ()) or ()) if str(s).strip()]
    return listed or ["pexels", "pixabay"]


def pixabay_api_key() -> str:
    return os.getenv("PIXABAY_API_KEY", "").strip()


def _get_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{3,}", str(text or "").lower())}


def _names(words: set[str], must: str) -> bool:
    """The clip's title or tags contain the main noun (or its plural)."""
    return bool({must, must + "s", must + "es"} & words) or (must.endswith("s") and must[:-1] in words)


def _run_used(run_dir: Path) -> set[str]:
    try:
        return set(json.loads((run_dir / _USED_FILE).read_text(encoding="utf-8")))
    except Exception:
        return set()


def _used(run_dir: Path) -> set[str]:
    """Clips this video tried or used, and those the channel's other videos used."""
    return _run_used(run_dir) | channel_clips()


def _mark_used(run_dir: Path, key: str) -> None:
    used = _run_used(run_dir) | {key}
    (run_dir / _USED_FILE).write_text(json.dumps(sorted(used)), encoding="utf-8")


def _credit(run_dir: Path, output_path: Path, title: str, creator: str, licence: str, page: str) -> None:
    """Written where the upload's description collects its credits (pipeline._append_image_credits)."""
    gen = run_dir / "gen"
    gen.mkdir(exist_ok=True)
    (gen / f"{output_path.stem}.wikimedia.json").write_text(json.dumps({
        "title": title[:90], "creator": creator[:80], "license": licence, "source_page": page,
    }, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ the check

def _gemini_pairs() -> list[tuple[str, str]]:
    """Every (key, model) to ask, in order: both keys, then the fallback models."""
    keys = [k for k in (settings.gemini_api_key, getattr(settings, "gemini_api_key_2", "")) if k]
    models = [settings.gemini_model, *[m.strip() for m in
                                      str(getattr(settings, "gemini_fallback_model", "") or "").split(",")
                                      if m.strip()]]
    pairs = [(key, model) for model in dict.fromkeys(models) for key in keys]
    return [pair for pair in pairs if pair not in _dead_pairs]


def _ask_fits(parts: list[dict]) -> bool | None:
    """Gemini's yes/no on the frames, or None when no key or model will answer."""
    global _checks_off
    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }).encode("utf-8")
    for key, model in _gemini_pairs():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read())
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return bool(json.loads(text).get("fits", False))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 403, 404):
                # Quota or a retired model: the next key or model may still answer.
                _dead_pairs.add((key, model))
                continue
            print(f"[clips] frame check error (Gemini {exc.code})")
            return None
        except Exception as exc:
            print(f"[clips] frame check skipped: {exc}")
            return None
    if not _checks_off:
        print("[clips] frame check off for this run (every Gemini key and model refused)")
    _checks_off = True
    return None


def frame_matches(clip: Path, scene: Scene, no_people: bool = False, generic: bool = False) -> bool:
    """True when frames from the start and the end of the clip show what the line is about.

    `no_people` (a story about real people): any face fails, since a stranger
    on screen reads as the person named; their own photos come from
    archive_images.py, where who they show is known.

    When the check cannot run (no key, every quota spent, a bad frame) the clip
    is kept, except `generic` stock (Pexels, Pixabay, Coverr) on a `strict`
    channel: there an unchecked search hit put an operating room into a quasar
    Short, so the scene shows its own picture instead."""
    unchecked = not (_context["strict"] and generic)
    if _checks_off or not settings.gemini_api_key:
        if not unchecked:
            print("[clips] stock clip refused: the frame check is off and this channel needs it")
        return unchecked
    from .visuals import ffmpeg_bin

    frames = [clip.with_suffix(".check1.jpg"), clip.with_suffix(".check2.jpg")]
    try:
        still = clip.suffix.lower() in (".jpg", ".jpeg", ".png")
        seeks = [[]] if still else [["-ss", "1.5"], ["-sseof", "-1.0"]]
        parts = []
        for seek, frame in zip(seeks, frames):
            subprocess.run([ffmpeg_bin(), "-y", "-v", "error", *seek, "-i", str(clip),
                            "-frames:v", "1", "-vf", "scale=512:-2", str(frame)],
                           check=True, capture_output=True, timeout=60)
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(frame.read_bytes()).decode("ascii")}})
        line = " ".join(str(scene.line or scene.label or "").split())[:300]
        people = (" Any recognisable person or face in a frame does NOT fit: viewers would take a "
                  "stranger for the person in the story.") if no_people else ""
        topic = _context["topic"]
        channel = (f" The video is a documentary about {topic}: footage of an unrelated setting (a "
                   "hospital or operating room, an office, a kitchen, a shop, a party) does NOT fit, "
                   "even when it shares a word with the line.") if topic else ""
        if _context["loose"] and topic:
            question = (f"Does every frame plainly show {topic} (a fitting illustration is fine; people, "
                        "text on screen, subtitles or a logo are not)?")
        else:
            question = ("Does every frame plainly show the thing or place the line is about (a fitting "
                        "illustration is fine; something unrelated, a person talking to camera, text "
                        "on screen, subtitles or a logo is not)?")
        parts.append({"text": f"{'These frames are' if len(parts) > 1 else 'This frame is'} from a clip "
                              "shown while a narrator says:\n"
                              f"\"{line}\"\n" + question + channel + people
                              + " Return JSON only: {\"fits\": true or false}"})
        fits = _ask_fits(parts)
        if fits is None:
            if not unchecked:
                print("[clips] stock clip refused: the frame check could not run and this channel needs it")
            return unchecked
        if not fits:
            print(f"[clips] frame does not fit '{line[:60]}'; trying another clip")
        return fits
    except Exception as exc:
        print(f"[clips] frame check skipped: {exc}")
        return unchecked
    finally:
        for frame in frames:
            frame.unlink(missing_ok=True)


def _cut(source: str, output_path: Path, min_seconds: float, seconds: float) -> bool:
    """Copy a stretch of a long online video into output_path; False when it fails."""
    from .visuals import ffmpeg_bin

    length = max(min_seconds, 3) + 1
    start = max(0.0, (seconds - length) * random.uniform(0.15, 0.6)) if seconds > length + 2 else 0.0
    done = subprocess.run([
        ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", source,
        "-t", f"{length:.2f}", "-an", "-vf", "fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(output_path),
    ], capture_output=True, timeout=300)
    if done.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 50_000:
        output_path.unlink(missing_ok=True)
        return False
    return True


def _duration(source: str) -> float:
    from .visuals import ffprobe_bin

    try:
        done = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=nw=1:nk=1", source],
                              capture_output=True, text=True, timeout=60)
        return float(done.stdout.strip() or 0)
    except Exception:
        return 0.0


# ------------------------------------------------------------------ NASA

def _nasa_search(query: str) -> list[dict]:
    key = ("nasa", query)
    if key not in _CACHE:
        url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
            {"q": query, "media_type": "video", "page_size": "40"})
        _CACHE[key] = list(_get_json(url).get("collection", {}).get("items") or [])
    return _CACHE[key]


def _nasa_file(item: dict) -> str:
    """The video file to read from: the medium rendition, else the original."""
    links = _get_json(str(item.get("href") or "")) if item.get("href") else []
    files = [str(link).replace("http://", "https://").replace(" ", "%20")
             for link in links if str(link).lower().endswith(".mp4")]
    for ending in ("~medium.mp4", "~orig.mp4", "~large.mp4"):
        for link in files:
            if link.endswith(ending):
                return link
    return files[0] if files else ""


def nasa_clip(scene: Scene, output_path: Path, run_dir: Path, searches: list[tuple[str, str]],
              min_seconds: float) -> Path:
    used = _used(run_dir)
    errors, misses = [], 0
    for query, must in searches:
        try:
            items = _nasa_search(query)
        except Exception as exc:
            raise RuntimeError(f"NASA search failed: {exc}")
        wanted = {must} if must else _words(query)
        for item in items[:15]:
            data = (item.get("data") or [{}])[0]
            nasa_id = str(data.get("nasa_id") or "")
            title = str(data.get("title") or "")
            words = _words(f"{title} {' '.join(data.get('keywords') or [])}")
            if not nasa_id or f"nasa:{nasa_id}" in used or words & _TALK_WORDS or off_topic(words):
                continue
            if not (_names(words, must) if must else words & wanted):
                continue
            try:
                source = _nasa_file(item)
            except Exception:
                continue
            if not source or not _cut(source, output_path, min_seconds, _duration(source)):
                continue
            if not frame_matches(output_path, scene):
                _mark_used(run_dir, f"nasa:{nasa_id}")
                output_path.unlink(missing_ok=True)
                misses += 1
                if misses >= _MAX_MISSES:
                    raise RuntimeError("NASA: no clip fit the line")
                continue
            _mark_used(run_dir, f"nasa:{nasa_id}")
            remember_clip(f"nasa:{nasa_id}")
            _credit(run_dir, output_path, title, "NASA", "Public domain",
                    f"https://images.nasa.gov/details/{urllib.parse.quote(nasa_id)}")
            print(f"[clips] {output_path.stem}: NASA '{title[:60]}'")
            return output_path
        errors.append(f"{query}: nothing fitting")
    raise RuntimeError("NASA: " + " | ".join(errors[-3:]) if errors else "NASA: no search phrase")


# ------------------------------------------------------------------ Pixabay

def _pixabay_search(query: str, key: str) -> list[dict]:
    cache = ("pixabay", query)
    if cache not in _CACHE:
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
            {"key": key, "q": query[:100], "per_page": "50", "safesearch": "true", "video_type": "film"})
        _CACHE[cache] = list(_get_json(url).get("hits") or [])
    return _CACHE[cache]


def _pixabay_file(hit: dict, landscape: bool) -> dict | None:
    """The rendition closest to 1080p, never smaller than 720p, in the right orientation."""
    best = None
    for item in (hit.get("videos") or {}).values():
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        if not item.get("url") or not width or not height or (width > height) != landscape:
            continue
        if min(width, height) < 720:
            continue
        distance = abs(min(width, height) - 1080)
        if best is None or distance < best[0]:
            best = (distance, item)
    return best[1] if best else None


def pixabay_clip(scene: Scene, output_path: Path, run_dir: Path, searches: list[tuple[str, str]],
                 landscape: bool, min_seconds: float, no_people: bool) -> Path:
    from .stock_video import _GRAPHIC_WORDS, _MAX_CLIP_BYTES, _MIN_CLIP_BYTES, has_people

    key = pixabay_api_key()
    if not key:
        raise RuntimeError("no Pixabay key (PIXABAY_API_KEY)")
    used = _used(run_dir)
    errors, misses = [], 0
    for query, must in searches:
        try:
            hits = _pixabay_search(query, key)
        except Exception as exc:
            raise RuntimeError(f"Pixabay search failed: {exc}")
        wanted = {must} if must else _words(query)
        candidates = []
        for hit in hits:
            words = _words(hit.get("tags"))
            if f"pixabay:{hit.get('id')}" in used or words & _GRAPHIC_WORDS or off_topic(words):
                continue
            if no_people and has_people(words):
                continue
            if (_names(words, must) if must else words & wanted) and _pixabay_file(hit, landscape):
                candidates.append(hit)
        random.shuffle(candidates)
        candidates.sort(key=lambda hit: float(hit.get("duration") or 0) < min_seconds)
        for hit in candidates[:4]:
            item = _pixabay_file(hit, landscape)
            try:
                request = urllib.request.Request(str(item["url"]), headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read(_MAX_CLIP_BYTES + 1)
            except Exception as exc:
                errors.append(f"{query}: {exc}")
                continue
            if not (_MIN_CLIP_BYTES <= len(data) <= _MAX_CLIP_BYTES):
                continue
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
            _mark_used(run_dir, f"pixabay:{hit.get('id')}")
            if not frame_matches(output_path, scene, no_people, generic=True):
                output_path.unlink(missing_ok=True)
                misses += 1
                if misses >= _MAX_MISSES:
                    raise RuntimeError("Pixabay: no clip fit the line")
                continue
            remember_clip(f"pixabay:{hit.get('id')}")
            _credit(run_dir, output_path, str(hit.get("tags") or "Video")[:60],
                    str(hit.get("user") or "Pixabay"), "Pixabay Content License", str(hit.get("pageURL") or ""))
            print(f"[clips] {output_path.stem}: Pixabay '{hit.get('tags')}'")
            return output_path
        errors.append(f"{query}: nothing fitting")
    raise RuntimeError("Pixabay: " + " | ".join(errors[-3:]) if errors else "Pixabay: no search phrase")


# ------------------------------------------------------------------ Smithsonian

def _smithsonian_search(query: str, key: str) -> list[dict]:
    cache = ("smithsonian", query)
    if cache not in _CACHE:
        url = "https://api.si.edu/openaccess/api/v1.0/search?" + urllib.parse.urlencode(
            {"q": f'{query} AND online_media_type:"Images"', "rows": "40", "api_key": key})
        _CACHE[cache] = list(_get_json(url).get("response", {}).get("rows") or [])
    return _CACHE[cache]


def _row_text(row: dict) -> str:
    """The record's title and every free-text note (common names live there)."""
    parts = [str(row.get("title") or "")]
    for entries in ((row.get("content") or {}).get("freetext") or {}).values():
        parts += [str(entry.get("content") or "") for entry in entries if isinstance(entry, dict)]
    return " ".join(parts)


def _still_to_clip(picture: Path, output_path: Path, landscape: bool, seconds: float) -> bool:
    """A slow zoom into a photo, fitted on a blurred copy of itself."""
    from .visuals import ffmpeg_bin

    w, h = (1920, 1080) if landscape else (1080, 1920)
    frames = int(max(seconds, 3) + 1) * 30
    graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=40,"
             f"eq=brightness=-0.15[bg];"
             f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={w * 2}:{h * 2},"
             f"zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
             f"d={frames}:s={w}x{h}:fps=30,format=yuv420p")
    done = subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(picture), "-filter_complex", graph,
                           "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                           str(output_path)], capture_output=True, timeout=300)
    return done.returncode == 0 and output_path.exists() and output_path.stat().st_size > 20_000


def smithsonian_clip(scene: Scene, output_path: Path, run_dir: Path, searches: list[tuple[str, str]],
                     landscape: bool, min_seconds: float) -> Path:
    key = os.getenv("DATA_GOV_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no api.data.gov key (DATA_GOV_API_KEY)")
    used = _used(run_dir)
    errors, misses = [], 0
    for query, must in searches:
        try:
            rows = _smithsonian_search(must or query, key)
        except Exception as exc:
            raise RuntimeError(f"Smithsonian search failed: {exc}")
        wanted = {must} if must else _words(query)
        for row in rows:
            # The natural-history museum only, and only what is free to reuse.
            if not str(row.get("unitCode") or "").startswith("NMNH"):
                continue
            words = _words(_row_text(row))
            if not (_names(words, must) if must else words & wanted):
                continue
            media = ((row.get("content") or {}).get("descriptiveNonRepeating") or {})                 .get("online_media", {}).get("media") or []
            media = [m for m in media if (m.get("usage") or {}).get("access") == "CC0" and m.get("content")]
            if not media or f"si:{row.get('id')}" in used:
                continue
            _mark_used(run_dir, f"si:{row.get('id')}")
            picture = output_path.with_suffix(".si.jpg")
            try:
                link = str(media[0]["content"]) + "&max=2000"
                request = urllib.request.Request(link, headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    picture.write_bytes(response.read())
            except Exception:
                continue
            if not frame_matches(picture, scene):
                picture.unlink(missing_ok=True)
                misses += 1
                if misses >= _MAX_MISSES:
                    raise RuntimeError("Smithsonian: no photo fit the line")
                continue
            if not _still_to_clip(picture, output_path, landscape, min_seconds):
                picture.unlink(missing_ok=True)
                output_path.unlink(missing_ok=True)
                continue
            picture.unlink(missing_ok=True)
            title = str(row.get("title") or "Specimen")
            record = str(((row.get("content") or {}).get("descriptiveNonRepeating") or {})
                         .get("record_link") or "")
            remember_clip(f"si:{row.get('id')}")
            _credit(run_dir, output_path, title, "Smithsonian National Museum of Natural History", "CC0",
                    record)
            print(f"[clips] {output_path.stem}: Smithsonian '{title[:60]}'")
            return output_path
        errors.append(f"{query}: nothing fitting")
    raise RuntimeError("Smithsonian: " + " | ".join(errors[-3:]) if errors else "Smithsonian: no search phrase")


# ------------------------------------------------------------------ Coverr

def _download(link: str, output_path: Path) -> bool:
    from .stock_video import _MAX_CLIP_BYTES, _MIN_CLIP_BYTES

    try:
        request = urllib.request.Request(link, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(_MAX_CLIP_BYTES + 1)
    except Exception:
        return False
    if not (_MIN_CLIP_BYTES <= len(data) <= _MAX_CLIP_BYTES):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return True


def coverr_clip(scene: Scene, output_path: Path, run_dir: Path, searches: list[tuple[str, str]],
                landscape: bool, no_people: bool) -> Path:
    from .stock_video import _GRAPHIC_WORDS, has_people

    key = os.getenv("COVERR_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no Coverr key (COVERR_API_KEY)")
    used = _used(run_dir)
    misses = 0
    for query, must in searches:
        cache = ("coverr", query)
        try:
            if cache not in _CACHE:
                url = "https://api.coverr.co/videos?" + urllib.parse.urlencode(
                    {"query": query, "page_size": "25", "urls": "true", "api_key": key})
                _CACHE[cache] = list(_get_json(url).get("hits") or [])
        except Exception as exc:
            raise RuntimeError(f"Coverr search failed: {exc}")
        wanted = {must} if must else _words(query)
        for hit in _CACHE[cache]:
            words = _words(f"{hit.get('title')} {' '.join(hit.get('tags') or [])}")
            link = str((hit.get("urls") or {}).get("mp4") or "")
            if not link or hit.get("is_ai_generated") or bool(hit.get("is_vertical")) == landscape:
                continue
            if (f"coverr:{hit.get('id')}" in used or words & _GRAPHIC_WORDS or off_topic(words)
                    or (no_people and has_people(words))):
                continue
            if not (_names(words, must) if must else words & wanted):
                continue
            _mark_used(run_dir, f"coverr:{hit.get('id')}")
            if not _download(link, output_path):
                continue
            if not frame_matches(output_path, scene, no_people, generic=True):
                output_path.unlink(missing_ok=True)
                misses += 1
                if misses >= _MAX_MISSES:
                    raise RuntimeError("Coverr: no clip fit the line")
                continue
            remember_clip(f"coverr:{hit.get('id')}")
            _credit(run_dir, output_path, str(hit.get("title") or "Video"), "Coverr", "Coverr License",
                    f"https://coverr.co/videos/{hit.get('slug') or ''}")
            print(f"[clips] {output_path.stem}: Coverr '{hit.get('title')}'")
            return output_path
    raise RuntimeError("Coverr: nothing fitting")


# ------------------------------------------------------------------ National Park Service

def nps_clip(scene: Scene, output_path: Path, run_dir: Path, searches: list[tuple[str, str]],
             min_seconds: float) -> Path:
    """B-roll only: the rest of the park videos are rangers talking to camera."""
    key = os.getenv("NPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no NPS key (NPS_API_KEY)")
    used = _used(run_dir)
    misses = 0
    for query, must in searches:
        cache = ("nps", query)
        try:
            if cache not in _CACHE:
                url = "https://developer.nps.gov/api/v1/multimedia/videos?" + urllib.parse.urlencode(
                    {"q": query, "limit": "50", "api_key": key})
                _CACHE[cache] = list(_get_json(url).get("data") or [])
        except Exception as exc:
            raise RuntimeError(f"NPS search failed: {exc}")
        wanted = {must} if must else _words(query)
        for video in _CACHE[cache]:
            words = _words(f"{video.get('title')} {' '.join(video.get('tags') or [])}")
            if not video.get("isBRoll") or f"nps:{video.get('id')}" in used:
                continue
            # Burned-in captions, and classroom demonstrations ("Model Glaciers": hands in a sandbox).
            if video.get("hasOpenCaptions") or words & {"model", "models", "demo", "demonstration",
                                                        "activity", "experiment", "lesson", "classroom"}:
                continue
            if not (_names(words, must) if must else words & wanted):
                continue
            versions = sorted((v for v in video.get("versions") or [] if str(v.get("url")).endswith(".mp4")),
                              key=lambda v: -int(v.get("heightPixels") or 0))
            if not versions or int(versions[0].get("heightPixels") or 0) < 720:
                continue
            _mark_used(run_dir, f"nps:{video.get('id')}")
            source = str(versions[0]["url"])
            if not _cut(source, output_path, min_seconds, float(video.get("durationMs") or 0) / 1000):
                continue
            if not frame_matches(output_path, scene):
                output_path.unlink(missing_ok=True)
                misses += 1
                if misses >= _MAX_MISSES:
                    raise RuntimeError("NPS: no clip fit the line")
                continue
            remember_clip(f"nps:{video.get('id')}")
            _credit(run_dir, output_path, str(video.get("title") or "Park video"), "U.S. National Park Service",
                    "Public domain", str(video.get("permalinkUrl") or ""))
            print(f"[clips] {output_path.stem}: NPS '{video.get('title')}'")
            return output_path
    raise RuntimeError("NPS: nothing fitting")
