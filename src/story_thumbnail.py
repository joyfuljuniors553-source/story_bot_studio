"""The true-story thumbnail: "The story of / NAME / subtitle" beside the person's photo.

A dark panel on the left carries the words in a serif face with gold accents;
the subject's own photo fills the right and fades into the panel. Used for
channels whose videos are about one real person (verified_facts channels).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _escape, _text_width
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

SERIF = settings.root / "fonts" / "DMSerifDisplay-Regular.ttf"
SERIF_ITALIC = settings.root / "fonts" / "DMSerifDisplay-Italic.ttf"
_PANEL = (13, 20, 32)
_GOLD = "0xD4AF5A"
_CREAM = "0xF3E9D2"
_LEFT = 84
_TEXT_WIDTH = 600
_BOTTOM = 640
_PHOTO_MAX_W = 760
_SHADOW = "shadowcolor=black@0.65:shadowx=3:shadowy=3"
# Words that say nothing a subtitle should repeat: the name is already on the card.
_GENERIC = {"life", "story", "stories", "true", "facts", "fact", "biography", "film", "career",
            "and", "the", "of", "his", "her", "their", "journey", "remarkable", "celebrity",
            "full", "untold", "real"}
_DEFAULT_SUBTITLE = "The Road to Fame"


def story_name(subject: str) -> str:
    """'Emma Thompson (actress)' -> 'EMMA THOMPSON'."""
    return re.sub(r"\s*\(.*?\)", "", subject).strip().upper()


def story_subtitle(title: str, subject: str) -> str:
    """A few words from the video title that are not the name: 'The Highest Grossing Actor'."""
    text = title.split("|")[0]
    for part in [re.sub(r"\s*\(.*?\)", "", subject), *subject.split()]:
        if len(part) > 2:
            text = re.sub(rf"\b{re.escape(part)}\b'?s?", " ", text, flags=re.I)
    text = re.split(r"\s+(?:and|&)\s+(?:his|her|their)\b", text, flags=re.I)[0]
    words = [word for word in re.split(r"[\s:,–—-]+", text) if word]
    if not (2 <= len(words) <= 5) or all(word.lower() in _GENERIC for word in words):
        return _DEFAULT_SUBTITLE
    return " ".join(word if word.isupper() else word.capitalize() for word in words)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _fit(text_file: Path, font: Path, start: int, smallest: int, width: int) -> tuple[int, int]:
    """(font size, drawn width): the largest size from `start` down that fits `width`."""
    size = start
    while True:
        drawn = _text_width(text_file, str(font), size)
        if drawn <= width or size <= smallest:
            return size, drawn
        size = max(smallest, int(size * min(0.95, width / drawn)))


def _name_lines(name: str, work: Path) -> tuple[list[Path], int]:
    """The name on one line when it stays big, otherwise split over two."""
    one = _write(work / "story_name0.txt", name)
    size, _ = _fit(one, SERIF, 150, 60, _TEXT_WIDTH)
    words = name.split()
    if size >= 110 or len(words) < 2:
        return [one], size
    cut = min(range(1, len(words)),
              key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    files = [_write(work / f"story_name{i}.txt", line)
             for i, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])])]
    sizes = [_fit(path, SERIF, 150, 60, _TEXT_WIDTH)[0] for path in files]
    return files, min(sizes)


def compose_story_thumbnail(subject: str, title: str, photo: Path, output_path: Path,
                            channel=None) -> Path:
    """Draw the card at 1280x720 from the subject's own (uncropped) photo."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    serif, italic = _escape(SERIF), _escape(SERIF_ITALIC)

    intro = _write(work / "story_intro.txt", "The story of")
    intro_size = 58
    intro_w = _text_width(intro, str(SERIF_ITALIC), intro_size)
    names, name_size = _name_lines(story_name(subject), work)
    sub = _write(work / "story_sub.txt", story_subtitle(title, subject))
    sub_size, _ = _fit(sub, SERIF_ITALIC, 60, 36, _TEXT_WIDTH)
    badge = _write(work / "story_badge.txt", str(getattr(channel, "name", "") or "").upper())

    # Bottom up: subtitle, name line(s), "The story of".
    sub_y = _BOTTOM - int(sub_size * 1.05)
    name_step = int(name_size * 1.02)
    name_top = sub_y - 18 - name_step * len(names)
    intro_y = name_top - int(intro_size * 1.25)

    text = [
        f"drawtext=fontfile='{italic}':textfile='{_escape(intro)}':fontsize={intro_size}:"
        f"fontcolor={_CREAM}:x={_LEFT}:y={intro_y}:{_SHADOW}",
        f"drawbox=x={_LEFT + intro_w + 22}:y={intro_y + int(intro_size * 0.42)}:w=120:h=12:"
        f"color={_GOLD}:t=fill",
        *[f"drawtext=fontfile='{serif}':textfile='{_escape(path)}':fontsize={name_size}:"
          f"fontcolor={_CREAM}:x={_LEFT}:y={name_top + index * name_step}:{_SHADOW}"
          for index, path in enumerate(names)],
        f"drawtext=fontfile='{italic}':textfile='{_escape(sub)}':fontsize={sub_size}:"
        f"fontcolor={_GOLD}:x={_LEFT}:y={sub_y}:{_SHADOW}",
        f"drawbox=x=40:y=70:w=6:h={THUMB_HEIGHT - 140}:color={_GOLD}:t=fill",
    ]
    if badge.read_text(encoding="utf-8"):
        text.append(f"drawtext=fontfile='{serif}':textfile='{_escape(badge)}':fontsize=26:"
                    f"fontcolor={_GOLD}:x=w-tw-40:y=34:{_SHADOW}")

    size = f"{THUMB_WIDTH}:{THUMB_HEIGHT}"
    r, g, b = _PANEL
    graph = ";".join([
        # The photo blurred and darkened behind everything, so nothing is empty.
        f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
        "boxblur=30:3,eq=brightness=-0.22:saturation=0.6[bg]",
        # The sharp photo on the right, its left edge feathered.
        f"[0:v]scale=-2:{THUMB_HEIGHT},crop='min(iw,{_PHOTO_MAX_W})':ih,format=rgba,"
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*min(1,X/160)'[fg]",
        "[bg][fg]overlay=x=W-w:y=0[pic]",
        # The text panel: solid on the left, gone by the middle of the photo.
        f"color=c=black:s={THUMB_WIDTH}x{THUMB_HEIGHT},format=rgba,"
        f"geq=r='{r}':g='{g}':b='{b}':a='255*clip((900-X)/500,0,1)'[shade]",
        "[pic][shade]overlay=0:0," + ",".join(text) + "[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", "-i", str(photo), "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
