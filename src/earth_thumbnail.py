"""The prehistory thumbnail: a natural-history documentary frame.

Veylora Earth's card (1280x720). A real landscape (Pexels), graded cool and
filmic, with the topic's own picture (Wikipedia) on the right: an animal, a
skull or a model is cut out (rembg) and stands sharp in front of it; a ruin or
landscape that cannot be cut out becomes the backdrop itself. Bottom left: the
headline in Anton capitals, ivory, with the words marked *like this* larger in
an ivory-to-beige gradient. A parchment label sits top left, a thin muted
copper frame runs round the card, and fine grain and a vignette finish it.
No glow anywhere: it should look like film, not a game.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _text_width
from .space_thumbnail import _lines, _rounded
from .story_thumbnail import _backdrop, _cutout, _drawtext, _fit, _gradient_layer, _write
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

TITLE = settings.root / "fonts" / "Anton-Regular.ttf"
LABEL = settings.root / "fonts" / "Cinzel-Black.ttf"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_MARGIN = 56       # the same space above the label and below the headline
_LEFT = 70
_COLUMN_W = 660    # about half the card
_CAP = 0.73        # Anton's capitals run from drawtext's y to y + 0.73 * size
_LABEL_CAP = 0.72  # Cinzel's
_TAGS = ["FORGOTTEN WORLD", "PREHISTORIC FILES", "ANCIENT EARTH"]
_BACKDROPS = ["misty forest", "snowy tundra mountains", "desert canyon", "foggy valley",
              "volcanic landscape", "ancient ruins", "rocky cliffs fog", "glacier landscape"]


def _cut_or_scene(photo: Path, work: Path) -> Path | None:
    """The subject cut out, or None when the picture is a scene (a ruin, a landscape).

    A cut-out that keeps most of the picture, or almost none of it, means
    there was no single subject to lift out."""
    cut = _cutout(photo, work / "earth_cutout.png")
    if not cut:
        return None
    try:
        from PIL import Image

        alpha = Image.open(cut).getchannel("A").resize((64, 64))
        share = sum(1 for value in alpha.getdata() if value > 128) / (64 * 64)
        return cut if 0.08 < share < 0.75 else None
    except Exception:
        return None


def compose_earth_thumbnail(headline: str, photo: Path, output_path: Path, channel=None,
                            tag: str | None = None, scene: str = "", vertical: bool = False) -> Path:
    """Draw the card. `headline` marks its highlighted words with *stars*; `scene`
    names the backdrop to search for (a few words), else one of the stock ones.

    1280x720 with the subject on the right and the words bottom left, or for a
    Short (vertical=True) 1080x1920 with the subject above the words: the
    Shorts shelf shows only the middle of a wide card."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = output_path.parent
    seed = int(hashlib.sha1(headline.encode("utf-8")).hexdigest(), 16)
    cutout = _cut_or_scene(photo, work)
    # A scene is its own backdrop; a cut-out subject stands in front of a landscape.
    backdrop = _backdrop(headline, work / "earth_backdrop.jpg", [scene] if scene else _BACKDROPS) if cutout else None
    if vertical:
        # The Shorts shelf crops about 8% off the top and the bottom, so the label
        # and the headline keep 190px clear of both edges.
        w, h, k, margin, left = 1080, 1920, 1.45, 190, 80
        # Words fill the width: the shelf shows the card small.
        column, chars, kt = w - 2 * left, 11, 1.7
    else:
        w, h, k, margin, left = W, H, 1.0, _MARGIN, _LEFT
        column, chars, kt = _COLUMN_W, 16, 1.0

    # ---- the headline, stacked up from the bottom margin
    lines = _lines(headline, chars)[:4]
    files, sizes = [], []
    for index, (text, highlight) in enumerate(lines):
        path = _write(work / f"earth_line{index}.txt", text)
        start = (110 if highlight else 86) if len(lines) <= 3 else (96 if highlight else 76)
        files.append(path)
        sizes.append(_fit(path, TITLE, int(start * kt), int(52 * k), column)[0])
    tops, y = [], h - margin
    for size in reversed(sizes):
        y -= size * _CAP
        tops.insert(0, int(y))
        y -= size * 0.20
    edge = "borderw=2:bordercolor=0x101311@0.75:shadowcolor=black@0.65:shadowx=3:shadowy=5"
    x = str(left)
    rows = list(zip(files, sizes, tops, [highlight for _, highlight in lines]))
    plain = [_drawtext(path, TITLE, size, top, "0xF8F5EE", x=x, extra=edge)
             for path, size, top, highlight in rows if not highlight]
    marked = [(path, size, top) for path, size, top, highlight in rows if highlight]
    marked_texts = [_drawtext(path, TITLE, size, top, "white", x=x) for path, size, top in marked]
    # The highlighted words' edge and shadow, drawn under their gradient.
    marked_under = [text.replace("fontcolor=white", "fontcolor=0x101311")
                    + ":borderw=2:bordercolor=0x101311@0.75:shadowcolor=black@0.55:shadowx=2:shadowy=4"
                    for text in marked_texts]
    marked_layers = [line for index, (_, size, top) in enumerate(marked)
                     for line in _gradient_layer(f"hi{index}", [marked_texts[index]], top,
                                                 int(top + size * _CAP), (255, 240, 214), (214, 180, 140),
                                                 w, h)]

    # ---- the parchment label and the frame
    tag_file = _write(work / "earth_tag.txt", tag or _TAGS[seed % len(_TAGS)])
    tag_size, tag_h = int(28 * k), int(62 * k)
    tag_w = _text_width(tag_file, str(LABEL), tag_size) + int(52 * k)
    tag_x, tag_y = left, margin
    label = _rounded(tag_x + tag_w / 2, tag_y + tag_h / 2, tag_w / 2, tag_h / 2, 4)
    inset = int(32 * k)
    frame = _rounded(w / 2, h / 2, w / 2 - inset, h / 2 - inset, 6)
    tag_text = _drawtext(tag_file, LABEL, tag_size, tag_y + int((tag_h - tag_size * _LABEL_CAP) / 2),
                         "0x241B13", x=str(tag_x + int(26 * k)))

    # ---- the picture
    size = f"{w}:{h}"
    grade = "colorbalance=rs=-0.04:bs=0.03:rh=0.06:bh=-0.04"
    if cutout:
        inputs = ["-i", str(backdrop or photo), "-i", str(cutout)]
        if vertical:
            # Large and centred between the label and the headline.
            box, sx, sy = "900:880", "(W-w)/2", f"{tag_y + tag_h + 40}+(880-h)/2"
            shadow_xy = f"x=(W-w)/2+14:y={tag_y + tag_h + 56}+(880-h)/2"
        else:
            box, sx, sy = "640:640", "W-w-50", "H-h-30"
            shadow_xy = "x=W-w-36:y=H-h-14"
        picture = [
            f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
            + ("gblur=sigma=3," if backdrop else "gblur=sigma=30,")
            + f"eq=brightness=-0.10:contrast=1.10:saturation=0.82,{grade},format=rgba[sky]",
            f"[1:v]scale={box}:force_original_aspect_ratio=decrease:flags=lanczos,"
            "eq=contrast=1.15:saturation=1.0,unsharp=5:5:0.7,format=rgba,split=2[s][s2]",
            # A soft ground shadow under the subject so it is not pasted on.
            "[s2]geq=r='0':g='0':b='0':a='alpha(X,Y)*0.6',gblur=sigma=18[shadow]",
            f"[sky][shadow]overlay={shadow_xy}[sky2]",
            f"[sky2][s]overlay=x={sx}:y={sy}[pic]",
        ]
    else:
        inputs = ["-i", str(photo)]
        # The scene fills the card.
        picture = [f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
                   f"eq=brightness=-0.04:contrast=1.14:saturation=0.86,{grade},format=rgba[pic]"]
    if vertical:
        # Darker from the middle down, under the headline.
        shade_alpha = f"235*clip((Y-{int(h * 0.50)})/{int(h * 0.22)},0,1)"
    else:
        shade_alpha = f"230*clip(1-X/{int(w * 0.62)},0,1)+60*clip((Y-{int(h * 0.55)})/{int(h * 0.45)},0,1)"
    shade = f"color=c=black:s={w}x{h},format=rgba,geq=r='8':g='12':b='11':a='{shade_alpha}'[shade]"
    words = (["[p2]" + ",".join(plain + marked_under) + "[h0]", *marked_layers]
             + [f"[h{i}][hi{i}]overlay=0:0[h{i + 1}]" for i in range(len(marked))]
             + [f"[h{len(marked)}]null[p3]"])
    graph = ";".join([
        *picture, shade,
        "[pic][shade]overlay=0:0[p1]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='182':g='106':b='56':"
        f"a='140*lt(abs({frame}),1.2)'[frame]",
        "[p1][frame]overlay=0:0[p2]",
        *words,
        f"color=c=black:s={w}x{h},format=rgba,geq=r='0':g='0':b='0':"
        f"a='115*lt({_rounded(tag_x + tag_w / 2 + 2, tag_y + tag_h / 2 + 5, tag_w / 2, tag_h / 2, 4)},0)',"
        "gblur=sigma=5[tagshadow]",
        # Parchment: beige with a fine paper grain, a weathered brown edge.
        f"color=c=black:s={w}x{h},format=rgba,"
        f"geq=r='if(lt({label},-2),198*(0.92+0.08*random(1)),118)':"
        f"g='if(lt({label},-2),164*(0.92+0.08*random(1)),88)':"
        f"b='if(lt({label},-2),122*(0.92+0.08*random(1)),61)':a='255*lt({label},0)'[tag]",
        "[p3][tagshadow]overlay=0:0[p4]",
        "[p4][tag]overlay=0:0," + tag_text + ",vignette=PI/5,format=yuv420p,noise=c0s=7:c0f=u[out]",
    ])
    subprocess.run(
        [_ffmpeg(), "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
        check=True, capture_output=True, text=True,
    )
    return output_path
