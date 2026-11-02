"""The true-story thumbnail: the person on the left, "THE UNTOLD LIFE OF NAME" on the right.

A movie-poster card: the subject's own photo large on the left over a dark,
blue-graded copy of itself; on the right white serif capitals, the name in
gold over a red brush stroke, a "RISE • FAME • LEGACY" banner, a red
"TRUE STORY" tag and the channel's brand in the corner. Used for channels
whose videos are about one real person (verified_facts channels).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _escape, _text_width
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

CAPS = settings.root / "fonts" / "Cinzel-Black.ttf"
SERIF = settings.root / "fonts" / "DMSerifDisplay-Regular.ttf"
TAG_FONT = settings.root / "fonts" / "ArchivoBlack-Regular.ttf"
_GOLD = "0xE8B64A"
_RED = "0xC8141E"
_NAVY = "0x0B1630"
_COLUMN_X, _COLUMN_W = 600, 650  # the text column on the right
_PHOTO_MAX_W = 700
_BANNER = "RISE  •  FAME  •  LEGACY"
_OUTLINE = "borderw=3:bordercolor=black@0.55:shadowcolor=black@0.7:shadowx=4:shadowy=5"


def story_name(subject: str) -> str:
    """'Emma Thompson (actress)' -> 'EMMA THOMPSON'."""
    return re.sub(r"\s*\(.*?\)", "", subject).strip().upper()


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


def _name_lines(name: str, work: Path) -> tuple[list[tuple[Path, int]], int]:
    """([(text file, drawn width)], size): one line when it stays big, else two."""
    one = _write(work / "story_name0.txt", name)
    size, drawn = _fit(one, CAPS, 140, 56, _COLUMN_W)
    words = name.split()
    if size >= 104 or len(words) < 2:
        return [(one, drawn)], size
    cut = min(range(1, len(words)),
              key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    files = [_write(work / f"story_name{i}.txt", line)
             for i, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])])]
    size = min(_fit(path, CAPS, 130, 56, _COLUMN_W)[0] for path in files)
    return [(path, _text_width(path, str(CAPS), size)) for path in files], size


def _centered(text_file: Path, font: Path, size: int, y: int, color: str, extra: str = "") -> str:
    return (f"drawtext=fontfile='{_escape(font)}':textfile='{_escape(text_file)}':fontsize={size}:"
            f"fontcolor={color}:x={_COLUMN_X + _COLUMN_W // 2}-tw/2:y={y}" + (f":{extra}" if extra else ""))


def compose_story_thumbnail(subject: str, title: str, photo: Path, output_path: Path,
                            channel=None) -> Path:
    """Draw the card at 1280x720 from the subject's own (uncropped) photo."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    mid = _COLUMN_X + _COLUMN_W // 2

    top_size = 76
    line1 = _write(work / "story_line1.txt", "THE UNTOLD")
    line2 = _write(work / "story_line2.txt", "LIFE OF")
    names, name_size = _name_lines(story_name(subject), work)
    banner = _write(work / "story_banner.txt", _BANNER)
    banner_w = _text_width(banner, str(CAPS), 38)
    tag = _write(work / "story_tag.txt", "TRUE STORY")
    tag_w = _text_width(tag, str(TAG_FONT), 40)
    brand = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "")

    # Top to bottom, the whole block centred in the column under the tag.
    line_step = int(top_size * 1.08)
    name_step = int(name_size * 1.0)
    banner_h = 72
    block = 2 * line_step + 10 + name_step * len(names) + 34 + banner_h
    top = max(118, 112 + (THUMB_HEIGHT - 150 - block) // 2)
    name_top = top + 2 * line_step + 10
    name_bottom = name_top + name_step * len(names)
    banner_y = name_bottom + 34
    widest = max(width for _, width in names)

    text = [
        _centered(line1, CAPS, top_size, top, "white", _OUTLINE),
        _centered(line2, CAPS, top_size, top + line_step, "white", _OUTLINE),
        # A dark offset copy under the gold letters gives them depth.
        *[_centered(path, CAPS, name_size, name_top + i * name_step + 5, "0x2A1704",
                    "borderw=4:bordercolor=0x2A1704")
          for i, (path, _) in enumerate(names)],
    ]
    banner_x = mid - (banner_w + 80) // 2
    finish = [
        f"drawbox=x={banner_x}:y={banner_y}:w={banner_w + 80}:h={banner_h}:color={_NAVY}@0.92:t=fill",
        f"drawbox=x={banner_x}:y={banner_y}:w={banner_w + 80}:h={banner_h}:color={_GOLD}:t=3",
        f"drawbox=x={banner_x + 7}:y={banner_y + 7}:w={banner_w + 66}:h={banner_h - 14}:color={_GOLD}@0.6:t=1",
        _centered(banner, CAPS, 38, banner_y + (banner_h - 38) // 2 - 2, "white"),
        f"drawbox=x={THUMB_WIDTH - tag_w - 70}:y=28:w={tag_w + 70}:h=70:color={_RED}:t=fill",
        f"drawtext=fontfile='{_escape(TAG_FONT)}':textfile='{_escape(tag)}':fontsize=40:"
        f"fontcolor=white:x={THUMB_WIDTH - tag_w - 35}:y=40",
    ]
    if brand:
        # "LegendraScope": the last capitalised part in gold, like the channel's logo.
        parts = re.match(r"^(.*?)([A-Z][a-z]+)$", brand.replace(" ", "")) or None
        first, second = (parts.group(1), parts.group(2)) if parts and parts.group(1) else (brand, "")
        first_file = _write(work / "story_brand1.txt", first)
        first_w = _text_width(first_file, str(SERIF), 46)
        finish.append(f"drawtext=fontfile='{_escape(SERIF)}':textfile='{_escape(first_file)}':"
                      f"fontsize=46:fontcolor=white:x=34:y=28:{_OUTLINE}")
        if second:
            second_file = _write(work / "story_brand2.txt", second)
            finish.append(f"drawtext=fontfile='{_escape(SERIF)}':textfile='{_escape(second_file)}':"
                          f"fontsize=46:fontcolor={_GOLD}:x={34 + first_w + 2}:y=28:{_OUTLINE}")

    # The red brush stroke: a slightly rising band behind the lower half of the name.
    x1, x2 = mid - widest // 2 - 40, mid + widest // 2 + 50
    y0 = name_bottom - int(name_size * 0.22)
    stroke = (f"between(X,{x1},{x2})*lt(abs(Y-({y0}-(X-{x1})*0.035)),"
              f"{int(name_size * 0.32)}*min(1,(X-{x1})/90)*min(1,({x2}-X)/160)*(0.85+0.15*sin(X/9)))")

    size = f"{THUMB_WIDTH}:{THUMB_HEIGHT}"
    gold_top, gold_h = name_top, max(1, name_step * len(names))
    shade = lambda c, d: f"'{c}-{d}*clip((Y-{gold_top})/{gold_h},0,1)'"  # noqa: E731
    name_masks = ",".join(
        f"drawtext=fontfile='{_escape(CAPS)}':textfile='{_escape(path)}':fontsize={name_size}:"
        f"fontcolor=white:x={mid}-tw/2:y={name_top + i * name_step}"
        for i, (path, _) in enumerate(names))
    graph = ";".join([
        "[0:v]split=2[a][b]",
        # The photo blurred, darkened and graded blue as the sky behind everything.
        f"[a]scale={size}:force_original_aspect_ratio=increase,crop={size},boxblur=40:4,"
        "eq=brightness=-0.30:saturation=0.75:contrast=1.1,"
        "colorbalance=rs=-0.15:bs=0.30:bm=0.12:rh=0.20:gh=0.05,vignette=PI/4[bg]",
        # The sharp photo large on the left, its right edge feathered away.
        f"[b]scale=-2:{THUMB_HEIGHT},crop='min(iw,{_PHOTO_MAX_W})':ih,"
        "eq=contrast=1.08:saturation=1.1,format=rgba,"
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*min(1,(W-X)/200)'[fg]",
        "[bg][fg]overlay=x=0:y=0[pic]",
        # Darker behind the words, so they read on any photo.
        f"color=c=black:s={THUMB_WIDTH}x{THUMB_HEIGHT},format=rgba,"
        "geq=r='8':g='14':b='34':a='150*clip((X-520)/300,0,1)'[shade]",
        f"color=c=black:s={THUMB_WIDTH}x{THUMB_HEIGHT},format=rgba,"
        f"geq=r='205':g='18':b='28':a='235*{stroke}'[stroke]",
        # The name in a gold gradient: white letters used as the gold layer's alpha.
        f"color=c=black:s={THUMB_WIDTH}x{THUMB_HEIGHT},{name_masks},format=gray[mask]",
        f"color=c=black:s={THUMB_WIDTH}x{THUMB_HEIGHT},format=rgb24,"
        f"geq=r={shade(255, 40)}:g={shade(232, 92)}:b={shade(150, 120)}[grad]",
        "[grad][mask]alphamerge[gold]",
        "[pic][shade]overlay=0:0," + ",".join(text) + "[t]",
        "[t][stroke]overlay=0:0[s]",
        "[s][gold]overlay=0:0," + ",".join(finish) + "[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", "-i", str(photo), "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
