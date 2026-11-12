"""How long a recording really is. A browser's recording (webm) is written as it is made, so its header has no length and ffprobe cannot say;
an upload may carry one. The pure part of the `measure-audio` job: read the header when it has a length, otherwise listen to the whole file."""

import re
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


LEVEL_FLOOR = -60.0  # the quietest level a meter shows; anything below reads as this


def levels(path: Path) -> tuple[float, float]:
    """How loud a recording is: its average level and its loudest moment, in dB below full scale (0 is as loud as a file can be, so both are
    negative). What ffmpeg's volumedetect hears over the whole file; a silent one reads at the floor instead of minus infinity."""
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean, peak = (re.search(rf"{name}_volume:\s*(-?[\d.]+|-inf) dB", done.stderr) for name in ("mean", "max"))
    if done.returncode != 0 or not mean or not peak:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    read = lambda m: LEVEL_FLOOR if m.group(1) == "-inf" else max(LEVEL_FLOOR, round(float(m.group(1)), 1))  # noqa: E731
    return read(mean), read(peak)
