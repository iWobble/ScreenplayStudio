"""How long a recording really is. A browser's recording (webm) is written as it is made, so its header has no length and ffprobe cannot say;
an upload may carry one. The pure part of the `measure-audio` job: read the header when it has a length, otherwise listen to the whole file."""

import json
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
NOISE_FLOOR_LOW = -90.0  # the quietest noise floor read: a clean room is well under the meters' floor
CLIP_DB = -0.1  # a peak at or above this has touched the ceiling: the top of the wave is probably cut off


def levels(path: Path) -> tuple[float, float]:
    """How loud a recording is: its average level and its loudest moment, in dB below full scale (0 is as loud as a file can be, so both are
    negative). What ffmpeg's volumedetect hears over the whole file; a silent one reads at the floor instead of minus infinity."""
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean, peak = (re.search(rf"{name}_volume:\s*(-?[\d.]+|-inf) dB", done.stderr) for name in ("mean", "max"))
    if done.returncode != 0 or not mean or not peak:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    read = lambda m: LEVEL_FLOOR if m.group(1) == "-inf" else max(LEVEL_FLOOR, round(float(m.group(1)), 1))  # noqa: E731
    return read(mean), read(peak)


# ── What else the recording says about itself ────────────────────────────────────────────────────────────────────────────────────────────────────

SILENCE_DB = -45  # quieter than this is silence: room tone and a breath sit above it, dead air below
SILENCE_SECONDS = 0.1


def parse_silence(stderr: str, seconds: float) -> tuple[float, float]:
    """(lead, tail): seconds of silence before the first sound and after the last, from ffmpeg's silencedetect lines. A silence that starts at 0 is the
    lead; one that starts and never ends (the file ends in it) is the tail. A file that is all silence reads as a lead of its whole length, no tail."""
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", stderr)]
    ends = ends + [seconds] * (len(starts) - len(ends))  # a silence with no end runs to the end of the file; a newer ffmpeg also closes the last one there
    lead = tail = 0.0
    if starts and starts[0] <= 0.05:
        lead = ends[0]
    if starts and not (starts[0] <= 0.05 and len(starts) == 1) and ends[-1] >= seconds - 0.05:
        tail = max(seconds - starts[-1], 0.0)
    return round(max(lead, 0.0), 2), round(tail, 2)


def silence_edges(path: Path, seconds: float) -> tuple[float, float]:
    """The silence at the start and the end of a recording (see `parse_silence`)."""
    done = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_SECONDS}", "-f", "null", "-"], capture_output=True, text=True
    )
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    return parse_silence(done.stderr, seconds)


def parse_loudness(stderr: str) -> tuple[float, float, float] | None:
    """(integrated loudness in LUFS, loudness range in LU, true peak in dBFS) from the summary ffmpeg's ebur128 filter prints, or None when it
    printed none (a file too short to measure)."""
    summary = stderr[stderr.rfind("Summary:") :] if "Summary:" in stderr else ""
    found = [re.search(rf"{key}:\s+(-?[\d.]+|-inf)\s+{unit}", summary) for key, unit in (("I", "LUFS"), ("LRA", "LU"), ("Peak", "dBFS"))]
    if not all(found):
        return None
    floor = lambda m: -70.0 if m.group(1) == "-inf" else float(m.group(1))  # noqa: E731
    return round(floor(found[0]), 1), round(floor(found[1]), 1), round(floor(found[2]), 1)


def loudness(path: Path) -> tuple[float, float, float] | None:
    """How loud a recording sounds to a listener (LUFS, the broadcast measure), how much it varies, and its true peak (see `parse_loudness`)."""
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    return parse_loudness(done.stderr)


def format_summary(probed: dict) -> str:
    """The recording's make in a line ("opus · 48 kHz · mono · 64 kbit/s"), from ffprobe's JSON (`probe_audio`)."""
    stream = next((s for s in probed.get("streams", []) if s.get("codec_type") == "audio"), {})
    parts = [str(stream.get("codec_name") or "").strip()]
    if (rate := stream.get("sample_rate")) and str(rate).isdigit():
        parts.append(f"{int(rate) / 1000:g} kHz")
    if (channels := stream.get("channels")) in (1, 2):
        parts.append("mono" if channels == 1 else "stereo")
    elif channels:
        parts.append(f"{channels} channels")
    bits = stream.get("bit_rate") or (probed.get("format") or {}).get("bit_rate")
    if bits and str(bits).isdigit():
        parts.append(f"{round(int(bits) / 1000)} kbit/s")
    return " · ".join(p for p in parts if p)


def probe_audio(path: Path) -> dict:
    """ffprobe's JSON for the audio stream's codec, rate, channels and bit rate (`ffmpeg.probe` leaves them out)."""
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate:stream=codec_type,codec_name,sample_rate,channels,bit_rate", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffprobe can't read {path.name}: {done.stderr.strip()[-300:]}")
    return json.loads(done.stdout)


def source_of(metadata: dict | None) -> str:
    """Where a recording came from, from the facts kept on its asset: "recorded" when the browser's recorder made it (it marks `recording.source`),
    "generated" when it carries a voice service's own word times (the worker's own timing says `words_from`), else "uploaded"."""
    meta = metadata or {}
    if isinstance(meta.get("recording"), dict) and meta["recording"].get("source") == "browser":
        return "recorded"
    if meta.get("words") and not meta.get("words_from"):
        return "generated"
    return "uploaded"


def parse_stats(stderr: str) -> dict | None:
    """(average level `rms_db`, quietest stretch `noise_floor_db`, loudest moment `peak_db`) from the "Overall" block of ffmpeg's astats filter, in dB
    below full scale, or None when there is none. The quietest stretch's RMS is how a standard such as ACX reads the noise floor."""
    overall = stderr[stderr.rfind("Overall") :] if "Overall" in stderr else ""
    found = {key: re.search(rf"{pattern}:\s*(-?[\d.]+|-inf|nan)", overall) for key, pattern in (("rms_db", "RMS level dB"), ("noise_floor_db", "RMS trough dB"), ("peak_db", "Peak level dB"))}
    if not all(found.values()):
        return None
    def read(m: re.Match, floor: float) -> float:
        return floor if m.group(1) in ("-inf", "nan") else max(floor, round(float(m.group(1)), 1))

    # the noise floor reads lower than the meters do: a standard's line (ACX: -60 dB) sits at the meters' floor, so it must not be clamped there
    return {key: read(m, NOISE_FLOOR_LOW if key == "noise_floor_db" else LEVEL_FLOOR) for key, m in found.items()}


def stats(path: Path) -> dict | None:
    """The recording's average level, noise floor and peak (see `parse_stats`)."""
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af", "astats=metadata=0:reset=0", "-f", "null", "-"], capture_output=True, text=True)
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.strip()[-300:]}")
    return parse_stats(done.stderr)
