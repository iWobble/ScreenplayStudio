"""The only place that runs ffmpeg/ffprobe: probing durations and running a command with its stderr on failure."""

import json
import subprocess
from pathlib import Path


class FfmpegError(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    if cmd[0] == "ffmpeg" and "-nostdin" not in cmd:
        cmd = [cmd[0], "-nostdin", *cmd[1:]]  # ffmpeg reads the keyboard unless told not to, and a job has none: on some builds that stalls it
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


def probe_video(path: Path) -> dict:
    """A video's own make, for describing it (never for a render, whose `probe` stays as it is): each stream's kind, size, both frame rates
    and its turn (a phone's portrait take is stored landscape with a rotation, in its side data or, from an older muxer, a `rotate` tag)."""
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,avg_frame_rate:stream_tags=rotate:stream_side_data=rotation", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise FfmpegError(f"ffprobe can't read {path}: {done.stderr.strip()[-300:]}")
    return json.loads(done.stdout)


def packets(path: Path) -> int:
    """How many frames the first picture stream holds, by reading (not decoding) the file: for a browser's webm, whose rates say nothing."""
    done = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return int(done.stdout.strip().split(",")[0]) if done.returncode == 0 else 0
    except ValueError:
        return 0


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
