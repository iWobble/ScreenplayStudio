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
    """Seconds of audio or video in a file — measured, never trusted from a manifest."""
    seconds = probe(path).get("format", {}).get("duration")
    if seconds is None:
        raise FfmpegError(f"{path} has no duration")
    return float(seconds)
