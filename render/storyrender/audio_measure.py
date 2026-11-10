"""How long a recording really is. A browser's recording (webm) is written as it is made, so its header has no length and ffprobe cannot say;
an upload may carry one. The pure part of the `measure-audio` job: read the header when it has a length, otherwise listen to the whole file."""

import subprocess
from pathlib import Path

from . import ffmpeg


def decoded_seconds(path: Path) -> float:
    """Decode the file to nowhere and read how far the decoder got: the length of the sound, whatever the header says."""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-f", "null", "-progress", "pipe:1", "-"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    micro = 0
    for line in done.stdout.splitlines():
        key, _, value = line.partition("=")
        if key in ("out_time_us", "out_time_ms") and value.strip().lstrip("-").isdigit():  # both are microseconds
            micro = max(micro, int(value))
    if micro <= 0:
        raise ffmpeg.FfmpegError(f"{path.name} has no sound in it")
    return micro / 1_000_000


def seconds(path: Path) -> float:
    """The sound's length in seconds: from the header when it has one (an mp3, a wav), else by decoding it (a browser's webm)."""
    try:
        length = ffmpeg.duration(path)
        if length > 0:
            return length
    except (ffmpeg.FfmpegError, ValueError):
        pass
    return decoded_seconds(path)
