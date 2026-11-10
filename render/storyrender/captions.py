"""Captions: short readable chunks timed to the speech, written as an ASS file ffmpeg burns in (libass wraps and outlines them).

Word timings (ElevenLabs gives them) make chunks follow the voice; without them a line's text is spread over its audio by
length. Captions sit above the bottom edge, clear of the interface a Short draws over it.
"""

import re
from dataclasses import dataclass, field

from .manifest import Timeline

MAX_WORDS = 4
MAX_CHARS = 26
CLOSE_GAP = 0.15  # a pause shorter than this between cues is closed so the text doesn't flicker
_BREAK_AFTER = (".", "?", "!", ";", ":", ",")


def word_chunks(words: list[dict], *, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS) -> list[list[dict]]:
    """A line's word timings cut into the words of each chunk: a chunk ends at punctuation or when it gets long."""
    chunks: list[list[dict]] = []
    current: list[dict] = []

    def flush() -> None:
        if current:
            chunks.append(list(current))
            current.clear()

    for w in words:
        if current and (len(current) >= max_words or len(" ".join(x["text"] for x in current + [w])) > max_chars):
            flush()
        current.append(w)
        if str(w["text"]).endswith(_BREAK_AFTER):
            flush()
    flush()
    return chunks


def chunk_words(words: list[dict], *, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS) -> list[tuple[str, float, float]]:
    """[(text, start, end)] seconds from a line's word timings: a chunk ends at punctuation or when it gets long."""
    return [(" ".join(w["text"] for w in c), float(c[0]["start"]), float(c[-1]["end"])) for c in word_chunks(words, max_words=max_words, max_chars=max_chars)]


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


@dataclass
class Cue:
    """One caption: its words and when it shows, in seconds on the film, and who says it."""

    text: str
    start: float
    end: float
    speaker: str | None = None
    words: list[tuple[str, float, float]] = field(default_factory=list)  # each word with its own start and end, for the word-by-word highlight


def _split(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    """Times for the words of a caption that has none of its own: its seconds shared out by the length of each word."""
    words = text.split()
    total = sum(len(w) for w in words) or 1
    out, clock = [], start
    for w in words:
        span = (end - start) * len(w) / total
        out.append((w, clock, clock + span))
        clock += span
    return out


def rich_cues(timeline: Timeline) -> list[Cue]:
    """Every caption on the whole timeline, in order, with its words and speaker."""
    found: list[Cue] = []
    for planned in timeline.shots:
        for placed in planned.lines:
            line = placed.line
            if not line.caption or not line.text.strip():
                continue
            if line.words:
                for chunk in word_chunks(line.words):
                    words = [(str(w["text"]), placed.start + float(w["start"]), placed.start + float(w["end"])) for w in chunk]
                    found.append(Cue(" ".join(w[0] for w in words), words[0][1], words[-1][2], line.speaker, words))
            else:
                for text, a, b in chunk_text(line.text, line.duration):
                    found.append(Cue(text, placed.start + a, placed.start + b, line.speaker, _split(text, placed.start + a, placed.start + b)))
    found.sort(key=lambda c: c.start)
    for i, cue in enumerate(found[:-1]):
        if 0 < found[i + 1].start - cue.end < CLOSE_GAP:  # a short pause between cues is closed so the text does not flicker
            cue.end = found[i + 1].start
    return found


def cues(timeline: Timeline) -> list[tuple[str, float, float]]:
    """Every caption on the whole timeline: [(text, start, end)]."""
    return [(c.text, c.start, c.end) for c in rich_cues(timeline)]


def _time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


STYLES = ("classic", "box", "highlight", "none")
SIZES = {"small": 0.032, "medium": 0.04, "large": 0.05}  # of the picture's height
POSITIONS = {"bottom": (2, 0.20), "middle": (5, 0.0), "top": (8, 0.14)}  # ASS alignment, and the margin as a share of the height (bottom: clear of what a Short draws over it)
DEFAULT_HIGHLIGHT = "#ffd400"
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def ass_colour(value: object, fallback: str) -> str:
    """A hex colour (#RRGGBB) as ASS writes it (&H00BBGGRR); the fallback for anything that is not six hex digits."""
    m = _HEX.match(str(value or "").strip()) or _HEX.match(fallback)
    h = m.group(1)  # type: ignore[union-attr]
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _line_text(cue: Cue, kind: str, speakers: dict[str, str]) -> str:
    """The caption's text with its tags: the speaker's colour, and for the highlight style each word's own sweep."""
    tint = speakers.get(str(cue.speaker or "").strip().lower())
    if kind == "highlight":
        sweeps = []
        for i, (word, start, end) in enumerate(cue.words):
            until = cue.words[i + 1][1] if i + 1 < len(cue.words) else max(end, cue.end)  # each word lasts until the next begins: the sweep never stalls
            sweeps.append(f"{{\\kf{max(1, round((until - start) * 100))}}}{_escape(word)}")
        body = " ".join(sweeps)
        return (f"{{\\2c{ass_colour(tint, '#ffffff')}}}" if tint else "") + body
    return (f"{{\\1c{ass_colour(tint, '#ffffff')}}}" if tint else "") + _escape(cue.text)


def ass(timeline: Timeline, size: tuple[int, int], style: dict | None = None) -> str:
    """An ASS subtitle file for the timeline. `style` sets how it looks: `style` (classic outline, box, highlight word by word, or none),
    `position` (bottom, middle, top), `size` (small, medium, large), `color` and `highlight` (#RRGGBB) and `speakers` ({speaker: #RRGGBB}).
    The older keys font, size (pixels), margin_v, colour (&HBBGGRR) and outline still win when given."""
    width, height = size
    given = style or {}
    kind = given.get("style") if given.get("style") in STYLES else "classic"
    alignment, margin_share = POSITIONS.get(str(given.get("position")), POSITIONS["bottom"])
    if height < width * 1.7:  # not a tall Short: no strip at the bottom to keep clear of, so the text sits lower and closer to the edge
        margin_share = {2: 0.10, 8: 0.08}.get(alignment, margin_share)
    share = SIZES.get(str(given.get("size")), SIZES["medium"])
    text_colour = given.get("colour") or ass_colour(given.get("color"), "#ffffff")
    lit = ass_colour(given.get("highlight"), DEFAULT_HIGHLIGHT)
    st = {
        "font": "Lato",
        "size": round(height * share),
        "margin_v": round(height * margin_share),
        "outline": round(height * 0.0022) + 2,
        **{k: v for k, v in given.items() if k in ("font", "margin_v", "outline") or (k == "size" and isinstance(v, int))},
    }
    primary, secondary = (lit, text_colour) if kind == "highlight" else (text_colour, "&H000000FF")  # the highlight is what has been spoken; the rest waits in the text colour
    border, outline_colour, back = (3, "&H99000000", "&H99000000") if kind == "box" else (1, "&H00101010", "&H80000000")
    outline = round(height * 0.009) if kind == "box" else st["outline"]  # in a box, the outline is the padding around the words
    side = round(width * 0.08)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{st['font']},{st['size']},{primary},{secondary},{outline_colour},{back},-1,0,0,0,100,100,0,0,{border},{outline},{0 if kind == 'box' else 1},{alignment},{side},{side},{st['margin_v']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    speakers = {str(k).strip().lower(): v for k, v in dict(given.get("speakers") or {}).items() if _HEX.match(str(v))}
    shown = [] if kind == "none" else rich_cues(timeline)
    body = "".join(f"Dialogue: 0,{_time(c.start)},{_time(c.end)},Default,,0,0,0,,{_line_text(c, kind, speakers)}\n" for c in shown)
    return header + body


def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(timeline: Timeline) -> str:
    """The captions as a SubRip file, for a platform that takes its subtitles as a file rather than burned in. Empty when there are none."""
    return "".join(f"{n}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n\n" for n, c in enumerate(rich_cues(timeline), 1))
