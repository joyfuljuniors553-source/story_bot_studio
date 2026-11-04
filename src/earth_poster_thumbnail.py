"""The natural-history poster thumbnail (Veylora Earth), drawn from the channel's design spec.

Used when data/brand/<channel>/thumbnail_spec.json says "design": "earth_poster".

Long (1280x720): the animal huge on the left and its world small in the lower
right (one Cloudflare FLUX image), the logo top left, "THE / ICE AGE / GIANTS"
on the right (Cinzel, icy silver and gold), three story words on a red brush
stroke, a rounded gold border.
Short (1080x1920): the animal in the upper right, three tilted lines in
Barlow Condensed ExtraBold Italic (icy, gold, gold), a blue-to-orange light
streak under them, the logo and the border.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .cinematic_thumbnail import _cover, _gradient, _rgb, cinzel, draw_brush, load_spec, styled_layer, text_mask
from .config import settings

FONTS = settings.root / "fonts"
ITALIC = FONTS / "BarlowCondensed-ExtraBoldItalic.ttf"


def _cap_font(path: Path, cap: int):
    from PIL import ImageFont

    probe = ImageFont.truetype(str(path), 200)
    box = probe.getbbox("H")
    return ImageFont.truetype(str(path), max(8, round(200 * cap / max(1, box[3] - box[1]))))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


# ------------------------------------------------------------------ plan

def plan_for(title: str) -> dict:
    """{top, white, gold, words[3], scene} from one AI call; a question title stays a question."""
    from .genre_topics import _script_json

    try:
        raw = _script_json(
            "You design a YouTube thumbnail for a natural-history documentary "
            "(prehistoric animals, Ice Age, human origins, ancient worlds).\n"
            f"Video title: {title}\n"
            'Return ONLY JSON: {"top": str, "white": str, "gold": str, "words": [str, str, str], "scene": str}\n'
            "- top: 'THE' when the headline reads 'THE ...', else ''.\n"
            "- white: 1-2 words of the headline (e.g. 'ICE AGE', 'DINOSAURS:').\n"
            "- gold: 1-3 words that finish it (e.g. 'GIANTS', 'REAL REASON THEY VANISHED?'). "
            "No claim the title does not make. When the title is a question, keep it a question "
            "in the title's own words, ending with '?'.\n"
            "- words: three single CAPITAL words for the story (e.g. LIFE, SURVIVAL, EXTINCTION), "
            "each at most 10 letters.\n"
            "- scene: an image prompt for a photorealistic documentary painting: the MAIN SUBJECT "
            "described as science shows it (e.g. 'a woolly mammoth with shaggy brown fur and long "
            "curved tusks') and its world (e.g. 'snowy Ice Age valley, frozen mountains, a small "
            "herd far away'). Scientifically plausible; people only far away or from behind; "
            "no text, no logos.\n"
        )
    except Exception as exc:
        print(f"[earth-thumb] plan failed ({exc}); headline from the title")
        raw = {}
    if raw and (len(str(raw.get("white") or "").split()) > 2 or len(str(raw.get("gold") or "").split()) > 4):
        try:
            again = _script_json(
                f"Shorten this thumbnail headline for the video '{title}': white "
                f"'{raw.get('white')}', gold '{raw.get('gold')}'. white 1-2 words, gold 1-3 words, "
                "same meaning, a question stays a question. Return ONLY JSON: "
                '{"top": str, "white": str, "gold": str}')
            raw.update({k: again[k] for k in ("top", "white", "gold") if again.get(k)})
        except Exception:
            pass
    top = "THE" if str(raw.get("top") or "").strip().upper() == "THE" else ""
    white = " ".join(str(raw.get("white") or "").split()).upper()
    gold = " ".join(str(raw.get("gold") or "").split()).upper()
    if title.strip().endswith("?") and white and gold:
        own = set(_words(title))
        if any(w not in own for w in _words(f"{top} {white} {gold}")) or not gold.endswith("?"):
            print(f"[earth-thumb] '{white} / {gold}' changes the question; using the title's words")
            top = white = gold = ""
    if not white or not gold:
        words = title.upper().split()
        if words and words[0] == "THE" and len(words) > 2:
            top, words = "THE", words[1:]
        cut = max(1, min(2, len(words) // 2))
        white, gold = " ".join(words[:cut]), " ".join(words[cut:]) or "EXPLAINED"
    story = [re.sub(r"[^A-Z]", "", str(w).upper()) for w in (raw.get("words") or [])]
    story = [w for w in story if 2 <= len(w) <= 10][:3]
    if len(story) < 3:
        story = ["LIFE", "SURVIVAL", "EXTINCTION"]
    scene = " ".join(str(raw.get("scene") or "").split())[:420] or f"{title}, prehistoric landscape"
    return {"top": top, "white": white[:30], "gold": gold[:40], "words": story, "scene": scene}


# ------------------------------------------------------------------ background

def _fallback(w: int, h: int, spec: dict) -> Image.Image:
    pal = spec["palette"]
    return _gradient((w, h), [[0, pal["navy"]], [55, pal["storm_blue"]], [100, pal["sunset"]]]).convert("RGB")


def backdrop(plan: dict, w: int, h: int, spec: dict, area: str, work: Path, vertical: bool) -> Image.Image:
    prompt = (
        f"{plan['scene']}. Composition: {area}. Photorealistic cinematic natural-history documentary "
        "poster art, dark dramatic deep blue storm clouds, warm amber sunset light, icy blue shadows, "
        "rich detail, sharp focus on the subject. ONE single continuous photograph with one animal of the main kind in front, "
        "not a collage, no split panels, no duplicate animals side by side. No text, no letters, no logos, no frame, no border."
    )
    try:
        from .image_assets import generate_cloudflare_image
        from .thumbnails import cloudflare_thumbnail_ready

        if cloudflare_thumbnail_ready():
            out = generate_cloudflare_image(prompt, work / "earth_scene.jpg", landscape=not vertical)
            return _cover(Image.open(out).convert("RGB"), w, h)
    except Exception as exc:
        print(f"[earth-thumb] scene not generated ({exc}); plain sky instead")
    return _fallback(w, h, spec)


def grade(img: Image.Image, spec: dict, seed: int) -> Image.Image:
    g = spec["grade"]
    img = ImageEnhance.Contrast(img).enhance(g["contrast"])
    img = ImageEnhance.Color(img).enhance(g["saturation"])
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.2, -h * 0.2, w * 1.2, h * 1.2), fill=255)
    dark = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5)).point(lambda v: int((255 - v) * g["vignette"]))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, dark)
    rng = random.Random(seed)
    noise = Image.frombytes("L", (w // 2, h // 2), bytes(rng.getrandbits(8) for _ in range((w // 2) * (h // 2))))
    return Image.blend(img, ImageChops.overlay(img, noise.resize((w, h)).convert("RGB")), g["grain"])


# ------------------------------------------------------------------ pieces

def draw_border(canvas: Image.Image, spec: dict, fmt: dict) -> None:
    pal, b = spec["palette"], fmt["border"]
    x, y, w, h = b["box"]
    glow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(glow).rounded_rectangle((x, y, x + w, y + h), radius=b["radius"], outline=255,
                                           width=b["stroke"] + 2 * b["glow"])
    glow = glow.filter(ImageFilter.GaussianBlur(b["glow"])).point(lambda v: int(v * b["glow_opacity"]))
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", canvas.size, _rgb(pal["border_glow"])).split(), glow)))
    ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + w, y + h), radius=b["radius"],
                                             outline=_rgb(pal["border"]) + (255,), width=b["stroke"])


def draw_logo(canvas: Image.Image, channel_id: str, fmt: dict) -> None:
    from .brand import logo

    path = logo(channel_id)
    if path is None:
        return
    bx, by, bw, bh = fmt["logo"]["box"]
    img = Image.open(path).convert("RGBA")
    k = min(bw / img.width, bh / img.height)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    glow = img.getchannel("A").filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.65))
    canvas.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", img.size, (0, 0, 0)).split(), glow)), (bx + 2, by + 3))
    canvas.alpha_composite(img, (bx, by))


def _layer(text: str, font, tracking: float, spec: dict, fmt: dict, effect: str, max_w: int) -> Image.Image:
    eff = spec["effects"][effect]
    mask, _ = text_mask(text, font, tracking)
    if mask.width > max_w:
        k = max_w / mask.width
        mask = mask.resize((max_w, max(1, round(mask.height * k))), Image.LANCZOS)
    fill = _gradient(mask.size, spec["gradients"][eff["gradient"]]) if "gradient" in eff else _rgb(eff["fill"])
    return styled_layer(mask, fill, eff["outline"], fmt["outline"].get(effect, 0), eff.get("bevel"),
                        fmt.get("bevel", {}).get(effect, 0), tuple(fmt["shadow"][effect]), eff["shadow_opacity"])


def _place(canvas: Image.Image, layer: Image.Image, box: list, rotate: float = 0.0, align: str = "center") -> None:
    if rotate:
        layer = layer.rotate(-rotate, resample=Image.BICUBIC, expand=True)
    x, y, w, h = box
    left = x - 40 if align == "left" else round(x + w / 2 - layer.width / 2)
    canvas.alpha_composite(layer, (left, round(y + h / 2 - layer.height / 2)))


def draw_streak(canvas: Image.Image, spec: dict, fmt: dict) -> None:
    """A thin light streak, blue on the left to orange on the right, rising slightly."""
    pal = spec["palette"]
    x, y, w, h = fmt["streak"]["box"]
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    mid = h * 0.65
    pts_top, pts_bot = [], []
    for i in range(41):
        t = i / 40
        cy = mid - h * 0.45 * t ** 1.4
        half = 1 + 9 * (t if t < 0.8 else (1 - t) * 4)
        pts_top.append((w * t, cy - half))
        pts_bot.append((w * t, cy + half))
    d.polygon(pts_top + pts_bot[::-1], fill=255)
    colour = Image.linear_gradient("L").rotate(90, expand=True).resize((w, h))
    blue, orange = Image.new("RGB", (w, h), _rgb(pal["streak_blue"])), Image.new("RGB", (w, h), _rgb(pal["streak_orange"]))
    paint = Image.composite(blue, orange, colour)
    glow = mask.filter(ImageFilter.GaussianBlur(10)).point(lambda v: min(255, int(v * 1.6)))
    canvas.alpha_composite(Image.merge("RGBA", (*paint.split(), glow)), (x, y))
    core = Image.composite(Image.new("RGB", (w, h), (255, 255, 240)), paint, mask.filter(ImageFilter.MinFilter(3)))
    canvas.alpha_composite(Image.merge("RGBA", (*core.split(), mask)), (x, y))


# ------------------------------------------------------------------ compose

def _short_lines(plan: dict) -> list[tuple[str, str]]:
    """Three lines for the Short: (text, effect). The gold part is split over two lines."""
    first = " ".join(filter(None, [plan["top"], plan["white"]]))
    gold = plan["gold"].split()
    if len(gold) >= 2:
        best = min(range(1, len(gold)), key=lambda i: abs(len(" ".join(gold[:i])) - len(" ".join(gold[i:]))))
        return [(first, "ice"), (" ".join(gold[:best]), "gold"), (" ".join(gold[best:]), "gold")]
    return [(first, "ice"), (plan["gold"], "gold")]


def compose(title: str, output_path: Path, channel, vertical: bool = False, plan: dict | None = None) -> Path:
    channel_id = str(getattr(channel, "id", "") or "")
    spec = load_spec(channel_id)
    if not spec or spec.get("design") != "earth_poster":
        raise RuntimeError(f"no earth poster spec for {channel_id}")
    fmt = spec["short" if vertical else "long"]
    w, h = fmt["size"]
    work = output_path.parent
    work.mkdir(parents=True, exist_ok=True)
    plan = plan or plan_for(title)
    print(f"[earth-thumb] {plan['top']} {plan['white']} / {plan['gold']} · {' • '.join(plan['words'])} "
          f"· scene: {plan['scene'][:60]}")
    seed = sum(map(ord, title))
    canvas = grade(backdrop(plan, w, h, spec, fmt["subject_area"], work, vertical), spec, seed).convert("RGBA")
    draw_border(canvas, spec, fmt)
    draw_logo(canvas, channel_id, fmt)

    if vertical:
        rotate = fmt["rotate_deg"]
        for (text, effect), line in zip(_short_lines(plan), fmt["lines"]):
            layer = _layer(text, _cap_font(ITALIC, line["cap"]), line["tracking"], spec, fmt, effect, line["box"][2])
            _place(canvas, layer, line["box"], rotate)
        draw_streak(canvas, spec, fmt)
    else:
        if plan["top"]:
            t = fmt["top"]
            _place(canvas, _layer(plan["top"], cinzel(t["weight"], t["cap"]), t["tracking"], spec, fmt,
                                  t["effect"], t["box"][2]), t["box"])
        for key in ("white", "gold"):
            t = fmt[key]
            _place(canvas, _layer(plan[key], cinzel(t["weight"], t["cap"]), t["tracking"], spec, fmt,
                                  t["effect"], t["box"][2]), t["box"])
        draw_brush(canvas, spec, fmt, seed)
        t = fmt["words"]
        layer = _layer("  •  ".join(plan["words"]), _cap_font(ITALIC, t["cap"]), t["tracking"], spec, fmt,
                       "words", t["box"][2])
        _place(canvas, layer, t["box"], t["rotate_deg"])
    canvas.convert("RGB").save(output_path, quality=92)
    return output_path
