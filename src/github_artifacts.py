"""Get a finished video back from the artifacts a GitHub run kept.

A runner starts empty: the videos of an earlier run are gone, and only the
database remembers them. A video that could not be uploaded when it was made
(quota, a refused login) therefore had nothing left to upload on the next run
and failed for ever with "Thumbnail missing". The daily workflow keeps every
run's video.mp4 and thumbnail.jpg as an artifact for a week, so the retry
fetches them from there.

Only works inside GitHub Actions (GITHUB_TOKEN and GITHUB_REPOSITORY set, and
`actions: read` permission); anywhere else it finds nothing and says so.
"""
from __future__ import annotations

import io
import json
import os
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

KEPT_FILES = ("video.mp4", "thumbnail.jpg")


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """An artifact download redirects to a signed storage URL that rejects
    the GitHub token, so the token must not follow the redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_OPENER = urllib.request.build_opener(_DropAuthOnRedirect)


def available() -> bool:
    return bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPOSITORY"))


def github(path: str) -> bytes:
    token = os.environ["GITHUB_TOKEN"]
    url = path if path.startswith("http") else f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "StoryBotStudio",
    })
    with _OPENER.open(request, timeout=600) as response:
        return response.read()


_LISTING: list[dict] | None = None
_BUNDLES: dict[int, dict[str, bytes]] = {}  # artifact id -> the kept files in it, read once per run
# A run's artifact is saved when that run ends; a run lasts at most this long.
_RUN_HOURS = 6


def _artifacts() -> list[dict]:
    global _LISTING
    if _LISTING is None:
        found: list[dict] = []
        for page in range(1, 6):
            batch = json.loads(github(f"actions/artifacts?per_page=100&page={page}")).get("artifacts", [])
            found += batch
            if len(batch) < 100:
                break
        _LISTING = [a for a in found if not a.get("expired") and str(a.get("name", "")).startswith("videos-")]
    return _LISTING


def _job_time(job_id: str):
    from datetime import datetime, timezone

    try:
        return datetime.strptime(job_id[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _candidates(job_id: str) -> list[dict]:
    """The artifact(s) that can hold this job: saved after the job started and
    within one run's length of it, the earliest first. Every artifact from the
    newest backwards used to be downloaded whole, one after another, for each
    video: fifteen held DimeHorizon Shorts kept the retry busy for 5.5 hours and
    the day's runs were cancelled behind it."""
    from datetime import datetime, timedelta

    started = _job_time(job_id)
    rows = []
    for artifact in _artifacts():
        try:
            saved = datetime.fromisoformat(str(artifact["created_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if started is None or started <= saved <= started + timedelta(hours=_RUN_HOURS):
            rows.append((saved, artifact))
    return [artifact for _, artifact in sorted(rows, key=lambda row: row[0])][:2]


def _bundle(artifact: dict) -> dict[str, bytes]:
    key = int(artifact["id"])
    if key not in _BUNDLES:
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(github(artifact["archive_download_url"]))) as bundle:
            for name in bundle.namelist():
                parts = Path(name).parts
                if len(parts) >= 2 and parts[-1] in KEPT_FILES:
                    files[f"{parts[-2]}/{parts[-1]}"] = bundle.read(name)
        _BUNDLES[key] = files
    return _BUNDLES[key]


def restore_run_files(run_dir: Path) -> list[str]:
    """Put a run's kept video and thumbnail back into `run_dir`; returns what was restored."""
    if not available():
        return []
    job_id = run_dir.name
    for artifact in _candidates(job_id):
        files = _bundle(artifact)
        restored = []
        for name in KEPT_FILES:
            data = files.get(f"{job_id}/{name}")
            if data is not None:
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / name).write_bytes(data)
                restored.append(name)
        if restored:
            return restored
    return []
