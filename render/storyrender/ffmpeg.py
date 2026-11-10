"""The only place that runs ffmpeg/ffprobe: probing durations and running a command with its stderr on failure."""

import json
import subprocess
from pathlib import Path


class FfmpegError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise FfmpegError(f"{' '.join(cmd[:3])} … failed ({done.returncode}):\n{done.stderr[-2000:]}")


def probe(path: Path) -> dict:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise FfmpegError(f"ffprobe can't read {path}: {done.stderr.strip()[-300:]}")
    return json.loads(done.stdout)


def duration(path: Path) -> float:
    """Seconds of audio or video in a file — measured, never trusted from a manifest. A browser's recording (webm) is written as it is made,
    so its header has no length: that one is measured by listening to the whole file, however its name ends."""
    seconds = probe(path).get("format", {}).get("duration")
    try:
        if seconds not in (None, "N/A") and float(seconds) > 0:
            return float(seconds)
    except (TypeError, ValueError):
        pass
    from .audio_measure import decoded_seconds  # here, not at the top: audio_measure reads this module

    return decoded_seconds(path)
