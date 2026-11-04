"""Chronovanta's thumbnail: "Future Science Editorial".

Graphite, ivory and one orange; a clean editorial headline with the year or
key word on an orange slanted bar; one photorealistic future-technology visual;
restrained blueprint grid and IBM-Plex-Mono annotations. Long videos get a
1280x720 card (headline left, visual right), Shorts a 1080x1920 card (brand
on top, headline, visual below).

    channels.json: "thumbnail_style": "future"

A logo of your own (a PNG with real transparency) at data/brand/<channel id>_logo.png
replaces the drawn monogram.
"""
from __future__ import annotations

import math
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import settings

GRAPHITE = (17, 19, 24)
IVORY = (244, 242, 237)
ORANGE = (255, 106, 0)
STEEL = (142, 149, 156)
ICE = (217, 228, 232)

FONTS = settings.root / "fonts"


def _font(name: str, size: int, weight: str = "") -> ImageFont.FreeTypeFont:
    files = {
        "grotesk": "SpaceGrotesk-Variable.ttf", "sora": "Sora-Variable.ttf",
        "mono": "IBMPlexMono-Medium.ttf", "anton": "Anton-Regular.ttf",
    }
    font = ImageFont.truetype(str(FONTS / files[name]), size)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except Exception:
            pass
    return font


# ------------------------------------------------------------------ the plan

def plan_for(title: str, guide: str = "") -> dict:
    """Headline words, labels and the visual, written by the AI writer from the title.

    `guide` is the channel's saved style guide (brand.style_text): its concepts
    and rules steer the headline and the picture."""
    from .genre_topics import _script_json

    guide_text = f"The channel's thumbnail style guide (follow it):\n{guide[:3000]}\n\n" if guide else ""
    plan = _script_json(
        guide_text
        + "Write the text for a premium future-science YouTube thumbnail.\n"
        f"Video title: {title}\n"
        'Return ONLY JSON: {"top": str, "big": str, "sub": str, "labels": [str], "visual": str}.\n'
        "- top + big together are 2 to 5 words, the headline. big is the ONE thing to shout: the year "
        "or number when the title has one (\"2050\", \"150\"), else the single key word (max 10 letters). "
        "top is the words before it (e.g. top \"LIFE IN\", big \"2050\"; top \"HUMAN\", big \"2.0\"; "
        "top \"ROBOTS\", big \"EVERYWHERE?\"). Keep a question mark when the title is a question.\n"
        "- sub: 4 to 7 words, a calm supporting line; wrap the 1 to 3 key words in *stars* "
        "(e.g. \"A science-based look at *our future*\").\n"
        "- labels: 0 to 4 short scientific labels (1-2 words each) that the video really covers, "
        "e.g. [\"AI\", \"CLEAN ENERGY\"]. Empty list if none fit.\n"
        "- visual: one sentence for a photorealistic image: ONE realistic advanced-technology subject "
        "or future scene for this topic, real materials, cinematic studio lighting, strong perspective. "
        "No text, no logos, no close-up faces.\n"
        "Never claim more than the title does; a future thing is a possibility, not a fact."
    )
    top = re.sub(r"\s+", " ", str(plan.get("top") or "")).strip().upper()[:28]
    big = re.sub(r"\s+", " ", str(plan.get("big") or "")).strip().upper()[:12]
    if not big:
        words = title.upper().split()
        top, big = " ".join(words[:-1])[:28], (words[-1] if words else "FUTURE")[:12]
    labels = [re.sub(r"\s+", " ", str(x)).strip().upper()[:16] for x in (plan.get("labels") or [])][:4]
    return {
        "top": top, "big": big,
        "sub": re.sub(r"\s+", " ", str(plan.get("sub") or "")).strip()[:60],
        "labels": [x for x in labels if x],
        "visual": str(plan.get("visual") or title).strip()[:400],
    }


# ------------------------------------------------------------------ the visual

_STYLE = ("premium future-science editorial photograph, photorealistic, authentic industrial materials, "
          "realistic studio and cinematic lighting, subtle shadows, cinematic depth, warm orange and cool "
          "steel tones, high detail. No text, no letters, no logos, no watermark, no neon-blue sci-fi glow, "
          "no cartoon, no fantasy spaceships, no distorted faces.")


def render_visual(visual: str, out: Path, vertical: bool) -> Path | None:
    """The photorealistic visual: Cloudflare FLUX, then Pollinations, else None."""
    prompt = f"{visual}. {_STYLE}" + (" Vertical 9:16 composition, subject in the lower two thirds."
                                      if vertical else " 16:9 composition, subject on the right half.")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .thumbnails import cloudflare_thumbnail_ready

        if cloudflare_thumbnail_ready():
            from .image_assets import generate_cloudflare_image

            return generate_cloudflare_image(prompt, out, landscape=not vertical)
    except Exception as exc:
        print(f"[future-thumb] Cloudflare visual failed: {exc}")
    try:
        from .image_assets import pollinations_api_key

        key = pollinations_api_key()
        base = "https://gen.pollinations.ai/image" if key else "https://image.pollinations.ai/prompt"
        w, h = (768, 1344) if vertical else (1280, 720)
        params = urllib.parse.urlencode({"width": w, "height": h, "seed": random.randint(0, 999999),
                                         "model": "zimage" if key else "flux", "nologo": "true",
                                         "enhance": "true", "safe": "true"})
        headers = {"User-Agent": "story-bot-studio"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for attempt in range(3):
            try:
                request = urllib.request.Request(f"{base}/{urllib.parse.quote(prompt)}?{params}", headers=headers)
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read()
                if len(data) > 30_000:
                    out.write_bytes(data)
                    return out
            except Exception as exc:
                print(f"[future-thumb] Pollinations visual try {attempt + 1} failed: {exc}")
    except Exception as exc:
        print(f"[future-thumb] Pollinations unavailable: {exc}")
    return None


# ------------------------------------------------------------------ drawing helpers

def _cover(image: Image.Image, w: int, h: int, focus_x: float = 0.5) -> Image.Image:
    scale = max(w / image.width, h / image.height)
    image = image.resize((math.ceil(image.width * scale), math.ceil(image.height * scale)), Image.LANCZOS)
    left = int((image.width - w) * focus_x)
    top = (image.height - h) // 2
    return image.crop((left, top, left + w, top + h))


def _grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], step: int, alpha: int) -> None:
    x0, y0, x1, y1 = box
    for x in range(x0, x1, step):
        draw.line([(x, y0), (x, y1)], fill=STEEL + (alpha,), width=1)
    for y in range(y0, y1, step):
        draw.line([(x0, y), (x1, y)], fill=STEEL + (alpha,), width=1)


def _text_w(font, text: str) -> int:
    box = font.getbbox(text)
    return box[2] - box[0]


def _fit(name: str, weight: str, text: str, max_w: int, hi: int, lo: int):
    size = hi
    while size > lo and _text_w(_font(name, size, weight), text) > max_w:
        size -= 3
    return _font(name, size, weight)


def _shadowed(canvas: Image.Image, xy, text: str, font, fill, shear: float = 0.0, blur: int = 6) -> None:
    """Text with a soft drop shadow; `shear` slants it like an italic."""
    w = _text_w(font, text) + 60
    h = font.size * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((24, 10 + 4), text, font=font, fill=(0, 0, 0, 190))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    layer.alpha_composite(shadow)
    d.text((20, 10), text, font=font, fill=fill)
    if shear:
        layer = layer.transform(layer.size, Image.AFFINE, (1, shear, -shear * h / 2, 0, 1, 0), Image.BICUBIC)
    canvas.alpha_composite(layer, (int(xy[0]) - 20, int(xy[1]) - 10))


def _bar(canvas: Image.Image, x: int, y: int, text: str, font, slant: int = 26, pad: int = 26) -> int:
    """The orange slanted bar with the big word in graphite; returns its height."""
    tb = font.getbbox(text)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    w, h = tw + pad * 2 + slant, th + pad * 1.2
    layer = Image.new("RGBA", (int(w + 40), int(h + 40)), (0, 0, 0, 0))
    glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    poly = [(20 + slant, 20), (20 + w, 20), (20 + w - slant, 20 + h), (20, 20 + h)]
    ImageDraw.Draw(glow).polygon(poly, fill=ORANGE + (150,))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(layer)
    d.polygon(poly, fill=ORANGE + (255,))
    d.text((20 + pad + slant / 2 - tb[0], 20 + (h - th) / 2 - tb[1]), text, font=font, fill=GRAPHITE + (255,))
    canvas.alpha_composite(layer, (int(x) - 20, int(y) - 20))
    return int(h)


def _rich(canvas: Image.Image, x: int, y: int, text: str, font, center_w: int | None = None) -> None:
    """A line where *starred* words are orange."""
    parts = re.split(r"(\*[^*]+\*)", text)
    total = sum(_text_w(font, p.strip("*")) for p in parts if p)
    cx = x + (center_w - total) // 2 if center_w else x
    d = ImageDraw.Draw(canvas)
    for part in parts:
        if not part:
            continue
        word = part.strip("*")
        d.text((cx + 2, y + 3), word, font=font, fill=(0, 0, 0, 160))
        d.text((cx, y), word, font=font, fill=(ORANGE if part.startswith("*") else IVORY) + (255,))
        cx += _text_w(font, word)


def _monogram(size: int) -> Image.Image:
    """A white C inside a tilted orange orbit (stand-in for the logo file)."""
    s = size * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = _font("grotesk", int(s * 0.95), "Bold")
    b = c.getbbox("C")
    d.text(((s - (b[2] - b[0])) / 2 - b[0], (s - (b[3] - b[1])) / 2 - b[1]), "C", font=c, fill=IVORY + (255,))
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((s * 0.02, s * 0.36, s * 0.98, s * 0.66), outline=ORANGE + (255,), width=int(s * 0.06))
    ring = ring.rotate(18, resample=Image.BICUBIC)
    # The orbit passes behind the C on its upper half: cut it where the letter is.
    back = ring.copy()
    back.putalpha(Image.eval(back.getchannel("A"), lambda a: a))
    img.alpha_composite(ring)
    return img.resize((size, size), Image.LANCZOS)


def _brand(canvas: Image.Image, channel, x: int, y: int, scale: float, center_w: int | None = None) -> None:
    name = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "CHRONOVANTA").upper()
    from .brand import logo as brand_logo

    logo_file = brand_logo(str(getattr(channel, "id", "") or "_"))
    if logo_file is not None:
        logo = Image.open(logo_file).convert("RGBA")
        h = int(64 * scale)
        logo = logo.resize((int(logo.width * h / logo.height), h), Image.LANCZOS)
        lx = x + (center_w - logo.width) // 2 if center_w else x
        canvas.alpha_composite(logo, (lx, y))
        return
    mark = _monogram(int(62 * scale))
    title = _font("grotesk", int(34 * scale), "Bold")
    tag = _font("mono", int(12.5 * scale))
    tagline = "EXPLORING TOMORROW, THROUGH SCIENCE."
    text_w = max(_text_w(title, name + "™"), _text_w(tag, tagline))
    total = mark.width + int(18 * scale) + text_w
    bx = x + (center_w - total) // 2 if center_w else x
    canvas.alpha_composite(mark, (bx, y))
    d = ImageDraw.Draw(canvas)
    lx = bx + mark.width + int(9 * scale)
    d.line([(lx, y + int(6 * scale)), (lx, y + mark.height - int(6 * scale))], fill=ORANGE + (255,), width=max(2, int(2 * scale)))
    tx = lx + int(10 * scale)
    d.text((tx, y + int(4 * scale)), name, font=title, fill=IVORY + (255,))
    d.text((tx + _text_w(title, name) + 3, y + int(2 * scale)), "™", font=_font("grotesk", int(13 * scale), "Bold"),
           fill=IVORY + (255,))
    d.text((tx + 2, y + int(44 * scale)), tagline, font=tag, fill=ICE + (230,))
    d.line([(tx + 2, y + int(64 * scale)), (tx + _text_w(tag, tagline), y + int(64 * scale))],
           fill=ORANGE + (255,), width=max(2, int(2 * scale)))


def _labels_panel(canvas: Image.Image, labels: list[str], right: int, top: int, scale: float) -> None:
    if not labels:
        return
    font = _font("sora", int(17 * scale), "ExtraBold")
    row = int(52 * scale)
    w = max(_text_w(font, x) for x in labels) + int(64 * scale)
    h = row * len(labels) + int(22 * scale)
    x0 = right - w
    panel = Image.new("RGBA", (w, h), (17, 19, 24, 150))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(12 * scale), outline=ICE + (120,), width=2)
    for i, label in enumerate(labels):
        cy = int(11 * scale) + i * row + row // 2
        pd.rectangle((int(16 * scale), cy - int(9 * scale), int(22 * scale), cy + int(9 * scale)), fill=ORANGE + (255,))
        pd.text((int(36 * scale), cy - font.size // 2 - 2), label, font=font, fill=IVORY + (255,))
        if i < len(labels) - 1:
            pd.line([(int(14 * scale), cy + row // 2), (w - int(14 * scale), cy + row // 2)], fill=ICE + (50,), width=1)
    canvas.alpha_composite(panel, (x0, top))


def _annotation(canvas: Image.Image, x: int, y: int, text: str, scale: float) -> None:
    ImageDraw.Draw(canvas).text((x, y), text, font=_font("mono", int(13 * scale)), fill=STEEL + (210,))


# ------------------------------------------------------------------ the cards

def compose_long(plan: dict, visual: Path | None, out: Path, channel) -> Path:
    W, H = 1280, 720
    canvas = Image.new("RGBA", (W, H), GRAPHITE + (255,))
    if visual and Path(visual).is_file():
        art = _cover(Image.open(visual).convert("RGB"), 860, H, 0.5).convert("RGBA")
        mask = Image.new("L", (860, H), 255)
        md = ImageDraw.Draw(mask)
        for x in range(320):
            md.line([(x, 0), (x, H)], fill=int(255 * (x / 320) ** 1.6))
        art.putalpha(mask)
        canvas.alpha_composite(art, (W - 860, 0))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    _grid(od, (0, 0, 620, H), 40, 22)
    for y in range(H - 140, H):  # a darker floor so the subline reads
        od.line([(0, y), (W, y)], fill=GRAPHITE + (int(150 * (y - (H - 140)) / 140),))
    canvas.alpha_composite(over)

    _brand(canvas, channel, 40, 34, 1.0)
    left, max_w = 44, 600
    y = 176
    if plan["top"]:
        top = _fit("grotesk", "Bold", plan["top"], max_w, 104, 60)
        _shadowed(canvas, (left, y), plan["top"], top, IVORY + (255,), shear=0.12)
        y += int(top.size * 1.02)
    big = _fit("anton", "", plan["big"], max_w - 80, 150, 80)
    y += _bar(canvas, left - 6, y + 6, plan["big"], big) + 28
    if plan["sub"]:
        sub = _fit("sora", "ExtraBold", plan["sub"].replace("*", ""), max_w - 30, 34, 22)
        d = ImageDraw.Draw(canvas)
        d.line([(left + 8, y + 2), (left, y + sub.size * 2 + 6)], fill=ORANGE + (255,), width=4)
        words, lines, line = plan["sub"].split(), [], ""
        for word in words:
            trial = (line + " " + word).strip()
            if _text_w(sub, trial.replace("*", "")) > max_w - 40 and line:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        lines = _carry_stars(lines)
        for i, text in enumerate(lines[:2]):
            _rich(canvas, left + 22, y + i * int(sub.size * 1.15), text, sub)
    _labels_panel(canvas, plan["labels"], W - 30, 210, 1.0)
    _annotation(canvas, left, H - 36, "FIG. 01 — CONCEPTUAL RECONSTRUCTION", 1.0)
    ImageDraw.Draw(canvas).line([(0, H - 4), (W, H - 4)], fill=ORANGE + (255,), width=4)
    return _save(canvas, out)


def compose_short(plan: dict, visual: Path | None, out: Path, channel) -> Path:
    W, H = 1080, 1920
    canvas = Image.new("RGBA", (W, H), GRAPHITE + (255,))
    art_top = 760
    if visual and Path(visual).is_file():
        art = _cover(Image.open(visual).convert("RGB"), W, H - art_top + 260, 0.5).convert("RGBA")
        mask = Image.new("L", art.size, 255)
        md = ImageDraw.Draw(mask)
        for y in range(380):
            md.line([(0, y), (W, y)], fill=int(255 * (y / 380) ** 1.5))
        art.putalpha(mask)
        canvas.alpha_composite(art, (0, art_top - 260))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _grid(ImageDraw.Draw(over), (0, 0, W, art_top), 54, 20)
    canvas.alpha_composite(over)

    _brand(canvas, channel, 0, 84, 1.45, center_w=W)
    y = 300
    if plan["top"]:
        top = _fit("grotesk", "Bold", plan["top"], W - 120, 150, 80)
        tx = (W - _text_w(top, plan["top"])) // 2
        _shadowed(canvas, (tx, y), plan["top"], top, IVORY + (255,), shear=0.12, blur=8)
        y += int(top.size * 1.05)
    big = _fit("anton", "", plan["big"], W - 260, 230, 110)
    tb = big.getbbox(plan["big"])
    bar_w = (tb[2] - tb[0]) + 52 + 26
    _bar(canvas, (W - bar_w) // 2, y + 10, plan["big"], big)
    floor = Image.new("RGBA", (W, 220), (0, 0, 0, 0))
    fd = ImageDraw.Draw(floor)
    for y in range(220):
        fd.line([(0, y), (W, y)], fill=GRAPHITE + (int(220 * (y / 220) ** 1.4),))
    canvas.alpha_composite(floor, (0, H - 220))
    _annotation(canvas, 60, H - 70, "FIG. 01 — CONCEPTUAL RECONSTRUCTION", 1.5)
    ImageDraw.Draw(canvas).line([(0, H - 6), (W, H - 6)], fill=ORANGE + (255,), width=6)
    return _save(canvas, out)


def _carry_stars(lines: list[str]) -> list[str]:
    """Keep *highlight* pairs closed per line after wrapping."""
    fixed, open_ = [], False
    for line in lines:
        text = ("*" if open_ else "") + line
        if text.count("*") % 2:
            text += "*"
            open_ = True
        else:
            open_ = False
        fixed.append(text)
    return fixed


def _save(canvas: Image.Image, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out


def compose_for_lesson(lesson, out: Path, channel, content_type: str = "long",
                       plan: dict | None = None, visual: Path | None = None) -> Path:
    """The whole card for one video: plan, visual, layout."""
    vertical = content_type == "short"
    if plan is None:
        from .brand import style_text

        plan = plan_for(lesson.title, style_text(str(getattr(channel, "id", "") or "_")))
    if visual is None:
        visual = render_visual(plan["visual"], out.with_name("thumbnail_visual.jpg"), vertical)
    if visual is None:
        print("[future-thumb] no visual could be made; the card is drawn on the blueprint alone")
    compose = compose_short if vertical else compose_long
    return compose(plan, visual, out, channel)
