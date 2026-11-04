"""Abyssoryn's two thumbnail styles, one picked per video by its subject.

  * "dossier" (places, expeditions, wrecks): an aged, torn sheet of parchment
    on a dark navy desk with the subject's name in black Anton capitals and a
    red rubber stamp under it (the words marked *like this*), beside the
    subject's photo in a white print frame, tilted and pinned.
  * "giants" (sea creatures): the animal large on the right over a cold blue
    underwater backdrop; on the left a red brush-stroke banner (the plain
    words) above a huge icy-white headline (the marked words).

Both carry the ABYSSORYN logo top left, come wide (1280x720) or tall for a
Short (1080x1920, clear of the shelf crop), and use only the subject's own
free photo (Wikipedia) or a stock backdrop (Pexels): no invented scenes.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .config import settings
from .presenter import _text_width
from .space_thumbnail import _lines, _on_black
from .story_thumbnail import _backdrop, _cutout, _drawtext, _fit, _write
from .thumbnails import THUMB_HEIGHT, THUMB_WIDTH, _ffmpeg

FONTS = settings.root / "fonts"
TITLE = FONTS / "Anton-Regular.ttf"
STAMP = FONTS / "Oswald-Bold.ttf"
BANNER = FONTS / "BarlowCondensed-ExtraBoldItalic.ttf"
LOGO = FONTS / "Montserrat-ExtraBold.ttf"
W, H = THUMB_WIDTH, THUMB_HEIGHT
_CAP = 0.73  # Anton's capitals run from drawtext's y to y + 0.73 * size
_BACKDROPS = {"giants": ["deep ocean underwater", "underwater blue light rays", "ocean surface underwater"],
              "dossier": ["deep ocean underwater", "ocean waves dark"]}


def _split(headline: str) -> tuple[str, str]:
    """('Giants of the', 'Deep') from 'Giants of the *Deep*': plain words, marked words."""
    parts = headline.split("*")
    plain = " ".join(p.strip() for p in parts[0::2] if p.strip())
    marked = " ".join(p.strip() for p in parts[1::2] if p.strip())
    return plain, marked


def _logo(work: Path, x: int, y: int, k: float) -> list[str]:
    """A big "A" mark and the name, white, top left."""
    mark = _write(work / "ocean_logo_a.txt", "A")
    name = _write(work / "ocean_logo.txt", "ABYSSORYN")
    size = int(30 * k)
    shadow = "shadowcolor=black@0.7:shadowx=2:shadowy=2"
    mark_w = _text_width(mark, str(LOGO), int(size * 1.6))
    return [_drawtext(mark, LOGO, int(size * 1.6), y - int(size * 0.18), "white", x=str(x), extra=shadow),
            _drawtext(name, LOGO, size, y + int(size * 0.22), "white", x=str(x + mark_w + int(10 * k)),
                      extra=shadow)]


def _subject_layer(photo: Path, work: Path, box: str, name: str) -> tuple[list[str], Path]:
    """Graph lines making [name] (rgba): the subject cut out, or its light keyed from black."""
    if _on_black(photo):
        light = "(0.3*r(X,Y)+0.59*g(X,Y)+0.11*b(X,Y))"
        return [f"[1:v]scale={box}:force_original_aspect_ratio=decrease:flags=lanczos,"
                "eq=contrast=1.12:saturation=1.1,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='clip(({light}-8)*2.5,0,255)'[{name}]"], photo
    cut = _cutout(photo, work / "ocean_cutout.png")
    if cut:
        try:
            from PIL import Image

            image = Image.open(cut)
            bbox = image.getchannel("A").getbbox()
            if bbox:
                image.crop(bbox).save(cut)
        except Exception:
            pass
        return [f"[1:v]scale={box}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"eq=contrast=1.1:saturation=1.05,unsharp=5:5:0.6,format=rgba[{name}]"], cut
    feather = "min(1,min(min(X,W-X),min(Y,H-Y))/60)"
    return [f"[1:v]scale={box}:force_original_aspect_ratio=decrease:flags=lanczos,format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*{feather}'[{name}]"], photo


def _run(inputs: list[str], graph: str, output_path: Path) -> Path:
    subprocess.run([_ffmpeg(), "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
                    "-frames:v", "1", "-update", "1", "-q:v", "2", str(output_path)],
                   check=True, capture_output=True, text=True)
    return output_path


# ------------------------------------------------------------------ Style B: Ocean Giants

def _giants(headline: str, photo: Path, output_path: Path, scene: str, vertical: bool) -> Path:
    work = output_path.parent
    if vertical:
        w, h, k, top, bottom, left = 1080, 1920, 1.45, 190, 190, 70
        column, box = w - 2 * left, "1040:900"
    else:
        w, h, k, top, bottom, left = W, H, 1.0, 34, 40, 44
        column, box = 600, "820:720"
    plain, marked = _split(headline)
    hero_text = marked or plain
    banner_text = plain if marked else ""
    backdrop = _backdrop(headline, work / "ocean_backdrop.jpg", [scene] if scene else _BACKDROPS["giants"])

    # The hero words, as large as fit; one or two lines.
    hero_lines = [text for text, _ in _lines(hero_text, 10)][:2]
    hero_files = [_write(work / f"giant_hero{i}.txt", t) for i, t in enumerate(hero_lines)]
    hero_size = min(_fit(f, TITLE, int(200 * k * (0.8 if vertical else 1)), int(80 * k), column)[0]
                    for f in hero_files)
    banner_size = int(60 * k)
    banner_file = _write(work / "giant_banner.txt", banner_text.upper() or " ")
    banner_w = _text_width(banner_file, str(BANNER), banner_size) if banner_text else 0
    block = (banner_size + int(30 * k) if banner_text else 0) + len(hero_lines) * int(hero_size * 0.95)
    if vertical:
        y = h - bottom - block
    else:
        logo_bottom = top + int(60 * k)
        y = logo_bottom + max(0, (h - bottom - logo_bottom - block) // 2)

    texts, bands = [], ""
    if banner_text:
        x1, x2 = left - int(14 * k), left + banner_w + int(34 * k)
        y1, y2 = y - int(10 * k), y + int(banner_size * 0.95)
        # A rough red brush stroke: ragged ends, a slight upward slant.
        bands = (f"between(X,{x1},{x2})*between(Y,{y1}+(X-{x1})*-0.03+6*sin(X/9),{y2}+(X-{x1})*-0.03+5*sin(X/13))"
                 f"*min(1,(X-{x1})/25+0.2*sin(Y/3))*min(1,({x2}-X)/40+0.2*sin(Y/4))")
        texts.append(_drawtext(banner_file, BANNER, banner_size, y + int(banner_size * 0.08), "white",
                               x=str(left + int(8 * k)), extra="shadowcolor=black@0.5:shadowx=2:shadowy=3"))
        y = y2 + int(26 * k)
    hero_tops = []
    for f in hero_files:
        hero_tops.append(y)
        y += int(hero_size * 0.95)
    hero_white = [_drawtext(f, TITLE, hero_size, t, "white", x=str(left)) for f, t in zip(hero_files, hero_tops)]
    hero_edge = [d.replace("fontcolor=white", "fontcolor=0x041521")
                 + f":borderw={int(6 * k)}:bordercolor=0x041521:shadowcolor=black@0.8:shadowx=5:shadowy=8"
                 for d in hero_white]
    hero_top, hero_bottom = hero_tops[0], hero_tops[-1] + int(hero_size * _CAP)
    span = max(1, hero_bottom - hero_top)

    subject_lines, subject = _subject_layer(photo, work, box, "beast")
    size = f"{w}:{h}"
    inputs = ["-i", str(backdrop or photo), "-i", str(subject)]
    shade = (f"min(245,235*clip(({int(w * 0.55)}-X)/{int(w * 0.35)},0,1))" if not vertical
             else f"min(245,235*clip((Y-{int(h * 0.48)})/{int(h * 0.18)},0,1))")
    rays = "38*max(0,sin((X*0.55+Y*0.25)/38))*clip(1-Y/H*1.2,0,1)"
    place = (f"x=(W-w)/2:y={top + int(80 * k)}" if vertical else "x=W-w+10:y=(H-h)/2+30")
    graph = ";".join([
        f"[0:v]scale={size}:force_original_aspect_ratio=increase,crop={size},"
        + ("gblur=sigma=2," if backdrop else "gblur=sigma=30,")
        + "eq=brightness=-0.08:contrast=1.15:saturation=1.05,"
        "colorbalance=rs=-0.14:gs=0.0:bs=0.16:rm=-0.08:bm=0.12,format=rgba[sea]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='136':g='217':b='244':a='{rays}',gblur=sigma=6[rays]",
        *subject_lines,
        "[beast]split=2[b1][b2]",
        "[b2]geq=r='136':g='217':b='244':a='alpha(X,Y)*0.5',gblur=sigma=22[rim]",
        "[sea][rays]overlay=0:0[s1]",
        f"[s1][rim]overlay={place}[s2]",
        f"[s2][b1]overlay={place}[s3]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='4':g='21':b='33':a='{shade}'[shade]",
        "[s3][shade]overlay=0:0[s4]",
        f"color=c=black:s={w}x{h},format=rgba,geq=r='215':g='25':b='32':a='240*clip({bands or 0},0,1)'[band]",
        "[s4][band]overlay=0:0," + ",".join(hero_edge) + "[s5]",
        # Icy letters: white at the top to ice cyan, with a frosty grain.
        f"color=c=black:s={w}x{h},{','.join(hero_white)},format=gray[ice_m]",
        f"color=c=black:s={w}x{h},format=rgb24,"
        f"geq=r='255-119*clip((Y-{hero_top})/{span},0,1)-30*random(1)':"
        f"g='255-38*clip((Y-{hero_top})/{span},0,1)-24*random(1)':"
        f"b='255-11*clip((Y-{hero_top})/{span},0,1)-14*random(1)'[ice_g]",
        "[ice_g][ice_m]alphamerge[ice]",
        "[s5][ice]overlay=0:0," + ",".join(texts + _logo(work, left, top, k))
        + ",vignette=PI/6,format=yuv420p,noise=c0s=4:c0f=u[out]",
    ])
    return _run(inputs, graph, output_path)


# ------------------------------------------------------------------ Style A: Expedition Dossier

def _dossier(headline: str, photo: Path, output_path: Path, scene: str, vertical: bool) -> Path:
    work = output_path.parent
    if vertical:
        w, h, k, top, bottom, left = 1080, 1920, 1.45, 190, 190, 70
        sheet = (40, int(h * 0.50), w - 40, h - bottom + 20)   # x1, y1, x2, y2
        frame_box, frame_xy = "820:660", ("(W-w)/2", f"{top + int(90 * k)}")
    else:
        w, h, k, top, bottom, left = W, H, 1.0, 34, 40, 44
        sheet = (24, 96, 640, h - 24)
        frame_box, frame_xy = "520:440", ("W-w-40", "(H-h)/2+22")
    title_text, stamp_text = _split(headline)
    if not title_text:
        title_text, stamp_text = stamp_text, ""
    sx1, sy1, sx2, sy2 = sheet
    pad = int(36 * k)
    column = sx2 - sx1 - 2 * pad

    title_lines = [text for text, _ in _lines(title_text, 9)][:3]
    title_files = [_write(work / f"dossier_title{i}.txt", t) for i, t in enumerate(title_lines)]
    title_size = min(_fit(f, TITLE, int(150 * k), int(70 * k), column)[0] for f in title_files)
    stamp_size = int(52 * k)
    stamp_file = _write(work / "dossier_stamp.txt", stamp_text.upper() or " ")
    stamp_w = _text_width(stamp_file, str(STAMP), stamp_size) if stamp_text else 0
    block = len(title_lines) * int(title_size * 0.92) + (int(stamp_size * 1.9) + int(24 * k) if stamp_text else 0)
    y = sy1 + max(pad, (sy2 - sy1 - block) // 2)
    ink = []
    for f in title_files:
        ink.append(_drawtext(f, TITLE, title_size, y, "0x241C16", x=str(sx1 + pad)))
        y += int(title_size * 0.92)
    stamp_lines = []
    if stamp_text:
        y += int(24 * k)
        bx1, by1 = sx1 + pad, y
        bx2, by2 = bx1 + stamp_w + int(44 * k), by1 + int(stamp_size * 1.5)
        line = int(5 * k)
        rim = (f"between(X,{bx1},{bx2})*between(Y,{by1},{by2})"
               f"*(1-between(X,{bx1 + line},{bx2 - line})*between(Y,{by1 + line},{by2 - line}))")
        stamp_lines = [
            f"color=c=black@0:s={w}x{h},format=rgba,geq=r='199':g='45':b='37':"
            f"a='235*{rim}*(0.55+0.45*gt(random(1),0.25))',"
            + _drawtext(stamp_file, STAMP, stamp_size, by1 + int(stamp_size * 0.22), "0xC72D25@0.9",
                        x=str(bx1 + int(22 * k)))
            + f",rotate=a=-3*PI/180:c=none:ow=iw:oh=ih[stamp]",
        ]

    # The torn sheet: wavy edges, grain, edges darkened like old paper.
    def rag(v: str, seed: int) -> str:
        # Several unrelated waves plus a little noise: a torn edge, not a stamp's.
        return (f"(5*sin({v}/23+{seed})+3*sin({v}/9.7+{seed * 2})+2*sin({v}/4.1+{seed * 3})"
                f"+1.5*sin({v}/1.9+{seed}))")

    edge = (f"gte(X,{sx1}+{rag('Y', 1)})*lte(X,{sx2}+{rag('Y', 2)})"
            f"*gte(Y,{sy1}+{rag('X', 3)})*lte(Y,{sy2}+{rag('X', 4)})")
    burn = (f"clip(min(min(X-{sx1},{sx2}-X),min(Y-{sy1},{sy2}-Y))/{int(60 * k)},0,1)")
    sheet_layer = (f"color=c=black@0:s={w}x{h},format=rgba,"
                   f"geq=r='(217-18*random(1))*(0.72+0.28*{burn})':g='(185-16*random(1))*(0.70+0.30*{burn})':"
                   f"b='(135-14*random(1))*(0.66+0.34*{burn})':a='255*{edge}',"
                   + ",".join(ink) + ",rotate=a=-2*PI/180:c=none:ow=iw:oh=ih,split=2[sheet][sheet2];"
                   "[sheet2]geq=r='0':g='0':b='0':a='alpha(X,Y)*0.65',gblur=sigma=12[sheetshadow]")

    size = f"{w}:{h}"
    inputs = ["-i", str(photo)]
    # The photograph in a white print border, tilted, with a red pin.
    border = int(16 * k)
    graph = ";".join([
        # A dark navy desk with a faint stained texture.
        f"color=c=black:s={w}x{h},format=rgb24,"
        f"geq=r='16+10*sin(X/53)*sin(Y/37)+8*random(1)':g='43+12*sin(X/61)*sin(Y/41)+8*random(1)':"
        f"b='58+14*sin(X/47)*sin(Y/43)+8*random(1)',format=rgba[desk]",
        f"[0:v]scale={frame_box}:force_original_aspect_ratio=decrease:flags=lanczos,"
        "eq=contrast=1.12:saturation=0.9,colorbalance=rs=-0.05:bs=0.08,"
        f"pad=iw+{2 * border}:ih+{2 * border}+{int(30 * k)}:{border}:{border}:color=0xF4EFE4,format=rgba,"
        "split=2[print0][print2]",
        f"color=c=black@0:s={int(44 * k)}x{int(44 * k)},format=rgba,"
        f"geq=r='if(lt(hypot(X-{int(17 * k)},Y-{int(17 * k)}),{int(6 * k)}),255,200)':g='if(lt(hypot(X-{int(17 * k)},Y-{int(17 * k)}),{int(6 * k)}),170,30)':"
        f"b='if(lt(hypot(X-{int(17 * k)},Y-{int(17 * k)}),{int(6 * k)}),170,30)':"
        f"a='255*lt(hypot(X-{int(22 * k)},Y-{int(22 * k)}),{int(15 * k)})'[pin]",
        f"[print0][pin]overlay=x=W-{int(70 * k)}:y={int(2 * k)}[print]",
        "[print2]geq=r='0':g='0':b='0':a='170',gblur=sigma=14[printshadow]",
        "[print]rotate=a=4*PI/180:c=none:ow=rotw(4*PI/180):oh=roth(4*PI/180)[tilted]",
        "[printshadow]rotate=a=4*PI/180:c=none:ow=rotw(4*PI/180):oh=roth(4*PI/180)[tiltshadow]",
        f"[desk][tiltshadow]overlay=x={frame_xy[0]}+12:y={frame_xy[1]}+16[d1]",
        f"[d1][tilted]overlay=x={frame_xy[0]}:y={frame_xy[1]}[d2]",
        sheet_layer,
        "[d2][sheetshadow]overlay=10:14[d2s]",
        "[d2s][sheet]overlay=0:0[d3]",
        *stamp_lines,
        "[d3][stamp]overlay=0:0[d4]" if stamp_lines else "[d3]null[d4]",
        "[d4]" + ",".join(_logo(work, left, top, k)) + ",vignette=PI/5,format=yuv420p,noise=c0s=6:c0f=u[out]",
    ])
    return _run(inputs, graph, output_path)


def compose_ocean_thumbnail(headline: str, photo: Path, output_path: Path, channel=None,
                            scene: str = "", vertical: bool = False, kind: str = "giants") -> Path:
    """Draw Abyssoryn's card in the style for its subject: "giants" or "dossier"."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "dossier":
        return _dossier(headline, photo, output_path, scene, vertical)
    return _giants(headline, photo, output_path, scene, vertical)
