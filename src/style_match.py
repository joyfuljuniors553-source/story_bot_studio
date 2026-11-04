"""Check and balance for designed thumbnails: does a card really look like the
channel's own hand-made examples (data/brand/<channel>/examples/)?

The technical check (thumbnail_check.py) only knows sizes and files. This one
measures the design itself, on the card and on every example of the same
shape (16:9 or 9:16), and compares:

    bar height / width   the orange highlight bar, as a share of the card
    headline weight      how much of the headline area is ivory text: a smaller
                         or thinner headline covers less of it

A card more than ~25% off the examples on any of them fails, with the reason
in plain words. The composer then redraws with the sizes corrected toward the
examples (future_thumbnail.compose_for_lesson), and the dashboard shows the
score next to the samples.
"""
from __future__ import annotations

from pathlib import Path

TOLERANCE = 0.25


def _load(path: Path):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"not an image: {path.name}")
    tall = image.shape[0] > image.shape[1]
    size = (180, 320) if tall else (320, 180)
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA), tall


def measure(path: str | Path) -> dict:
    """Design numbers of one card (all shares of the card, 0..1)."""
    import cv2
    import numpy as np

    image, tall = _load(Path(path))
    h, w = image.shape[:2]
    b, g, r = (image[:, :, i].astype(int) for i in range(3))
    # Orange by hue, so a bar with a light-to-deep gradient still counts as one.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    orange = ((hue >= 4) & (hue <= 24) & (sat > 150) & (val > 170)).astype(np.uint8)
    # Close the gaps the dark letters cut into the bar.
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # The bar is the biggest orange area in the headline part of the card.
    zone = np.zeros_like(orange)
    if tall:
        zone[: int(h * 0.5), :] = 1
    else:
        zone[:, : int(w * 0.62)] = 1
    count, _, stats, _ = cv2.connectedComponentsWithStats(orange * zone, connectivity=8)
    bar_h = bar_w = 0.0
    off_edge = False
    if count > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        bar_w = stats[biggest, cv2.CC_STAT_WIDTH] / w
        bar_h = stats[biggest, cv2.CC_STAT_HEIGHT] / h
        left = stats[biggest, cv2.CC_STAT_LEFT]
        # A bar cut by the card's edge looks like a mistake (the examples keep a margin).
        right_cut = left + stats[biggest, cv2.CC_STAT_WIDTH] >= w
        # A long card's bar may bleed off the left side (the examples do); never off the right.
        off_edge = (left <= 0 or right_cut) if tall else right_cut
    ivory = ((r > 205) & (g > 205) & (b > 195) & (abs(r - b) < 40)).astype(np.uint8)
    if tall:
        area = ivory[int(h * 0.1): int(h * 0.3), :]
    else:
        area = ivory[int(h * 0.18): int(h * 0.5), : int(w * 0.5)]
    # Headline letters touching the side edges.
    edge_text = bool(ivory[int(h * 0.1): int(h * 0.3), :2].any() or ivory[int(h * 0.1): int(h * 0.3), -2:].any())         if tall else bool(ivory[int(h * 0.18): int(h * 0.5), :2].any())
    return {"tall": tall, "bar_h": round(float(bar_h), 3), "bar_w": round(float(bar_w), 3),
            "headline": round(float(area.mean()), 3), "off_edge": bool(off_edge), "edge_text": edge_text}


def reference(channel_id: str, tall: bool) -> dict | None:
    """The average numbers of the channel's examples of this shape."""
    from .brand import examples

    rows = []
    for path in examples(channel_id):
        try:
            m = measure(path)
        except Exception:
            continue
        if m["tall"] == tall and m["bar_h"] > 0:
            rows.append(m)
    if not rows:
        return None
    return {key: sum(r[key] for r in rows) / len(rows) for key in ("bar_h", "bar_w", "headline")} | {
        "count": len(rows)}


_WORDS = {
    "bar_h": "orange bar height",
    "bar_w": "orange bar width",
    "headline": "headline size/weight",
}


def compare(path: str | Path, channel_id: str) -> dict:
    """{'ok', 'score' (0-100), 'issues', 'ratios'}; ok when there are no examples to compare with."""
    card = measure(path)
    ref = reference(channel_id, card["tall"])
    if not ref:
        return {"ok": True, "score": None, "issues": [], "ratios": {},
                "note": "no example of this shape to compare with"}
    ratios, issues = {}, []
    for key in ("bar_h", "bar_w", "headline"):
        ratio = card[key] / ref[key] if ref[key] else 1.0
        ratios[key] = round(ratio, 2)
        if abs(ratio - 1) > TOLERANCE:
            more = "bigger" if ratio > 1 else "smaller"
            issues.append(f"{_WORDS[key]} is {abs(ratio - 1):.0%} {more} than your examples")
    if card.get("off_edge"):
        issues.append("orange bar runs off the edge of the card")
        ratios["edge"] = 1
    if card.get("edge_text"):
        issues.append("headline letters touch the edge of the card")
        ratios["edge"] = 1
    worst = max(abs(r - 1) for k, r in ratios.items() if k != "edge")
    if "edge" in ratios:
        worst = max(worst, 0.3)
    score = max(0, round(100 * (1 - worst)))
    if "edge" in ratios:
        score = min(score, 30)  # a cut-off bar or headline is never acceptable, whatever the sizes
    return {"ok": not issues, "score": score, "issues": issues, "ratios": ratios,
            "examples": ref["count"]}
