"""The transcript's three forms, from the segments the model returns: [{start, end, text}] in seconds."""

from __future__ import annotations


def stamp(seconds: float) -> str:
    """h:mm:ss, for the timestamped form."""
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def plain(segments: list[dict]) -> str:
    """The words alone, one segment a line (a place to start editing from)."""
    return "".join(f"{s['text']}\n" for s in segments)


def timestamped(segments: list[dict]) -> str:
    """Each segment led by where it starts, `[0:01:05] text`, so a passage can be found in the recording."""
    return "".join(f"[{stamp(s['start'])}] {s['text']}\n" for s in segments)


def paragraphs(segments: list[dict], gap: float = 1.2) -> str:
    """The words run together, a new paragraph where the speaker paused for `gap` seconds or more: the form to read, or to cut into beats."""
    out: list[str] = []
    last_end = None
    for s in segments:
        if last_end is not None and s["start"] - last_end >= gap and out:
            out.append("\n\n")
        elif out:
            out.append(" ")
        out.append(s["text"])
        last_end = s["end"]
    return "".join(out) + "\n"
