"""The true-story thumbnail: the person on the left, "THE UNTOLD LIFE OF NAME" on the right.

A movie-poster card. The subject's own photo, cut out of its background
(rembg), stands large on the left in front of a dramatic stock backdrop
(Pexels) graded blue and orange. On the right: "THE / UNTOLD / LIFE OF" in
silver capitals, the name in gold over a red brush stroke, a pointed
"RISE • FAME • LEGACY" ribbon, a slanted red "TRUE STORY" tag, and the
channel's brand in the corner. Without rembg or a Pexels key the photo itself
is used, feathered into a blurred copy of itself.
Used for channels whose videos are about one real person (verified_facts).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .config import settings
from .presenter import _escape, _text_width
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

CAPS = settings.root / "fonts" / "Cinzel-Black.ttf"
SERIF = settings.root / "fonts" / "DMSerifDisplay-Regular.ttf"
TAG_FONT = settings.root / "fonts" / "ArchivoBlack-Regular.ttf"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_GOLD = "0xE8B64A"
_COLUMN_X, _COLUMN_W = 590, 670  # the text column on the right
_MID = _COLUMN_X + _COLUMN_W // 2
_BANNER = "RISE  •  FAME  •  LEGACY"
# Backdrops searched on Pexels, one picked per person so videos differ.
_BACKDROPS = ["red carpet event lights", "stage spotlight dark", "hollywood night lights",
              "cinema theater dark", "city skyline night dramatic", "dramatic sunset clouds",
              "film set lights", "concert stage lights smoke"]
_CUTOUT_MODEL = "isnet-general-use"
_MARGIN = 30  # the same space above the tag and below the ribbon
_CAP = 0.72   # Cinzel's capitals run from drawtext's y to y + 0.72 * size
_GAP = 0.2    # between stacked lines, as a share of the smaller line's size


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
    size, drawn = _fit(one, CAPS, 150, 56, _COLUMN_W)
    words = name.split()
    if size >= 108 or len(words) < 2:
        return [(one, drawn)], size
    cut = min(range(1, len(words)),
              key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    files = [_write(work / f"story_name{i}.txt", line)
             for i, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])])]
    size = min(_fit(path, CAPS, 136, 56, _COLUMN_W)[0] for path in files)
    return [(path, _text_width(path, str(CAPS), size)) for path in files], size


def _cutout(photo: Path, out: Path) -> Path | None:
    """The person without their background (transparent PNG), or None without rembg."""
    try:
        from rembg import new_session, remove

        cut = remove(photo.read_bytes(), session=new_session(_CUTOUT_MODEL))
        out.write_bytes(_largest_figure(cut))
        return out
    except Exception as exc:
        print(f"[thumbnail] no cut-out, using the whole photo: {exc}")
        return None


def _largest_figure(png: bytes) -> bytes:
    """Keep only the biggest shape of the cut-out: the subject, not a shoulder beside them."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return png
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        return png
    alpha = image[:, :, 3]
    count, labels, stats, _ = cv2.connectedComponentsWithStats((alpha > 100).astype(np.uint8))
    if count <= 2:
        return png
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = cv2.dilate((labels == biggest).astype(np.uint8), np.ones((9, 9), np.uint8))
    image[:, :, 3] = alpha * keep
    return cv2.imencode(".png", image)[1].tobytes()


def _backdrop(subject: str, out: Path) -> Path | None:
    """A dramatic landscape stock photo from Pexels, or None without a key/result."""
    from .thumbnails import pexels_api_key

    key = pexels_api_key()
    if not key:
        return None
    seed = int(hashlib.sha1(subject.encode("utf-8")).hexdigest(), 16)
    query = _BACKDROPS[seed % len(_BACKDROPS)]
    try:
        request = urllib.request.Request(
            "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
                {"query": query, "orientation": "landscape", "size": "large", "per_page": 15}),
            headers={"Authorization": key, "User-Agent": "story-bot-studio"})
        with urllib.request.urlopen(request, timeout=20) as response:
            photos = json.load(response).get("photos") or []
        if not photos:
            return None
        chosen = photos[(seed // 7) % len(photos)]
        # Pexels' image host refuses Python's default User-Agent.
        image = urllib.request.Request(chosen["src"]["large2x"],
                                       headers={"User-Agent": "Mozilla/5.0 story-bot-studio"})
        with urllib.request.urlopen(image, timeout=30) as response:
            out.write_bytes(response.read())
        return out
    except Exception as exc:
        print(f"[thumbnail] no backdrop from Pexels ({query}): {exc}")
        return None


def _drawtext(text_file: Path, font: Path, size: int, y: int, color: str, x: str | None = None,
              extra: str = "") -> str:
    x = x or f"{_MID}-tw/2"
    return (f"drawtext=fontfile='{_escape(font)}':textfile='{_escape(text_file)}':fontsize={size}:"
            f"fontcolor={color}:x={x}:y={y}" + (f":{extra}" if extra else ""))


def _gradient_layer(name: str, texts: list[str], top: int, bottom: int,
                    light: tuple[int, int, int], dark: tuple[int, int, int]) -> list[str]:
    """Graph lines making [name]: the white `texts` filled with a top-to-bottom gradient."""
    span = max(1, bottom - top)
    channel = lambda a, b: f"'{a}-{a - b}*clip((Y-{top})/{span},0,1)'"  # noqa: E731
    return [
        f"color=c=black:s={W}x{H},{','.join(texts)},format=gray[{name}_m]",
        f"color=c=black:s={W}x{H},format=rgb24,geq=r={channel(light[0], dark[0])}:"
        f"g={channel(light[1], dark[1])}:b={channel(light[2], dark[2])}[{name}_g]",
        f"[{name}_g][{name}_m]alphamerge[{name}]",
    ]


def compose_story_thumbnail(subject: str, title: str, photo: Path, output_path: Path,
                            channel=None) -> Path:
    """Draw the card at 1280x720 from the subject's own (uncropped) photo."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    cutout = _cutout(photo, work / "story_cutout.png")
    backdrop = _backdrop(subject, work / "story_backdrop.jpg")

    # ---- the words, laid out top to bottom in the right-hand column
    the = _write(work / "story_the.txt", "THE")
    untold = _write(work / "story_untold.txt", "UNTOLD")
    life = _write(work / "story_life.txt", "LIFE OF")
    names, name_size = _name_lines(story_name(subject), work)
    banner = _write(work / "story_banner.txt", _BANNER)
    banner_w = _text_width(banner, str(CAPS), 40)
    tag = _write(work / "story_tag.txt", "TRUE STORY")
    tag_w = _text_width(tag, str(TAG_FONT), 42)

    # The tag's top and the ribbon's bottom sit the same distance from the
    # frame; the words are centred in the space between them, smaller if needed.
    ty1, ty2 = _MARGIN, _MARGIN + 72
    banner_h = 74
    banner_y = H - _MARGIN - banner_h
    room_top, room_bottom = ty2 + 26, banner_y - 34  # the brush stroke hangs below the name
    sizes = [58, 112, 88] + [name_size] * len(names)

    def stacked(scale: float) -> list[int]:
        return [max(24, int(size * scale)) for size in sizes]

    def height(scaled: list[int]) -> float:
        caps = sum(size * _CAP for size in scaled)
        return caps + sum(_GAP * min(a, b) for a, b in zip(scaled, scaled[1:]))

    scale = min(1.0, (room_bottom - room_top) / height(sizes))
    sizes = stacked(scale)
    y = room_top + (room_bottom - room_top - height(sizes)) / 2
    tops = []
    for index, size in enumerate(sizes):
        tops.append(int(round(y)))
        y += size * _CAP + (_GAP * min(size, sizes[index + 1]) if index + 1 < len(sizes) else 0)
    y_the, y_untold, y_life, name_top = tops[:4]
    sizes, name_size = sizes[:3], sizes[3]
    name_tops = tops[3:]
    name_bottom = int(name_tops[-1] + name_size * _CAP)
    widest = int(max(width for _, width in names) * scale)

    dark_edge = "borderw=4:bordercolor=0x1A0F04"
    silver_texts = [_drawtext(path, CAPS, size, y, "white")
                    for path, size, y in ((the, sizes[0], y_the), (untold, sizes[1], y_untold),
                                          (life, sizes[2], y_life))]
    gold_texts = [_drawtext(path, CAPS, name_size, top, "white")
                  for (path, _), top in zip(names, name_tops)]
    # Depth: a dark copy of every word, offset down-right, under the bright one.
    depth = [text.replace("fontcolor=white", "fontcolor=0x120A03") + f":{dark_edge}"
             for text in silver_texts + gold_texts]
    depth = [re.sub(r":y=(\d+)", lambda m: f":y={int(m.group(1)) + 6}",
                    re.sub(r"x=(\d+)-tw/2", lambda m: f"x={int(m.group(1)) + 4}-tw/2", text))
             for text in depth]

    # ---- shapes drawn with geq: brush stroke, ribbon, tag
    x1, x2 = _MID - widest // 2 - 70, _MID + widest // 2 + 40
    y0 = name_bottom + int(name_size * 0.06)
    thick = int(name_size * 0.36)
    stroke = (f"between(X,{x1},{x2})*lt(abs(Y-({y0}-(X-{x1})*0.06)),"
              f"{thick}*min(1,(X-{x1})/160)*min(1,({x2}-X)/60)*(0.8+0.2*sin(X/11+Y/3)))"
              f"*(0.7+0.3*sin(Y*1.9+X/37))")
    bx1, bx2 = _MID - banner_w // 2 - 70, _MID + banner_w // 2 + 70
    cy, half = banner_y + banner_h // 2, banner_h // 2
    outer = f"lt(abs(Y-{cy}),{half})*gte(X,{bx1}+abs(Y-{cy})*0.7)*lte(X,{bx2}-abs(Y-{cy})*0.7)"
    inner = (f"lt(abs(Y-{cy}),{half - 4})*gte(X,{bx1 + 6}+abs(Y-{cy})*0.7)"
             f"*lte(X,{bx2 - 6}-abs(Y-{cy})*0.7)")
    tx2 = W - 24
    tx1 = tx2 - tag_w - 80
    tag_shape = f"between(Y,{ty1},{ty2})*gte(X,{tx1}+({ty2}-Y)*0.3)*lte(X,{tx2}+({ty2}-Y)*0.3-22)"

    finish = [
        _drawtext(banner, CAPS, 40, cy - int(40 * _CAP / 2), "white", extra="shadowcolor=black@0.6:shadowx=2:shadowy=2"),
        _drawtext(tag, TAG_FONT, 42, ty1 + 14, "white", x=f"{tx1 + 40}",
                  extra="shadowcolor=black@0.4:shadowx=2:shadowy=2"),
    ]
    brand = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "")
    if brand:
        # "LegendraScope": the last capitalised part in gold, like the channel's logo.
        parts = re.match(r"^(.+?)([A-Z][a-z]+)$", brand.replace(" ", ""))
        first, second = (parts.group(1), parts.group(2)) if parts else (brand, "")
        first_file = _write(work / "story_brand1.txt", first)
        first_w = _text_width(first_file, str(SERIF), 48)
        logo = "borderw=2:bordercolor=black@0.6:shadowcolor=black@0.8:shadowx=3:shadowy=3"
        finish.append(_drawtext(first_file, SERIF, 48, 30, "white", x="36", extra=logo))
        if second:
            second_file = _write(work / "story_brand2.txt", second)
            finish.append(_drawtext(second_file, SERIF, 48, 30, _GOLD, x=f"{36 + first_w + 2}", extra=logo))

    # ---- the picture: backdrop, person, shading
    size = f"{W}:{H}"
    inputs = ["-i", str(backdrop or photo), "-i", str(cutout or photo)]
    sky = (f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
           + ("gblur=sigma=2,eq=brightness=-0.10:contrast=1.18:saturation=0.95,"
              if backdrop else "boxblur=40:4,eq=brightness=-0.28:saturation=0.7:contrast=1.1,")
           + "colorbalance=rs=-0.12:gs=0.02:bs=0.28:rh=0.22:gh=0.08:bh=-0.12,vignette=PI/4.5[bg]")
    person_h = int(H * 1.1) if cutout else H
    person = (f"[1:v]scale=-2:{person_h}:flags=lanczos,unsharp=5:5:0.9,"
              f"crop='min(iw,700)':ih,eq=contrast=1.08:saturation=1.08,format=rgba")
    if cutout:
        layers = [
            sky,
            person + ",split=2[p][p2]",
            # A soft dark halo around the person lifts them off the backdrop.
            "[p2]geq=r='0':g='0':b='0':a='alpha(X,Y)*0.85',gblur=sigma=22[halo]",
            "[bg][halo]overlay=x=26:y=34[bg2]",
            "[bg2][p]overlay=x=20:y=26[pic]",
        ]
    else:
        layers = [
            sky,
            person + ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*min(1,(W-X)/200)'[p]",
            "[bg][p]overlay=x=0:y=0[pic]",
        ]
    graph = ";".join([
        *layers,
        # Darker behind the words, so they read on any backdrop.
        f"color=c=black:s={W}x{H},format=rgba,"
        "geq=r='6':g='10':b='28':a='165*clip((X-540)/260,0,1)'[shade]",
        f"color=c=black:s={W}x{H},format=rgba,geq=r='196':g='16':b='24':a='245*{stroke}'[stroke]",
        f"color=c=black:s={W}x{H},format=rgba,"
        f"geq=r='if({inner},12,232)':g='if({inner},22,182)':b='if({inner},48,74)':a='238*{outer}'[ribbon]",
        f"color=c=black:s={W}x{H},format=rgba,geq=r='200':g='14':b='22':a='255*{tag_shape}'[tag]",
        *_gradient_layer("silver", silver_texts, y_the, y_life + sizes[2],
                         (255, 255, 255), (196, 202, 214)),
        *_gradient_layer("gold", gold_texts, name_top, name_bottom, (255, 236, 160), (196, 128, 26)),
        "[pic][shade]overlay=0:0," + ",".join(depth) + "[d]",
        "[d][stroke]overlay=0:0[s]",
        "[s][silver]overlay=0:0[s2]",
        "[s2][gold]overlay=0:0[s3]",
        "[s3][ribbon]overlay=0:0[s4]",
        "[s4][tag]overlay=0:0," + ",".join(finish) + "[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
