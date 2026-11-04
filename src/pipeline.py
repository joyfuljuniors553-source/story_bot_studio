from __future__ import annotations

from datetime import datetime
import json

from pathlib import Path

from .config import settings
from .db import active_upload_backoff, apply_upload_error_backoff, approval_mode_enabled, save_video, set_drive_url
from .models import Lesson, RenderedAssets, Scene
from .music import add_background_music
from .quality import inspect_video
from .seo import build_metadata
from .subtitles import generate_subtitles
from .tts import generate_voice, generate_voice_with_marks, prosody_for
from .video import render_video, validate_rendered_video
from .visuals import create_thumbnail, resolve_scene_image


def _cleanup_run(run_dir: Path) -> None:
    """Delete big disposable render files; keep the final video, thumbnail, subtitles."""
    keep = {"video.mp4", "thumbnail.jpg", "subtitles.srt"}
    try:
        for f in run_dir.iterdir():
            if f.is_file() and f.name not in keep:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def _append_image_credits(metadata: dict, run_dir: Path) -> None:
    """Add required attribution for free CC images to the upload description."""
    credits: list[str] = []
    for path in sorted((run_dir / "gen").glob("*.openverse.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            title = str(row.get("title") or "Image").strip()
            creator = str(row.get("creator") or "Unknown creator").strip()
            license_name = str(row.get("license") or "CC").upper()
            source = str(row.get("source_page") or row.get("license_url") or "").strip()
            credit = f"- {title} — {creator} ({license_name})"
            if source:
                credit += f": {source}"
            if credit not in credits:
                credits.append(credit)
        except Exception:
            continue
    for path in sorted((run_dir / "gen").glob("*.wikimedia.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            title = str(row.get("title") or "Image").strip()
            creator = str(row.get("creator") or "Wikimedia contributor").strip()
            license_name = str(row.get("license") or "CC").strip()
            source = str(row.get("source_page") or row.get("license_url") or "").strip()
            credit = f"- {title} — {creator} ({license_name})"
            if source:
                credit += f": {source}"
            if credit not in credits:
                credits.append(credit)
        except Exception:
            continue
    # Pexels does not require attribution, but the photographer is credited anyway.
    for path in sorted(run_dir.glob("thumbnail_art.*.pexels.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            creator = str(row.get("creator") or "").strip()
            source = str(row.get("source_page") or "").strip()
            if creator:
                credit = f"- Thumbnail photo — {creator} (Pexels)"
                if source:
                    credit += f": {source}"
                if credit not in credits:
                    credits.append(credit)
        except Exception:
            continue
    for path in sorted(run_dir.glob("clip_scene_*.pexels.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            creator = str(row.get("creator") or "").strip()
            if creator:
                credit = f"- Stock footage — {creator} (Pexels)"
                if credit not in credits:
                    credits.append(credit)
        except Exception:
            continue
    if credits:
        base = str(metadata.get("description") or "")
        block = "\n\nCredits:\n" + "\n".join(credits)
        metadata["description"] = (base + block)[:5000]


def _interactive_kids_lesson(lesson: Lesson) -> Lesson:
    """Turn passive Kids Shorts into a quick question-and-answer game."""
    import dataclasses

    scenes: list[Scene] = []
    for index, scene in enumerate(lesson.scenes):
        if index == 0:
            line = f"Quick! Can you find {scene.label}? Yes! {scene.line}"
        elif index % 2:
            line = f"What do you see? {scene.label}! {scene.line}"
        else:
            line = f"Say {scene.label} with me! {scene.line}"
        scenes.append(Scene(
            label=scene.label, line=line, image=scene.image,
            image_prompt=scene.image_prompt,
        ))
    # A bank lesson alone runs about 20 seconds. Quiz rounds over the same
    # pictures bring the Short to a minute, and repetition is how small
    # children learn the words.
    rounds = (
        lambda s: f"Do you remember this one? Think... Yes! It is {s.label}! {s.line}",
        lambda s: f"One more time, say it loud with me: {s.label}! Great job!",
    )
    first = list(scenes)
    for make in rounds:
        if sum(len(s.line.split()) for s in scenes) >= 150:
            break
        scenes += [Scene(label=s.label, line=make(s), image=s.image, image_prompt=s.image_prompt)
                   for s in lesson.scenes]
    if len(scenes) > len(first):
        scenes[len(first)] = dataclasses.replace(
            scenes[len(first)], line="Now let's play a memory game! " + scenes[len(first)].line,
        )
    return Lesson(
        topic_key=lesson.topic_key, title=lesson.title, category=lesson.category,
        intro=lesson.intro, outro=lesson.outro, scenes=scenes,
    )


def _needs_interactive_rewrite(lesson: Lesson, channel) -> bool:
    """True only for the built-in kids bank, whose scenes are bare words.

    Those entries carry a label ("Red") and a stub line, so the pipeline turns
    them into spoken question-and-answer. A written script — an AI-generated
    kids topic, for instance — already has real narration; rewriting it would
    flatten every video back into the same four sentences, which is exactly the
    sameness that makes a channel look mass-produced.
    """
    if channel is not None and not getattr(channel, "builtin", False):
        return False
    words = [len(str(scene.line or "").split()) for scene in lesson.scenes]
    return not words or max(words) <= 8


def _topic_thumbnail(lesson, channel, run_dir: Path, fallback: Path | None,
                     content_type: str = "long") -> Path | None:
    """The thumbnail of a topic channel with a look of its own (thumbnail_style).

    One AI call turns the title into a short headline with its key words
    marked and names the Wikipedia article whose free photo shows the subject;
    the scene picture stands in when there is none. None (the ordinary
    thumbnail is made) for other channels or when anything fails.
    """
    style = str(getattr(channel, "thumbnail_style", "") or "")
    if style not in ("space", "earth", "money", "ocean"):
        return None
    try:
        from .genre_topics import _script_json
        from .page_posts import real_photo
        from .thumbnails import manual_thumbnail_for

        if manual_thumbnail_for(lesson):
            return None
        # A money card shows a stock photo of the topic (Wikipedia's finance
        # pictures are charts); the others the subject's own photo on a backdrop.
        scene_brief = (
            "- scene: 2 to 4 words to search a stock photo site for ONE realistic money object or "
            "scene that shows the topic (e.g. \"glass jar dollar bills\", \"credit card close up\", "
            "\"calculator and bills\"), no faces.") if style == "money" else (
            "- scene: 2 or 3 words to search a stock photo site for the water or place behind it "
            "(e.g. \"deep ocean underwater\", \"underwater light rays\", \"dark cave\"), no animals "
            "or people.") if style == "ocean" else (
            "- scene: 2 or 3 words to search a stock photo site for the landscape or sky behind "
            "it (e.g. \"snowy tundra\", \"purple nebula\", \"jungle river\"), no animals or people.")
        plan = _script_json(
            "Write the text for a YouTube documentary thumbnail.\n"
            f"Video title: {lesson.title}\n"
            'Return ONLY JSON: {"headline": str, "wikipedia": str, "scene": str}.\n'
            "- headline: 3 to 7 words, a gripping hook, with the 1 to 3 most striking words "
            "wrapped in *stars* (e.g. \"Black Holes: *Gates of Time?*\", "
            "\"When giants *ruled the Ice Age*\"). No claim the title does not make.\n"
            "- wikipedia: the exact title of the English Wikipedia article about the thing the "
            "video is about (a planet, an animal, a site), whose photo would show it.\n"
            + scene_brief
            + ("\n- kind: \"giants\" when the video is about an animal, else \"dossier\" (a place, "
               "an expedition, a wreck, an event). For giants the starred words are the one or two "
               "huge words after a short banner; for dossier the plain words name the subject and "
               "the starred ones are a 2-3 word stamp under it. Write words for THIS video's subject "
               "(the animal's name or what makes it strange); never reuse an example's words.\n"
               'Add "kind" to the JSON.' if style == "ocean" else "")
        )
        headline = str(plan.get("headline") or "").strip() or lesson.title
        scene = str(plan.get("scene") or "").strip()[:40]
        if style == "money":
            from .money_thumbnail import compose_money_thumbnail

            return compose_money_thumbnail(headline, fallback, run_dir / "thumbnail.jpg", channel,
                                           scene=scene, vertical=content_type == "short")
        photo = fallback
        wiki = str(plan.get("wikipedia") or "").strip()
        from .verified_facts import _bank_rows, is_verified_channel

        if is_verified_channel(channel):
            # The script came from one article; its photo is the right one.
            wiki = _bank_rows(channel).get(lesson.topic_key, {}).get("source_title") or wiki
        try:
            if wiki and real_photo(wiki, run_dir):
                photo = run_dir / "article_photo.jpg"
                print(f"[thumbnail] real photo of {wiki}")
        except Exception as exc:
            print(f"[thumbnail] no photo of {wiki}, using the scene picture: {exc}")
        if not photo or not Path(photo).is_file():
            return None
        extra = {}
        if style == "ocean":
            # Abyssoryn's two styles: Ocean Giants for animals, Expedition Dossier
            # for places, expeditions and wrecks (ocean_thumbnail.py).
            from .ocean_thumbnail import compose_ocean_thumbnail as compose

            extra["kind"] = "dossier" if str(plan.get("kind") or "").lower() == "dossier" else "giants"
        elif style == "space":
            from .space_thumbnail import compose_space_thumbnail as compose
        else:
            from .earth_thumbnail import compose_earth_thumbnail as compose
        return compose(headline, Path(photo), run_dir / "thumbnail.jpg", channel, **extra,
                       scene=scene,
                       vertical=content_type == "short")
    except Exception as exc:
        print(f"[thumbnail] {style} layout skipped: {exc}")
        return None


def channel_thumbnail(lesson, channel, output_path: Path, fallback: Path | None = None,
                      content_type: str = "short", subject: str | None = None) -> Path:
    """This channel's own card (true-story or topic style), else the ordinary one.

    The same choice a new video makes, for every later remake (Remake
    thumbnail, the YouTube audit, samples), so a remade card never falls back
    to the plain look just because it was made outside a render.
    """
    import shutil
    import tempfile

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="thumb_", dir=output_path.parent))
    try:
        made = (_real_subject_thumbnail(lesson, channel, work, content_type, subject=subject)
                or _topic_thumbnail(lesson, channel, work, fallback, content_type))
        if made and Path(made).is_file():
            shutil.copyfile(made, output_path)
            return output_path
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return Path(create_thumbnail(lesson, fallback, output_path, channel, content_type))


def _real_subject_thumbnail(lesson, channel, run_dir: Path, content_type: str,
                            subject: str | None = None) -> Path | None:
    """The thumbnail of a true story about a real person: that person's own photo.

    AI or stock artwork under a real name would show a stranger as that
    person. Returns None (the ordinary thumbnail is made) for other channels,
    when you dropped in a thumbnail of your own, or when the article has no
    photo that is free to reuse.
    """
    try:
        from .page_posts import real_photo
        from .thumbnails import compose_thumbnail, manual_thumbnail_for
        from .verified_facts import _bank_rows, is_verified_channel

        if channel is None or not is_verified_channel(channel) or manual_thumbnail_for(lesson):
            return None
        if getattr(channel, "thumbnail_style", ""):
            return None  # a space or prehistory card instead (_topic_thumbnail)
        subject = subject or _bank_rows(channel).get(lesson.topic_key, {}).get("source_title")
        if not subject:
            return None
        found = real_photo(subject, run_dir)
        if not found:
            # No photo of them that may be reused: the name on a plain card,
            # rather than artwork of somebody else.
            print(f"[thumbnail] no free photo of {subject}; plain title card")
            return compose_thumbnail(lesson, None, run_dir / "thumbnail.jpg", channel, content_type)
        print(f"[thumbnail] real photo of {subject}. {found[1]}")
        try:
            from .story_thumbnail import compose_story_thumbnail

            # The uncropped photo real_photo saved: the story card places it itself.
            return compose_story_thumbnail(subject, lesson.title, run_dir / "article_photo.jpg",
                                           run_dir / "thumbnail.jpg", channel,
                                           vertical=content_type == "short")
        except Exception as exc:
            print(f"[thumbnail] story layout failed, using the plain one: {exc}")
        return compose_thumbnail(lesson, found[0], run_dir / "thumbnail.jpg", channel, content_type)
    except Exception as exc:
        print(f"[thumbnail] real photo skipped: {exc}")
        return None


def _connected(channel) -> bool:
    """True when this channel/account already has a saved YouTube login."""
    try:
        return bool(channel is not None and channel.token_path.is_file())
    except Exception:
        return False


_END_CALL = {
    "en": "If you enjoyed this, hit like, subscribe for more, and tell us in the comments what you think.",
    "sleep": "If this story helped you rest, like it, subscribe, and tell us in the comments "
             "which story you want next. Sleep well.",
}
_END_CALL_UR = (
    "Video achi lagi ho to like karein, channel subscribe karein, aur comment mein apni raye zaroor batayein.",
    "ویڈیو اچھی لگی ہو تو لائک کریں، چینل سبسکرائب کریں، اور کمنٹ میں اپنی رائے ضرور بتائیں۔",
)


def _with_end_call(lesson: Lesson, channel) -> Lesson:
    """The narrator closes by asking for a like, a subscribe and a comment.

    Not on made-for-kids channels (comments are off there).
    """
    import dataclasses

    from .language import is_urdu

    if channel is None or getattr(channel, "made_for_kids", False) or not lesson.scenes:
        return lesson
    last = lesson.scenes[-1]
    if "subscribe" in f"{last.line} {last.speech}".lower():
        return lesson
    if is_urdu(channel):
        line, speech = f"{last.line} {_END_CALL_UR[0]}", f"{last.speech or last.line} {_END_CALL_UR[1]}"
    else:
        sleepy = "sleep" in f"{channel.id} {getattr(channel, 'genre', '')}".lower() or "snuggle" in channel.id
        call = _END_CALL["sleep" if sleepy else "en"]
        line, speech = f"{last.line} {call}", (f"{last.speech} {call}" if last.speech else "")
    scenes = [*lesson.scenes[:-1], dataclasses.replace(last, line=line, speech=speech)]
    return dataclasses.replace(lesson, scenes=scenes)


def run_pipeline(
    lesson: Lesson, upload: bool = False, channel=None, content_type: str = "short",
    queue: bool | None = None, resume_run_dir: Path | None = None,
    is_daily: bool = False,
) -> RenderedAssets:
    # queue: None = use the channel's auto-upload-queue setting (default for the
    # kids/other flows). True = force the timed drip queue. False = upload
    # immediately now (skip the queue). Only matters when upload is True.
    # channel=None keeps the original kids behavior (voice/seo/upload unchanged).
    from .language import display_marks, voice_for

    voice = voice_for(channel) if channel is not None else None
    prosody = prosody_for(channel)
    channel_id = channel.id if channel is not None else "kids"
    # Which of the channel's connected YouTube accounts this video is for. The
    # caller passes an account-specific channel object, so the upload below
    # already uses that account's token.
    account_id = str(getattr(channel, "account", "main") or "main")

    if content_type not in {"short", "long"}:
        raise ValueError(f"Unsupported content type: {content_type}")
    if content_type == "short" and _needs_interactive_rewrite(lesson, channel):
        lesson = _interactive_kids_lesson(lesson)
    lesson = _with_end_call(lesson, channel)
    run_dir = Path(resume_run_dir).resolve() if resume_run_dir else settings.runs_dir / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    job_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=True)
    if channel is not None:
        from .verified_facts import is_verified_channel, source_url

        if is_verified_channel(channel):
            from urllib.parse import unquote

            from .stock_video import write_subject

            article = source_url(channel, lesson.topic_key)
            write_subject(run_dir, unquote(article.rsplit("/", 1)[-1]).replace("_", " ") if article else "")

    scene_audio_paths = []
    scene_marks: list = []
    for index, scene in enumerate(lesson.scenes, start=1):
        out = run_dir / f"voice_scene_{index:02}.mp3"
        completed_clip = run_dir / f"scene_{index:02}.mp4"
        if out.exists() and completed_clip.exists() and completed_clip.stat().st_size > 100_000:
            path, marks = out, None
        elif settings.enable_karaoke_captions:
            path, marks = generate_voice_with_marks(scene.speech or scene.line, out, voice=voice, **prosody)
            if scene.speech and scene.speech != scene.line:
                # The voice read Urdu script; the caption shows Roman Urdu.
                marks = display_marks(marks, scene.line)
        else:
            path, marks = generate_voice(scene.speech or scene.line, out, voice=voice, **prosody), None
        scene_audio_paths.append(path)
        scene_marks.append(marks)
    full_voice = run_dir / "voice.mp3"
    audio_path = full_voice if full_voice.exists() and full_voice.stat().st_size > 10_000 else generate_voice(lesson.spoken_narration, full_voice, voice=voice, **prosody)
    video_path = render_video(
        lesson, audio_path, run_dir / "video.mp4", run_dir,
        scene_audio_paths=scene_audio_paths, channel=channel,
        scene_marks=scene_marks, content_type=content_type,
    )
    from .presenter import add_presenter, presenter_enabled

    if presenter_enabled(channel):
        try:
            video_path = add_presenter(video_path, run_dir, channel, content_type)
        except Exception as exc:
            print(f"[presenter] left out of this video: {exc}")
    if content_type == "long":
        from .end_screen import add_end_screen

        # Before the music, so the music plays under the outro too.
        video_path = add_end_screen(video_path, run_dir, channel)
    video_path = add_background_music(
        video_path, run_dir, seed_text=lesson.topic_key, channel=channel, lesson=lesson,
    )
    validate_rendered_video(video_path, content_type=content_type)
    quality_report = inspect_video(video_path, content_type)
    subtitle_path = generate_subtitles(audio_path, run_dir / "subtitles.srt", lesson.narration)
    first_stem = Path(lesson.scenes[0].image).stem
    generated_first_scene = [
        path for path in sorted((run_dir / "gen").glob(f"{first_stem}_fresh_*"))
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if generated_first_scene:
        thumbnail_source = generated_first_scene[0]
    else:
        # Only a fallback now — the thumbnail's own AI artwork comes first — so a
        # missing scene image must not fail an otherwise finished video.
        try:
            thumbnail_source = resolve_scene_image(
                lesson.scenes[0], run_dir, channel, require_real_image=True,
                landscape=content_type == "long",
            )
        except Exception as exc:
            print(f"[thumbnail] no scene image available as fallback: {exc}")
            thumbnail_source = None
    thumbnail_path = (
        _real_subject_thumbnail(lesson, channel, run_dir, content_type)
        or _topic_thumbnail(lesson, channel, run_dir, thumbnail_source, content_type)
        or create_thumbnail(lesson, thumbnail_source, run_dir / "thumbnail.jpg", channel, content_type)
    )
    # Check the thumbnail now (remaking it once if it fails); a video whose
    # thumbnail is still not good enough is kept back from upload below.
    from .thumbnail_check import ThumbnailNotReady, ensure_ready, thumbnail_required

    thumbnail_problem = None
    try:
        thumbnail_path = ensure_ready(
            thumbnail_path,
            regenerate=lambda: channel_thumbnail(
                lesson, channel, run_dir / "thumbnail_remade.jpg", thumbnail_source, content_type,
            ),
        )
    except ThumbnailNotReady as exc:
        thumbnail_problem = str(exc)
        print(f"[thumbnail] not ready: {thumbnail_problem}")
    metadata = build_metadata(lesson, channel, content_type=content_type)
    _append_image_credits(metadata, run_dir)
    from .end_screen import watch_next_block

    footer = str(getattr(channel, "description_footer", "") or "").strip()
    metadata["description"] = (str(metadata.get("description") or "") + watch_next_block(channel)
                               + (f"\n\n{footer}" if footer else ""))[:5000]
    if channel is not None:
        from .verified_facts import source_url

        source = source_url(channel, lesson.topic_key)
        if source:
            metadata["description"] = f"{metadata['description']}\n\nSource: Wikipedia — {source}"

    approval_required = upload and quality_report["passed"] and not is_daily and approval_mode_enabled(channel_id)
    # There is no timed upload queue: a rendered video uploads straight away,
    # limited only by this channel's own daily budget. YouTube then keeps it
    # private until its scheduled publish time. The `queue` argument is kept so
    # older callers and saved scripts still work, but it no longer holds videos
    # back.
    status = (
        "quality_failed" if not quality_report["passed"]
        else "awaiting_approval" if approval_required
        else "daily_upload_pending" if is_daily
        else "rendered"
    )
    video_url = None
    error = None if quality_report["passed"] else "; ".join(quality_report["issues"])
    publish_at = None
    reservation_key = f"job:{job_id}"
    if upload and quality_report["passed"] and not approval_required and not _connected(channel):
        # Rendered fine, but this YouTube account was never authorized. Keep the
        # video and say so, instead of opening a sign-in nobody may be there to
        # answer (which is what hangs an unattended run).
        from .social_accounts import facebook_auto_ready

        if facebook_auto_ready(channel_id):
            # A Facebook-only channel: the video is finished once it is on the
            # Page, so it must not wait in the YouTube upload queue. Videos
            # built after YouTube is connected go to both.
            status = "facebook_only"
        else:
            status = "daily_upload_pending" if is_daily else "rendered"
            error = (f"{getattr(channel, 'name', channel_id)} is not connected to YouTube. "
                     f"Connect it in the dashboard, then this video uploads by itself.")
    elif upload and quality_report["passed"] and not approval_required \
            and thumbnail_problem and thumbnail_required():
        status = "daily_upload_pending" if is_daily else "rendered"
        error = (f"Held: thumbnail not ready ({thumbnail_problem}). Press 'Remake thumbnail' "
                 f"on the dashboard; the video uploads once its thumbnail passes the check.")
    elif upload and quality_report["passed"] and not approval_required:
        backoff = active_upload_backoff(channel_id)
        if backoff:
            reason, retry_after = backoff
            error = f"Upload paused until {retry_after}: {reason}"
            if is_daily:
                status = "daily_upload_pending"
        else:
            try:
                from .youtube_upload import ThumbnailUploadError, upload_video
                from .schedule import next_publish_at
                from .pending_uploads import (
                    _UPLOAD_GATE, daily_upload_cap_reached, upload_limit_for_channel, find_uploaded_duplicate,
                    disable_thumbnail_upload, thumbnail_permission_denied, thumbnail_upload_allowed,
                )

                with _UPLOAD_GATE:
                    duplicate = find_uploaded_duplicate(
                        channel_id, lesson.topic_key, content_type, Path(video_path),
                    )
                    if duplicate:
                        status = "duplicate_blocked"
                        error = (
                            f"Duplicate upload blocked ({duplicate[2]}); "
                            f"existing video #{duplicate[0]}: {duplicate[1]}"
                        )
                    elif daily_upload_cap_reached(channel_id, account_id):
                        # This channel already used its own daily budget. The
                        # video waits as pending and the worker uploads it as
                        # soon as the quota day resets.
                        status = "daily_upload_pending"
                        error = (
                            f"{channel.name} app upload cap reached "
                            f"({upload_limit_for_channel(channel_id, account_id)}/day "
                            "for this YouTube account); "
                            "automatic upload resumes after the YouTube quota day resets"
                        )
                    else:
                        publish_at = next_publish_at(channel_id, reservation_key=reservation_key,
                                                     content_type=content_type)
                        video_url = upload_video(
                            video_path, thumbnail_path, metadata, channel=channel,
                            publish_at=publish_at,
                            # Tried even on a channel marked as unable: one refused
                            # call costs little, and once the owner verifies the
                            # channel the first success turns thumbnails back on
                            # without anyone editing the saved state.
                            # With REQUIRE_THUMBNAIL the video waits instead: an
                            # upload that cannot get its thumbnail is not made.
                            upload_thumbnail=(thumbnail_upload_allowed(channel_id)
                                              if thumbnail_required() else True),
                        )
                        status = "scheduled" if publish_at else "uploaded"
                        if not thumbnail_upload_allowed(channel_id):
                            from .pending_uploads import enable_thumbnail_upload

                            enable_thumbnail_upload(channel_id)
                            print(f"[thumbnail] {channel_id}: thumbnails work again; switched back on")
            except ThumbnailUploadError as exc:
                video_url = exc.video_url
                error = str(exc)
                if thumbnail_permission_denied(error) and thumbnail_required():
                    disable_thumbnail_upload(channel_id)
                    status = "thumbnail_pending"
                    error = ("Video is on YouTube but kept PRIVATE: this channel cannot set custom "
                             "thumbnails yet. Verify it at youtube.com/verify, then press 'Thumbnails "
                             "Are Verified'. " + error)
                elif thumbnail_permission_denied(error):
                    disable_thumbnail_upload(channel_id)
                    status = "scheduled" if publish_at else "uploaded"
                    error = "Video uploaded; custom thumbnail skipped because this channel does not have thumbnail permission."
                else:
                    status = "thumbnail_pending"
                    apply_upload_error_backoff(channel_id, error)
            except ThumbnailNotReady as exc:
                # Nothing reached YouTube: wait, without pausing the channel's other uploads.
                from .schedule import cancel_publish_at

                cancel_publish_at(reservation_key)
                status = "daily_upload_pending" if is_daily else "rendered"
                error = f"Held: {exc}"
                publish_at = None
            except Exception as exc:
                from .schedule import cancel_publish_at

                cancel_publish_at(reservation_key)
                status = "daily_upload_pending" if is_daily else "upload_failed"
                error = str(exc)
                apply_upload_error_backoff(channel_id, error)
                publish_at = None  # nothing reached YouTube, so release the slot

    if video_url and channel is not None and getattr(channel, "focus_country", ""):
        try:
            from .playlists import add_to_playlist

            note = add_to_playlist(channel, video_url, lesson.topic_key)
            if note:
                print(f"[playlist] {note}")
        except Exception as exc:
            print(f"[playlist] skipped ({exc})")

    video_db_id = save_video(
        job_id=job_id,
        topic=lesson.topic_key,
        title=str(metadata["title"]),
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        status=status,
        video_url=video_url,
        error=error,
        channel=channel_id,
        publish_at=publish_at.isoformat() if publish_at else None,
        content_type=content_type,
        quality_report=str(quality_report),
        is_daily=is_daily,
        account=account_id,
        )

    # Cross-platform publishing is independent from YouTube. A social failure
    # is recorded per platform and never marks a valid rendered video failed.
    facebook_video = facebook_title = None
    if channel is not None and status not in {"quality_failed", "duplicate_blocked"}:
        try:
            from .dual_language import build_copy, facebook_language

            target = facebook_language(channel)
            if target:
                facebook_video, facebook_title = build_copy(lesson, channel, run_dir, content_type, target)
                print(f"[social] {target} copy for Facebook: {facebook_title}")
        except Exception as exc:
            print(f"[social] second-language copy failed ({exc}); Facebook gets the original")
    # Cross-posting follows the same rule as YouTube: a build-only run, a video
    # held for approval, or one that failed its checks is never posted anywhere.
    if upload and quality_report["passed"] and not approval_required \
            and status not in {"quality_failed", "duplicate_blocked"}:
        try:
            from .social_publish import auto_publish_video
            social_messages = auto_publish_video(
                video_db_id, channel_id, facebook_video=facebook_video, facebook_title=facebook_title,
            )
            for message in social_messages:
                print(f"[social] {message}")
        except Exception as exc:
            print(f"[social] automatic publish skipped: {exc}")
    else:
        print("[social] not posted: this run does not upload")
    # Optional: push the final video to Google Drive and free the local copy.
    if settings.enable_drive_storage and status not in {"daily_upload_pending", "duplicate_blocked", "quality_failed"}:
        try:
            from .drive_storage import upload_file
            link = upload_file(Path(video_path))
            set_drive_url(video_db_id, link)
            Path(video_path).unlink(missing_ok=True)
        except Exception as exc:
            print(f"[drive] backup failed: {exc}")

    # Always delete the big disposable intermediates to keep the app small.
    if settings.enable_run_cleanup:
        _cleanup_run(run_dir)
        if facebook_video:
            import shutil

            shutil.rmtree(Path(facebook_video).parent, ignore_errors=True)

    if status == "quality_failed":
        raise RuntimeError(
            f"Quality check failed for {job_id}: {error}. "
            "The video was kept for review and was not added to the upload queue."
        )

    return RenderedAssets(
        job_id=job_id,
        run_dir=run_dir,
        audio_path=audio_path,
        video_path=video_path,
        subtitle_path=subtitle_path,
        thumbnail_path=thumbnail_path,
    )
