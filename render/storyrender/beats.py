"""Beat sheet (Markdown table) → the records a story is made of: beats, spoken lines, sound cues and a skeleton manifest.

    | 08 | 42–48s | Narrator: He picked up the onion. Cook: How many bowls? Captain: Everyone. | Cabin two-shot … |

becomes beat 08 with three lines (Narrator, Cook, Captain). A `Sound:` line is a cue for a sound effect, not something to
speak; a beat with no speech is a held image.
"""

import re
from pathlib import Path

_ROW = re.compile(r"^\|\s*(\d+[a-z]?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
_TIME = re.compile(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*s")
_LABEL = re.compile(r"(?:^|(?<=[.?!]\s))([A-Z][a-z]+):\s+")
SOUND = "Sound"


def split_audio(cell: str) -> list[dict]:
    """The audio cell as [{speaker, text, kind}] — kind is 'speech' or 'sound'. Text with no label is a note, not speech."""
    marks = list(_LABEL.finditer(cell))
    out: list[dict] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(cell)
        text = cell[m.end() : end].strip()
        if not text:
            continue
        kind = "sound" if m.group(1) == SOUND else "speech"
        out.append({"speaker": m.group(1), "text": text.rstrip(";"), "kind": kind})
    return out


def parse(markdown: str) -> list[dict]:
    """Every shot row of a beat sheet: [{beat, start, end, hold, audio_cell, picture, lines, sounds}]."""
    beats = []
    for raw in markdown.splitlines():
        m = _ROW.match(raw)
        if not m:
            continue
        number, when, audio, picture = m.groups()
        t = _TIME.search(when)
        start, end = (float(t.group(1)), float(t.group(2))) if t else (0.0, 0.0)
        parts = split_audio(audio)
        beats.append(
            {
                "beat": number.zfill(2),
                "start": start,
                "end": end,
                "hold": round(end - start, 3),
                "audio_cell": audio,
                "picture": picture,
                "lines": [p for p in parts if p["kind"] == "speech"],
                "sounds": [p for p in parts if p["kind"] == "sound"],
            }
        )
    return beats


def speech_lines(beats: list[dict]) -> list[dict]:
    """The lines to record, in story order: [{id, beat, speaker, text, characters}] — what the speech-line records hold.
    `characters` is what recording it spends on a per-character plan, so an approval can say what it is approving."""
    return [
        {"id": f"b{b['beat']}-{n}", "beat": b["beat"], "speaker": ln["speaker"], "text": ln["text"], "characters": len(ln["text"])}
        for b in beats
        for n, ln in enumerate(b["lines"], 1)
    ]


def skeleton_manifest(beats: list[dict], title: str, *, stills: str = "stills", audio: str = "audio", ext: str = "mp3") -> dict:
    """A manifest with every beat's still and line paths filled in by convention (`stills/b04.png`, `audio/b04-1.mp3`), ready
    for the pictures and the recorded lines to be dropped in. Holds come from the sheet's provisional times."""
    shots = []
    for b in beats:
        shots.append(
            {
                "id": f"b{b['beat']}",
                "still": f"{stills}/b{b['beat']}.png",
                "hold": b["hold"],
                "lines": [{"speaker": ln["speaker"], "text": ln["text"], "audio": f"{audio}/b{b['beat']}-{n}.{ext}"} for n, ln in enumerate(b["lines"], 1)],
                **({"sfx_notes": [s["text"] for s in b["sounds"]]} if b["sounds"] else {}),
            }
        )
    return {"title": title, "size": [1080, 1920], "fps": 30, "shots": shots}


def load(path: Path) -> list[dict]:
    return parse(path.read_text())
