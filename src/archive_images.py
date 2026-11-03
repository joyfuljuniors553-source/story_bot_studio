"""The real photos of the person or case a fact-only video is about.

On a fact channel (verified_facts.py) the opening scene, and every scene that
names the subject, shows the subject's own free photo; on a channel about
people every third scene does too, so a life story shows its person and not
only stock footage. The photos come, in order, from the Wikipedia article,
then the person's own Wikimedia Commons category (found through Wikidata,
so a namesake cannot slip in). Only files
free to reuse are taken, each with its credit line for the video description.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .models import Scene

_STATE_FILE = "archive_photos.json"
# Pictures that say nothing on screen: flags, logos, icons, signatures.
_SKIP_NAMES = re.compile(r"flag|logo|icon|signature|coat[ _]of[ _]arms|seal[ _.]|ribbon|commons-|"
                         r"symbol|emblem|question_book|edit-clear|disambig|ticket|statue|fullsig|"
                         r"grave|memorial|mural| & ", re.I)
_MIN_SIDE = 320
_MAX_ARTICLE_PHOTOS = 4
_MAX_PHOTOS = 15


def _plain_name(text: str) -> str:
    """Lower-case without accents, so "Beyoncé" also finds "Beyonce_2011.jpg"."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _subject(run_dir: Path) -> str:
    from .stock_video import SUBJECT_FILE

    path = run_dir / SUBJECT_FILE
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _photos(title: str) -> list[tuple[str, dict]]:
    """[(url, credit row)] of the article's free photos, its lead photo first."""
    from .page_posts import _PHOTO_INFO, _usable
    from .verified_facts import _api

    lead = (_api({"action": "query", "prop": "pageimages", "piprop": "name", "redirects": "1",
                  "titles": title}).get("query", {}).get("pages") or [{}])[0].get("pageimage") or ""
    pages = _api({"action": "query", "generator": "images", "gimlimit": "50", "redirects": "1",
                  "titles": title, **_PHOTO_INFO}).get("query", {}).get("pages") or []
    lead_name = lead.replace("_", " ")
    surname = title.split("(")[0].split()[-1]
    pages.sort(key=lambda page: 0 if lead_name and str(page.get("title", "")).endswith(lead_name) else 1)
    found: list[tuple[str, dict]] = []
    for page in pages:
        name = str(page.get("title", ""))
        if _SKIP_NAMES.search(name):
            continue
        # An article also shows people the subject only knew or admired. A photo
        # counts as the subject's only as the lead photo or with their name on the file.
        is_lead = bool(lead_name) and name.endswith(lead_name)
        if not is_lead and _plain_name(surname) not in _plain_name(name):
            continue
        usable =_usable(page, own_repository=page.get("imagerepository") == "shared")
        if not usable or usable[2] < _MIN_SIDE:
            continue
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        found.append((usable[0], {
            "title": name.replace("File:", "").rsplit(".", 1)[0][:90],
            "creator": re.sub(r"^Photo: | \(.*$", "", usable[1]) or "Wikimedia Commons",
            "license": str((meta.get("LicenseShortName") or {}).get("value") or "CC"),
            "source_page": str(info.get("descriptionurl") or ""),
        }))
        if len(found) >= _MAX_ARTICLE_PHOTOS:
            break
    return found


def _category_photos(title: str) -> list[tuple[str, dict]]:
    """The free photos in the person's own Commons category (Wikidata P373)."""
    from .page_posts import _NOT_THE_PERSON, _PHOTO_INFO, _usable
    from .verified_facts import _api

    commons = "https://commons.wikimedia.org/w/api.php"
    pages = _api({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                  "redirects": "1", "titles": title}).get("query", {}).get("pages") or []
    entity = ((pages[0] if pages else {}).get("pageprops") or {}).get("wikibase_item")
    if not entity:
        return []
    claims = _api({"action": "wbgetclaims", "entity": entity, "property": "P373"},
                  base="https://www.wikidata.org/w/api.php").get("claims") or {}
    try:
        category = str(claims["P373"][0]["mainsnak"]["datavalue"]["value"])
    except (KeyError, IndexError, TypeError):
        return []
    files = _api({"action": "query", "generator": "categorymembers", "gcmtitle": f"Category:{category}",
                  "gcmtype": "file", "gcmlimit": "80", **_PHOTO_INFO},
                 base=commons).get("query", {}).get("pages") or []
    found = []
    for page in files:
        name = str(page.get("title") or "")
        if _SKIP_NAMES.search(name) or any(word in name.lower() for word in _NOT_THE_PERSON):
            continue
        usable = _usable(page)
        if not usable or usable[2] < 500:
            continue
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        found.append((usable[0], {
            "title": name.replace("File:", "").rsplit(".", 1)[0][:90],
            "creator": re.sub(r"^Photo: | \(.*$", "", usable[1]) or "Wikimedia Commons",
            "license": str((meta.get("LicenseShortName") or {}).get("value") or "CC"),
            "source_page": str(info.get("descriptionurl") or ""),
        }))
    return found


def _all_photos(title: str, people: bool) -> list[tuple[str, dict]]:
    """The article's photos, then (on a channel about people) the Commons
    category's, without repeats, up to _MAX_PHOTOS."""
    sources = [_photos] + ([_category_photos] if people else [])
    found: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for source in sources:
        try:
            rows = source(title)
        except Exception as exc:
            print(f"[archive] {title}: {source.__name__} skipped ({exc})")
            continue
        for url, credit in rows:
            key = _plain_name(url.rsplit("/", 1)[-1]).split("px-", 1)[-1]
            if key in seen:
                continue
            seen.add(key)
            found.append((url, credit))
            if len(found) >= _MAX_PHOTOS:
                return found
    return found


def _state(run_dir: Path, people: bool = False) -> dict:
    """The run's photos, downloaded once."""
    path = run_dir / _STATE_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    state: dict = {"files": [], "next": 0}
    title = _subject(run_dir)
    if title:
        from .verified_facts import fetch

        folder = run_dir / "archive"
        folder.mkdir(exist_ok=True)
        try:
            photos = _all_photos(title, people)
        except Exception as exc:
            print(f"[archive] {title}: no photo ({exc})")
            photos = []
        for number, (url, credit) in enumerate(photos, 1):
            target = folder / f"photo_{number:02}.jpg"
            try:
                target.write_bytes(fetch(url))
            except Exception:
                continue
            state["files"].append({"path": str(target), "credit": credit})
        print(f"[archive] {title}: {len(state['files'])} free photo(s)")
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def _names_subject(scene: Scene, title: str) -> bool:
    """The scene's line names the subject (any word of the title of 4+ letters)."""
    words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", re.sub(r"\(.*?\)", "", title))}
    line = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", f"{scene.line} {scene.speech or ''}")}
    return bool(words & line)


def photo_for_scene(scene_number: int, scene: Scene, run_dir: Path, channel=None) -> Path | None:
    """The subject's real photo for scene 1, scenes naming the subject and (on a
    channel about people) every third scene; else None.

    Each such scene gets the next photo, so one picture is not shown twice in a
    row; when the photos run out the remaining scenes use video.
    """
    title = _subject(run_dir)
    # A topic channel (space, prehistory, money) has its own pictures.
    people = not getattr(channel, "thumbnail_style", "")
    wanted = scene_number == 1 or _names_subject(scene, title) or (people and scene_number % 3 == 0)
    if not title or not wanted:
        return None
    state = _state(run_dir, people)
    if state["next"] >= len(state["files"]):
        return None
    picture = state["files"][state["next"]]
    state["next"] += 1
    (run_dir / _STATE_FILE).write_text(json.dumps(state, indent=1), encoding="utf-8")
    path = Path(picture["path"])
    gen = run_dir / "gen"
    gen.mkdir(exist_ok=True)
    # Credit line for the video description (pipeline._append_image_credits).
    (gen / f"{path.stem}.wikimedia.json").write_text(json.dumps(picture["credit"]), encoding="utf-8")
    return path
