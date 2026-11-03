"""What a long video ends with, and where its description sends viewers next.

YouTube's API cannot place end-screen elements or cards; those are set in
YouTube Studio (Editor -> End screen -> "Import from video" copies one
video's layout in a click). The bot does the two parts it can:

  * every long video gets a 20-second outro: a blurred, darkened still of its
    last frame with "WATCH NEXT" over the left half and "SUBSCRIBE" over the
    right, the places YouTube's standard end-screen template puts a video and
    the subscribe button, so the elements land on a clean background;
  * every upload's description lists the channel's latest long videos under
    "Watch next", so a viewer has somewhere on the channel to go.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from .config import settings

OUTRO_SECONDS = 20  # YouTube allows end-screen elements in the last 5-20 seconds
TITLE_FONT = settings.root / "fonts" / "Anton-Regular.ttf"
BRAND_FONT = settings.root / "fonts" / "Cinzel-Black.ttf"


def _probe(video: Path) -> dict:
    from .visuals import ffprobe_bin

    done = subprocess.run([ffprobe_bin(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                           str(video)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def add_end_screen(video_path: Path, run_dir: Path, channel=None) -> Path:
    """The video with a 20-second outro joined on; the video unchanged if anything fails."""
    from .presenter import _escape
    from .visuals import ffmpeg_bin

    try:
        info = _probe(video_path)
        streams = info.get("streams") or []
        video = next(s for s in streams if s.get("codec_type") == "video")
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        w, h = int(video["width"]), int(video["height"])
        rate = str(video.get("r_frame_rate") or "30/1")
        length = float((info.get("format") or {}).get("duration") or 0)
        last = run_dir / "end_frame.jpg"
        subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{max(0.0, length - 0.5):.2f}",
                        "-i", str(video_path), "-frames:v", "1", str(last)],
                       check=True, capture_output=True, timeout=120)
        brand = str(getattr(channel, "brand", "") or getattr(channel, "name", "") or "").upper()
        texts = run_dir / "end_texts"
        texts.mkdir(exist_ok=True)
        (texts / "next.txt").write_text("WATCH NEXT", encoding="utf-8")
        (texts / "sub.txt").write_text("SUBSCRIBE", encoding="utf-8")
        (texts / "brand.txt").write_text(brand or " ", encoding="utf-8")
        size = int(h * 0.075)

        def text(name: str, font: Path, fontsize: int, x: str, y: int, color: str = "white") -> str:
            return (f"drawtext=fontfile='{_escape(font)}':textfile='{_escape(texts / name)}':"
                    f"fontsize={fontsize}:fontcolor={color}:x={x}:y={y}:"
                    "shadowcolor=black@0.7:shadowx=3:shadowy=4")

        # Left half: YouTube's video element; right: its subscribe button.
        look = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=30,"
                "eq=brightness=-0.30:saturation=0.8,"
                + text("brand.txt", BRAND_FONT, int(h * 0.05), "(w-tw)/2", int(h * 0.08), "0xE8B64A") + ","
                + text("next.txt", TITLE_FONT, size, f"{int(w * 0.27)}-tw/2", int(h * 0.20)) + ","
                + text("sub.txt", TITLE_FONT, size, f"{int(w * 0.75)}-tw/2", int(h * 0.20))
                + f",fade=t=in:st=0:d=0.6,format=yuv420p")
        outro = run_dir / "end_screen.mp4"
        sample_rate = str((audio or {}).get("sample_rate") or "48000")
        layout = "stereo" if int((audio or {}).get("channels") or 2) >= 2 else "mono"
        subprocess.run([
            ffmpeg_bin(), "-y", "-v", "error", "-loop", "1", "-framerate", rate, "-i", str(last),
            "-f", "lavfi", "-i", f"anullsrc=channel_layout={layout}:sample_rate={sample_rate}",
            "-vf", look, "-t", str(OUTRO_SECONDS), "-r", rate,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", str(outro),
        ], check=True, capture_output=True, timeout=300)
        joined = run_dir / "video_with_end_screen.mp4"
        # Re-encoding joins clips whatever their settings; the outro is short and
        # the main video is copied through the same encoder once.
        subprocess.run([
            ffmpeg_bin(), "-y", "-v", "error", "-i", str(video_path), "-i", str(outro),
            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(joined),
        ], check=True, capture_output=True, timeout=3600)
        print(f"[end screen] {OUTRO_SECONDS}s outro added")
        return joined
    except Exception as exc:
        print(f"[end screen] left out: {exc}")
        return video_path


def watch_next_block(channel, limit: int = 3) -> str:
    """'Watch next' links to the channel's latest uploaded long videos (Shorts if it has none)."""
    channel_id = str(getattr(channel, "id", "") or "")
    if not channel_id:
        return ""
    try:
        with sqlite3.connect(settings.db_path) as conn:
            rows = conn.execute(
                """SELECT title, video_url FROM videos
                   WHERE channel = ? AND video_url LIKE 'https://%' AND status IN ('uploaded', 'thumbnail_pending')
                   ORDER BY (content_type = 'long') DESC, created_at DESC LIMIT ?""",
                (channel_id, limit),
            ).fetchall()
    except Exception:
        return ""
    lines = []
    for title, url in rows:
        name = str(title or "").split(" | ")[0].strip()
        if name and url:
            lines.append(f"▶ {name}: {url}")
    return ("\n\nWatch next:\n" + "\n".join(lines)) if lines else ""
