"""Captions: short readable chunks timed to the speech, written as an ASS file ffmpeg burns in (libass wraps and outlines them).

Word timings (ElevenLabs gives them) make chunks follow the voice; without them a line's text is spread over its audio by
length. Captions sit above the bottom edge, clear of the interface a Short draws over it.
"""

from .manifest import Timeline

MAX_WORDS = 4
MAX_CHARS = 26
CLOSE_GAP = 0.15  # a pause shorter than this between cues is closed so the text doesn't flicker
_BREAK_AFTER = (".", "?", "!", ";", ":", ",")


def chunk_words(words: list[dict], *, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS) -> list[tuple[str, float, float]]:
    """[(text, start, end)] seconds from a line's word timings: a chunk ends at punctuation or when it gets long."""
    chunks: list[tuple[str, float, float]] = []
    current: list[dict] = []

    def flush() -> None:
        if current:
            chunks.append((" ".join(w["text"] for w in current), float(current[0]["start"]), float(current[-1]["end"])))
            current.clear()

    for w in words:
        if current and (len(current) >= max_words or len(" ".join(x["text"] for x in current + [w])) > max_chars):
            flush()
        current.append(w)
        if str(w["text"]).endswith(_BREAK_AFTER):
            flush()
    flush()
    return chunks


def chunk_text(text: str, duration: float, *, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS) -> list[tuple[str, float, float]]:
    """The same from plain text: the line's seconds split across its chunks by their length."""
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        if current and (len(current) >= max_words or len(" ".join(current + [word])) > max_chars):
            pieces.append(" ".join(current))
            current = []
        current.append(word)
        if word.endswith(_BREAK_AFTER):
            pieces.append(" ".join(current))
            current = []
    if current:
        pieces.append(" ".join(current))
    total = sum(len(p) for p in pieces) or 1
    out, clock = [], 0.0
    for piece in pieces:
        span = duration * len(piece) / total
        out.append((piece, clock, clock + span))
        clock += span
    return out


def cues(timeline: Timeline) -> list[tuple[str, float, float]]:
    """Every caption on the whole timeline: [(text, start, end)]."""
    found: list[tuple[str, float, float]] = []
    for planned in timeline.shots:
        for placed in planned.lines:
            line = placed.line
            if not line.caption or not line.text.strip():
                continue
            parts = chunk_words(line.words) if line.words else chunk_text(line.text, line.duration)
            found += [(text, placed.start + a, placed.start + b) for text, a, b in parts]
    found.sort(key=lambda c: c[1])
    return [(t, s, found[i + 1][1] if i + 1 < len(found) and 0 < found[i + 1][1] - e < CLOSE_GAP else e) for i, (t, s, e) in enumerate(found)]


def _time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass(timeline: Timeline, size: tuple[int, int], style: dict | None = None) -> str:
    """An ASS subtitle file for the timeline. `style` may set font, size, margin_v (from the bottom), colour (&HBBGGRR) and outline."""
    width, height = size
    st = {"font": "Lato", "size": round(height * 0.04), "margin_v": round(height * 0.2), "colour": "&H00FFFFFF", "outline": round(height * 0.0022) + 2, **(style or {})}
    side = round(width * 0.08)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{st['font']},{st['size']},{st['colour']},&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,{st['outline']},1,2,{side},{side},{st['margin_v']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = "".join(f"Dialogue: 0,{_time(s)},{_time(e)},Default,,0,0,0,,{_escape(t)}\n" for t, s, e in cues(timeline))
    return header + body
