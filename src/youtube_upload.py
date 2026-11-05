from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import settings


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # read the connected channel's name to verify it
]
# Changing a video after upload (private -> scheduled/public once its thumbnail
# is on) needs more than youtube.upload. New sign-ins ask for it; older logins
# without it still upload, the way they did before (see can_update).
UPDATE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
LOGIN_SCOPES = [*SCOPES, UPDATE_SCOPE]
_UPDATE_SCOPES = ("/auth/youtube", "/auth/youtube.force-ssl", "/auth/youtubepartner")


def can_update(token_file: Path | None = None) -> bool:
    """True when this channel's login may change a video after upload."""
    import json

    token_file = token_file or settings.youtube_token_file
    try:
        scopes = json.loads(Path(token_file).read_text(encoding="utf-8")).get("scopes") or []
    except Exception:
        return False
    if isinstance(scopes, str):
        scopes = scopes.split()
    return any(str(s).endswith(_UPDATE_SCOPES) for s in scopes)


# YouTube refuses a description over 5000 bytes or with < or > in it
# ("invalidDescription"). A long video's script summary plus its clip credits
# and source line ran past the limit, and the video waited forever.
_DESCRIPTION_BYTES = 4900


def youtube_description(text: str) -> str:
    text = text.replace("<", "(").replace(">", ")")
    if len(text.encode("utf-8")) <= _DESCRIPTION_BYTES:
        return text
    # Drop whole lines from the middle (the script summary), keeping the
    # opening and the closing lines, which carry the hashtags, credits and source.
    lines = text.split("\n")
    head, tail = lines[:4], lines[4:]
    while tail and len("\n".join(head + ["..."] + tail).encode("utf-8")) > _DESCRIPTION_BYTES:
        tail.pop(0)
    trimmed = "\n".join(head + ["..."] + tail)
    return trimmed.encode("utf-8")[:_DESCRIPTION_BYTES].decode("utf-8", "ignore")


class ThumbnailUploadError(RuntimeError):
    def __init__(self, video_url: str, message: str) -> None:
        super().__init__(message)
        self.video_url = video_url


def _credentials(client_secret_file: Path | None = None, token_file: Path | None = None) -> Credentials:
    client_secret_file = client_secret_file or settings.youtube_client_secret_file
    token_file = token_file or settings.youtube_token_file
    creds = None
    if token_file.exists():
        # The login's own granted scopes: refreshing with SCOPES alone would
        # drop the update scope a newer sign-in carries.
        creds = Credentials.from_authorized_user_file(str(token_file))
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not client_secret_file.exists():
            raise FileNotFoundError(f"Missing YouTube client secret: {client_secret_file}")
        # Opening a browser is only ever right on a real desktop. On a server or
        # a CI runner there is nobody to click, so the flow would block until
        # the job is killed; say what is wrong instead.
        if os.getenv("NO_INTERACTIVE_AUTH", "").strip().lower() in {"1", "true", "yes"}:
            raise RuntimeError(
                f"No usable YouTube login in {token_file.name} and this machine "
                "cannot open a browser. Connect the channel on your PC first, "
                "then re-run scripts/setup_github_actions.py."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), LOGIN_SCOPES)
        creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _youtube(client_secret_file: Path | None = None, token_file: Path | None = None):
    return build("youtube", "v3", credentials=_credentials(client_secret_file, token_file))


def set_thumbnail(video_id: str, thumbnail_path: Path, attempts: int = 4,
                  client_secret_file: Path | None = None, token_file: Path | None = None) -> None:
    youtube = _youtube(client_secret_file, token_file)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
            return
        except Exception as exc:
            last_error = exc
            # Daily quota errors cannot recover seconds later. The queue retries later.
            if isinstance(exc, HttpError):
                reason = str(exc).lower()
                if (
                    "quotaexceeded" in reason
                    or ("exceeded your" in reason and "quota" in reason)
                    or "doesn't have permissions to upload and set custom video thumbnails" in reason
                    # Too many thumbnails on this channel today: retrying seconds
                    # later only spends more of the day's allowance.
                    or "uploadratelimitexceeded" in reason
                    or "too many thumbnails" in reason
                ):
                    break
            if attempt < attempts:
                time.sleep(8 * attempt)
    raise RuntimeError(f"Thumbnail upload failed after {attempts} attempts: {last_error}")


def upload_video(video_path: Path, thumbnail_path: Path, metadata: dict[str, object],
                 channel=None, publish_at: datetime | None = None,
                 progress_callback: Callable[[int], None] | None = None,
                 upload_thumbnail: bool = True) -> str:
    # Resolve per-channel credentials + settings; default = original kids behavior.
    if channel is not None:
        client_secret_file = channel.client_secret_path
        token_file = channel.token_path
        category_id = channel.category_id
        made_for_kids = channel.made_for_kids
        privacy = channel.privacy
    else:
        client_secret_file = None
        token_file = None
        category_id = "27"
        made_for_kids = True
        privacy = settings.youtube_privacy_status

    status_body: dict[str, object] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": made_for_kids,
    }
    # Scheduled publish: YouTube requires the video be private until publishAt,
    # then it flips it public automatically at that timestamp (RFC3339 UTC).
    if publish_at is not None:
        status_body["privacyStatus"] = "private"
        status_body["publishAt"] = publish_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # No video goes up without a checked thumbnail. It is uploaded private and
    # only scheduled / made public once its thumbnail is on (see release_video).
    from .thumbnail_check import ThumbnailNotReady, check_thumbnail, thumbnail_required

    required = thumbnail_required()
    final_status = status_body
    if required:
        if not upload_thumbnail:
            raise ThumbnailNotReady(
                "YouTube does not allow custom thumbnails on this channel yet. Verify it at "
                "youtube.com/verify, then press 'Thumbnails Are Verified' on the dashboard"
            )
        check = check_thumbnail(thumbnail_path)
        if not check.ok:
            raise ThumbnailNotReady(f"thumbnail failed its check: {check.summary}")
        if can_update(token_file):
            status_body = {"privacyStatus": "private", "selfDeclaredMadeForKids": made_for_kids}
        else:
            # This login may upload but not change a video afterwards, so a
            # private video could never be released: upload it scheduled, as
            # before, and set the checked thumbnail right after. Reconnecting
            # the channel on the dashboard grants the update permission.
            print("[upload] this channel's login cannot change a video after upload; "
                  "uploading it scheduled (reconnect the channel to hold it private)")
            required = False

    youtube = _youtube(client_secret_file, token_file)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": metadata["title"],
                "description": youtube_description(str(metadata["description"])),
                "tags": metadata["tags"],
                "categoryId": category_id,
                # Tells YouTube which language the title and the voice are in.
                "defaultLanguage": str(metadata.get("language") or "en"),
                "defaultAudioLanguage": str(metadata.get("language") or "en"),
            },
            "status": status_body,
        },
        media_body=MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    if progress_callback:
        progress_callback(0)
    while response is None:
        status, response = request.next_chunk()
        if status is not None and progress_callback:
            progress_callback(max(1, min(99, int(status.progress() * 100))))
    if progress_callback:
        progress_callback(100)
    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    if upload_thumbnail:
        try:
            set_thumbnail(video_id, thumbnail_path, client_secret_file=client_secret_file, token_file=token_file)
        except Exception as exc:
            held = " (video kept private until its thumbnail is set)" if required else ""
            raise ThumbnailUploadError(video_url, f"{exc}{held}") from exc
    if required and final_status != status_body:
        try:
            _set_status(youtube, video_id, final_status)
        except Exception as exc:
            raise ThumbnailUploadError(
                video_url, f"thumbnail is set, but releasing the private video failed: {exc}"
            ) from exc
    return video_url


def _set_status(youtube, video_id: str, status: dict[str, object]) -> None:
    youtube.videos().update(part="status", body={"id": video_id, "status": status}).execute()


def release_video(video_url: str, channel, publish_at: str | datetime | None) -> datetime | None:
    """Schedule or publish a video that was held private until its thumbnail was set.

    Returns the publish time when it is scheduled, or None when it went live now.
    """
    from urllib.parse import parse_qs, urlparse

    video_id = (parse_qs(urlparse(video_url).query).get("v") or [video_url.rsplit("/", 1)[-1]])[0]
    when = publish_at
    if isinstance(when, str) and when:
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if isinstance(when, datetime) and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    status: dict[str, object] = {"selfDeclaredMadeForKids": bool(channel.made_for_kids)}
    # publishAt must lie ahead; a slot that passed while the video waited goes live now.
    if isinstance(when, datetime) and when > datetime.now(timezone.utc) + timedelta(minutes=10):
        status["privacyStatus"] = "private"
        status["publishAt"] = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        when = None
        status["privacyStatus"] = channel.privacy
    if not can_update(channel.token_path):
        raise RuntimeError("this channel's YouTube login cannot change a video after upload; "
                           "reconnect the channel on the dashboard, then the video is released")
    _set_status(_youtube(channel.client_secret_path, channel.token_path), video_id, status)
    return when


def connect_and_verify(client_secret_file, token_file) -> str:
    """Authorize one channel and return the connected YouTube channel's name.

    Powers the dashboard 'Connect & verify' button so you can confirm each
    channel is linked to the CORRECT YouTube channel before any upload.
    """
    service = _youtube(client_secret_file, token_file)
    resp = service.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return "Connected, but no YouTube channel found on this account."
    return items[0]["snippet"]["title"]
