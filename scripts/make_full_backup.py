"""One zip with the COMPLETE setup of this PC, to carry the bot to another PC.

    .venv\\Scripts\\python.exe scripts\\make_full_backup.py

Unlike a GitHub download, this zip also holds the private files: .env (every
API key), the YouTube logins (token_*.json), the Google client files, the
database, channels.json and the data folder. It is written to your Downloads
folder and never uploaded anywhere. Keep it private: whoever has it can post
to your channels.

Left out, because the new PC makes them itself or does not need them:
  .venv       built by START_DASHBOARD.bat on the first start
  runs/       work files of videos already made (hundreds of MB)
  __pycache__ and *.pyc

On the new PC: unzip it, open the folder and double-click START_DASHBOARD.bat.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "runs", "__pycache__"}
SKIP_SUFFIXES = {".pyc"}
PRIVATE = (".env", "token_", "client_secret", "credentials", "bot.sqlite3", "channels.json")


def files() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or path.suffix in SKIP_SUFFIXES:
            continue
        if path.is_file():
            found.append(path)
    return found


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    target = out_dir / f"story_bot_studio_FULL_SETUP_{stamp}.zip"
    chosen = files()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in chosen:
            zf.write(path, Path("story_bot_studio") / path.relative_to(ROOT))
    private = [p.relative_to(ROOT).as_posix() for p in chosen
               if p.relative_to(ROOT).as_posix().startswith(PRIVATE)]
    print(f"Wrote {target} ({target.stat().st_size // (1024 * 1024)} MB, {len(chosen)} files)")
    print(f"Private files inside ({len(private)}): " + ", ".join(private))
    print("Keep this zip private: it holds every key and YouTube login of this bot.")


if __name__ == "__main__":
    main()
