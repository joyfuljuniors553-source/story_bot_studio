"""The cosmic headline thumbnail (Quasorynth), drawn from the channel's design spec.

Used when data/brand/<channel>/thumbnail_spec.json says "design": "cosmic_headline".

Layers: one oversized space object made by Cloudflare FLUX from the video's
subject (deep navy-black space, violet nebula, blue stars) -> grade, darker
lower left, vignette, grain -> rounded gold border -> "SPACE EXPLAINED"
capsule with a ringed-planet icon -> white first headline line -> metallic
gold second headline line (Barlow Condensed ExtraBold Italic).
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .cinematic_thumbnail import _cover, _gradient, _rgb, styled_layer, text_mask, load_spec
from .config import settings

FONTS = settings.root / "fonts"
HEADLINE_FONT = FONTS / "BarlowCondensed-ExtraBoldItalic.ttf"
BADGE_FONT = FONTS / "Montserrat-ExtraBold.ttf"


def _cap_font(path: Path, cap: int):
    from PIL import ImageFont

    probe = ImageFont.truetype(str(path), 200)
    box = probe.getbbox("H")
    return ImageFont.truetype(str(path), max(8, round(200 * cap / max(1, box[3] - box[1]))))


# ------------------------------------------------------------------ plan

def plan_for(title: str) -> dict:
    """{white, gold, scene}: the headline split in two lines and the space object to paint."""
    from .genre_topics import _script_json

    try:
        raw = _script_json(
            "You design a YouTube thumbnail for a space documentary.\n"
            f"Video title: {title}\n"
            'Return ONLY JSON: {"white": str, "gold": str, "scene": str}\n'
            "- white: the first headline line, 1-3 words (e.g. 'BLACK HOLES:', 'DO GALAXIES').\n"
            "- gold: the second line, 2-4 words that finish the hook (e.g. 'GATES OF TIME?', "
            "'HAVE AN END?'). Together at most 7 words, no claim the title does not make. When the "
            "title is a question or a 'what if', the headline stays that question, uses the title's "
            "own words and ends with '?' (e.g. 'WHAT IF A MAGNETAR' / 'HIT EARTH?').\n"
            "- scene: an image prompt for ONE oversized, realistic astronomical object or event "
            "from this video's subject (e.g. 'a black hole with a brilliant orange-gold accretion "
            "disk and purple gravitational lensing'). No text, no people, no spacecraft logos.\n"
        )
    except Exception as exc:
        print(f"[cosmic-thumb] plan failed ({exc}); headline from the title")
        raw = {}
    white = " ".join(str(raw.get("white") or "").split()).upper()
    gold = " ".join(str(raw.get("gold") or "").split()).upper()
    if title.strip().endswith("?") and white and gold:
        # A question must not become a claim ("What if a magnetar hit Earth?" ->
        # "EARTH VAPORIZED"): its words must all come from the title.
        own = set(re.findall(r"[a-z0-9']+", title.lower()))
        used = re.findall(r"[a-z0-9']+", f"{white} {gold}".lower())
        if any(word not in own for word in used) or not gold.endswith("?"):
            print(f"[cosmic-thumb] '{white} / {gold}' changes the question; using the title's words")
            white = gold = ""
    if not white or not gold:
        words = title.upper().split()
        cut = max(1, min(3, len(words) // 2))
        white, gold = " ".join(words[:cut]), " ".join(words[cut:]) or "EXPLAINED"
    scene = " ".join(str(raw.get("scene") or "").split())[:400] or f"{title}, realistic astronomy"
    return {"white": white[:40], "gold": gold[:48], "scene": scene}


# ------------------------------------------------------------------ background

def _space(w: int, h: int, spec: dict, seed: int) -> Image.Image:
    """Stand-in: a violet nebula gradient with stars, when no image can be generated."""
    pal = spec["palette"]
    img = _gradient((w, h), [[0, pal["background_black"]], [65, pal["background_violet"]],
                             [100, pal["nebula_mid"]]]).convert("RGB")
    d = ImageDraw.Draw(img)
    rng = random.Random(seed)
    for _ in range(w * h // 1800):
        x, y, r = rng.randrange(w), rng.randrange(h), rng.choice((1, 1, 1, 2))
        c = rng.choice(((255, 255, 255), _rgb(pal["electric_blue"]), _rgb(pal["nebula_bright"])))
        d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    return img


def backdrop(plan: dict, w: int, h: int, spec: dict, area: str, work: Path, vertical: bool, seed: int) -> Image.Image:
    prompt = (
        f"{plan['scene']}. Composition: {area}. Deep navy-black space, vivid saturated violet, purple and magenta "
        "nebula clouds swirling around it, electric-blue stars, warm golden light on the object, cinematic, "
        "photorealistic astronomy art, high detail. No text, no letters, no logos, no people, no frame, no grid, no straight lines, no user-interface elements."
    )
    try:
        from .image_assets import generate_cloudflare_image
        from .thumbnails import cloudflare_thumbnail_ready

        if cloudflare_thumbnail_ready():
            out = generate_cloudflare_image(prompt, work / "cosmic_scene.jpg", landscape=not vertical)
            return _cover(Image.open(out).convert("RGB"), w, h)
    except Exception as exc:
        print(f"[cosmic-thumb] scene not generated ({exc}); painted space instead")
    return _space(w, h, spec, seed)


def grade(img: Image.Image, spec: dict, vertical: bool, seed: int) -> Image.Image:
    g = spec["grade"]
    img = ImageEnhance.Contrast(img).enhance(g["contrast"])
    img = ImageEnhance.Color(img).enhance(g["saturation"])
    w, h = img.size
    # Darker where the headline sits: lower left (long) or the bottom third (Short).
    shade = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(shade)
    if vertical:
        d.rectangle((0, int(h * 0.6), w, h), fill=int(255 * g["text_region_darkening"] * 3))
    else:
        d.ellipse((-w * 0.35, h * 0.35, w * 0.8, h * 1.5), fill=int(255 * g["text_region_darkening"] * 3))
    shade = shade.filter(ImageFilter.GaussianBlur(w // 10))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, shade)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.2, -h * 0.2, w * 1.2, h * 1.2), fill=255)
    dark = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5)).point(lambda v: int((255 - v) * g["vignette"]))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, dark)
    rng = random.Random(seed)
    noise = Image.frombytes("L", (w // 2, h // 2), bytes(rng.getrandbits(8) for _ in range((w // 2) * (h // 2))))
    return Image.blend(img, ImageChops.overlay(img, noise.resize((w, h)).convert("RGB")), g["grain"])


# ------------------------------------------------------------------ frame and badge

def draw_border(canvas: Image.Image, spec: dict, fmt: dict) -> None:
    pal, b = spec["palette"], fmt["border"]
    x, y, w, h = b["box"]
    glow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(glow).rounded_rectangle((x, y, x + w, y + h), radius=b["radius"], outline=255,
                                           width=b["stroke"] + 2 * b["glow"])
    glow = glow.filter(ImageFilter.GaussianBlur(b["glow"])).point(lambda v: int(v * b["glow_opacity"]))
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", canvas.size, _rgb(pal["outer_glow"])).split(), glow)))
    ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + w, y + h), radius=b["radius"],
                                             outline=_rgb(pal["outer_border"]) + (255,), width=b["stroke"])


def _planet(size: tuple[int, int], color: tuple, stroke: int) -> Image.Image:
    """A ringed planet in gold outline: a circle crossed by a tilted ring."""
    w, h = size
    s = 4  # draw large, shrink smooth
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = h * s * 0.36
    cx, cy = w * s / 2, h * s / 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color + (255,), width=stroke * s)
    ring = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((w * s * 0.04, cy - h * s * 0.17, w * s * 0.96, cy + h * s * 0.17),
                                 outline=color + (255,), width=stroke * s)
    ring = ring.rotate(18, resample=Image.BICUBIC, center=(cx, cy))
    # The ring passes behind the planet on top: hide its upper part inside the circle.
    cut = Image.new("L", img.size, 255)
    ImageDraw.Draw(cut).pieslice((cx - r + stroke * s, cy - r + stroke * s, cx + r - stroke * s, cy + r - stroke * s),
                                 180, 360, fill=0)
    ring.putalpha(ImageChops.multiply(ring.getchannel("A"), cut))
    img.alpha_composite(ring)
    return img.resize((w, h), Image.LANCZOS)


def draw_badge(canvas: Image.Image, spec: dict, fmt: dict) -> None:
    pal, b = spec["palette"], fmt["badge"]
    x, y, w, h = b["box"]
    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x + 3, y + 5, x + w + 3, y + h + 5), radius=b["radius"], fill=150)
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", canvas.size, (0, 0, 0)).split(),
                                                shadow.filter(ImageFilter.GaussianBlur(6)))))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x, y, x + w, y + h), radius=b["radius"], fill=_rgb(pal["badge_fill"]) + (255,),
                        outline=_rgb(pal["badge_border"]) + (255,), width=b["border"])
    ix, iy, iw, ih = b["icon_box"]
    canvas.alpha_composite(_planet((iw, ih), _rgb(pal["planet_gold"]), b["icon_stroke"]), (ix, iy))
    mask, _ = text_mask(spec.get("badge_text", "SPACE EXPLAINED"), _cap_font(BADGE_FONT, b["cap"]), b["tracking"])
    tx, ty, tw, th = b["text_box"]
    if mask.width > tw:
        k = tw / mask.width
        mask = mask.resize((tw, max(1, round(mask.height * k))), Image.LANCZOS)
    eff = spec["effects"]["badge"]
    layer = styled_layer(mask, _rgb(eff["fill"]), eff["outline"], 0, None, 0,
                         tuple(fmt["shadow"]["badge"]), eff["shadow_opacity"], pad=20)
    canvas.alpha_composite(layer, (tx - 20, round(ty + th / 2 - mask.height / 2) - 20))


# ------------------------------------------------------------------ headline

def draw_line(canvas: Image.Image, text: str, spec: dict, fmt: dict, which: str) -> None:
    eff, line = spec["effects"][which], fmt[which]
    mask, _ = text_mask(text, _cap_font(HEADLINE_FONT, line["cap"]), line["tracking"])
    x, y, w, h = line["box"]
    if mask.width > w:  # one line always: shrink to fit
        k = w / mask.width
        mask = mask.resize((w, max(1, round(mask.height * k))), Image.LANCZOS)
    fill = _gradient(mask.size, spec["gradients"][eff["gradient"]]) if "gradient" in eff else _rgb(eff["fill"])
    pad = 40
    layer = styled_layer(mask, fill, eff["outline"], fmt["outline"][which], eff.get("bevel"),
                         fmt["bevel"][which], tuple(fmt["shadow"][which]), eff["shadow_opacity"], pad=pad)
    # Left aligned; the capitals stand on the bottom of the box.
    canvas.alpha_composite(layer, (x - pad, y + h - mask.height - pad))


# ------------------------------------------------------------------ compose

def compose(title: str, output_path: Path, channel, vertical: bool = False, plan: dict | None = None) -> Path:
    channel_id = str(getattr(channel, "id", "") or "")
    spec = load_spec(channel_id)
    if not spec or spec.get("design") != "cosmic_headline":
        raise RuntimeError(f"no cosmic thumbnail spec for {channel_id}")
    fmt = spec["short" if vertical else "long"]
    w, h = fmt["size"]
    work = output_path.parent
    work.mkdir(parents=True, exist_ok=True)
    plan = plan or plan_for(title)
    print(f"[cosmic-thumb] {plan['white']} / {plan['gold']} · scene: {plan['scene'][:70]}")
    seed = sum(map(ord, title))

    canvas = grade(backdrop(plan, w, h, spec, fmt["subject_area"], work, vertical, seed), spec, vertical, seed)
    canvas = canvas.convert("RGBA")
    draw_border(canvas, spec, fmt)
    draw_badge(canvas, spec, fmt)
    draw_line(canvas, plan["white"], spec, fmt, "white")
    draw_line(canvas, plan["gold"], spec, fmt, "gold")
    canvas.convert("RGB").save(output_path, quality=92)
    return output_path
