"""Title and end cards: a picture made from text on a colour, which the pull hands the renderer as the still of an `intro` or `outro` shot.

The rules (which story fields make a card, and how long it lasts) must match the timeline view's `spine.cards` (Marvin: timeline.ts `cardOf`):
a card exists when its title field has text, and lasts its seconds field when that is above 0, else a default. A card is a real shot, so the
render, the filmstrip, the audio cut and the timeline all lay out the same seconds."""

import re
import textwrap
from pathlib import Path

from . import ffmpeg

DEFAULT_SECONDS = {"intro": 2.5, "outro": 3.0}
DEFAULT_COLOUR = "#111111"
DEFAULT_TEXT_COLOUR = "#ffffff"
SIZE = (1080, 1920)
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def colour(value: object, fallback: str) -> str:
    """A hex colour as ffmpeg writes it (0xRRGGBB); the fallback for anything that is not six hex digits."""
    m = _HEX.match(str(value or "").strip())
    return f"0x{(m.group(1) if m else fallback.lstrip('#')).lower()}"


def seconds_of(story: dict, kind: str) -> float:
    """How long the card lasts: the story's `<kind>_seconds` when that is a number above 0, else the default."""
    try:
        value = float(story.get(f"{kind}_seconds"))
    except (TypeError, ValueError):
        return DEFAULT_SECONDS[kind]
    return value if value > 0 else DEFAULT_SECONDS[kind]


def card_of(story: dict, kind: str) -> dict | None:
    """The card the story asks for (`intro` or `outro`), or None when its title is empty: {title, subtitle, seconds, color, text_color}."""
    title = str(story.get(f"{kind}_title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "subtitle": str(story.get(f"{kind}_subtitle") or "").strip(),
        "seconds": seconds_of(story, kind),
        "color": colour(story.get("card_color"), DEFAULT_COLOUR),
        "text_color": colour(story.get("card_text_color"), DEFAULT_TEXT_COLOUR),
    }


def _lines(text: str, size: int, width: int) -> list[str]:
    """The text broken into lines that fit the picture's width (a character is about 0.6 of the font size wide), keeping the writer's own breaks."""
    per_line = max(6, int(width * 0.84 / (size * 0.6)))
    return [piece for para in text.splitlines() or [""] for piece in (textwrap.wrap(para, per_line) or [""])]


def make_still(card: dict, path: Path, size: tuple[int, int] = SIZE) -> Path:
    """Draw the card: the title large and centred, the subtitle smaller under it. Text goes in through files with expansion off, so a title with
    an apostrophe, a colon or a percent sign is shown as it is written."""
    width, height = size
    title_size, sub_size = round(width * 0.085), round(width * 0.042)
    blocks = [(_lines(card["title"], title_size, width), title_size)] + ([(_lines(card["subtitle"], sub_size, width), sub_size)] if card["subtitle"] else [])
    gap = round(width * 0.04)
    step = lambda size: round(size * 1.25)  # noqa: E731 - the distance from one line to the next
    heights = [len(lines) * step(fontsize) for lines, fontsize in blocks]
    y = (height - sum(heights) - gap * (len(blocks) - 1)) / 2
    path.parent.mkdir(parents=True, exist_ok=True)
    font = f"fontfile={FONT}:" if FONT.is_file() else ""
    draws = []
    for lines, fontsize in blocks:
        for line in lines:  # one drawtext a line, each centred on its own: no dependence on how a build of ffmpeg lays out several lines
            if line:  # a blank line is only space
                source = path.with_suffix(f".text{len(draws)}.txt")
                source.write_text(line, encoding="utf-8")
                draws.append(f"drawtext={font}textfile={source}:expansion=none:fontcolor={card['text_color']}:fontsize={fontsize}:x=(w-text_w)/2:y={y:.0f}")
            y += step(fontsize)
        y += gap
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={card['color']}:s={width}x{height}", "-vf", ",".join(draws), "-frames:v", "1", str(path)])
    return path


def shots(story: dict, out: Path, size: tuple[int, int] = SIZE) -> tuple[dict | None, dict | None]:
    """The intro and outro shots for the manifest (each None when the story asks for none), with their pictures made under `out/stills`."""
    made: list[dict | None] = []
    for kind in ("intro", "outro"):
        card = card_of(story, kind)
        if card is None:
            made.append(None)
            continue
        still = make_still(card, out / "stills" / f"{kind}-card.png", size)
        made.append({"id": kind, "still": str(still.relative_to(out)), "hold": card["seconds"], "lines": []})
    return made[0], made[1]
