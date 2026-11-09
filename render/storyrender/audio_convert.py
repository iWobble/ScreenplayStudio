"""Turning a recording into a file that plays anywhere. A browser records what it can (webm/opus in Chrome and Firefox, mp4 in Safari, ogg);
a voice sample or a take that gets downloaded, shared or put in another tool wants mp3 or m4a. The pure part of the `convert-audio` job."""

import re
from pathlib import Path

from . import ffmpeg

# format → (file ending, mime type, ffmpeg arguments for the audio)
FORMATS: dict[str, tuple[str, str, list[str]]] = {
    "mp3": (".mp3", "audio/mpeg", ["-c:a", "libmp3lame", "-q:a", "2"]),
    "m4a": (".m4a", "audio/mp4", ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]),
}
DEFAULT_FORMAT = "mp3"
# what each target format is also called as a mime type, so a file already in it is left alone
SAME = {"mp3": {"audio/mpeg", "audio/mp3"}, "m4a": {"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"}}


class ConvertError(ValueError):
    """Something the person can fix (a wrong format name, no recording in the field); the job's log shows the message."""


def format_of(asked) -> str:
    """The format asked for ("mp3", "m4a", any case, a leading dot allowed); empty means the default."""
    name = str(asked or "").strip().lower().lstrip(".")
    if not name:
        return DEFAULT_FORMAT
    if name not in FORMATS:
        raise ConvertError(f"“{asked}” is not a format this can make: use {' or '.join(FORMATS)}")
    return name


def is_already(mime: str | None, name: str | None, fmt: str) -> bool:
    """True when the asset is already in `fmt`, by its mime type (parameters like `; codecs=opus` ignored) or, failing that, its file ending."""
    kind = str(mime or "").split(";")[0].strip().lower()
    if kind in SAME[fmt]:
        return True
    return not kind and str(name or "").lower().endswith(FORMATS[fmt][0])


def is_audio(mime: str | None, name: str | None) -> bool:
    """Recordings from a browser are often typed video/webm although they hold only sound, so a webm or mp4 counts; a picture or a PDF does not."""
    kind = str(mime or "").split(";")[0].strip().lower()
    if kind.startswith("audio/") or kind in {"video/webm", "video/mp4", "application/ogg"}:
        return True
    return not kind and bool(re.search(r"\.(webm|ogg|oga|opus|wav|mp3|m4a|mp4|aac|flac)$", str(name or ""), re.I))


def named(name: str | None, fmt: str) -> str:
    """The converted asset's name: the old one with its ending swapped ("Granny voice.webm" → "Granny voice.mp3")."""
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(name or "").strip()) or "Recording"
    return base + FORMATS[fmt][0]


def convert(src: Path, dest: Path, fmt: str) -> float:
    """Write `src`'s sound to `dest` in `fmt` (a video track, if any, dropped; mono and stereo kept as recorded). Returns the seconds of sound."""
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", *FORMATS[fmt][2], str(dest)])
    return ffmpeg.duration(dest)
