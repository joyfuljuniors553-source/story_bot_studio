"""The cinematic biography thumbnail, drawn from a channel's design spec.

A channel uses it when data/brand/<channel>/thumbnail_spec.json exists
(LegendraScope: "THE UNTOLD LIFE OF NAPOLEON"). Every size and colour comes
from that file, so the look can be tuned without touching the code.

Layers, back to front: a scene from the person's own story (Cloudflare FLUX,
no faces, no text) under a stormy teal sky with a sunset glow -> colour grade
-> the person's REAL photo (Wikipedia), cut out and placed by their face ->
vignette and grain -> logo -> TRUE STORY tag -> chrome "THE / UNTOLD /
LIFE OF" -> red brush stroke -> gold NAME -> navy ribbon with three words.

The person is never painted by AI: an AI face of a real person shows a
stranger. Only the background scene is generated.
"""
from __future__ import annotations

import json
import math
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import settings

FONTS = settings.root / "fonts"
CINZEL = FONTS / "Cinzel-Variable.ttf"
TAG_FONT = FONTS / "Oswald-Bold.ttf"
FACE_MODEL = settings.root / "third_party" / "face_detection_yunet_2023mar.onnx"


# ------------------------------------------------------------------ spec

def spec_path(channel_id: str) -> Path:
    return settings.root / "data" / "brand" / str(channel_id) / "thumbnail_spec.json"


def load_spec(channel_id: str) -> dict | None:
    path = spec_path(channel_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rgb(hex_code: str) -> tuple[int, int, int]:
    hex_code = hex_code.lstrip("#")
    return tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------ the plan

def _summary(subject: str) -> str:
    url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + urllib.parse.quote(subject.replace(" ", "_")))
    request = urllib.request.Request(url, headers={"User-Agent": "StoryBotStudio/1.0 (thumbnail)"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return str(json.load(response).get("extract") or "")[:1500]
    except Exception:
        return ""


def _short_name(subject: str, proposed: str) -> str:
    """The AI's short form only when every word of it is in the article's name."""
    full = re.sub(r"\s*\(.*?\)", "", subject).strip()
    words = {w.lower() for w in re.findall(r"[\w'.-]+", full)}
    short = " ".join(str(proposed or "").split()).strip()
    if short and all(w.lower() in words for w in re.findall(r"[\w'.-]+", short)):
        return short.upper()
    return full.upper()


def plan_for(subject: str, vertical: bool, spec: dict, area: str) -> dict:
    """{name, words[3], scene}: one AI call that reads the article's summary."""
    from .genre_topics import _script_json

    summary = _summary(subject)
    try:
        raw = _script_json(
            "You design a YouTube thumbnail for a true-story biography video.\n"
            f"Person: {subject}\nWikipedia summary: {summary or '(none)'}\n"
            'Return ONLY JSON: {"name": str, "words": [str, str, str], "scene": str}\n'
            "- name: the best-known short form of the name, from words of the full name "
            "(e.g. 'Napoleon', 'Audrey Hepburn', 'Einstein'), as short as is still clear.\n"
            "- words: three single CAPITAL words that sum up the arc of this life "
            "(e.g. RISE, POWER, DOWNFALL / FAME, STRUGGLE, LEGACY), each at most 8 letters. Only what the summary supports.\n"
            "- scene: an image prompt for the BACKGROUND only, from this person's own story: "
            "an OUTDOOR place under an open sky, with the era, event and objects (a famous building, a street, a stage outside, a battlefield; e.g. 'Napoleonic battlefield at dusk, French flags, "
            "cannon, soldiers far away, Arc de Triomphe'). Crowds only far away and small; no "
            "portrait, no close face, no text, no logos.\n"
        )
    except Exception as exc:
        print(f"[cinematic-thumb] plan failed ({exc}); plain words")
        raw = {}
    words = [re.sub(r"[^A-Z]", "", str(w).upper()) for w in (raw.get("words") or [])]
    words = [w for w in words if 2 <= len(w) <= 9][:3]
    if len(words) < 3:
        words = list(spec.get("default_words") or ["RISE", "FAME", "LEGACY"])
    scene = " ".join(str(raw.get("scene") or "").split())[:400] or f"historic setting from the life of {subject}"
    return {"name": _short_name(subject, raw.get("name")), "words": words, "scene": scene}


# ------------------------------------------------------------------ backdrop

def _sky(w: int, h: int, spec: dict, vertical: bool) -> Image.Image:
    """Stand-in backdrop: stormy teal gradient with a sunset glow (no AI / no key)."""
    pal = spec["palette"]
    top, mid, glow = _rgb(pal["sky_top"]), _rgb(pal["sky_mid"]), _rgb(pal["sunset_glow"])
    img = Image.new("RGB", (w, h))
    px = img.load()
    gx, gy = (w * 0.5, h * 0.88) if vertical else (w * 0.88, h * 0.72)
    reach = (w if vertical else h) * 0.75
    for y in range(h):
        t = y / max(1, h - 1)
        base = tuple(int(top[i] + (mid[i] - top[i]) * t) for i in range(3))
        for x in range(0, w):
            d = math.hypot(x - gx, y - gy) / reach
            k = max(0.0, 1 - d) ** 2 * 0.85
            px[x, y] = tuple(int(base[i] + (glow[i] - base[i]) * k) for i in range(3))
    return img.filter(ImageFilter.GaussianBlur(2))


def backdrop(plan: dict, w: int, h: int, spec: dict, area: str, work: Path, vertical: bool) -> Image.Image:
    prompt = (
        f"{plan['scene']}. Cinematic historical documentary matte painting, photorealistic, "
        f"outdoors under a big dramatic sky: luminous teal-blue storm clouds lit from below, a bright warm "
        f"orange sunset glow low on the horizon. Composition: the scene sits in {area}. Deep shadows, film look, high detail. "
        "No portrait, no close-up face, no text, no letters, no logos, no watermark."
    )
    try:
        from .image_assets import generate_cloudflare_image
        from .thumbnails import cloudflare_thumbnail_ready

        if cloudflare_thumbnail_ready():
            out = generate_cloudflare_image(prompt, work / "cinematic_scene.jpg", landscape=not vertical)
            return _cover(Image.open(out).convert("RGB"), w, h)
    except Exception as exc:
        print(f"[cinematic-thumb] scene not generated ({exc}); painted sky instead")
    return _sky(w, h, spec, vertical)


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def grade_background(img: Image.Image, spec: dict, vertical: bool) -> Image.Image:
    g, pal = spec["grade"], spec["palette"]
    img = ImageEnhance.Contrast(img).enhance(g["background_contrast"])
    img = ImageEnhance.Color(img).enhance(g["background_saturation"])
    w, h = img.size
    # Teal into the shadows, warmth only where the sunset is.
    lum = img.convert("L")
    shadows = lum.point(lambda v: int(255 * max(0.0, 1 - v / 110) * g["teal_overlay_opacity"] * 1.6))
    img = Image.composite(Image.new("RGB", img.size, _rgb(pal["sky_mid"])), img, shadows)
    warm_mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(warm_mask)
    if vertical:
        d.ellipse((-w * 0.2, h * 0.68, w * 1.2, h * 1.15), fill=int(255 * g["warm_overlay_opacity"] * 2))
    else:
        d.ellipse((w * 0.55, h * 0.45, w * 1.25, h * 1.2), fill=int(255 * g["warm_overlay_opacity"] * 2))
    warm_mask = warm_mask.filter(ImageFilter.GaussianBlur(w // 8))
    return Image.composite(Image.new("RGB", img.size, _rgb(pal["sunset_glow"])), img, warm_mask)


def vignette_and_grain(img: Image.Image, spec: dict, seed: int) -> Image.Image:
    g = spec["grade"]
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.18, -h * 0.18, w * 1.18, h * 1.18), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = mask.point(lambda v: int((255 - v) * g["vignette"]))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, dark)
    rng = random.Random(seed)
    noise = Image.frombytes("L", (w // 2, h // 2), bytes(rng.getrandbits(8) for _ in range((w // 2) * (h // 2))))
    noise = noise.resize((w, h)).convert("RGB")
    return Image.blend(img, ImageChops.overlay(img, noise), g["grain"])


# ------------------------------------------------------------------ person

def _cutout(photo: Path, work: Path) -> Image.Image:
    from .story_thumbnail import _cutout as cut

    made = cut(photo, work / "cinematic_cutout.png")
    if made:
        return Image.open(made).convert("RGBA")
    # No rembg: the photo itself with soft edges.
    img = Image.open(photo).convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((-img.width * 0.15, -img.height * 0.05, img.width * 1.15, img.height * 1.4), fill=255)
    img.putalpha(mask.filter(ImageFilter.GaussianBlur(img.width // 12)))
    return img


def _face(photo: Path) -> tuple[float, float, float] | None:
    """(eye centre x, eye centre y, face height) of the largest face, or None."""
    try:
        import cv2

        image = cv2.imread(str(photo))
        h, w = image.shape[:2]
        finder = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (w, h), 0.7)
        faces = finder.detect(image)[1]
    except Exception:
        return None
    if faces is None or len(faces) == 0:
        return None
    f = max(faces, key=lambda face: face[2] * face[3])
    # YuNet: box x, y, w, h, then right eye (x, y), left eye (x, y), ...
    return (float(f[4] + f[6]) / 2, float(f[5] + f[7]) / 2, float(f[3]))


def place_person(canvas: Image.Image, photo: Path, spec: dict, fmt: dict, work: Path) -> None:
    g, pal = spec["grade"], spec["palette"]
    person = _cutout(photo, work)
    bx, by, bw, bh = fmt["person"]["box"]
    face = _face(photo)
    if face:
        ex, ey, fh = face
        scale = fmt["person"]["face_height"] / fh
        tx, ty = fmt["person"]["eye"]
        x, y = tx - ex * scale, ty - ey * scale
    else:
        trimmed = person.getbbox() or (0, 0, person.width, person.height)
        person = person.crop(trimmed)
        scale = bh / person.height
        x, y = bx + (bw - person.width * scale) / 2, by
    person = person.resize((max(1, round(person.width * scale)), max(1, round(person.height * scale))), Image.LANCZOS)
    if scale > 1.2:
        person = person.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))
    rgb = person.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(g["portrait_contrast"])
    rgb = ImageEnhance.Color(rgb).enhance(g["portrait_saturation"])
    alpha = person.getchannel("A")
    # Shoulders that stop before the bottom edge melt into the dark instead of a hard cut.
    bottom = round(y + person.height)
    if bottom < canvas.height + 5:
        fade = Image.linear_gradient("L").resize((person.width, max(1, person.height // 4)))
        ramp = Image.new("L", person.size, 255)
        ramp.paste(ImageChops.invert(fade), (0, person.height - fade.height))
        alpha = ImageChops.multiply(alpha, ramp)
    # Cool rim light along the outline.
    edge = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(5))).filter(ImageFilter.GaussianBlur(1.5))
    rim = Image.new("RGB", person.size, _rgb(pal["rim_light"]))
    rgb = Image.composite(rim, rgb, edge.point(lambda v: int(v * g["rim_opacity"])))
    person = rgb.convert("RGBA")
    person.putalpha(alpha)
    canvas.alpha_composite(person, (round(x), round(y)))


# ------------------------------------------------------------------ type

def cinzel(weight: int, cap: int) -> ImageFont.FreeTypeFont:
    """Cinzel at the size whose capital height is `cap` px."""
    probe = ImageFont.truetype(str(CINZEL), 200)
    probe.set_variation_by_axes([weight])
    box = probe.getbbox("H")
    size = max(8, round(200 * cap / max(1, box[3] - box[1])))
    font = ImageFont.truetype(str(CINZEL), size)
    font.set_variation_by_axes([weight])
    return font


def _cap_font(path: Path, cap: int) -> ImageFont.FreeTypeFont:
    probe = ImageFont.truetype(str(path), 200)
    box = probe.getbbox("H")
    return ImageFont.truetype(str(path), max(8, round(200 * cap / max(1, box[3] - box[1]))))


def text_mask(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> tuple[Image.Image, int]:
    """(mask cropped to the capitals' height band, cap top offset) with letter spacing."""
    widths = [font.getlength(ch) for ch in text]
    total = int(sum(widths) + tracking * max(0, len(text) - 1)) + 4
    ascent, descent = font.getmetrics()
    mask = Image.new("L", (max(1, total), ascent + descent), 0)
    d = ImageDraw.Draw(mask)
    x = 2.0
    for ch, w in zip(text, widths):
        d.text((x, 0), ch, font=font, fill=255)
        x += w + tracking
    box = mask.getbbox() or (0, 0, mask.width, mask.height)
    return mask.crop(box), box[1]


def _gradient(size: tuple[int, int], stops: list) -> Image.Image:
    w, h = size
    col = Image.new("RGB", (1, h))
    px = col.load()
    stops = [(p / 100, _rgb(c)) for p, c in stops]
    for y in range(h):
        t = y / max(1, h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                k = (t - p0) / max(1e-6, p1 - p0)
                px[0, y] = tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3))
                break
    return col.resize((w, h))


def styled_layer(mask: Image.Image, fill: Image.Image | tuple, outline: str, outline_px: int,
                 bevel: str | None, bevel_px: int, shadow: tuple[int, int, int], shadow_opacity: float,
                 pad: int = 40) -> Image.Image:
    """Shadow, outline, fill and an upper-left bevel highlight, as one RGBA layer."""
    w, h = mask.width + 2 * pad, mask.height + 2 * pad
    m = Image.new("L", (w, h), 0)
    m.paste(mask, (pad, pad))
    grown = m.filter(ImageFilter.MaxFilter(outline_px * 2 + 1)) if outline_px else m
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sx, sy, blur = shadow
    sh = Image.new("L", (w, h), 0)
    sh.paste(grown, (sx, sy))
    sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * shadow_opacity))
    layer.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (w, h), (0, 0, 0)).split(), sh)))
    if outline_px:
        layer.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (w, h), _rgb(outline)).split(), grown)))
    if isinstance(fill, tuple):
        body = Image.new("RGB", (w, h), fill)
    else:
        body = Image.new("RGB", (w, h), (0, 0, 0))
        body.paste(fill.resize(mask.size), (pad, pad))
    layer.alpha_composite(Image.merge("RGBA", (*body.split(), m)))
    if bevel and bevel_px:
        shifted = ImageChops.offset(m, bevel_px, bevel_px)
        rim = ImageChops.subtract(m, shifted).filter(ImageFilter.GaussianBlur(0.6))
        layer.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (w, h), _rgb(bevel)).split(),
                                                   rim.point(lambda v: int(v * 0.85)))))
    return layer


def draw_text(canvas: Image.Image, text: str, box: list, font, tracking: float, spec: dict, fmt: dict,
              effect: str, fit: bool = False, rotate: float = 0.0) -> None:
    eff = spec["effects"][effect]
    mask, _ = text_mask(text, font, tracking)
    bx, by, bw, bh = box
    if fit and mask.width > bw:
        k = bw / mask.width
        mask = mask.resize((bw, max(1, round(mask.height * k))), Image.LANCZOS)
    fill = _gradient(mask.size, spec["gradients"][eff["gradient"]]) if "gradient" in eff else _rgb(eff["fill"])
    layer = styled_layer(mask, fill, eff["outline"], fmt["outline"][effect], eff.get("bevel"),
                         fmt.get("bevel", {}).get(effect, 0), tuple(fmt["shadow"][effect]), eff["shadow_opacity"])
    if rotate:
        layer = layer.rotate(-rotate, resample=Image.BICUBIC, expand=True)
    cx, cy = bx + bw / 2, by + bh / 2
    canvas.alpha_composite(layer, (round(cx - layer.width / 2), round(cy - layer.height / 2)))


# ------------------------------------------------------------------ shapes

def draw_brush(canvas: Image.Image, spec: dict, fmt: dict, seed: int) -> None:
    pal = spec["palette"]
    bx, by, bw, bh = fmt["brush"]["box"]
    jag = fmt["brush"]["jag"]
    rng = random.Random(seed)
    pad = 40
    w, h = bw + 2 * pad, bh + 2 * pad
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    top, bottom = [], []
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        x = pad + bw * t
        # Thin, frayed start on the left; full width from a third of the way.
        thick = bh * (0.45 + 0.55 * min(1.0, t * 5)) * (1 - 0.35 * max(0.0, t - 0.9) / 0.1)
        mid = pad + bh / 2
        top.append((x, mid - thick / 2 + rng.uniform(-jag, jag)))
        bottom.append((x, mid + thick / 2 + rng.uniform(-jag, jag)))
    d.polygon(top + bottom[::-1], fill=255)
    for _ in range(10):  # dry-brush streaks off both ends
        y = pad + rng.uniform(0.15, 0.85) * bh
        x0 = pad + rng.uniform(-0.05, 0.25) * bw
        d.line([(x0 - rng.uniform(20, 90), y), (x0 + rng.uniform(40, 200), y)], fill=255, width=rng.randint(1, 4))
        x1 = pad + bw * rng.uniform(0.8, 1.0)
        d.line([(x1, y), (x1 + rng.uniform(20, 60), y)], fill=255, width=rng.randint(1, 3))
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))
    paint = Image.new("RGB", (w, h), _rgb(pal["brush_red"]))
    hd = ImageDraw.Draw(paint)
    for _ in range(26):  # lighter and darker bristle lines
        y = rng.uniform(pad, pad + bh)
        color = _rgb(pal["brush_highlight"]) if rng.random() < 0.6 else (110, 8, 12)
        hd.line([(rng.uniform(0, w * 0.4), y), (rng.uniform(w * 0.5, w), y + rng.uniform(-3, 3))], fill=color,
                width=rng.randint(1, 3))
    paint = paint.filter(ImageFilter.GaussianBlur(0.8))
    layer = Image.merge("RGBA", (*paint.split(), mask.point(lambda v: int(v * 0.98))))
    layer = layer.rotate(-fmt["brush"]["rotate_deg"], resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(layer, (round(bx + bw / 2 - layer.width / 2), round(by + bh / 2 - layer.height / 2)))


def draw_ribbon(canvas: Image.Image, words: list[str], spec: dict, fmt: dict) -> None:
    pal, r = spec["palette"], fmt["ribbon"]
    bx, by, bw, bh = r["box"]
    pad = 40
    w, h = bw + 2 * pad, bh + 2 * pad
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    p = r["point"]
    pts = [(pad + p, pad), (pad + bw - p, pad), (pad + bw, pad + bh / 2), (pad + bw - p, pad + bh),
           (pad + p, pad + bh), (pad, pad + bh / 2)]
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).polygon([(x + 3, y + 5) for x, y in pts], fill=170)
    layer.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (w, h), (0, 0, 0)).split(),
                                               shadow.filter(ImageFilter.GaussianBlur(6)))))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=_rgb(pal["ribbon_navy"]) + (255,))
    d.line(pts + [pts[0]], fill=_rgb(pal["gold_border"]) + (255,), width=r["border"], joint="curve")
    text = "  •  ".join(words)
    font = cinzel(700, r["text_cap"])
    inner = (pad + p + 10, pad + 4, bw - 2 * p - 20, bh - 8)
    draw_text(layer, text, list(inner), font, r["tracking"], spec, fmt, "ribbon", fit=True)
    layer = layer.rotate(-r["rotate_deg"], resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(layer, (round(bx + bw / 2 - layer.width / 2), round(by + bh / 2 - layer.height / 2)))


def draw_tag(canvas: Image.Image, spec: dict, fmt: dict) -> None:
    t = fmt["tag"]
    bx, by, bw, bh = t["box"]
    pad = 30
    w, h = bw + 2 * pad, bh + 2 * pad
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    s = bh * math.tan(math.radians(t["slant_deg"]))
    pts = [(pad + s, pad), (pad + bw, pad), (pad + bw - s, pad + bh), (pad, pad + bh)]
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).polygon([(x + 3, y + 4) for x, y in pts], fill=150)
    layer.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (w, h), (0, 0, 0)).split(),
                                               shadow.filter(ImageFilter.GaussianBlur(5)))))
    body = _gradient((w, h), [[0, "#D0182A"], [100, "#8E0B16"]]).convert("RGBA")
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    body.putalpha(m)
    layer.alpha_composite(body)
    # Oswald has no italic: slant the upright capitals.
    font = _cap_font(TAG_FONT, t["cap"])
    mask, _ = text_mask("TRUE STORY", font, 1)
    shear = math.tan(math.radians(12))
    mask = mask.transform((mask.width + int(mask.height * shear), mask.height), Image.AFFINE,
                          (1, shear, -mask.height * shear, 0, 1, 0), resample=Image.BICUBIC)
    if mask.width > bw - 2 * s - 6:
        k = (bw - 2 * s - 6) / mask.width
        mask = mask.resize((round(mask.width * k), round(mask.height * k)), Image.LANCZOS)
    text = styled_layer(mask, (255, 255, 255), "#5A0A10", 0, None, 0, tuple(fmt["shadow"]["tag"]), 0.6, pad=12)
    layer.alpha_composite(text, (round(pad + bw / 2 - text.width / 2), round(pad + bh / 2 - text.height / 2)))
    layer = layer.rotate(-t["rotate_deg"], resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(layer, (round(bx + bw / 2 - layer.width / 2), round(by + bh / 2 - layer.height / 2)))


def draw_logo(canvas: Image.Image, channel_id: str, spec: dict, fmt: dict) -> None:
    from .brand import logo

    bx, by, bw, bh = fmt["logo"]["box"]
    path = logo(channel_id)
    if path is None:
        font = cinzel(700, round(bh * 0.32))
        draw_text(canvas, spec.get("brand_text", ""), [bx, by, bw, bh], font, -1, spec, fmt, "chrome", fit=True)
        return
    img = Image.open(path).convert("RGBA")
    k = min(bw / img.width, bh / img.height)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    glow = img.getchannel("A").filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.55))
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", img.size, (0, 0, 0)).split(), glow)), (bx + 2, by + 3))
    canvas.alpha_composite(img, (bx, by))


# ------------------------------------------------------------------ compose

def compose(subject: str, photo: Path, output_path: Path, channel, vertical: bool = False,
            plan: dict | None = None) -> Path:
    channel_id = str(getattr(channel, "id", "") or "")
    spec = load_spec(channel_id)
    if spec is None:
        raise RuntimeError(f"no thumbnail_spec.json for {channel_id}")
    fmt = spec["short" if vertical else "long"]
    w, h = fmt["size"]
    work = output_path.parent
    work.mkdir(parents=True, exist_ok=True)
    plan = plan or plan_for(subject, vertical, spec, fmt["scene_area"])
    print(f"[cinematic-thumb] {plan['name']} · {' • '.join(plan['words'])} · scene: {plan['scene'][:70]}")
    seed = sum(map(ord, subject))

    back = grade_background(backdrop(plan, w, h, spec, fmt["scene_area"], work, vertical), spec, vertical)
    canvas = back.convert("RGBA")
    place_person(canvas, photo, spec, fmt, work)
    canvas = vignette_and_grain(canvas.convert("RGB"), spec, seed).convert("RGBA")

    draw_logo(canvas, channel_id, spec, fmt)
    draw_tag(canvas, spec, fmt)
    for line in fmt["title"]:
        draw_text(canvas, line["text"], line["box"], cinzel(line["weight"], line["cap"]),
                  line["tracking"], spec, fmt, "chrome")
    draw_brush(canvas, spec, fmt, seed)
    n = fmt["name"]
    draw_text(canvas, plan["name"], n["box"], cinzel(n["weight"], n["cap"]), n["tracking"], spec, fmt,
              "gold", fit=True)
    draw_ribbon(canvas, plan["words"], spec, fmt)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=92)
    return output_path
