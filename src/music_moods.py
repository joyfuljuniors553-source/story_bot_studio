"""Background music that fits the video: one mood per kind of story.

Every video used to get the same cheerful toy-piano tune, which is right for
the kids channel and wrong under a war story or a crime case. The mood is
chosen from the channel (its genre and tone) and from the words of the script
itself, and each mood has its own key, tempo, chords and instruments. The
music is synthesised here, so there is no licence to worry about and nothing
to download on the GitHub runner.

Your own tracks win over the synthesiser: drop .mp3/.wav/.m4a files into
data/music/<channel id>/ or data/music/<mood>/ and one of them is used
instead (picked per video, looped to the video's length).
"""
from __future__ import annotations

import random
import re
import wave
from pathlib import Path

from .config import settings

MUSIC_DIR = settings.root / "data" / "music"
SAMPLE_RATE = 44100

# Words that point at a mood, looked for in the genre, the tone and the script.
MOOD_WORDS = {
    "epic": ("history", "histor", "hero", "valor", "war", "battle", "empire", "army", "soldier", "king",
             "conquer", "legend", "courage", "brave", "general", "siege", "medal", "expedition", "explor"),
    "tense": ("crime", "mystery", "detective", "murder", "case", "police", "evidence", "suspect",
              "investigat", "heist", "spy", "escape", "secret"),
    "dark": ("horror", "ghost", "haunted", "eerie", "curse", "nightmare", "scary", "creepy", "paranormal"),
    "warm": ("love", "romance", "romantic", "heart", "wedding", "family", "mother", "kindness",
             "humanitarian", "orphan", "charity", "nurse", "mercy", "care"),
    "uplift": ("motivation", "motivat", "success", "inspir", "dream", "champion", "win", "goal",
               "discipline", "sport", "record", "athlete"),
    "news": ("news", "trending", "headline", "economy", "election", "market", "technology", "report"),
    "calm": ("cook", "recipe", "kitchen", "food", "travel", "nature", "health", "garden", "science",
             "learn", "tutorial"),
    # Slow, wide and a little uneasy: the sound of a space or deep-sea documentary.
    "ambient": ("space", "universe", "galax", "cosmic", "cosmos", "nebula", "black hole", "quasar",
                "planet", "ocean", "deep sea", "underwater", "abyss", "trench", "void"),
}
GENRE_MOOD = {
    "kids": "kids", "crime": "tense", "mystery": "tense", "horror": "dark", "love": "warm",
    "motivation": "uplift", "trending": "news", "cooking": "calm",
    # The documentary channels: their tones say "awe-inspiring", which alone
    # pulled ocean and space videos to upbeat rock.
    "deep ocean & unknown earth": "ambient", "space documentaries": "ambient",
    "paleontology & history": "epic", "personal finance": "news", "celebrity": "warm",
}

# Semitones above the root for each chord of the loop, and how the mood plays.
#   root: Hz of the key note; bpm; chords: 4 chords, 2 bars each
#   pad: level of the held chord; arp: level of the broken-chord notes
#   bass: "held" | "pulse" | ""; drum: "taiko" | "kick" | "tick" | ""
_MINOR, _MAJOR = (0, 3, 7), (0, 4, 7)
MOODS = {
    "epic":   {"root": 146.83, "bpm": 84,  "chords": [(0, _MINOR), (8, _MAJOR), (3, _MAJOR), (10, _MAJOR)],
               "pad": 0.55, "arp": 0.12, "bass": "held", "drum": "taiko", "lead": 0.22},
    "tense":  {"root": 110.00, "bpm": 100, "chords": [(0, _MINOR), (0, _MINOR), (5, _MINOR), (7, _MAJOR)],
               "pad": 0.35, "arp": 0.10, "bass": "pulse", "drum": "tick", "lead": 0.0},
    "dark":   {"root": 65.41,  "bpm": 60,  "chords": [(0, (0, 1, 7)), (0, (0, 3, 6)), (0, (0, 1, 7)), (0, (0, 6, 10))],
               "pad": 0.70, "arp": 0.0, "bass": "held", "drum": "", "lead": 0.10},
    "warm":   {"root": 174.61, "bpm": 72,  "chords": [(0, _MAJOR), (9, _MINOR), (5, _MAJOR), (7, _MAJOR)],
               "pad": 0.40, "arp": 0.30, "bass": "held", "drum": "", "lead": 0.0},
    "uplift": {"root": 130.81, "bpm": 112, "chords": [(0, _MAJOR), (7, _MAJOR), (9, _MINOR), (5, _MAJOR)],
               "pad": 0.35, "arp": 0.28, "bass": "pulse", "drum": "kick", "lead": 0.0},
    "calm":   {"root": 196.00, "bpm": 76,  "chords": [(0, _MAJOR), (5, _MAJOR), (9, _MINOR), (7, _MAJOR)],
               "pad": 0.40, "arp": 0.24, "bass": "", "drum": "", "lead": 0.0},
    # Cinematic motivation: starts as a bare minor piano chord and grows, the
    # tune, then the bass, then the drums coming in ("build" below).
    "rise":   {"root": 110.00, "bpm": 96,  "chords": [(0, _MINOR), (8, _MAJOR), (3, _MAJOR), (10, _MAJOR)],
               "pad": 0.45, "arp": 0.30, "bass": "pulse", "drum": "taiko", "lead": 0.16, "build": True},
    # Held, airy chords with a slow swell and a few soft notes: no drums, no pulse.
    "ambient": {"root": 98.00, "bpm": 58, "chords": [(0, (0, 3, 10)), (8, (0, 4, 11)), (5, (0, 3, 10)), (10, (0, 4, 7))],
                "pad": 0.65, "arp": 0.05, "bass": "held", "drum": "", "lead": 0.07},
    "news":   {"root": 146.83, "bpm": 104, "chords": [(0, _MINOR), (5, _MAJOR), (0, _MINOR), (10, _MAJOR)],
               "pad": 0.40, "arp": 0.12, "bass": "pulse", "drum": "tick", "lead": 0.0},
}


def _count(word: str, text: str) -> int:
    """How often a mood word occurs; short words whole ("war", not "warm"), longer ones as a stem."""
    end = r"\b" if len(word) <= 4 else ""
    return len(re.findall(rf"\b{re.escape(word)}{end}", text))


def mood_for(channel=None, lesson=None) -> str:
    """The mood for one video: the channel's own, unless the script clearly says otherwise."""
    from .video import is_cinematic

    genre = str(getattr(channel, "genre", "") or "kids").lower()
    if getattr(channel, "builtin", False) or genre == "kids":
        return "kids"
    own = str(getattr(channel, "music_mood", "") or "").strip().lower()
    if own in MOODS:
        return own
    if is_cinematic(channel):
        return "rise"
    channel_text = f"{genre} {getattr(channel, 'tone', '')} {getattr(channel, 'name', '')}".lower()
    script_text = ""
    if lesson is not None:
        script_text = " ".join(
            [str(lesson.title), *[f"{scene.label} {scene.line}" for scene in lesson.scenes]]
        ).lower()
    scores = {mood: 0.0 for mood in MOOD_WORDS}
    if genre in GENRE_MOOD:
        scores[GENRE_MOOD[genre]] += 6
    for mood, words in MOOD_WORDS.items():
        # The channel sets the base; the script can outweigh it with enough
        # of its own words (a humanitarian's life on a war-history channel).
        scores[mood] += 2 * sum(1 for word in words if _count(word, channel_text))
        scores[mood] += sum(_count(word, script_text) for word in words)
    best = max(scores, key=lambda mood: scores[mood])
    return best if scores[best] > 0 else "calm"


# Moods that sound close enough to stand in when a mood has few tracks of its own.
_NEAR = {
    "calm": ("warm",), "warm": ("calm",), "epic": ("uplift",), "uplift": ("epic",),
    "news": ("uplift",), "tense": ("news", "epic"), "dark": ("tense", "epic"), "rise": ("epic", "uplift"),
    "ambient": ("calm", "dark"),
}

# The strongest beat a track may have to play under a mood (beat_strength:
# 0 = no pulse, about 0.6 = a dance tune). The space channel's quiet "calm"
# folder had one track, so it borrowed from "warm" and a quasar Short got
# "Friendly Dance" (0.59). Moods not listed take any beat.
MAX_BEAT = {"ambient": 0.25, "calm": 0.30, "dark": 0.30, "warm": 0.45}
_FEEL_FILE = MUSIC_DIR / ".beat_strength.json"


def beat_strength(track: Path) -> float | None:
    """How strongly a track pulses, 0..1: the autocorrelation peak of its loudness
    onsets at 60-180 BPM, over 40 s from its middle. None when it cannot be read.
    Measured once per file and remembered in data/music/.beat_strength.json."""
    import json
    import subprocess

    try:
        stat = track.stat()
        key = f"{track.parent.name}/{track.name}:{stat.st_size}"
    except OSError:
        return None
    try:
        known = json.loads(_FEEL_FILE.read_text(encoding="utf-8"))
    except Exception:
        known = {}
    if key in known:
        return known[key]
    try:
        import numpy as np

        from .visuals import ffmpeg_bin

        rate = 11025
        raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", "20", "-t", "40", "-i", str(track),
                              "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                             capture_output=True, timeout=120).stdout
        x = np.frombuffer(raw, np.int16).astype(float) / 32768
        hop = rate // 100
        count = len(x) // hop
        if count < 600:  # under 6 s of sound: too short to judge
            return None
        level = np.sqrt((x[: count * hop].reshape(count, hop) ** 2).mean(axis=1))
        onsets = np.maximum(0.0, np.diff(np.log(level + 1e-4)))
        onsets -= onsets.mean()
        corr = np.correlate(onsets, onsets, "full")[len(onsets) - 1:]
        if not corr[0]:
            return None
        corr /= corr[0]
        value = round(float(corr[33:100].max()), 3)   # lags of 0.33-1.0 s = 180-60 BPM
    except Exception as exc:
        print(f"[music] could not measure {track.name}: {exc}")
        return None
    known[key] = value
    try:
        _FEEL_FILE.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return value


def fits_mood(track: Path, mood: str) -> bool:
    """False for a track that pulses harder than the mood allows."""
    ceiling = MAX_BEAT.get(mood)
    if ceiling is None:
        return True
    strength = beat_strength(track)
    if strength is None or strength <= ceiling:
        return True
    print(f"[music] {track.name} left out: beat {strength:.2f} is too strong for {mood} (max {ceiling})")
    return False


def _tracks(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"})


def own_track(channel, mood: str, seed_text: str) -> Path | None:
    """A track the owner dropped into data/music/, if there is one for this video.

    The channel's own folder wins; else the mood's, joined by the moods near it
    while it holds fewer than three, so one track is not heard in every video."""
    # The channel's own folder is the owner's choice and is used as it is.
    tracks = _tracks(MUSIC_DIR / str(getattr(channel, "id", "") or "_"))
    if not tracks:
        # Every other track, the mood's own included, must be calm enough for
        # the mood; with none left the mood's music is synthesised instead.
        tracks = [t for t in _tracks(MUSIC_DIR / mood) if fits_mood(t, mood)]
        for near in _NEAR.get(mood, ()):
            if len(tracks) >= 3:
                break
            tracks += [t for t in _tracks(MUSIC_DIR / near) if fits_mood(t, mood)]
    return random.Random(seed_text).choice(tracks) if tracks else None


def _envelope(np, length: int, attack: float, release: float):
    """Fade in and out over a note so joined notes do not click."""
    env = np.ones(length)
    a = min(length // 2, max(1, int(attack * SAMPLE_RATE)))
    r = min(length // 2, max(1, int(release * SAMPLE_RATE)))
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def _voice(np, freq: float, t, harmonics: tuple[float, ...]):
    """A note as a few stacked sine partials (1st, 2nd, 3rd ...)."""
    out = np.zeros_like(t)
    for number, level in enumerate(harmonics, start=1):
        out += level * np.sin(2.0 * np.pi * freq * number * t)
    return out


def _ramp(x: float, begin: float, full: float) -> float:
    """0 before `begin`, 1 after `full`, a straight line between."""
    return min(1.0, max(0.0, (x - begin) / (full - begin)))


def write_mood_music(output_path: Path, duration: float, mood: str, seed_text: str) -> Path:
    """Synthesise `duration` seconds of `mood` music; each video gets its own variation."""
    import numpy as np

    spec = MOODS[mood]
    rng = random.Random(f"{mood}:{seed_text}")
    root = spec["root"] * 2 ** (rng.choice([-2, -1, 0, 0, 1, 2]) / 12)   # a nearby key
    beat = 60.0 / (spec["bpm"] * rng.uniform(0.94, 1.06))
    chord_len = int(beat * 8 * SAMPLE_RATE)                              # two bars of four
    total = max(1, int(duration * SAMPLE_RATE))
    mix = np.zeros(total + chord_len)
    noise = np.random.default_rng(rng.randrange(1 << 30))
    arp_order = rng.choice([(0, 1, 2, 1), (0, 2, 1, 2), (2, 1, 0, 1), (0, 1, 2, 2)])
    lead_step = 0

    for index, start in enumerate(range(0, total, chord_len)):
        shift, shape = spec["chords"][index % len(spec["chords"])]
        notes = [root * 2 ** ((shift + step) / 12) for step in shape]
        t = np.arange(chord_len) / SAMPLE_RATE
        part = np.zeros(chord_len)
        x = start / total
        if spec.get("build"):
            gain = {"pad": 0.7 + 0.3 * x, "arp": _ramp(x, 0.0, 0.15), "bass": _ramp(x, 0.10, 0.25),
                    "drum": _ramp(x, 0.20, 0.35), "lead": _ramp(x, 0.45, 0.60)}
        else:
            gain = {"pad": 1.0, "arp": 1.0, "bass": 1.0, "drum": 1.0, "lead": 1.0}

        # Held chord: the "strings" under everything.
        pad = sum(_voice(np, note, t, (1.0, 0.45, 0.22, 0.10)) for note in notes) / len(notes)
        if mood in ("dark", "ambient"):
            pad *= 0.75 + 0.25 * np.sin(2.0 * np.pi * 0.23 * t)           # slow uneasy swell
        part += gain["pad"] * spec["pad"] * pad * _envelope(np, chord_len, 0.9, 1.1)

        beat_len = int(beat * SAMPLE_RATE)
        bass_note = notes[0] / 2
        if spec["bass"] == "held":
            part += gain["bass"] * 0.5 * _voice(np, bass_note, t, (1.0, 0.3)) * _envelope(np, chord_len, 0.3, 0.8)
        for step in range(8):
            at = step * beat_len
            seg = slice(at, min(chord_len, at + beat_len))
            ts = np.arange(seg.stop - seg.start) / SAMPLE_RATE
            decay = np.exp(-ts * 5.0)
            if spec["bass"] == "pulse":
                # Two pushes a beat: the restless drive of a chase or a headline.
                half = len(ts) // 2
                pulse = np.concatenate([np.exp(-ts[:half] * 9.0), np.exp(-ts[: len(ts) - half] * 9.0)])
                part[seg] += gain["bass"] * 0.45 * _voice(np, bass_note, ts, (1.0, 0.4)) * pulse
            if spec["arp"]:
                note = notes[arp_order[step % 4] % len(notes)] * 2
                part[seg] += gain["arp"] * spec["arp"] * _voice(np, note, ts, (1.0, 0.25, 0.08)) * decay * np.minimum(1.0, ts * 200)
            if spec["drum"] == "taiko" and step in (0, 3, 4):
                sweep = 2.0 * np.pi * (48.0 * ts + 22.0 * (1 - np.exp(-ts * 18.0)) / 18.0)
                part[seg] += gain["drum"] * 0.85 * np.sin(sweep) * np.exp(-ts * 4.5)
                part[seg] += gain["drum"] * 0.10 * noise.standard_normal(len(ts)) * np.exp(-ts * 30.0)
            elif spec["drum"] == "kick":
                sweep = 2.0 * np.pi * (52.0 * ts + 40.0 * (1 - np.exp(-ts * 30.0)) / 30.0)
                part[seg] += gain["drum"] * 0.50 * np.sin(sweep) * np.exp(-ts * 9.0)
            elif spec["drum"] == "tick":
                part[seg] += 0.05 * noise.standard_normal(len(ts)) * np.exp(-ts * 60.0)
                half = len(ts) // 2
                part[at + half: seg.stop] += 0.03 * noise.standard_normal(seg.stop - at - half) * np.exp(-ts[: seg.stop - at - half] * 80.0)

        # A slow tune on top, moving by step inside the chord's scale.
        if spec["lead"]:
            for step in range(0, 8, 2):
                lead_step = max(-2, min(4, lead_step + rng.choice([-1, -1, 0, 1, 1, 2])))
                note = notes[lead_step % len(notes)] * (4 if lead_step >= len(notes) else 2)
                at = step * beat_len
                seg = slice(at, min(chord_len, at + 2 * beat_len))
                ts = np.arange(seg.stop - seg.start) / SAMPLE_RATE
                part[seg] += gain["lead"] * spec["lead"] * _voice(np, note, ts, (1.0, 0.5, 0.2)) * _envelope(np, len(ts), 0.12, 0.5)

        mix[start:start + chord_len] += part

    mix = mix[:total]
    fade = int(min(1.5, duration / 4) * SAMPLE_RATE)
    if fade > 1:
        mix[:fade] *= np.linspace(0.0, 1.0, fade)
        mix[-fade:] *= np.linspace(1.0, 0.0, fade)
    # Same loudness as the kids tune, so one volume setting suits every mood.
    peak = float(np.max(np.abs(mix))) or 1.0
    samples = np.int16(mix / peak * 0.30 * 32767)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(np.column_stack([samples, samples]).tobytes())
    return output_path
