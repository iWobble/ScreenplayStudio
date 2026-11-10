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


# --- the info card: a label, a title and a sentence (and a picture) over a dimmed beat -------------------------------------------------------
# A beat's own `info_*` fields make one transparent picture the size of the frame: a dimmed backdrop, then the icon, the label, the title and the
# sentence, in the middle of the picture (the captions live low, so the two never meet). It goes to the renderer as the beat's overlay, so it
# comes in after `overlay_delay` and fades with `overlay_fade` like any picture overlay.

INFO_DIM = 0.5
INFO_DELAY = 0.6
INFO_FADE = 0.35
INFO_LABEL_COLOUR = (255, 200, 60)  # gold, as the label of a "REAL FACT" card
INFO_TITLE_COLOUR = (255, 255, 255)
INFO_TEXT_COLOUR = (232, 232, 232)
INFO_FONTS = {
    "bold": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    "regular": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
}


def info_of(beat: dict) -> dict | None:
    """The info card a beat asks for, or None when it has neither a title nor a sentence: {label, title, text, icon, dim}. `dim` is how dark the
    backdrop is (0 to 1, default 0.5); `icon` is the id of a picture asset, or None."""
    title, text = str(beat.get("info_title") or "").strip(), str(beat.get("info_text") or "").strip()
    if not (title or text):
        return None
    try:
        dim = min(1.0, max(0.0, float(beat.get("info_dim"))))
    except (TypeError, ValueError):
        dim = INFO_DIM
    return {"label": str(beat.get("info_label") or "").strip(), "title": title, "text": text, "icon": str(beat.get("info_icon") or "").strip() or None, "dim": dim}


def _font(kind: str, size: int):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(INFO_FONTS[kind]), size)
    except OSError:  # a machine without the DejaVu fonts: Pillow's own, in the size asked
        return ImageFont.load_default(size)


def _wrapped(draw, text: str, font, width: int) -> list[str]:
    """The text broken at spaces into lines no wider than `width` pixels (measured with the font), keeping the writer's own breaks."""
    lines: list[str] = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if line and draw.textlength(trial, font=font) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def make_info(card: dict, path: Path, size: tuple[int, int] = SIZE, icon: Path | None = None) -> Path:
    """Draw the info card as a transparent PNG the size of the frame: a dimmed backdrop, with the icon, label, title and sentence centred in the
    middle of the picture."""
    from PIL import Image, ImageDraw

    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, round(card["dim"] * 255)))
    draw = ImageDraw.Draw(image)
    unit = min(width, height * 9 / 16)  # type is sized against the narrow side, so a wide picture does not get giant text
    box = round(min(width * 0.84, unit * 0.92))
    label_font, title_font, text_font = _font("bold", round(unit * 0.036)), _font("bold", round(unit * 0.078)), _font("regular", round(unit * 0.044))
    parts: list[tuple[str, object, tuple[int, int, int], list[str]]] = []
    for kind, text, font, colour in (("label", card["label"].upper(), label_font, INFO_LABEL_COLOUR), ("title", card["title"], title_font, INFO_TITLE_COLOUR), ("text", card["text"], text_font, INFO_TEXT_COLOUR)):
        if text:
            parts.append((kind, font, colour, _wrapped(draw, text, font, box)))
    gap = round(unit * 0.03)
    step = {kind: round(font.size * 1.3) for kind, font, _, _ in parts}
    badge = None
    if icon is not None:
        try:
            badge = Image.open(icon).convert("RGBA")
            side = round(unit * 0.2)
            badge.thumbnail((side, side))
        except OSError:
            badge = None  # an icon that cannot be read leaves the card without one
    total = sum(len(lines) * step[kind] for kind, _, _, lines in parts) + gap * max(0, len(parts) - 1) + ((badge.height + gap * 2) if badge else 0)
    y = height * 0.42 - total / 2
    if badge:
        image.alpha_composite(badge, (round((width - badge.width) / 2), round(y)))
        y += badge.height + gap * 2
    for kind, font, colour, lines in parts:
        for line in lines:
            if line:
                draw.text((width / 2, y + max(2, unit * 0.004)), line, font=font, fill=(0, 0, 0, 170), anchor="ma")  # a soft shadow keeps the text readable on a light still
                draw.text((width / 2, y), line, font=font, fill=(*colour, 255), anchor="ma")
            y += step[kind]
        y += gap
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
