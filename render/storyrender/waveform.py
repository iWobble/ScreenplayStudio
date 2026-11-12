"""A recording's waveform, as the peaks the Timeline draws in its block. The browser cannot decode a stored take (the assets host sends no CORS
headers), so the worker does, once, when a take is attached: ffmpeg decodes it to 8 kHz mono, and the loudest and quietest sample of each stretch
are kept, 8-bit, in the audiowaveform JSON format ({version 2, bits 8, data: [min, max, …]}) that the Timeline and other tools read."""

import subprocess
from array import array
from pathlib import Path

from . import ffmpeg

RATE = 8000  # samples a second to look at: plenty for a picture, and a minute of it is under a megabyte
POINTS = 240  # stretches kept: the Timeline shows no more than this per block


def peaks(path: Path, points: int = POINTS, rate: int = RATE) -> dict:
    """The audio file as `points` stretches of its (lowest, highest) 8-bit sample each, audiowaveform-style."""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], capture_output=True
    )
    if done.returncode != 0:
        raise ffmpeg.FfmpegError(f"ffmpeg can't read {path.name} as sound: {done.stderr.decode(errors='replace').strip()[-300:]}")
    samples = array("h")
    samples.frombytes(done.stdout[: len(done.stdout) // 2 * 2])
    if not samples:
        raise ffmpeg.FfmpegError(f"{path.name} has no sound in it")
    n = len(samples)
    points = max(2, min(points, n))
    data: list[int] = []
    for i in range(points):
        chunk = samples[i * n // points : max(i * n // points + 1, (i + 1) * n // points)]
        data += [min(chunk) >> 8, max(chunk) >> 8]  # 16-bit to 8-bit
    return {"version": 2, "channels": 1, "sample_rate": rate, "samples_per_pixel": max(1, n // points), "bits": 8, "length": points, "data": data}
