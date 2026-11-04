"""Each channel's brand kit, kept in data/brand/<channel id>/ so the bot and
the dashboard both remember it:

    style.md          the thumbnail style guide; the thumbnail writer reads it
    logo.png          a logo with real transparency (drawn on the thumbnails)
    logo_reference.*  a picture of the logo, only shown on the dashboard
    examples/         thumbnails you made by hand, the look to aim for
    samples/          the bot's latest sample cards (long.jpg, short.jpg)
    youtube.json      the channel's own picture, name and numbers (cached 12 h)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
STYLE_NAMES = {
    "": "Standard (photo + title bar)",
    "future": "Future Science Editorial",
    "space": "Space documentary",
    "earth": "Prehistory / Earth",
    "ocean": "Ocean giants / expedition dossier",
    "money": "Personal finance",
}


def brand_dir(channel_id: str) -> Path:
    path = settings.root / "data" / "brand" / str(channel_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def style_text(channel_id: str) -> str:
    path = brand_dir(channel_id) / "style.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def save_style(channel_id: str, text: str) -> None:
    (brand_dir(channel_id) / "style.md").write_text(text.strip() + "\n", encoding="utf-8")


def palette(channel_id: str) -> list[tuple[str, str]]:
    """(hex, name) pairs written in the style guide, e.g. '- #FF6A00 Orange'."""
    found = []
    for hex_code, name in re.findall(r"(#[0-9A-Fa-f]{6})\s*[^\n#]*?([A-Za-z][A-Za-z ]{1,20})?(?:\(|\n|$)",
                                     style_text(channel_id)):
        code = hex_code.upper()
        if code not in [c for c, _ in found]:
            found.append((code, (name or "").strip()))
    return found[:8]


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_TYPES), key=lambda p: p.name)


def examples(channel_id: str) -> list[Path]:
    return _images(brand_dir(channel_id) / "examples")


def samples(channel_id: str) -> list[Path]:
    return _images(brand_dir(channel_id) / "samples")


def logo(channel_id: str) -> Path | None:
    path = brand_dir(channel_id) / "logo.png"
    return path if path.is_file() else None


def logo_reference(channel_id: str) -> Path | None:
    for path in _images(brand_dir(channel_id)):
        if path.stem in ("logo", "logo_reference"):
            return path
    return None


def save_upload(channel_id: str, storage, kind: str) -> Path:
    """Store a file from the dashboard: kind = example | logo | logo_reference."""
    name = Path(str(storage.filename or "")).name
    suffix = Path(name).suffix.lower()
    if suffix not in IMAGE_TYPES:
        raise ValueError("Upload a JPG, PNG or WEBP picture.")
    folder = brand_dir(channel_id)
    if kind == "logo":
        if suffix != ".png":
            raise ValueError("The logo must be a PNG with a transparent background.")
        target = folder / "logo.png"
    elif kind == "logo_reference":
        target = folder / f"logo_reference{suffix}"
    else:
        (folder / "examples").mkdir(exist_ok=True)
        stem = re.sub(r"[^a-z0-9_-]+", "_", Path(name).stem.lower()).strip("_")[:40] or "example"
        target = folder / "examples" / f"{stem}{suffix}"
    storage.save(str(target))
    return target


def delete_example(channel_id: str, name: str) -> None:
    path = (brand_dir(channel_id) / "examples" / Path(name).name)
    if path.is_file():
        path.unlink()


# ------------------------------------------------------------------ YouTube identity

def youtube_identity(channel, max_age_hours: float = 12) -> dict:
    """The channel's own YouTube picture, name and numbers, cached."""
    cache = brand_dir(channel.id) / "youtube.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched_at"]) < timedelta(hours=max_age_hours):
            return data
    except Exception:
        data = {}
    try:
        from .youtube_accounts import channel_for_account, connected_accounts
        from .youtube_upload import _youtube

        accounts = connected_accounts(channel.id)
        if not accounts:
            return data
        own = channel_for_account(channel.id, accounts[0].id)
        found = _youtube(own.client_secret_path, own.token_path).channels().list(
            part="snippet,statistics,brandingSettings", mine=True).execute().get("items") or []
        if not found:
            return data
        item = found[0]
        thumbs = item["snippet"].get("thumbnails") or {}
        stats = item.get("statistics") or {}
        data = {
            "id": item["id"],
            "title": item["snippet"].get("title", ""),
            "handle": item["snippet"].get("customUrl", ""),
            "description": item["snippet"].get("description", "")[:300],
            "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
            "banner": ((item.get("brandingSettings") or {}).get("image") or {}).get("bannerExternalUrl", ""),
            "subs": int(stats.get("subscriberCount", 0) or 0),
            "videos": int(stats.get("videoCount", 0) or 0),
            "views": int(stats.get("viewCount", 0) or 0),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[brand] {channel.id}: YouTube identity not read ({exc})")
    return data


# ------------------------------------------------------------------ samples

SAMPLE_TITLES = {"long": "What Will Life Look Like in 2050?", "short": "Could Robots Run Entire Cities?"}


def make_samples(channel) -> list[str]:
    """Draw one long and one Short card with today's style, for the dashboard."""
    from .models import Lesson, Scene
    from .thumbnail_check import check_thumbnail
    from .thumbnails import create_thumbnail

    folder = brand_dir(channel.id) / "samples"
    folder.mkdir(exist_ok=True)
    notes = []
    for kind, title in SAMPLE_TITLES.items():
        lesson = Lesson(topic_key=f"sample_{kind}", title=title, category=str(channel.genre).title(),
                        intro="", outro="", scenes=[Scene(label=title[:30], line=title, image="")])
        path = create_thumbnail(lesson, None, folder / f"{kind}.jpg", channel, kind)
        notes.append(f"{kind}: {title} -> {check_thumbnail(path).summary}")
    for leftover in folder.glob("thumbnail_*"):
        leftover.unlink(missing_ok=True)
    return notes
