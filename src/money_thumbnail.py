"""The personal-finance thumbnail: a magazine-cover headline beside a real money photo.

DimeHorizon's card (1280x720, or 1080x1920 for a Short). A realistic stock
photo of the topic (a jar of savings, a credit card, a receipt; Pexels) fills
the card, darkened to charcoal on the left where the headline stands in
Archivo Black capitals, ivory, with the words marked *like this* in charcoal
on a slanted gold band. The channel's logo sits top left ("Dime" ivory,
"Horizon" teal, a teal underline) and a "DH" monogram in a teal corner
bottom right. Fine grain and a soft vignette; no glow.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _text_width
from .space_thumbnail import _lines
from .story_thumbnail import _backdrop, _drawtext, _fit, _write
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

TITLE = settings.root / "fonts" / "ArchivoBlack-Regular.ttf"
LOGO = settings.root / "fonts" / "Poppins-BoldItalic.ttf"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_CAP = 0.70     # Archivo Black's capitals run from drawtext's y to y + 0.70 * size
_IVORY = "0xF5F1E8"
_CHARCOAL = "0x101820"
_GOLD = (213, 165, 71)
_TEAL = (29, 233, 200)
_BACKDROPS = ["dollar bills on table", "wallet with cash", "calculator and bills", "credit card close up",
              "coins stack", "savings jar money"]


def compose_money_thumbnail(headline: str, photo: Path | None, output_path: Path, channel=None,
                            scene: str = "", vertical: bool = False) -> Path:
    """Draw the card. `headline` marks its gold-band words with *stars*; `scene`
    names the photo to search for; `photo` stands in when the search finds nothing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    picture = _backdrop(headline, work / "money_photo.jpg", [scene] if scene else _BACKDROPS) or photo
    if not picture:
        raise RuntimeError("no photo for the money card")
    if vertical:
        # The Shorts shelf crops about 8% off the top and the bottom: 190px clear.
        w, h, k, top, bottom, left = 1080, 1920, 1.45, 190, 190, 70
        column, chars, kt = w - 2 * left, 10, 1.75
    else:
        w, h, k, top, bottom, left = W, H, 1.0, 34, 40, 42
        column, chars, kt = 640, 10, 1.3

    # ---- the logo, top left: "Dime" ivory, "Horizon" teal, a teal underline
    brand = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "DimeHorizon").replace(" ", "")
    parts = re.match(r"^(.+?)([A-Z][a-z]+)$", brand)
    first, second = (parts.group(1), parts.group(2)) if parts else (brand, "")
    logo_size = int(40 * k)
    first_file = _write(work / "money_logo1.txt", first)
    second_file = _write(work / "money_logo2.txt", second or " ")
    first_w = _text_width(first_file, str(LOGO), logo_size)
    second_w = _text_width(second_file, str(LOGO), logo_size) if second else 0
    teal = "0x{:02X}{:02X}{:02X}".format(*_TEAL)
    logo = [_drawtext(first_file, LOGO, logo_size, top, _IVORY, x=str(left),
                      extra="shadowcolor=black@0.6:shadowx=2:shadowy=2"),
            _drawtext(second_file, LOGO, logo_size, top, teal, x=str(left + first_w + 2),
                      extra="shadowcolor=black@0.6:shadowx=2:shadowy=2")]
    bar_y, bar_w = top + int(logo_size * 1.18), first_w + second_w
    underline = (f"between(Y,{bar_y},{bar_y + int(5 * k)})*between(X,{left},{left + bar_w})"
                 f"*clip(1-(X-{left})/{max(1, bar_w)}*0.8,0,1)")

    # ---- the headline, centred in the space below the logo
    lines = _lines(headline, chars)[:4]
    files, sizes = [], []
    for index, (text, gold) in enumerate(lines):
        path = _write(work / f"money_line{index}.txt", text)
        start = (118 if gold else 104) if len(lines) <= 3 else (96 if gold else 86)
        files.append(path)
        sizes.append(_fit(path, TITLE, int(start * kt), int(48 * k), column - int(40 * k))[0])
    gap = [int(size * (0.42 if gold else 0.22)) for size, (_, gold) in zip(sizes, lines)]
    block = sum(int(size * _CAP) for size in sizes) + sum(gap[:-1])
    room_top = bar_y + int(40 * k)
    room_bottom = (int(h * 0.62) if vertical else h - bottom)
    if vertical:
        # On a Short the photo takes the top; the words sit low, above the bottom margin.
        room_top, room_bottom = int(h * 0.52), h - bottom
    y = room_top + max(0, (room_bottom - room_top - block) // 2)
    texts, bands = [], []
    edge = "shadowcolor=black@0.7:shadowx=3:shadowy=5"
    for path, size, (text, gold), space in zip(files, sizes, lines, gap):
        if gold:
            width = _text_width(path, str(TITLE), size)
            pad_x, pad_y = int(size * 0.18), int(size * 0.20)
            y1, y2 = y - pad_y, y + int(size * _CAP) + pad_y
            x1, x2 = left - pad_x // 2, left + width + pad_x
            bands.append((x1, x2, y1, y2))
            texts.append(_drawtext(path, TITLE, size, y, _CHARCOAL, x=str(left + pad_x // 3)))
        else:
            texts.append(_drawtext(path, TITLE, size, y, _IVORY, x=str(left), extra=edge))
        y += int(size * _CAP) + space

    slant = 0.12
    band = "+".join(f"between(Y,{y1},{y2})*gte(X,{x1}+({y2}-Y)*{slant})*lte(X,{x2}+({y2}-Y)*{slant})"
                    for x1, x2, y1, y2 in bands) or "0"

    # ---- the "DH" monogram in a teal quarter circle, bottom right
    radius = int(150 * k)
    # On a Short the corner sits above the shelf crop.
    cy = h - (bottom - 40 if vertical else 0)
    corner = f"hypot(X-{w},Y-{cy})"
    mono_file = _write(work / "money_mono.txt",
                       "".join(word[0] for word in re.findall(r"[A-Z][a-z]*", brand))[:2] or "DH")
    mono_size = int(46 * k)
    mono = _drawtext(mono_file, LOGO, mono_size, cy - int(radius * 0.45) - int(mono_size * 0.5), _IVORY,
                     x=f"{w - int(radius * 0.42)}-tw/2")

    # ---- the picture: the photo, charcoal from the left (on a Short: from the bottom)
    size = f"{w}:{h}"
    if vertical:
        shade = f"min(250,235*clip((Y-{int(h * 0.40)})/{int(h * 0.18)},0,1)+90*clip(1-Y/{int(h * 0.12)},0,1))"
    else:
        # Kept under 255: geq wraps a larger alpha round to a light band.
        shade = f"min(248,242*clip(({int(w * 0.62)}-X)/{int(w * 0.30)},0,1)+70*clip(1-Y/{int(h * 0.22)},0,1))"
    graph = ";".join([
        f"[0:v]scale={size}:force_original_aspect_ratio=increase,"
        + (f"crop={size}" if vertical else f"crop={w}:{h}:(iw-{w})*0.85:(ih-{h})/2")
        + ",eq=contrast=1.12:saturation=1.05:brightness=-0.02,"
        "colorbalance=rs=-0.03:bs=0.03:rh=0.05:bh=-0.03,unsharp=5:5:0.5,format=rgba[pic]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='16':g='24':b='32':a='{shade}'[shade]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='{_GOLD[0]}':g='{_GOLD[1]}':b='{_GOLD[2]}':"
        f"a='255*clip({band},0,1)'[band]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='{_TEAL[0]}':g='{_TEAL[1]}':b='{_TEAL[2]}':"
        f"a='255*{underline}'[line]",
        # The corner: dark teal fill, a bright teal rim.
        f"color=c=black:s={w}x{h},format=rgba,"
        f"geq=r='if(lt({corner},{radius - 5}),14,{_TEAL[0]})':g='if(lt({corner},{radius - 5}),58,{_TEAL[1]})':"
        f"b='if(lt({corner},{radius - 5}),52,{_TEAL[2]})':a='245*lt({corner},{radius})'[corner]",
        "[pic][shade]overlay=0:0[p1]",
        "[p1][band]overlay=0:0[p2]",
        "[p2][line]overlay=0:0[p3]",
        "[p3][corner]overlay=0:0," + ",".join(logo + texts + [mono])
        + ",vignette=PI/6,format=yuv420p,noise=c0s=5:c0f=u[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", "-i", str(picture), "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
