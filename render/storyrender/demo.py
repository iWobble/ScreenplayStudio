"""Placeholder stills and tones, so the whole timeline can be proved before the real pictures and voices exist."""

import json
from pathlib import Path

from . import ffmpeg

DEMO = [
    ("b01", "#7a4b2a", "Narrator", "The captain ordered a feast. At dawn, they would attack a merchant ship twice their size.", 220),
    ("b04", "#2a5a7a", "Cook", "Your feast.", 150),
    ("b05", "#5a2a7a", "Captain", "Make do.", 330),
]


def _still(path: Path, colour: str, label: str, size: tuple[int, int]) -> None:
    ffmpeg.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={colour}:s={size[0]}x{size[1]}",
            "-vf", f"drawgrid=w=120:h=120:t=2:c=white@0.35,drawtext=text='{label}':fontcolor=white:fontsize=140:x=(w-text_w)/2:y=(h-text_h)/2",
            "-frames:v", "1", str(path),
        ]
    )  # fmt: skip


def _tone(path: Path, hertz: int, seconds: float) -> None:
    """A voice stand-in: a warbling tone as long as the line would take to say."""
    ffmpeg.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hertz}:duration={seconds:.3f}",
            "-af", "tremolo=f=5:d=0.7,afade=t=in:d=0.03,afade=t=out:st=" + f"{max(seconds - 0.05, 0):.3f}:d=0.05,volume=0.6", "-ar", "48000", str(path),
        ]
    )  # fmt: skip


def make(folder: Path, size: tuple[int, int] = (1080, 1920)) -> Path:
    """Write a 3-beat project into `folder` and return its manifest path."""
    (folder / "stills").mkdir(parents=True, exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    shots = []
    for beat, colour, speaker, text, hertz in DEMO:
        words = text.split()
        seconds = max(0.9, len(words) * 0.32)
        _still(folder / "stills" / f"{beat}.png", colour, beat, size)
        _tone(folder / "audio" / f"{beat}.wav", hertz, seconds)
        clock = [i * seconds / len(words) for i in range(len(words) + 1)]
        timed = [{"text": w, "start": round(clock[i], 3), "end": round(clock[i + 1], 3)} for i, w in enumerate(words)]
        shots.append(
            {
                "id": beat,
                "still": f"stills/{beat}.png",
                "hold": 3,
                "move": {"from": {"x": 0.5, "y": 0.5, "zoom": 1.0}, "to": {"x": 0.6, "y": 0.4, "zoom": 1.25}},
                "lines": [{"speaker": speaker, "text": text, "audio": f"audio/{beat}.wav", "words": timed}],
            }
        )
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"title": "Storyrender demo", "size": list(size), "fps": 30, "shots": shots}, indent=2))
    return manifest
