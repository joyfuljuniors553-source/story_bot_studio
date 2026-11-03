"""The space thumbnail: a hook headline with gold words over the real object.

Quasorynth's card (1280x720). The topic's own picture (Wikipedia/NASA) glows
on the right over a bright nebula stock backdrop (Pexels): a picture on black
space is screened in so the black melts away, any other is cut out (rembg).
Bottom left: the headline, two to four short lines in heavy condensed
capitals, white with the words marked *like this* in a glowing gold
gradient. A pill-shaped category tag sits top left and a thin glowing gold
frame runs round it all. Without a Pexels key the backdrop is a blurred copy
of the picture.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _text_width
from .story_thumbnail import _backdrop, _cutout, _drawtext, _fit, _gradient_layer, _write
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

TITLE = settings.root / "fonts" / "BarlowCondensed-Black.ttf"
LABEL = settings.root / "fonts" / "Rajdhani-Bold.ttf"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_MARGIN = 48       # the same space above the tag and below the headline
_LEFT = 58
_COLUMN_W = 600    # the headline's column, bottom left
_CAP = 0.70        # Barlow Condensed's capitals run from drawtext's y to y + 0.70 * size
_LABEL_CAP = 0.68  # Rajdhani's
_LINE_CHARS = 14   # wrap the headline at about this many letters
_TAGS = ["SPACE EXPLAINED", "COSMIC FILES"]
_BACKDROPS = ["nebula", "galaxy", "purple galaxy", "milky way galaxy", "colorful nebula", "outer space"]


def _lines(headline: str, chars: int = _LINE_CHARS) -> list[tuple[str, bool]]:
    """'BLACK HOLES: *GATES OF TIME?*' -> [('BLACK HOLES:', False), ('GATES OF TIME?', True)].

    The *marked* words are gold. Each run of white or gold words is wrapped on
    its own, so a line is never half gold, and split evenly, so no word is left
    alone on the last line ("RULED THE ICE / AGE")."""
    lines = []
    for index, part in enumerate(headline.upper().split("*")):
        words = part.split()
        if words:
            lines += [(line, index % 2 == 1) for line in _even_split(words, chars)]
    return lines


def _even_split(words: list[str], chars: int) -> list[str]:
    """The fewest lines of about `chars` letters, with the longest line as short as possible."""
    from itertools import combinations

    for count in range(1, len(words) + 1):
        best = None
        for cuts in combinations(range(1, len(words)), count - 1):
            edges = (0, *cuts, len(words))
            rows = [" ".join(words[a:b]) for a, b in zip(edges, edges[1:])]
            longest = max(len(row) for row in rows)
            if (longest <= chars or any(" " not in row for row in rows if len(row) > chars)) \
                    and (best is None or longest < best[0]):
                best = (longest, rows)
        if best:
            return best[1]
    return words


def _on_black(photo: Path) -> bool:
    """True when the picture's border is dark: it can be screened onto the sky."""
    try:
        from PIL import Image

        pixels = list(Image.open(photo).convert("L").resize((64, 64)).getdata())
        border = [value for i, value in enumerate(pixels)
                  if i < 128 or i >= 64 * 62 or i % 64 in (0, 1, 62, 63)]
        return sum(border) / len(border) < 45
    except Exception:
        return True


def _rounded(cx: float, cy: float, half_w: float, half_h: float, r: float) -> str:
    """geq expression: signed distance to a rounded rectangle (negative inside)."""
    qx, qy = f"(abs(X-{cx})-{half_w - r})", f"(abs(Y-{cy})-{half_h - r})"
    return f"(hypot(max({qx},0),max({qy},0))+min(max({qx},{qy}),0)-{r})"


def compose_space_thumbnail(headline: str, photo: Path, output_path: Path, channel=None,
                            tag: str | None = None, scene: str = "", vertical: bool = False) -> Path:
    """Draw the card. `headline` marks its gold words with *stars*; `scene` names
    the backdrop to search for (a few words), else one of the stock ones.

    1280x720 with the object on the right and the words bottom left, or for a
    Short (vertical=True) 1080x1920 with the object above the words: the
    Shorts shelf shows only the middle of a wide card."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    seed = int(hashlib.sha1(headline.encode("utf-8")).hexdigest(), 16)
    backdrop = _backdrop(headline, work / "space_backdrop.jpg", [scene] if scene else _BACKDROPS)
    screened = _on_black(photo)
    cutout = None if screened else _cutout(photo, work / "space_cutout.png")
    if not screened and not cutout:
        screened = True
    if vertical:
        # The Shorts shelf crops about 8% off the top and the bottom, so the label
        # and the headline keep 190px clear of both edges.
        w, h, k, margin, left = 1080, 1920, 1.45, 190, 80
        # Words fill the width: the shelf shows the card small.
        column, chars, kt = w - 2 * left, 12, 1.65
    else:
        w, h, k, margin, left = W, H, 1.0, _MARGIN, _LEFT
        column, chars, kt = _COLUMN_W, _LINE_CHARS, 1.0

    # ---- the headline, each line as large as fits, stacked up from the bottom margin
    lines = _lines(headline, chars)[:4]
    files, sizes = [], []
    for index, (text, gold) in enumerate(lines):
        path = _write(work / f"space_line{index}.txt", text)
        start = (132 if gold else 104) if len(lines) <= 3 else (112 if gold else 88)
        files.append(path)
        sizes.append(_fit(path, TITLE, int(start * kt), int(56 * k), column)[0])
    tops, y = [], h - margin
    for size in reversed(sizes):
        y -= size * _CAP
        tops.insert(0, int(y))
        y -= size * 0.16
    outline = "borderw=5:bordercolor=0x020817:shadowcolor=black@0.85:shadowx=4:shadowy=6"
    x = str(left)
    rows = list(zip(files, sizes, tops, [gold for _, gold in lines]))
    white = [_drawtext(path, TITLE, size, top, "white", x=x, extra=outline)
             for path, size, top, gold in rows if not gold]
    gold_rows = [(path, size, top) for path, size, top, gold in rows if gold]
    gold_texts = [_drawtext(path, TITLE, size, top, "white", x=x) for path, size, top in gold_rows]
    # The gold words' dark outline and drop shadow, drawn under the gradient.
    gold_under = [text.replace("fontcolor=white", "fontcolor=0x020817") + f":{outline}"
                  for text in gold_texts]
    glow_texts = [text.replace("fontcolor=white", "fontcolor=0xFFAD27") for text in gold_texts]
    gold_layers = [line for index, (_, size, top) in enumerate(gold_rows)
                   for line in _gradient_layer(f"gold{index}", [gold_texts[index]], top,
                                               int(top + size * _CAP), (255, 245, 205), (255, 185, 0),
                                               w, h)]

    # ---- shapes drawn with geq: frame, tag, the tag's planet icon
    inset = int(14 * k)
    frame = _rounded(w / 2, h / 2, w / 2 - inset, h / 2 - inset, 22)
    tag_file = _write(work / "space_tag.txt", tag or _TAGS[seed % len(_TAGS)])
    tag_size, tag_h = int(28 * k), int(56 * k)
    icon = tag_h - int(26 * k)
    pad = int(20 * k)
    tag_w = pad + icon + int(12 * k) + _text_width(tag_file, str(LABEL), tag_size) + int(26 * k)
    tag_x, tag_y = left - 8, margin
    pill = _rounded(tag_x + tag_w / 2, tag_y + tag_h / 2, tag_w / 2, tag_h / 2, tag_h / 2)
    icx, icy = tag_x + pad + icon / 2, tag_y + tag_h / 2
    planet = f"lt(hypot(X-{icx},Y-{icy}),{icon * 0.3})"
    ring = (f"lt(abs(hypot((X-{icx})*cos(0.4)+(Y-{icy})*sin(0.4),"
            f"((Y-{icy})*cos(0.4)-(X-{icx})*sin(0.4))*2.6)-{icon * 0.5}),2)")
    tag_text = _drawtext(tag_file, LABEL, tag_size, tag_y + int((tag_h - tag_size * _LABEL_CAP) / 2),
                         "white", x=str(tag_x + pad + icon + int(12 * k)))

    # ---- the picture: a bright nebula, the object large on the right (on a Short: above the words)
    size = f"{w}:{h}"
    inputs = ["-i", str(backdrop or photo), "-i", str(cutout or photo)]
    sky = (f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
           + ("gblur=sigma=1.5,eq=brightness=-0.04:contrast=1.15:saturation=1.35,"
              if backdrop else "gblur=sigma=30,eq=brightness=-0.22:saturation=1.1,")
           + "colorbalance=rs=0.04:gs=-0.08:bs=0.16:rm=0.06:bm=0.10,format=rgba[sky0]")
    if vertical:
        glow_x, glow_y, obj_top = w / 2, h * 0.33, tag_y + tag_h + 40
        fit = "scale=920:880:force_original_aspect_ratio=decrease:flags=lanczos"
        ox, oy = "(W-w)/2", f"{obj_top}+(880-h)/2"
        hx, hy = "(W-w)/2", f"{obj_top - 60}+(880-h+120)/2"
        shade_alpha = f"215*clip((Y-{int(h * 0.50)})/{int(h * 0.20)},0,1)"
    else:
        glow_x, glow_y = 900, 330
        fit = "scale=760:650:force_original_aspect_ratio=decrease:flags=lanczos"
        ox, oy = "W-w-20", "(H-h)/2"
        hx, hy = "W-w+40", "(H-h)/2"
        shade_alpha = "200*clip((760-X)/520,0,1)*clip((Y-200)/260,0.25,1)"
    nebula = (f"color=c=black:s={w}x{h},format=rgba,geq=r='120':g='40':b='220':"
              f"a='110*exp(-(pow((X-{glow_x})/{380 * k},2)+pow((Y-{glow_y})/{300 * k},2)))'[neb]")
    # Darker behind the headline so it reads on any sky.
    shade = f"color=c=black:s={w}x{h},format=rgba,geq=r='2':g='6':b='20':a='{shade_alpha}'[shade]"
    if screened:
        feather = "min(1,min(min(X,W-X),min(Y,H-Y))/70)"
        light = "(0.3*r(X,Y)+0.59*g(X,Y)+0.11*b(X,Y))"
        picture = [
            # The object's black space turns see-through, its lit parts stay solid.
            f"[1:v]{fit},eq=contrast=1.12:saturation=1.25,unsharp=5:5:0.6,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='clip(({light}-8)*2.5,0,255)*{feather}'[obj]",
            "[sky0][neb]overlay=0:0[sky1]",
            f"[sky1][obj]overlay=x={ox}:y={oy}[pic]",
        ]
    else:
        picture = [
            f"[1:v]{fit},eq=contrast=1.08:saturation=1.15,unsharp=5:5:0.6,format=rgba,split=2[o][o2]",
            # A violet glow round the cut-out lifts it off the sky.
            "[o2]pad=iw+120:ih+120:60:60:color=black@0,"
            "geq=r='150':g='70':b='255':a='alpha(X,Y)*0.9',gblur=sigma=26[halo]",
            "[sky0][neb]overlay=0:0[sky1]",
            f"[sky1][halo]overlay=x={hx}:y={hy}[sky2]",
            f"[sky2][o]overlay=x={ox}:y={oy}[pic]",
        ]
    if gold_texts:
        words = ([f"color=c=black@0:s={w}x{h},format=rgba,{','.join(glow_texts)},gblur=sigma=12,"
                  "colorchannelmixer=aa=0.7[glow]", *gold_layers,
                  "[p3][glow]overlay=0:0," + ",".join(white + gold_under) + "[g0]"]
                 + [f"[g{i}][gold{i}]overlay=0:0[g{i + 1}]" for i in range(len(gold_texts))]
                 + [f"[g{len(gold_texts)}]null[p4]"])
    else:
        words = ["[p3]" + ",".join(white) + "[p4]"]
    graph = ";".join([
        sky, nebula, shade, *picture,
        f"color=c=black:s={w}x{h},format=rgba,geq=r='255':g='210':b='120':"
        f"a='255*lt(abs({frame}),1.6)'[frame]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='255':g='173':b='39':"
        f"a='220*lt(abs({frame}),5)',gblur=sigma=8[frameglow]",
        f"color=c=black:s={w}x{h},format=rgba,"
        f"geq=r='if(lt({pill},-2),4,255)':g='if(lt({pill},-2),8,188)':b='if(lt({pill},-2),24,69)':"
        f"a='225*lt({pill},0)'[tag]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='255':g='188':b='69':"
        f"a='255*max({planet},{ring})'[icon]",
        "[pic][shade]overlay=0:0[p1]",
        "[p1][frameglow]overlay=0:0[p2]",
        "[p2][frame]overlay=0:0[p3]",
        *words,
        "[p4][tag]overlay=0:0[p5]",
        "[p5][icon]overlay=0:0," + tag_text + ",format=yuv420p[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
