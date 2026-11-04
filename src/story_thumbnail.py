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
FACE_MODEL = settings.root / "third_party" / "face_detection_yunet_2023mar.onnx"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_GOLD = "0xE8B64A"
_COLUMN_X, _COLUMN_W = 590, 670  # the text column on the right
_MID = _COLUMN_X + _COLUMN_W // 2
_BANNER = "RISE  •  FAME  •  LEGACY"
# Backdrops searched on Pexels, one picked per person so videos differ.
# No streets or shops: their signs and logos would show up behind the person.
_BACKDROPS = ["stage spotlight dark", "concert stage lights smoke", "dramatic sunset clouds",
              "red theater curtain stage", "stormy sky dramatic", "golden bokeh lights",
              "film set lights", "dark cinema theater"]
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


def _name_lines(name: str, work: Path, width: int = _COLUMN_W,
                k: float = 1.0) -> tuple[list[tuple[Path, int]], int]:
    """([(text file, drawn width)], size): one line when it stays big, else two.

    k scales the font sizes for a bigger card (the vertical Shorts one)."""
    one = _write(work / "story_name0.txt", name)
    size, drawn = _fit(one, CAPS, int(150 * k), int(56 * k), width)
    words = name.split()
    if size >= 108 * k or len(words) < 2:
        return [(one, drawn)], size
    cut = min(range(1, len(words)),
              key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    files = [_write(work / f"story_name{i}.txt", line)
             for i, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])])]
    size = min(_fit(path, CAPS, int(136 * k), int(56 * k), width)[0] for path in files)
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


def _portrait(photo: Path, out: Path) -> Path:
    """Head and shoulders around the largest face, so the face is big and the
    table, microphone or crowd of a press photo is left out. The photo itself
    when no face is found."""
    try:
        import cv2

        image = cv2.imread(str(photo))
        if image is None:
            return photo
        height, width = image.shape[:2]
        # OpenCV's YuNet face model (third_party/, MIT licence).
        finder = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (width, height), 0.8)
        faces = finder.detect(image)[1]
    except Exception as exc:
        print(f"[thumbnail] face search skipped: {exc}")
        return photo
    if faces is None or len(faces) == 0:
        return photo
    x, y, fw, fh = (int(v) for v in max(faces, key=lambda face: face[2] * face[3])[:4])
    top, bottom = max(0, int(y - 0.7 * fh)), min(height, int(y + 2.4 * fh))
    left, right = max(0, int(x + fw / 2 - 1.5 * fw)), min(width, int(x + fw / 2 + 1.5 * fw))
    if (bottom - top) * (right - left) > 0.85 * height * width:
        return photo  # already a portrait
    cv2.imwrite(str(out), image[top:bottom, left:right])
    return out


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


def _backdrop(subject: str, out: Path, queries: list[str] = _BACKDROPS) -> Path | None:
    """A dramatic landscape stock photo from Pexels, or None without a key/result."""
    from .thumbnails import pexels_api_key

    key = pexels_api_key()
    if not key:
        return None
    seed = int(hashlib.sha1(subject.encode("utf-8")).hexdigest(), 16)
    query = queries[seed % len(queries)]
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
              extra: str = "", mid: int = _MID) -> str:
    x = x or f"{mid}-tw/2"
    return (f"drawtext=fontfile='{_escape(font)}':textfile='{_escape(text_file)}':fontsize={size}:"
            f"fontcolor={color}:x={x}:y={y}" + (f":{extra}" if extra else ""))


def _gradient_layer(name: str, texts: list[str], top: int, bottom: int,
                    light: tuple[int, int, int], dark: tuple[int, int, int],
                    w: int = W, h: int = H) -> list[str]:
    """Graph lines making [name]: the white `texts` filled with a top-to-bottom gradient."""
    span = max(1, bottom - top)
    channel = lambda a, b: f"'{a}-{a - b}*clip((Y-{top})/{span},0,1)'"  # noqa: E731
    return [
        f"color=c=black:s={w}x{h},{','.join(texts)},format=gray[{name}_m]",
        f"color=c=black:s={w}x{h},format=rgb24,geq=r={channel(light[0], dark[0])}:"
        f"g={channel(light[1], dark[1])}:b={channel(light[2], dark[2])}[{name}_g]",
        f"[{name}_g][{name}_m]alphamerge[{name}]",
    ]


def compose_story_thumbnail(subject: str, title: str, photo: Path, output_path: Path,
                            channel=None, vertical: bool = False) -> Path:
    """Draw the card from the subject's own (uncropped) photo.

    1280x720 with the person on the left and the words on the right, or for a
    Short (vertical=True) 1080x1920 with the person above the words.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    # A channel with a design spec of its own (data/brand/<id>/thumbnail_spec.json)
    # gets the cinematic poster; any failure falls back to this card.
    from .cinematic_thumbnail import load_spec

    if channel is not None and load_spec(str(getattr(channel, "id", "") or "")):
        try:
            from .cinematic_thumbnail import compose

            return compose(subject, photo, output_path, channel, vertical=vertical)
        except Exception as exc:
            print(f"[thumbnail] cinematic design failed, using the plain story card: {exc}")
    photo = _portrait(photo, work / "story_portrait.jpg")
    cutout = _cutout(photo, work / "story_cutout.png")
    backdrop = _backdrop(subject, work / "story_backdrop.jpg")

    # k scales the words; corner_k the brand and tag, which must share the top row.
    if vertical:
        # The Shorts shelf crops about 8% off the top and the bottom: 190px clear.
        w, h, margin, k, corner_k = 1080, 1920, 190, 1.4, 1.1
        side = 48  # the shelf keeps the full width
        col_x, col_w = 60, 960
    else:
        w, h, margin, k, corner_k = W, H, _MARGIN, 1.0, 1.0
        side = margin
        col_x, col_w = _COLUMN_X, _COLUMN_W
    mid = col_x + col_w // 2

    # ---- the words, laid out top to bottom in the text column
    the = _write(work / "story_the.txt", "THE")
    untold = _write(work / "story_untold.txt", "UNTOLD")
    life = _write(work / "story_life.txt", "LIFE OF")
    names, name_size = _name_lines(story_name(subject), work, col_w, k)
    banner_size, tag_size, brand_size = int(40 * k), int(42 * corner_k), int(48 * corner_k)
    banner = _write(work / "story_banner.txt", _BANNER)
    banner_w = _text_width(banner, str(CAPS), banner_size)
    tag = _write(work / "story_tag.txt", "TRUE STORY")
    tag_w = _text_width(tag, str(TAG_FONT), tag_size)

    # The tag's top and the ribbon's bottom sit the same distance from the
    # frame; the words are centred in the space left for them, smaller if needed.
    ty1, ty2 = margin, margin + int(72 * corner_k)
    banner_h = int(74 * k)
    banner_y = h - margin - banner_h
    # On a Short the person fills the top; the words take the lower part.
    room_top = int(h * 0.56) if vertical else ty2 + 26
    room_bottom = banner_y - int(34 * k)  # the brush stroke hangs below the name
    sizes = [int(58 * k), int(112 * k), int(88 * k)] + [name_size] * len(names)

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

    dark_edge = f"borderw={max(4, int(4 * k))}:bordercolor=0x1A0F04"
    silver_texts = [_drawtext(path, CAPS, size, y, "white", mid=mid)
                    for path, size, y in ((the, sizes[0], y_the), (untold, sizes[1], y_untold),
                                          (life, sizes[2], y_life))]
    gold_texts = [_drawtext(path, CAPS, name_size, top, "white", mid=mid)
                  for (path, _), top in zip(names, name_tops)]
    # Depth: a dark copy of every word, offset down-right, under the bright one.
    depth = [text.replace("fontcolor=white", "fontcolor=0x120A03") + f":{dark_edge}"
             for text in silver_texts + gold_texts]
    depth = [re.sub(r":y=(\d+)", lambda m: f":y={int(m.group(1)) + int(6 * k)}",
                    re.sub(r"x=(\d+)-tw/2", lambda m: f"x={int(m.group(1)) + int(4 * k)}-tw/2", text))
             for text in depth]

    # ---- shapes drawn with geq: brush stroke, ribbon, tag
    x1, x2 = mid - widest // 2 - int(70 * k), mid + widest // 2 + int(40 * k)
    y0 = name_bottom + int(name_size * 0.06)
    thick = int(name_size * 0.36)
    stroke = (f"between(X,{x1},{x2})*lt(abs(Y-({y0}-(X-{x1})*0.06)),"
              f"{thick}*min(1,(X-{x1})/160)*min(1,({x2}-X)/60)*(0.8+0.2*sin(X/11+Y/3)))"
              f"*(0.7+0.3*sin(Y*1.9+X/37))")
    bx1, bx2 = mid - banner_w // 2 - int(70 * k), mid + banner_w // 2 + int(70 * k)
    cy, half = banner_y + banner_h // 2, banner_h // 2
    edge = max(4, int(4 * k))
    outer = f"lt(abs(Y-{cy}),{half})*gte(X,{bx1}+abs(Y-{cy})*0.7)*lte(X,{bx2}-abs(Y-{cy})*0.7)"
    inner = (f"lt(abs(Y-{cy}),{half - edge})*gte(X,{bx1 + edge + 2}+abs(Y-{cy})*0.7)"
             f"*lte(X,{bx2 - edge - 2}-abs(Y-{cy})*0.7)")
    # A slanted tag whose top-right corner is `margin` from both the top and the
    # right edge; its text centred on the slant's middle.
    slant = 0.3
    tx2 = w - side - int((ty2 - ty1) * slant)
    tx1 = tx2 - tag_w - int(80 * corner_k)
    tag_shape = f"between(Y,{ty1},{ty2})*gte(X,{tx1}+({ty2}-Y)*{slant})*lte(X,{tx2}+({ty2}-Y)*{slant})"
    tag_mid = (tx1 + tx2) // 2 + int((ty2 - ty1) / 2 * slant)

    finish = [
        _drawtext(banner, CAPS, banner_size, cy - int(banner_size * _CAP / 2), "white", mid=mid,
                  extra="shadowcolor=black@0.6:shadowx=2:shadowy=2"),
        # Archivo Black's capitals are 0.70 of the size tall, starting at y.
        _drawtext(tag, TAG_FONT, tag_size, ty1 + int((ty2 - ty1 - tag_size * 0.70) / 2), "white",
                  x=f"{tag_mid}-tw/2", extra="shadowcolor=black@0.4:shadowx=2:shadowy=2"),
    ]
    brand = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "")
    if brand:
        # "LegendraScope": the last capitalised part in gold, like the channel's logo.
        parts = re.match(r"^(.+?)([A-Z][a-z]+)$", brand.replace(" ", ""))
        first, second = (parts.group(1), parts.group(2)) if parts else (brand, "")
        first_file = _write(work / "story_brand1.txt", first)
        first_w = _text_width(first_file, str(SERIF), brand_size)
        logo = "borderw=2:bordercolor=black@0.6:shadowcolor=black@0.8:shadowx=3:shadowy=3"
        finish.append(_drawtext(first_file, SERIF, brand_size, margin, "white",
                                x=f"{side + 6}", extra=logo))
        if second:
            second_file = _write(work / "story_brand2.txt", second)
            finish.append(_drawtext(second_file, SERIF, brand_size, margin, _GOLD,
                                    x=f"{side + 6 + first_w + 2}", extra=logo))

    # ---- the picture: backdrop, person, shading
    size = f"{w}:{h}"
    inputs = ["-i", str(backdrop or photo), "-i", str(cutout or photo)]
    sky = (f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
           # Blurred enough that shop signs and logos in the stock photo cannot be read.
           + ("gblur=sigma=11,eq=brightness=-0.03:contrast=1.18:saturation=1.05,"
              if backdrop else "boxblur=40:4,eq=brightness=-0.28:saturation=0.7:contrast=1.1,")
           + "colorbalance=rs=-0.12:gs=0.02:bs=0.28:rh=0.22:gh=0.08:bh=-0.12,vignette=PI/4.5[bg]")
    if vertical:
        # The person centred in the top two thirds, under the brand and the tag.
        person_h, max_w, px, py = int(h * 0.62), w, "(W-w)/2", f"{ty2 + 20}"
        feather = "a='255*min(1,(H-Y)/260)'"  # without a cut-out, fade the photo's foot
    else:
        person_h, max_w = (int(h * 1.1) if cutout else h), 700
        px, py = ("20", "26") if cutout else ("0", "0")
        feather = "a='255*min(1,(W-X)/200)'"
    person = (f"[1:v]scale=-2:{person_h}:flags=lanczos,unsharp=5:5:0.9,"
              f"crop='min(iw,{max_w})':ih,eq=contrast=1.08:saturation=1.08,format=rgba")
    if cutout:
        if vertical:
            # A head-and-shoulders crop ends in a straight line; fade it into the words.
            person += ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*min(1,(H-Y)/300)'"
        layers = [
            sky,
            person + ",split=2[p][p2]",
            # A soft dark halo around the person lifts them off the backdrop.
            # Padded first, so the blur fades out instead of stopping at the photo's edge.
            "[p2]pad=iw+120:ih+120:60:60:color=black@0,"
            "geq=r='0':g='0':b='0':a='alpha(X,Y)*0.85',gblur=sigma=22[halo]",
            # A centred x stays centred with the wider halo; a fixed x moves by the padding.
            f"[bg][halo]overlay=x={px + '+6' if vertical else px + '-54'}:y={py}-52[bg2]",
            f"[bg2][p]overlay=x={px}:y={py}[pic]",
        ]
    else:
        layers = [
            sky,
            person + f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':{feather}[p]",
            f"[bg][p]overlay=x={px}:y={py}[pic]",
        ]
    # Darker behind the words, so they read on any backdrop.
    shade_alpha = (f"190*clip((Y-{int(h * 0.48)})/{int(h * 0.12)},0,1)" if vertical
                   else "165*clip((X-540)/260,0,1)")
    graph = ";".join([
        *layers,
        f"color=c=black:s={w}x{h},format=rgba,geq=r='6':g='10':b='28':a='{shade_alpha}'[shade]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='196':g='16':b='24':a='245*{stroke}'[stroke]",
        f"color=c=black:s={w}x{h},format=rgba,"
        f"geq=r='if({inner},12,232)':g='if({inner},22,182)':b='if({inner},48,74)':a='238*{outer}'[ribbon]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='200':g='14':b='22':a='255*{tag_shape}'[tag]",
        *_gradient_layer("silver", silver_texts, y_the, int(y_life + sizes[2] * _CAP),
                         (255, 255, 255), (196, 202, 214), w, h),
        *_gradient_layer("gold", gold_texts, name_top, name_bottom, (255, 236, 160), (196, 128, 26), w, h),
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
