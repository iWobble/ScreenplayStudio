"""A Fountain screenplay, read and cut into chapters and beats, written out as the beat sheet `beat_import` already reads.

    parse(text)                 -> elements (scene headings, action, dialogue, transitions, sections)
    cut(elements)               -> a Plan: chapters (with their scenes), beats and lines, speakers, warnings
    plan.sheet()                -> `## Chapter 3 - Title` headings over `| 3012 | — | Granny: words ¶ Dog: words | picture |` rows
    plan.report()               -> the split as a table to read before anything is made

No AI and no cost: the same screenplay always gives the same beats. Where a chapter starts is the writer's to say with Fountain's own
sections (`# Act One`, `## The heist`); with none, scenes are grouped into chapters of about `chapter_pages` pages, only ever between scenes.
A beat is one picture: a scene heading with its first action, then each further action paragraph, with the dialogue that follows it as its
lines. Chapter numbers come from a leading number in the section title (`## 03 The heist`) when every chapter has one, otherwise 1, 2, 3…;
a beat is numbered chapter x 1000 + its place, so adding to one chapter never renumbers another (a story of one chapter is plain 01, 02…).
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field

from . import beat_import, beats, numbering

LINE_SEP = "¶"
"""Between two speakers in an audio cell: the importer reads a name after it as the next speaker, whatever the words before it end in."""
LINES_PER_BEAT = 6
CHAPTER_PAGES = 12
MAX_CHAPTER_PAGES = 25
LINES_PER_PAGE = 55
PICTURE_CHARS = 420

_BONEYARD = re.compile(r"/\*.*?\*/", re.S)
_NOTE = re.compile(r"\[\[(?:(?!\]\]|\n[ \t]*\n).)*(?:\]\]|(?=\n[ \t]*\n)|\Z)", re.S)  # a note ends at its `]]`, or at a blank line: one never closed cannot swallow what follows
HEADING_START = r"(?:INT\.?\s*/\s*EXT|EXT\.?\s*/\s*INT|I/E|E/I|INT|EXT|EST)"
"""How a scene heading starts, without its full stop: INT, EXT, EST and the ways of saying inside and outside at once the format lists (INT./EXT,
INT/EXT, I/E), and the same the other way round (EXT/INT., E/I.), which writers use as much; a space either side of the / between words is the same."""
_SCENE = re.compile(rf"^{HEADING_START}(?:\.|\s)", re.I)
_SCENE_NUMBER = re.compile(r"\s+#[\w.-]+#\s*$")
_TRANSITION = re.compile(r"^(?:[A-Z0-9 .'\-]+ TO:|FADE (?:IN|OUT)[.:]?|FADE TO BLACK[.:]?|CUT TO BLACK[.:]?|SMASH CUT TO BLACK[.:]?)$")
_SECTION = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
_TITLE_KEY = re.compile(r"^\s*(title|credit|author|authors|source|notes|draft date|date|contact|copyright|revision)\s*:", re.I)
_ANY_KEY = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 ]*?\s*:")  # any key will do after the first: the title page may hold keys of its own (`Format: Short Screenplay`)
_CONTD = re.compile(r"\s*\(\s*CONT[’']D\s*\)", re.I)
_EXTENSION = re.compile(r"\s*\(([^)]*)\)\s*$")
_LEADING_NUMBER = re.compile(r"^(?:chapter|part|sequence|act|scene)?\s*(\d{1,3})\b\s*[-–—:.]?\s*(.*)$", re.I)


def _title(text: str) -> str:
    """`EXT. GRANNY'S PORCH - DUSK` -> `Ext. Granny's Porch - Dusk` (str.title() would make it Granny'S)."""
    return " ".join(w.capitalize() for w in text.split())


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


# --- reading ------------------------------------------------------------------------------------------------------------------------


_FENCE = re.compile(r"^\s*```[A-Za-z]*\s*$")


def _normal(text: str) -> str:
    """The text with plain line breaks, no byte order mark, and no code fence round it: an AI (or a chat window) hands Fountain over wrapped in ```."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if first is not None and last is not None and first < last and _FENCE.match(lines[first]) and _FENCE.match(lines[last]):
        lines = lines[:first] + lines[first + 1 : last] + lines[last + 1 :]
    return "\n".join(lines)


AS_SPACE = "\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"  # no-break, figure, thin, em... spaces
NO_WIDTH = "\u200b\u2060\ufeff"  # a zero-width space, a word joiner, a byte order mark pasted inside the text
_READABLE = str.maketrans({**dict.fromkeys(AS_SPACE, " "), **dict.fromkeys(NO_WIDTH, None)})


def _readable(text: str) -> str:
    """The text as it looks: a no-break space (or a thin or figure one) is a space and a zero-width space is nothing, so `BIG EDWARD` typed with a
    no-break space is the speaker typed with a plain one. Only reading uses it: the writer's text (each beat's piece of it) keeps what was typed.
    Lines keep their numbers."""
    return text.translate(_READABLE)


_PIC = re.compile(r"[ \t]*\[\[[ \t]*pic[ \t]*(?::[ \t]*(?P<text>(?:(?!\]\]).)*?)|\.)?[ \t]*\]\][ \t]*", re.I)
"""A picture the writer asks for and directs, on a line of its own (`[[Pic: Close on the coin in her fist.]]`, `[[Pic]]`): it starts the next picture
as a page break does, and its words are that beat's Shot direction. To any other Fountain app it is a note, and ignored."""
PIC_CHARS = 400  # a direction longer than this is more than a shot: the check says so


_NUDGE_LINE = re.compile(r"^[ \t]*\[\[[ \t]*nudge[ \t]*:[ \t]*(?P<s>[+-]?(?:\d+(?:\.\d*)?|\.\d+))[ \t]*s?\.?[ \t]*\]\][ \t]*$", re.I | re.M)
"""A line's nudge, on a line of its own right before its speaker (as a paragraph of its own, or with no blank line) or right under the speaker:
`[[Nudge: -0.4]]` starts the line that many seconds earlier (+ later) than where it would start. To any other Fountain app it is a note."""
_NUDGE_MARK = "\u2063"  # what a nudge note is read as while the text is cut into paragraphs: a line no note-clearing removes, so a speech stays one


def _nudge_marked(text: str) -> str:
    return _NUDGE_LINE.sub(lambda m: f"{_NUDGE_MARK}{float(m['s']):g}", text)


def _take_nudges(block: list[str]) -> tuple[list[str], float | None]:
    """A paragraph without its nudge lines, and the last nudge they held (None when none)."""
    found = None
    kept = []
    for ln in block:
        if ln.startswith(_NUDGE_MARK):
            found = float(ln[len(_NUDGE_MARK) :])
        else:
            kept.append(ln)
    return kept, found


_CUE_PART = re.compile(r"^\s*(?P<kind>sound|pic|camera|nudge)\s*(?::\s*(?P<text>.*?))?\s*$", re.I | re.S)
"""One part of a cue note: `Sound: clang`, `Camera: punch 1.08`, `Pic: a probe in dark space` (or a bare `Pic`), and beside a Sound or a Camera,
`Nudge: 0.1` (seconds later, or earlier when negative, than the word puts them: v216)."""
_CUE_NUDGE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*s?$", re.I)
_CUE_MARK = "\u2064"  # a cue note inside a speech while the text is cut and read: `⁤<hex of the note's words>⁤`, no space in it, never cleared as a note


def cue_parts(words: str) -> "dict[str, str] | None":
    """A note's words as a cue, when every part of it (`|` between them) is a Sound, a Pic or a Camera: {"sound": "clang", "camera": "punch"}. None
    for any other note."""
    parts: dict[str, str] = {}
    for piece in words.split("|"):
        m = _CUE_PART.match(piece)
        if not m or m["kind"].lower() in parts:
            return None
        said = " ".join((m["text"] or "").split())
        parts[m["kind"].lower()] = said if m["kind"].lower() == "pic" else said.rstrip(".")  # a Pic's words are its Shot direction, as written
    if "nudge" in parts and not (("sound" in parts or "camera" in parts) and _CUE_NUDGE.match(parts["nudge"])):
        return None  # a nudge moves a sound or a camera move; alone it is a line's own Nudge note, or only a note
    return parts if parts and all(v or k == "pic" for k, v in parts.items()) else None


def _in_speech(note: "re.Match[str]") -> bool:
    """Whether a note stands inside a speech: in a paragraph that starts with a speaker's cue, below the cue."""
    s = note.string
    start = s.rfind("\n", 0, note.start()) + 1
    above = s[:start].split("\n")[:-1]
    top = len(above)
    while top and above[top - 1].strip():
        top -= 1
    return top < len(above) and _is_character(above[top]) and not above[top].lstrip().startswith("[[")


def _cue_note(note: "re.Match[str]") -> "dict[str, str] | None":
    """The cue a note is (see `cue_parts`) when it stands inside a speech: it marks a word of the line (v211). None for any other note."""
    body = note.group(0)
    return cue_parts(body[2:-2]) if body.endswith("]]") and _in_speech(note) else None


def _cues_marked(text: str) -> str:
    """The text with each cue note inside a speech replaced by a mark that no note-clearing removes and that holds its words, so the speech is read
    whole and the place of the note among the words is kept."""
    return _NOTE.sub(lambda m: f"{_CUE_MARK}{m.group(0)[2:-2].encode().hex()}{_CUE_MARK}" if _cue_note(m) else m.group(0), text)


_MARKED = re.compile(f"{_CUE_MARK}([0-9a-f]*){_CUE_MARK}")


def cues_out(text: str) -> "tuple[str, list[dict]]":
    """A speech's words without its cue marks, and each cue with `word`: how many words are spoken before it (a [tag] is not one). The words close up round a mark as they
    would round a note left out (a space, none before a stop or a comma)."""
    cues: list[dict] = []
    said = ""
    for n, piece in enumerate(_MARKED.split(text)):
        if n % 2:
            parts = cue_parts(bytes.fromhex(piece).decode()) or {}
            cues.append({"word": len([w for w in said.split() if not (w.startswith("[") and w.endswith("]"))]), **parts})  # a v3 tag ([sighs]) is not a word said
            continue
        piece = " ".join(piece.split()) if _MARKED.search(text) else piece
        if not piece:
            continue
        said += (" " if said and not re.match(r"[,.;:!?…)\]'’\"”]", piece) else "") + piece
    return said.strip(), cues


_INFO_CARD_NOTE = re.compile(r"[ \t]*\[\[[ \t]*info[ \t]+card[ \t]*:(?P<text>(?:(?!\]\]).)*?)\]\][ \t]*", re.I)
"""The info card shown over a picture, on a line of its own inside that picture's text: `[[Info card: label | title | sentence]]`. Any slot may be
empty; one slot alone is the title (`[[Info card: 2302]]`)."""
_CHANGES_NOTE = re.compile(r"[ \t]*\[\[[ \t]*changes[ \t]*:(?P<text>(?:(?!\]\]).)*?)\]\][ \t]*", re.I)
"""What stays changed in every later picture from this one on, on a line of its own inside the picture's text: `[[Changes: the mast is broken]]`."""
INFO_CARD_FIELDS = ("info_label", "info_title", "info_text")


def _alone(note: "re.Match[str]", pattern: "re.Pattern[str]") -> "re.Match[str] | None":
    """The note read with `pattern`, when it stands on a line of its own outside a speech; None for any other note. One written inside a speech
    stays a note: it belongs to the words spoken, not to the picture."""
    s = note.string
    start, end = s.rfind("\n", 0, note.start()) + 1, s.find("\n", note.end())
    found = pattern.fullmatch(s[start : end if end >= 0 else len(s)])
    if not found:
        return None
    above = s[:start].split("\n")[:-1]
    top = len(above)
    while top and above[top - 1].strip():
        top -= 1
    return None if top < len(above) and _is_character(above[top]) else found


def _pic_of(note: "re.Match[str]") -> "re.Match[str] | None":
    """The Pic note a note is, when it is one standing on a line of its own outside a speech (see `_PIC`); None for any other note. One written
    inside a speech stays a note: cutting there would make the rest of the speech action."""
    return _alone(note, _PIC)


def info_card(words: str) -> dict:
    """An Info card note's words as the beat's fields: `label | title | sentence` (a `|` after the second stays in the sentence), one slot alone the
    title. Empty slots are left out; nothing when no slot has words."""
    slots = [" ".join(s.split()) for s in words.split("|", 2)]
    if len(slots) == 1:
        slots = ["", slots[0]]
    return {key: value for key, value in zip(INFO_CARD_FIELDS, slots) if value}


def beat_notes(text: str) -> dict:
    """The info card and the changes a beat's own text gives in its `[[Info card: …]]` and `[[Changes: …]]` notes, each read only standing on a line
    of its own outside a speech (the first of each counts): {info_label, info_title, info_text, changes}, those that have words."""
    out: dict = {}
    for note in _NOTE.finditer(text or ""):
        if (card := _alone(note, _INFO_CARD_NOTE)) and not any(k in out for k in INFO_CARD_FIELDS):
            out.update(info_card(card["text"]))
        elif (changed := _alone(note, _CHANGES_NOTE)) and "changes" not in out and (words := " ".join(changed["text"].split())):
            out["changes"] = words
    return out


_NOTE_LINE = re.compile(r"[ \t]*\[\[(?P<text>(?:(?!\]\]).)*?)\]\][ \t]*")
"""Any note standing alone on its line."""
SCENE_LABELS = (("Place", "place"), ("Light", "look"), ("Set dressing", "set_dressing"), ("Continuity", "continuity"))
"""The parts of the `[[Scene <name>. Place: …. Light: …. Set dressing: …. Continuity: ….]]` note the complete script writes, in its order."""
BEAT_LABELS = ("Shows", "Hold", "Focus", "Expression", "Camera", "Cast", "Transition", "Ambience", "Note")
"""The parts of its `[[Beat NN. Hold: …. Focus: …. Expression: …. …]]` note, in its order; Focus and Expression are read back."""
_SCENE_NOTE = re.compile(r"Scene (?P<name>.+?)\. (?=(?:Place|Light|Set dressing|Continuity): )(?P<rest>.*)", re.S)
_BEAT_NOTE = re.compile(r"Beat (?P<number>[\w.-]+?)\.(?: (?P<rest>.*))?", re.S)


def labelled(text: str, labels: "tuple[str, ...]") -> "dict[str, str] | None":
    """`Label: value. Label: value.` read by `labels`, which must come in that order, each at most once, with nothing before the first: each value
    as written, its full stop kept. None when the text is not that (a label twice, out of order, or words before the first), so nothing is guessed."""
    found = [(m.start(), m.group(1)) for m in re.finditer(r"(?:^|(?<=\. ))(" + "|".join(re.escape(x) for x in labels) + r"): ", text)]
    names = [name for _at, name in found]
    if not found or found[0][0] != 0 or len(set(names)) != len(names) or names != sorted(names, key=labels.index):
        return None
    ends = [at for at, _name in found[1:]] + [len(text)]
    return {name: text[at + len(name) + 2 : end].strip() for (at, name), end in zip(found, ends, strict=True)}


def _own_notes(text: str) -> "list[str]":
    """The words of each note standing alone on a line of `text`, outside a speech, in order."""
    return [m["text"].strip() for note in _NOTE.finditer(text or "") if (m := _alone(note, _NOTE_LINE))]


def scene_note(text: str) -> "tuple[str, dict] | None":
    """The first `[[Scene <name>. Place: …]]` note of a beat's text that reads exactly: the scene's name and its fields (place, look, set_dressing,
    continuity) as the note says them. None when there is none."""
    for words in _own_notes(text):
        if (m := _SCENE_NOTE.fullmatch(words)) and (parts := labelled(m["rest"], tuple(label for label, _key in SCENE_LABELS))):
            return m["name"].strip(), {key: parts[label] for label, key in SCENE_LABELS if parts.get(label)}
    return None


def beat_note_fields(text: str) -> dict:
    """Focus and Expression from a beat's own `[[Beat NN. …]]` note, when it reads exactly; {} otherwise."""
    for words in _own_notes(text):
        if (m := _BEAT_NOTE.fullmatch(words)) and m["rest"] and (parts := labelled(m["rest"], BEAT_LABELS)):
            return {key: parts[label] for label, key in (("Focus", "focus"), ("Expression", "expression")) if parts.get(label)}
    return {}


def scenes_said(plan: "Plan") -> dict[str, dict]:
    """Each place's scene fields as a `[[Scene …]]` note in the text says them, read from the first beat of that place whose note names it."""
    out: dict[str, dict] = {}
    for _chapter, _number, beat in plan.rows():
        place = place_of(beat.get("place", ""))
        said = scene_note(beat.get("fountain") or "") if place and place["slug"] not in out else None
        if said and re.sub(r"[^a-z0-9]+", "-", said[0].lower().replace("'", "").replace("’", "")).strip("-") == place["slug"]:
            out[place["slug"]] = said[1]
    return out


def notes_to_fill(data: dict, text: str) -> dict:
    """What a beat's Info card and Changes notes give that the beat does not hold yet: the info card only when the beat has none of its three fields
    (a card is one thing, never half a person's and half the note's), the changes, and the focus and expression of the complete script's
    `[[Beat NN. …]]` note, only when empty. A value a person set is never written over."""
    noted = beat_notes(text)
    has = lambda key: bool(str(data.get(key) or "").strip())  # noqa: E731
    card = {k: v for k, v in noted.items() if k in INFO_CARD_FIELDS} if not any(has(k) for k in INFO_CARD_FIELDS) else {}
    shot = {k: v for k, v in beat_note_fields(text).items() if not has(k)}  # what the complete script's Beat note says of the shot (v204)
    return {**card, **({"changes": noted["changes"]} if noted.get("changes") and not has("changes") else {}), **shot}


def _notes_out(text: str, gone) -> str:
    """The text with each note replaced by `gone(note)`, but a Pic note on its own line kept as written: it is the story's, it starts a picture."""
    return _NOTE.sub(lambda m: m.group() if _pic_of(m) else gone(m), text)


def _clean(text: str) -> str:
    return _notes_out(_cues_marked(_BONEYARD.sub("", _nudge_marked(_readable(_normal(text))))), lambda _m: "")  # a boneyard and a note are the writer's, not the story's


def _blocks_at(text: str, *, marks: bool = False) -> list[tuple[int, list[str]]]:
    """The text's paragraphs (runs of lines between blank ones), each with the line it starts on. A nudge note's line (see `_nudge_marked`) is left
    out without ending the paragraph it stands in, unless `marks` keeps it for the reader that takes its value."""
    blocks: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    start = 0
    for n, raw in enumerate(text.split("\n")):
        if raw.startswith(_NUDGE_MARK) and not marks:
            continue
        if not raw.strip() and not (cur and raw == "  " and _is_character(cur[0])):  # two spaces keep a gap inside a speech
            if cur:
                blocks.append((start, cur))
            cur = []
        elif raw == "  " and cur and _is_character(cur[0]):
            continue
        elif _PIC.fullmatch(raw):  # a paragraph of its own, even written right above a speaker or action with no blank line
            if cur:
                blocks.append((start, cur))
            blocks.append((n, [raw.strip()]))
            cur = []
        else:
            if not cur:
                start = n
            cur.append(raw.rstrip())
    if cur:
        blocks.append((start, cur))
    return blocks


def _blocks(text: str) -> list[list[str]]:
    return [block for _start, block in _blocks_at(text)]


def _is_scene(s: str) -> bool:
    return bool(_SCENE.match(s)) or (s.startswith(".") and not s.startswith(".."))


def _is_transition(s: str) -> bool:
    return bool(_TRANSITION.match(s)) or (s.startswith(">") and not s.rstrip().endswith("<"))


def _cue_name(s: str) -> str:
    return _EXTENSION.sub("", _CONTD.sub("", s).lstrip("@").rstrip("^").strip()).strip()


def _is_character(s: str) -> bool:
    s = s.strip()
    if s.startswith("@"):
        return len(s) > 1
    if not s or _is_scene(s) or _is_transition(s) or s.startswith(("!", "#", "=", "~", ">")):
        return False
    name = _cue_name(s)
    return bool(re.search(r"[A-Z]", name)) and name == name.upper() and not name.endswith(".") or (bool(re.search(r"[A-Z]", name)) and name == name.upper() and len(name.split()) <= 4)


_EMPHASIS = (
    re.compile(r"\*\*\*(\S(?:.*?\S)?)\*\*\*"),
    re.compile(r"\*\*(\S(?:.*?\S)?)\*\*"),
    re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])"),
    re.compile(r"(?<!\w)_(?![\s_])(.+?)(?<![\s_])_(?!\w)"),
)


def _plain(text: str) -> str:
    """The words without Fountain's emphasis marks (`*italic*`, `**bold**`, `_underline_`): a picture prompt or a caption must not show them."""
    text = text.replace("\\*", "\x00a").replace("\\_", "\x00u")  # an escaped mark is a plain character: set it aside while the marks come off
    for pattern in _EMPHASIS:
        text = pattern.sub(r"\1", text)
    return text.replace("\x00a", "*").replace("\x00u", "_")


def _plain_elements(els: list[dict]) -> list[dict]:
    for el in els:
        if el["t"] in ("action", "centred"):
            el["text"] = _plain(el["text"])
        elif el["t"] == "dialogue":
            el["text"] = _plain(el["text"])
            el["paren"] = [_plain(x) for x in el["paren"]]
    return els


_SYNOPSIS_LINE = re.compile(r"^=(?!=)")
_EMPTY_CENTRE = re.compile(r"^>\s*<$")
_CENTRED = re.compile(r"^>\s*(\S.*?)\s*<$")


def _block_elements(block: list[str]) -> list[dict]:
    # A synopsis (`= text`) is the writer's note even when it sits right under a scene heading, and a centred block an AI wrote as `> <`, the text,
    # `> <` has empty markers round the words: neither belongs in a beat's picture.
    synopses = [{"t": "synopsis", "text": ln.strip()[1:].strip()} for ln in block if _SYNOPSIS_LINE.match(ln.strip()) and ln.strip()[1:].strip()]
    block = [ln for ln in block if not _SYNOPSIS_LINE.match(ln.strip()) and not _EMPTY_CENTRE.match(ln.strip())]
    return [*_block_content(block), *synopses] if block else synopses


def _block_content(block: list[str]) -> list[dict]:
    first = block[0].strip()
    if first.startswith("==="):
        return [{"t": "break"}]  # a page break: the next picture starts here (a writer's way to say "new shot" where two actions would be read as one)
    if pic := _PIC.fullmatch(first):
        return [{"t": "break", "direction": " ".join((pic["text"] or "").split())}]
    if first.startswith("=") and not first.startswith("=="):
        return []  # a synopsis is a note to the writer
    m = _SECTION.match(first)
    if m and len(block) == 1:
        return [{"t": "section", "depth": len(m.group(1)), "title": m.group(2)}]
    if _is_scene(first):
        heading = _SCENE_NUMBER.sub("", first.lstrip(".")).strip()
        out = [{"t": "scene", "text": heading}]
        rest = " ".join(ln.strip() for ln in block[1:] if ln.strip())
        if rest:
            out.append({"t": "action", "text": rest})
        return out
    if len(block) == 1 and _is_transition(first):
        return [{"t": "transition", "text": first.lstrip(">").strip()}]
    centred = [_CENTRED.match(ln.strip()) for ln in block]
    if all(centred):  # centred text standing alone (`> THE END <`): words to show on a card, not a picture to describe; one line of it for each line written
        return [{"t": "centred", "text": "\n".join(m.group(1) for m in centred)}]
    if len(block) >= 2 and _is_character(first):
        ext = _EXTENSION.search(_CONTD.sub("", first).lstrip("@").rstrip("^").strip())
        paren, speech = [], []
        for ln in block[1:]:
            s = ln.strip()
            (paren if s.startswith("(") and s.endswith(")") else speech).append(s.strip("()") if s.startswith("(") and s.endswith(")") else s.lstrip("~").strip())  # a sung line of a speech is the words, not the mark
        said, cues = cues_out(" ".join(speech).strip())  # a Sound, Pic or Camera note among the words marks a word of the line (v211): never spoken
        if said:
            return [{"t": "dialogue", "name": _cue_name(first), "ext": (ext.group(1) if ext else ""), "paren": paren, "text": said, "dual": first.rstrip().endswith("^"), **({"cues": cues} if cues else {})}]
    if all(ln.strip().startswith("~") for ln in block):  # lyrics: words that are sung, not described and not (yet) anyone's line
        return [{"t": "lyrics", "text": " ".join(ln.strip().lstrip("~").strip() for ln in block).strip()}]
    text_ = _MARKED.sub("", " ".join(ln.strip().lstrip("!~") for ln in block)).strip()
    text_ = re.sub(r"^>\s*(.*?)\s*<$", r"\1", text_)  # centred text is action
    return [{"t": "action", "text": text_}] if text_ else []


def parse(text: str, *, lines: bool = False) -> list[dict]:
    """The screenplay's elements in order: {t: scene|action|dialogue|transition|section|centred, ...}. A title page and synopses are left out; a page break (`===`) is {t: break},
    a Pic note {t: break, direction} (one written with a page break is one break).
    With `lines`, each element also says the line (counting from 0) of the text it starts on."""
    text = _nudge_marked(_normal(text))
    blocks = _blocks_at(_blank_comments(_readable(text)) if lines else _clean(text), marks=True)  # to say where each element is, a note or boneyard keeps its line breaks
    if blocks and all(_ANY_KEY.match(ln) or ln.startswith((" ", "\t")) for ln in blocks[0][1]) and _TITLE_KEY.match(blocks[0][1][0]):
        blocks = blocks[1:]  # a title page: it starts with a key Fountain knows, and every line is a key or the rest of one
    known = {_cue_name(block[0]) for _start, block in blocks if len(block) >= 2 and _is_character(block[0])}
    out: list[dict] = []
    pending: float | None = None  # a nudge note read: it is the next speech's, when nothing else comes first
    for start, block in blocks:
        while block and block[0].startswith(_NUDGE_MARK):  # written right above the speaker, with no blank line
            block, pending = block[1:], float(block[0][len(_NUDGE_MARK) :])
            start += 1
        if not block:
            continue
        pieces = _split_cues(start, block, known)
        for n, (at, piece) in enumerate(pieces):
            piece, said = _take_nudges(piece)
            pending = said if said is not None else pending
            for el in _plain_elements(_block_elements(piece) if piece else []):
                if el["t"] == "dialogue" and pending is not None:
                    el["nudge"] = pending
                pending = None
                if n == 0 and len(pieces) > 1 and el["t"] == "dialogue":
                    el["dual"] = False  # written together with no blank line, only the second can be the one that speaks over the first
                if el["t"] == "break" and out and out[-1]["t"] == "break":  # a Pic note and a page break written together are one break
                    if "direction" in el:
                        out[-1].setdefault("direction", el["direction"])  # of two Pic notes together the first is the picture (the check says so)
                    continue
                out.append({**el, "line": at} if lines else el)
    return out


def _split_cues(start: int, block: list[str], known: set[str]) -> list[tuple[int, list[str]]]:
    """A speech block cut where another speaker's cue appears inside it. Writers (and AIs) leave out the blank line between two speakers of a
    dual dialogue; a line is taken for a cue only when it is a name already used as a cue elsewhere and something follows it, so a shouted line
    of dialogue stays dialogue."""
    if len(block) < 3 or not _is_character(block[0]):
        return [(start, block)]
    for i in range(2, len(block) - 1):
        line = block[i].strip()
        if _is_character(line) and _cue_name(line) in known:
            return [(start, block[:i]), *_split_cues(start + i, block[i:], known)]
    return [(start, block)]


# --- speakers -----------------------------------------------------------------------------------------------------------------------


def handles(names: list[str], keep: "set[str] | None" = None) -> dict[str, str]:
    """Character cue -> the handle the importer reads (a capital, then lower case: Granny, Cook). A name of several words takes its last
    (`OLD COOK` -> Cook); two different names that would share one keep all their words, joined by hyphens (`MRS HALE` -> Mrs-hale, `DR HALE` ->
    Dr-hale). An apostrophe is dropped, not made a break between words (`A GIRL'S VOICE` -> A-girls-voice, `O'BRIEN` -> Obrien). `keep` is the
    handles a story already has (lower case, as its records hold them): a speaker brought in when the words were run together (Mrshale), or
    when an apostrophe still cut a word in two (A-girl-s-voice, Brien), keeps that handle, so a new import finds their Character and lines and
    makes no second one."""
    chosen = _handles(names, "")
    if keep:
        before = _handles(names, " ")  # as an apostrophe was read until it was dropped
        for name, handle in chosen.items():
            if handle.lower() in keep:
                continue
            older = (handle.replace("-", ""), before.get(name, ""), before.get(name, "").replace("-", ""))
            chosen[name] = next((h for h in older if h and h.lower() in keep), handle)
    return chosen


def _handles(names: list[str], apostrophe: str) -> dict[str, str]:
    """`handles` with nothing kept, an apostrophe read as `apostrophe` (dropped, or a break between words)."""
    clean = lambda n: [w for w in re.sub(r"[^A-Za-z ]", " ", re.sub(r"['’]", apostrophe, n)).split() if w]  # noqa: E731
    whole = lambda n: "-".join(clean(n)).capitalize()  # noqa: E731
    seen: dict[str, str] = {}
    chosen: dict[str, str] = {}
    for name in names:
        words = clean(name)
        if not words or name in chosen:
            continue
        short = words[-1].capitalize()
        if short in seen and seen[short] != name:
            for other, handle in list(chosen.items()):
                if handle == short and other != name:
                    chosen[other] = whole(other)
            short = whole(name)
        seen.setdefault(short, name)
        chosen[name] = short
    return chosen


# --- cutting ------------------------------------------------------------------------------------------------------------------------


def _lines_of(el: dict) -> int:
    t = el["t"]
    if t == "scene":
        return 2
    if t in ("action", "lyrics", "centred"):
        return math.ceil(len(el["text"]) / 60) + 1
    if t == "dialogue":
        return math.ceil(len(el["text"]) / 35) + 2 + len(el["paren"])
    if t == "transition":
        return 2
    return 0


def pages(elements: list[dict]) -> float:
    return sum(_lines_of(e) for e in elements) / LINES_PER_PAGE


@dataclass
class Scene:
    heading: str
    elements: list[dict]
    markers: list[tuple[int, str]] = field(default_factory=list)  # sections written just above it
    start: int = 0  # the line it starts on (a section written just above it starts it): only when the elements say where they are
    synopses: list[str] = field(default_factory=list)  # the writer's one-line summaries (`= text`) of the scene, those under a section above it first

    def pages(self) -> float:
        return pages(self.elements) + 2 / LINES_PER_PAGE


def _scenes(elements: list[dict]) -> list[Scene]:
    scenes: list[Scene] = []
    pending: list[tuple[int, str]] = []
    pending_at: int | None = None  # the line of the first section written above the next scene
    pending_syn: list[str] = []  # synopses written under a section, before the scene it starts
    waiting: list[dict] = []  # a Pic note under a section, or above the first scene: it directs the next scene's first picture
    for el in elements:
        if el["t"] == "break" and "direction" in el and (pending or not scenes):
            waiting.append(el)
            continue
        if el["t"] == "synopsis":
            if scenes and not pending:
                scenes[-1].synopses.append(el["text"])
            else:
                pending_syn.append(el["text"])
            continue
        if el["t"] == "section":
            pending.append((el["depth"], el["title"]))
            pending_at = el.get("line", 0) if pending_at is None else pending_at
            continue
        if el["t"] == "scene":
            scenes.append(Scene(el["text"], [], pending, el.get("line", 0) if pending_at is None else pending_at, pending_syn))
            pending, pending_at, pending_syn = [], None, []
        else:
            if not scenes:
                scenes.append(Scene("", [], pending, el.get("line", 0) if pending_at is None else pending_at, pending_syn))
                pending, pending_at, pending_syn = [], None, []
            elif pending:  # a section between a scene's action and its dialogue starts nothing: it is the writer's note about the scene
                scenes[-1].markers += pending
                pending, pending_at = [], None
        if scenes:
            scenes[-1].elements += [el, *waiting] if el["t"] == "scene" else [*waiting, el]
            waiting = []
    return scenes


def _split_by_size(scenes: list[Scene], target: float) -> list[list[Scene]]:
    """Groups of whole scenes of about `target` pages: each group ends where the page count is nearest the target, a little sooner after a
    transition (a place where a story takes a breath)."""
    groups: list[list[Scene]] = []
    cur: list[Scene] = []
    size = 0.0
    for i, scene in enumerate(scenes):
        cur.append(scene)
        size += scene.pages()
        if i == len(scenes) - 1:
            break
        nxt = scenes[i + 1].pages()
        breath = 0.12 * target if any(e["t"] == "transition" for e in scene.elements[-1:]) else 0
        if abs(size + nxt - target) - 0 >= abs(size - target) - breath and size >= target * 0.5:
            groups.append(cur)
            cur, size = [], 0.0
    if cur:
        groups.append(cur)
    return groups


def _split_by_sections(scenes: list[Scene], depth: int) -> list[tuple[str, list[Scene]]]:
    """Cut where a section of this depth or shallower is written; content before the first one is a chapter of its own."""
    out: list[tuple[str, list[Scene]]] = []
    title, cur = "", []
    for scene in scenes:
        starts = [t for d, t in scene.markers if d <= depth]
        if starts and cur:
            out.append((title, cur))
            cur = []
        if starts:
            title = starts[-1]
        cur.append(scene)
    if cur:
        out.append((title, cur))
    return out


def _depths(scenes: list[Scene]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for s in scenes:
        for d, _t in s.markers:
            counts[d] = counts.get(d, 0) + 1
    return counts


def _chapters(scenes: list[Scene], target: float, ceiling: float, depth_floor: int = 0) -> list[tuple[str, list[Scene]]]:
    """[(title, scenes)]: by the writer's sections (the shallowest depth written at least twice), a chapter longer than `ceiling` pages cut
    again by the next depth down or, with none, by size."""
    counts = {d: n for d, n in _depths(scenes).items() if d > depth_floor}
    depth = min((d for d, n in counts.items() if n >= 2), default=None)
    if depth is None:
        groups = _split_by_size(scenes, target)
        return [(_title(g[0].heading) if g[0].heading else "Opening", g) for g in groups]
    out: list[tuple[str, list[Scene]]] = []
    for title, group in _split_by_sections(scenes, depth):
        if sum(s.pages() for s in group) > ceiling:
            deeper = _chapters(group, target, ceiling, depth)
            if len(deeper) > 1:
                out += [(f"{title}: {t}" if title and t else (title or t), g) for t, g in deeper]
                continue
        out.append((title or (_title(group[0].heading) if group[0].heading else "Opening"), group))
    return out


@dataclass
class Chapter:
    number: int
    title: str
    scenes: list[Scene]
    beats: list[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """What the writer's synopses (`= text`) say of the chapter, in order: the ones under its section, then those of its scenes."""
        return " ".join(t for sc in self.scenes for t in sc.synopses).strip()[:1000]

    def lines(self) -> int:
        return sum(len(b["lines"]) for b in self.beats)

    def speakers(self) -> list[str]:
        return sorted({ln["speaker"] for b in self.beats for ln in b["lines"]})


@dataclass
class Plan:
    chapters: list[Chapter]
    speakers: dict[str, str]
    warnings: list[str]
    source: dict
    single: bool
    front: str = ""  # what is written before the first beat, as written: the title page, and anything the story does not make a beat of
    characters: list = field(default_factory=list)  # who the screenplay introduces (see `characters`)
    places: dict = field(default_factory=dict)  # place slug -> the place the scene headings name (see `places_of`)
    ambience: dict = field(default_factory=dict)  # place slug -> the bed its beats' action asks for (see `ambience_of`)
    renumber: dict = field(default_factory=dict)  # (chapter number, position) -> the number a beat keeps in a revision (see `align`)
    end_transition: str = ""  # `fade` when the transition written after the last beat (FADE OUT.) fades the film out; no beat follows it, so it is the story's
    end_transition_text: str = ""  # that line, as written

    def number(self, chapter: Chapter, i: int) -> str:
        if (chapter.number, i) in self.renumber:  # a revision: a beat keeps the number of the beat it is, and a new one is numbered after the beat before it (1002a)
            return self.renumber[(chapter.number, i)]
        return f"{i:02d}" if self.single else str(chapter.number * 1000 + i)

    def rows(self) -> list[tuple[Chapter | None, str, dict]]:
        """Every beat with its number, in order: each chapter's beats, and right after a beat the overlay beats its lines' Pic notes start (see
        `_beats_for`), numbered as beats inserted after it are (04a, 04b), past any number another beat already has."""
        out = []
        taken = {self.number(ch, i) for ch in self.chapters for i in range(1, len(ch.beats) + 1)}
        for ch in self.chapters:
            for i, b in enumerate(ch.beats, 1):
                number = self.number(ch, i)
                out.append((None if self.single else ch, number, b))
                for overlay in b.get("overlays") or []:
                    number = numbering.after(number)
                    while number in taken:
                        number = numbering.after(number)
                    taken.add(number)
                    out.append((None if self.single else ch, number, overlay))
        return out

    def sheet(self, parts: "set[int] | None" = None) -> str:
        """The beat sheet text; `parts` limits it to some chapters (by number)."""
        cell = lambda s: re.sub(r"\s+", " ", str(s).replace("|", "/")).strip()  # noqa: E731
        out: list[str] = []
        for ch in self.chapters:
            if parts is not None and ch.number not in parts:
                continue
            if not self.single:
                out += [f"## Chapter {ch.number} - {cell(ch.title) or 'Untitled'}", "| Beat | Time | Audio | Single still / composition |", "| --- | --- | --- | --- |"]
            elif not out:
                out += ["| Beat | Time | Audio | Single still / composition |", "| --- | --- | --- | --- |"]
            for _c, number, b in (row for row in self.rows() if (row[0] or self.chapters[0]) is ch):
                audio = f" {LINE_SEP} ".join(f"{ln['speaker']}: {cell(ln['text'])}" for ln in b["lines"]) or "No speech."
                if b.get("sung"):  # sung words are a cue for the sound library (a song, a hummed tune), kept with the beat as a note
                    audio += f" {LINE_SEP} Sound: sung: " + cell(" / ".join(b["sung"]))
                picture = cell(b["picture"])
                if b.get("card") and b["notes"]:  # how the lines read over a card are said: a dash stands where the picture's words would be
                    picture = f"— Delivery: {cell('; '.join(b['notes']))}."
                out.append(f"| {number} | — | {audio} | {picture} |")
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def report(self, parts: "set[int] | None" = None) -> str:
        total_pages = sum(pages(e for s in c.scenes for e in s.elements) if False else sum(s.pages() for s in c.scenes) for c in self.chapters)
        head = [
            f"{len(self.chapters)} chapter{'s' if len(self.chapters) != 1 else ''}, {sum(len(c.scenes) for c in self.chapters)} scenes, about {total_pages:.0f} pages, "
            f"{sum(len(c.beats) for c in self.chapters)} beats, {sum(c.lines() for c in self.chapters)} spoken lines.",
            "",
        ]
        rows = []
        first = 1
        for c in self.chapters:
            pg = sum(s.pages() for s in c.scenes)
            mark = "" if parts is None or c.number in parts else " (not in this run)"
            rows.append(f"{c.number:>3}  {c.title[:44]:<44}  scenes {first}–{first + len(c.scenes) - 1}  ·  ~{pg:.0f} pp  ·  {len(c.beats)} beats  ·  {c.lines()} lines  ·  {', '.join(c.speakers()) or 'no speech'}{mark}")
            first += len(c.scenes)
        tail = []
        if self.speakers:
            tail += ["", "Speakers: " + "; ".join(f"{_title(raw)} → {h}" for raw, h in sorted(self.speakers.items()))]
        if self.warnings:
            tail += ["", "Check:"] + [f"  - {w}" for w in self.warnings]
        return "\n".join(head + rows + tail)


_TRANSITION_KINDS = (
    (re.compile(r"\b(?:DISSOLVE|CROSS[ -]?FADE|CROSS[ -]?DISSOLVE)\b", re.I), "dissolve"),
    (re.compile(r"\bFADE\b|\bDIP TO BLACK\b", re.I), "fade"),
    (re.compile(r"\bCUT\b", re.I), "cut"),  # CUT TO:, SMASH CUT TO:, MATCH CUT TO:, JUMP CUT TO:
)


def transition_kind(text: str) -> "str | None":
    """How a transition line asks the picture to change: `dissolve` or `fade` when its words say so, else `cut`. Any line in capitals ending in TO:
    is a transition (the Fountain format says so), and one that names no dissolve or fade (BACK TO:, FLASHBACK TO:, WIPE TO:) is a cut, its words
    kept as written. None only when there is no line."""
    if not str(text or "").strip():
        return None
    return next((kind for pattern, kind in _TRANSITION_KINDS if pattern.search(text)), "cut")


def transition_seconds(beat: dict) -> "float | None":
    """How long the transition into a beat lasts, when a note in its own piece of the text says so (`[[Transition: 1.2s.]]`), kept to what the beat's
    field takes; None when no note does."""
    found = _TRANSITION_NOTE.search(" ".join(re.findall(r"\[\[(.*?)\]\]", beat.get("fountain") or "", re.S)))
    return min(TRANSITION_SECONDS[1], max(TRANSITION_SECONDS[0], float(found.group(1)))) if found else None


def follow_transition(held: dict, beat: dict) -> "tuple[dict, str]":
    """What an import changes of a beat that exists (`held`: its data) so that its transition follows the script (`beat`: as the Fountain now reads),
    and what to say when it does not. A beat follows the script until someone changes it by hand: one whose `transition` is empty or means what its
    `transition_text` says takes the script's line and its meaning (both go when the line is gone); one whose `transition` says something else was set
    by hand and is kept (and said, when the script has a line there), unless the script has come to say the same. Returns ({field: value, or None to take it out}, a sentence or "")."""
    kind, text = str(held.get("transition") or "").strip().lower(), str(held.get("transition_text") or "").strip()
    new_kind, new_text = str(beat.get("transition") or ""), str(beat.get("transition_text") or "")
    if not kind or kind == (transition_kind(text) or ""):
        wanted = {"transition": new_kind, "transition_text": new_text}
    elif kind == new_kind:
        wanted = {"transition_text": new_text}  # the script says what the hand set: it follows the script again
    else:
        return {}, f"keeps its {kind} (set by hand); the script says {new_text}" if new_text else ""
    now = {"transition": kind, "transition_text": text}
    return {key: (value or None) for key, value in wanted.items() if value != now[key]}, ""


def _beats_for(scenes: list[Scene], names: dict[str, str], carry: "dict | None" = None) -> list[dict]:
    """The beats of some scenes. `carry` is shared by all the chapters of a story: a transition written at the end of one chapter belongs to the
    first beat of the next. The story's very first beat has nothing before it to change from, so its transition (FADE IN:) is how the film opens;
    what is still held after the last beat (FADE OUT.) is how it ends (see `cut`)."""
    out: list[dict] = []
    carry = carry if carry is not None else {"held": []}
    carry.setdefault("held_at", None)
    held: list[str] = carry["held"]  # transition lines written since the last beat: they belong to the one that comes next
    scene_first = [True]
    here = [""]  # the heading of the scene being read: a beat is in that place

    def start(picture: str, at: "int | None" = None, scene_start: "int | None" = None) -> dict:
        beat: dict = {"picture": picture, "lines": [], "notes": [], "sung": []}
        if here[0]:
            beat["place"] = here[0]
        if at is not None:  # where the beat starts in the text: a section or transition written just above it starts it
            for earlier in (carry["held_at"], scene_start if scene_first[0] else None):
                at = at if earlier is None else min(at, earlier)
            beat["at"] = at
        carry["held_at"] = None
        scene_first[0] = False
        if carry.get("direction"):
            beat["direction"] = carry["direction"]
        carry["direction"] = None
        if held:
            beat["transition_text"] = held[-1]
            kind = transition_kind(held[-1])
            if kind:
                beat["transition"] = kind
            held.clear()
        out.append(beat)
        return beat

    cur: dict | None = None
    for scene in scenes:
        cur = None
        fresh_scene = True
        scene_first[0] = True
        here[0] = scene.heading
        for el in scene.elements:
            t = el["t"]
            ln = el.get("line")
            sc = scene.start if ln is not None else None
            if t == "scene":
                here[0] = el["text"]
                cur = start(heading_words(el["text"]), ln, sc)  # the heading in words: Interior: Captain's Cabin, night
                fresh_scene = True
            elif t == "action":
                # Action with no speech between it and the last action is the same picture (up to a paragraph's worth); after speech it is a new one.
                if cur is not None and not cur.get("card") and not cur["lines"] and (cur["picture"] == heading_words(scene.heading) or len(cur["picture"]) + len(el["text"]) <= PICTURE_CHARS):
                    joined = f"{cur['picture']}. {el['text']}" if fresh_scene else f"{cur['picture']} {el['text']}"
                    cur["picture"] = joined
                else:
                    cur = start(el["text"], ln, sc)
                fresh_scene = False
            elif t == "dialogue":
                if cur is None:
                    cur = start(scene.heading or "Continues", ln, sc)
                if len(cur["lines"]) >= LINES_PER_BEAT:
                    cur = start(f"(continued) {cur['picture'][:80]}", ln, sc)
                who = names.get(el["name"], el["name"].capitalize())
                cur["lines"].append({"speaker": who, "text": el["text"], "at": ln, "end": el.get("end"), "dual": bool(el.get("dual")), **({"nudge": el["nudge"]} if el.get("nudge") else {}), **({"cues": el["cues"]} if el.get("cues") else {})})
                for cue in el.get("cues") or []:  # a Pic note among the words: a picture of its own that comes in at that word, over this one (v211)
                    if "pic" in cue:
                        cur.setdefault("overlays", []).append(
                            {"picture": cue["pic"] or cur["picture"], "direction": cue["pic"], "lines": [], "notes": [], "sung": [], **({"place": cur["place"]} if cur.get("place") else {}), "starts_during": {"line": len(cur["lines"]), "word": cue["word"]}}
                        )
                note = ", ".join(el["paren"] + ([el["ext"]] if el["ext"] else []))
                if note:
                    cur["notes"].append(f"{who} ({note})")
                fresh_scene = False
            elif t == "lyrics":
                if cur is None:
                    cur = start(scene.heading or "Continues", ln, sc)
                cur["sung"].append(el["text"])
            elif t == "centred":
                # Centred text standing alone is a card in the film (THREE YEARS LATER, THE END): a beat of its own that shows the words and has no picture.
                title, _, more = el["text"].partition("\n")
                if cur is not None and cur.get("card") and not cur["lines"]:  # more centred text right after: the card's sentence
                    cur["card"]["text"] = " ".join(x for x in (cur["card"]["text"], el["text"].replace("\n", " ")) if x)
                else:
                    if not (fresh_scene and cur is not None and not cur["lines"] and not cur["sung"]):
                        cur = start("", ln, sc)  # (right under a scene heading it is that scene's first beat: the heading alone is no picture)
                    cur["picture"] = ""
                    cur["card"] = {"title": title, "text": more.replace("\n", " ")}
                fresh_scene = False
            elif t == "break" and "direction" in el and fresh_scene and cur is not None and not (cur["lines"] or cur["sung"] or cur.get("card")):
                # a Pic note right under a scene heading directs the heading's own picture: cutting there would leave a picture of the heading alone
                if el["direction"] and not cur.get("direction"):  # (one already written above the heading came first, and stays)
                    cur["direction"] = el["direction"]
                if ln is not None and "at" in cur:
                    cur["at"] = min(cur["at"], ln)  # (one written above the heading, under its section, is the beat's own text too)
            elif t == "break":
                cur = None
                fresh_scene = False
                if "direction" in el:
                    carry["direction"] = el["direction"] if carry.get("direction") is None else carry["direction"]
                    if ln is not None and carry["held_at"] is None:
                        carry["held_at"] = ln  # the note is the first line of the picture it starts, so it is in that beat's own text
            elif t == "transition":
                held.append(el["text"])
                if ln is not None and carry["held_at"] is None:
                    carry["held_at"] = ln
                cur = None
    for b in out:
        if b["notes"] and not b.get("card"):  # (a card has no picture to carry the note: the sheet writes it in the empty cell, see `Plan.sheet`)
            b["picture"] = f"{b['picture']} Delivery: {'; '.join(b['notes'])}."
    return out


def _piece(lines: list[str], start: int, stop: int) -> str:
    text = "\n".join(lines[start:stop]).strip("\n")
    return text + "\n" if text else ""


# --- characters and places ----------------------------------------------------------------------------------------------------------


_NAMEWORD = r"""(?:[A-Z][A-Z0-9'’.\-]*|"[^"]+"|“[^”]+”)"""
_AGE_WORDS = r"(?:early |mid-?|late )?\d{1,3}s?"
_INTRO = re.compile(rf"({_NAMEWORD}(?:\s+{_NAMEWORD})*)\s*(?:\(({_AGE_WORDS})\)|,\s*({_AGE_WORDS})(?=\s*[,.]))")  # `CAPTAIN VALERIE "THE VULTURE" VANE (40s)` or `CHET, 20s, clutches a logbook`
def age_state(age) -> str:
    """`young`, `mid` or `old` from an age the screenplay gives (`20s`, `40`, `mid-30s`), which picks the actor's picture of that age for the master;
    empty when there is no number to go by (up to 29 young, up to 54 mid, older old)."""
    found = re.search(r"\d{1,3}", str(age or ""))
    if not found:
        return ""
    years = int(found.group())
    return "young" if years < 30 else "mid" if years < 55 else "old"


_SHOWS_NOTE = re.compile(r"\bShows:\s*Plain card\b", re.I)  # `[[Beat 06. Shows: Plain card.]]`: a card with no words has nothing to centre, so a note says it
_HOLD_NOTE = re.compile(r"\bHold:\s*(\d+(?:\.\d+)?)\s*s\b")
_TRANSITION_NOTE = re.compile(r"\bTransition:\s*(\d+(?:\.\d+)?)\s*s\b")  # `[[Transition: 1.2s.]]`: how long the transition into the beat lasts
TRANSITION_SECONDS = (0.1, 5.0)  # the least and the most the beat's field takes
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_FEMALE = re.compile(r"\b(?:she|herself|woman|girl|lady|madam)\b", re.I)  # who a sentence is about, not whom it is done to: `frowns at her` says nothing of the one who frowns
_MALE = re.compile(r"\b(?:he|himself|man|boy|gentleman|lad)\b", re.I)
_FEMALE_POSSESSIVE = re.compile(r"\b(?:her|hers)\b", re.I)
_MALE_POSSESSIVE = re.compile(r"\b(?:his|him)\b", re.I)
_PRONOUN_FIRST = re.compile(r"^(?:she|he|her|his|their|they)\b", re.I)
_ARTICLES = {"A", "AN", "THE", "AND", "OR", "IN", "ON", "AT", "WITH"}


def _name_words(name: str) -> set[str]:
    return {w for w in re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split() if w}


def _introduction(text: str, cue: str, others_cues: "list[str] | None" = None, exact: bool = False) -> "dict | None":
    """How an action paragraph introduces the character who speaks as `cue`: `NAME (age), what they are and wear.` Their name as written, the age, the
    sentence that introduces them and the sentences after it that go on about them (those that begin with she, he, her, his or their).
    A name that holds the cue's words and more (`CAPTAIN VALERIE VANE` for VALERIE) is theirs only when no other speaker's cue fits it better: `YOUNG
    EDWARD (10)` is Young Edward's, not Edward's. With `exact`, only a name of the cue's words and no others will do."""
    others_cues = others_cues or []
    want = _name_words(cue)
    want_lower = {w.lower() for w in want}
    closer = [words for c in others_cues if c != cue and want < (words := _name_words(c))]  # speakers whose names hold this one's and more
    for m in _INTRO.finditer(text):
        words = m.group(1).split()
        while words and words[0] in _ARTICLES:
            words = words[1:]
        plain = _name_words(" ".join(words))
        if not want or not want <= plain or (exact and want != plain) or any(other <= plain for other in closer):
            continue
        sentences = _SENTENCES.split(text)
        at = next((i for i, snt in enumerate(sentences) if m.group(0) in snt), 0)
        others = [w for c in others_cues if c != cue for w in re.sub(r"[^A-Za-z ]", " ", c).split() if w.lower() not in want_lower]
        if others and re.search(r"\b(?:" + "|".join(map(re.escape, others)) + r")\b", text, re.I):  # a paragraph that also names someone else: only the sentences that go on about this one
            taken = [sentences[at]]
            for nxt in sentences[at + 1 :]:
                if not _PRONOUN_FIRST.match(nxt):
                    break
                taken.append(nxt)
        else:  # a paragraph about this one alone: all of it from where they come in
            taken = sentences[at:]
        said = " ".join(taken)
        she, he = len(_FEMALE.findall(said)), len(_MALE.findall(said))
        if not she and not he:
            she, he = len(_FEMALE_POSSESSIVE.findall(said)), len(_MALE_POSSESSIVE.findall(said))
        return {"name": " ".join(words), "age": m.group(2) or m.group(3), "sex": "female" if she > he else "male" if he > she else "", "description": said}
    return None


def _nice(name: str) -> str:
    """`CAPTAIN VALERIE "THE VULTURE" VANE` -> `Captain Valerie "The Vulture" Vane`; `BARNACLE'S` -> `Barnacle's`."""
    return re.sub(r"[A-Za-z][A-Za-z']*", lambda m: m.group(0).capitalize(), name)


def characters(elements: list[dict], names: dict[str, str]) -> list[dict]:
    """A character for each speaker: the cue as written, the one-word handle the speech lines use, and what the screenplay says of them where it
    introduces them (`CHET (20s), a young, terrified cabin boy`): name, age, sex (only when the pronouns or a word like boy or woman say it) and the
    sentences that describe them, as written. A speaker the screenplay never introduces still gets a character, with only the name."""
    actions = [e["text"] for e in elements if e["t"] == "action"]
    out = []
    for cue, handle in sorted(names.items(), key=lambda kv: kv[1]):
        found = next((i for exact in (True, False) for i in (_introduction(a, cue, list(names), exact) for a in actions) if i), None)  # their own name first
        out.append({"cue": cue, "handle": handle, **(found or {"name": _nice(cue), "age": "", "sex": "", "description": ""})})
    for c in out:
        c["name"] = _nice(c["name"])
    return out


VOICE_ONLY = re.compile(r"narrat|announcer|^voice$", re.I)
"""A speaker with no body in the picture: a narrator, an announcer, a bare VOICE."""


def cast_of(beat: dict, characters: list[dict]) -> list[str]:
    """The handles of the characters in a beat's picture: those who speak in it, in the order they first speak, then those its action names (by name or
    cue, whole words), in the order they come. A narrator or announcer is a voice, not someone in frame, so is never in the cast."""
    if beat.get("card"):
        return []  # a plain card shows words, not people: whoever reads over it is not in frame
    seen: list[str] = []
    spoke = [str(ln.get("speaker") or "").lower() for ln in beat.get("lines") or []]
    text = str(beat.get("picture") or "")
    named: list[tuple[int, str]] = []
    for c in characters:
        handle = str(c["handle"]).lower()
        if VOICE_ONLY.search(str(c.get("cue") or c.get("name") or handle)):
            continue
        if handle in spoke:
            continue
        hits = [m.start() for word in {c.get("name"), c.get("cue"), handle} if word for m in re.finditer(rf"\b{re.escape(str(word))}\b", text, re.I)]
        if hits:
            named.append((min(hits), handle))
    for handle in spoke:
        if handle and handle not in seen and any(str(c["handle"]).lower() == handle and not VOICE_ONLY.search(str(c.get("cue") or c.get("name") or handle)) for c in characters):
            seen.append(handle)
    return seen + [h for _i, h in sorted(named)]


_TIME_WORDS = re.compile(r"\b(?:day|night|dawn|dusk|evening|morning|afternoon|sunset|sunrise|twilight|noon|midnight|continuous|later|same|moments?|minutes|hours|days)\b", re.I)
_HEADING_KIND = re.compile(rf"^({HEADING_START}\.?)\s+", re.I)
_SCENE_NO = re.compile(r"\s*#[^#]+#\s*$")


def place_of(heading: str) -> "dict | None":
    """`INT. CAPTAIN'S CABIN - NIGHT #2#` -> the place (`Captain's Cabin`), whether it is inside or outside, and the time written after it (`Night`).
    The same place under another time of day is the same place."""
    h = _SCENE_NO.sub("", heading or "").strip().lstrip(".").strip()
    if not h:
        return None
    kind = ""
    m = _HEADING_KIND.match(h)
    if m:
        k = m.group(1).upper().replace(".", "")
        kind = "interior" if k == "INT" else "exterior" if k in ("EXT", "EST") else "both"
        h = h[m.end() :]
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", h) if p.strip()]
    time = ""
    if len(parts) > 1 and _TIME_WORDS.search(parts[-1]):
        time = parts.pop().capitalize()
    name = _nice(" - ".join(parts).replace("’", "'"))
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")
    return {"slug": slug, "name": name, "kind": kind, "time": time} if slug else None


INSIDE_OUTSIDE = ("interior", "exterior", "both")
_KIND_PREFIX = {"interior": "INT.", "exterior": "EXT.", "both": "INT./EXT."}
_KIND_WORDS = {"interior": "Interior", "exterior": "Exterior", "both": "Interior and exterior"}
_QUIET_TIME = re.compile(r"later|continuous|same|moments", re.I)  # a time that says when in the story, not what the light is


def kind_prefix(kind: object) -> str:
    """The other way: `interior` -> `INT.`, `exterior` -> `EXT.`, `both` -> `INT./EXT.`; anything else (not said) -> nothing."""
    return _KIND_PREFIX.get(str(kind or "").strip().lower(), "")


def kind_of_places(kinds: list[str]) -> str:
    """The one value a place's headings add up to: interior or exterior if they all agree, `both` if they differ or say so, nothing if none says."""
    return kinds[0] if len(kinds) == 1 and kinds[0] in INSIDE_OUTSIDE else "both" if kinds else ""


def heading_words(heading: str) -> str:
    """`INT. CAPTAIN'S CABIN - NIGHT #2#` -> `Interior: Captain's Cabin, night`: the heading in words, for the text a picture is made from (an image
    model reads words, not screenplay shorthand). A time that only says when in the story (continuous, later) is left out; a heading with no INT. or
    EXT. is the place and its time alone. Not a place at all -> the text as it was."""
    p = place_of(heading)
    if not p:
        return str(heading or "")
    said = p["name"] + (f", {p['time'].lower()}" if p["time"] and not _QUIET_TIME.search(p["time"]) else "")
    return f"{_KIND_WORDS[p['kind']]}: {said}" if p["kind"] in _KIND_WORDS else said


def _without_heading(picture: str, heading: str) -> str:
    """A beat's picture without the place heading its first picture starts with, whether that was kept as written or put in words."""
    if heading and heading in picture:
        return picture.replace(heading, "", 1)
    words = heading_words(heading) if heading else ""
    return picture.replace(words, "", 1) if words else picture


def places_of(scenes: list[Scene]) -> dict[str, dict]:
    """The places a screenplay's scene headings name, once each, with whether each is inside or outside and the times of day it is seen at."""
    out: dict[str, dict] = {}
    for sc in scenes:
        headings = [sc.heading] + [e["text"] for e in sc.elements if e["t"] == "scene" and e["text"] != sc.heading]
        for h in headings:
            p = place_of(h)
            if not p:
                continue
            rec = out.setdefault(p["slug"], {"name": p["name"], "kinds": [], "times": []})
            if p["kind"] and p["kind"] not in rec["kinds"]:
                rec["kinds"].append(p["kind"])
            if p["time"] and not _QUIET_TIME.search(p["time"]) and p["time"] not in rec["times"]:
                rec["times"].append(p["time"])
    return out


# --- sounds ---------------------------------------------------------------------------------------------------------------------------

_SOUND_NOTE = re.compile(r"^Sound:\s*(.+)$", re.S | re.I)  # `[[Sound: a pot lid clanks at 1.5s.]]`
_SOUND_OF = re.compile(r"\bsounds? of ([^.,;!?]+)", re.I)  # `The sound of wood splintering echoes from deep below.`
_A_SOUND = re.compile(r"\b(?:an?|the) ((?:[A-Za-z-]+ ){0,2}[A-Za-z-]+) sound\b")  # `a splashing sound nearby`
_SINGING = re.compile(r"\b(?:melody|song|tune|hum|humming|sing|sings|singing|chant|lullaby)\b", re.I)
_WEATHER = re.compile(r"\b(?:rain|rains|thunder\w*|storm\w*|waves?|wind|surf|lapping|crickets|cicadas|rustl\w+)(?![-\w])", re.I)  # not `rain-soaked`


def _sentences(text: str) -> list[str]:
    return [x for x in _SENTENCES.split(text) if x.strip()]


def _short(text: str, words: int = 4) -> str:
    return " ".join(re.sub(r"[^A-Za-z' -]", "", text).split()[:words]).strip().capitalize()


def cue_sounds(beat: dict) -> list[dict]:
    """The Sound notes among the words of a beat's lines (`The hammer strikes [[Sound: clang]] the wheel.`), as placeholders for a Sound each, with
    the line (1, 2… in the beat) and the word they belong to."""
    return [
        {"kind": "effect", "title": _short(cue["sound"], 3), "prompt": cue["sound"], "line": i, "word": cue["word"]}
        for i, ln in enumerate(beat.get("lines") or [], 1)
        for cue in ln.get("cues") or []
        if cue.get("sound")
    ]


CAMERA_CUES = ("punch", "shake", "nudge")


def camera_cue(words: str) -> dict:
    """A Camera note's words as the cue's camera: `punch` or `punch 1.1` ({"kind": "punch", "amount": 1.1}), `shake 2`, `nudge 0.7,0.4` ({"kind":
    "nudge", "x": 0.7, "y": 0.4}). Any other words are kept as the kind, for the export to write back."""
    kind, _, rest = " ".join(str(words or "").split()).partition(" ")
    out: dict = {"kind": kind.lower()}
    numbers = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", rest)]
    if out["kind"] == "nudge" and len(numbers) >= 2:
        out["x"], out["y"] = numbers[0], numbers[1]
    elif out["kind"] in CAMERA_CUES and numbers:
        out["amount"] = numbers[0]
    elif rest:
        out["said"] = rest
    return out


def camera_words(camera: dict) -> str:
    """A cue's camera as its note writes it: the reverse of `camera_cue`."""
    kind = str((camera or {}).get("kind") or "")
    if "x" in camera and "y" in camera:
        return f"{kind} {float(camera['x']):g},{float(camera['y']):g}"
    if camera.get("amount") is not None:
        return f"{kind} {float(camera['amount']):g}"
    return f"{kind} {camera['said']}".strip() if camera.get("said") else kind


def beat_cues(beat: dict, story: str, number: str, numbers: dict[int, str]) -> list[dict]:
    """A beat's `cues`: each note among its lines' words as {line: the speech line's slug, word: words spoken before it, sound: the Sound's slug,
    camera: {kind, …}, pic: the slug of the beat it starts}. `numbers` gives each overlay beat (by id) its number."""
    sounds = beat.get("sounds") or []
    out = []
    for i, ln in enumerate(beat.get("lines") or [], 1):
        for cue in ln.get("cues") or []:
            entry: dict = {"line": f"{story}-line-{number}-{i}", "word": cue["word"]}
            if cue.get("sound"):
                k = next((k for k, c in enumerate(sounds, 1) if c.get("line") == i and c.get("word") == cue["word"] and c.get("prompt") == cue["sound"]), None)
                if k:
                    entry["sound"] = f"{story}-sound-{number}-{k}"
            if cue.get("camera"):
                entry["camera"] = camera_cue(cue["camera"])
            if cue.get("nudge") and (seconds := float(_CUE_NUDGE.match(cue["nudge"]).group(1))):
                entry["nudge"] = seconds  # the sound and the camera move, that much later (or earlier) than the word puts them (v216)
            if "pic" in cue:
                overlay = next((o for o in beat.get("overlays") or [] if o["starts_during"] == {"line": i, "word": cue["word"]}), None)
                if overlay is not None and id(overlay) in numbers:
                    entry["pic"] = f"{story}-beat-{numbers[id(overlay)]}"
            out.append(entry)
    return out


def own_sounds(beat: dict, story: str, number: str) -> list[dict]:
    """A beat's `sounds`: the sounds its own words call for, placed from its start; a Sound note among a line's words is a cue instead (`beat_cues`)."""
    return [{"sound": f"{story}-sound-{number}-{i}", "at": c.get("at", 0)} for i, c in enumerate(beat.get("sounds") or [], 1) if "line" not in c]


def sound_cues(beat: dict) -> list[dict]:
    """The sounds a beat's own words call for, as placeholders for a Sound each: sung words (`~` lyrics) as music; the writer's `[[Sound: …]]` note,
    else `the sound of X` and `a X sound`, as effects. Each keeps the sentence it came from as its prompt. A word in capitals is not a sound: a
    screenplay writes camera words (TILT UP, FREEZE FRAME, CLOSE ON), names (BAKER'S WIFE) and titles that way too, and a feature made hundreds of
    drafts nobody wanted from them. Nothing here is made or paid for: a Sound is a draft until someone uploads a recording or asks for one to be generated."""
    cues: list[dict] = []
    picture = (beat.get("picture") or "").split(" Delivery:")[0]
    here = beat.get("place", "")
    if here:
        picture = _without_heading(picture, here)
    picture = re.sub(r"^[\s.]+", "", picture)
    sentences = _sentences(picture)
    if beat.get("sung"):
        about = next((x for x in sentences if _SINGING.search(x)), "")
        cues.append({"kind": "music", "title": "Sung: " + _short(beat["sung"][0]), "prompt": "Sung, as written: " + " / ".join(beat["sung"]) + (f". {about}" if about else "")})
    seen: set[str] = set()
    on_words = cue_sounds(beat)  # a Sound note among a line's words is that word's (v211): it comes after the beat's own sounds
    for found in _NOTE.finditer(beat.get("fountain") or ""):  # a note that says `Sound: …` is the writer's own cue: the clearest there is
        if not found.group(0).endswith("]]") or _cue_note(found) is not None:
            continue
        note = found.group(0)[2:-2]
        m = _SOUND_NOTE.match(note.strip())
        if not m:
            continue
        said = m.group(1).strip().rstrip(".")
        at = re.search(r"\s+at\s+(\d+(?:\.\d+)?)\s*s$", said)
        if at:
            said = said[: at.start()].rstrip(". ")
        if said and said.lower() not in seen:
            seen.add(said.lower())
            cues.append({"kind": "effect", "title": _short(said, 3), "prompt": said, "at": float(at.group(1)) if at else 0.0})
    if seen or on_words:  # the writer named this beat's sounds: what the words might suggest is not added to them
        return cues + on_words
    for sentence in sentences:
        found = []
        m = _SOUND_OF.search(sentence)
        if m:
            found.append(_short(m.group(1), 2))
        m = _A_SOUND.search(sentence)
        if m and m.group(1).lower() not in ("the", "a", "an"):
            found.append(_short(m.group(1) + " sound", 3))
        for title in found:
            if title and title.lower() not in seen:
                seen.add(title.lower())
                cues.append({"kind": "effect", "title": title, "prompt": sentence.strip()})
    return cues + on_words


def ambience_of(beats: list[dict], name: str) -> "dict | None":
    """The bed under a place: what its beats' action says of the weather and water (rain, thunder, waves, wind), as one placeholder for an ambience Sound."""
    said: list[str] = []
    for b in beats:
        picture = re.sub(r"^[\s.]+", "", _without_heading((b.get("picture") or "").split(" Delivery:")[0], b.get("place", "")) if b.get("place") else (b.get("picture") or ""))
        said += [x for x in _sentences(picture) if _WEATHER.search(x) and x not in said]
    if not said:
        return None
    return {"kind": "ambience", "title": f"{name} ambience", "prompt": f"Ambience for {name}: " + " ".join(said[:3])}



# --- revisions -----------------------------------------------------------------------------------------------------------------------

REWORDED = 0.55  # how alike two beats' text must be for the new one to be the old one reworded rather than a new beat
_NOTE_TEXT = re.compile(r"\[\[.*?\]\]", re.S)


def _sameness(text: str) -> str:
    """A beat's piece of the Fountain as it is compared in a revision: its words, without notes, scene numbers, page breaks or spacing."""
    text = _NOTE_TEXT.sub(" ", text or "")
    text = re.sub(r"(?m)^\s*(?:===+|#{1,6}\s.*|=.*|\.[^.].*|" + HEADING_START + r"\b.*)$", " ", text, flags=re.I)  # a page break, a section, a synopsis, a scene heading: structure, not what the beat says
    text = re.sub(r"#[^#\s]+#", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def align(plan: Plan, existing: dict[str, str]) -> "dict | None":
    """Fit a revised Fountain to the beats already made from it, by what they say and not by where they stand. `existing` is each made beat's number and
    its own piece of the Fountain. A beat whose words are unchanged keeps its number (and with it its picture, recording and sounds); one reworded keeps it
    too, to be updated or flagged as a refresh does; one that is new is numbered after the beat before it (`1002a`), so nothing after it is renumbered; a beat
    gone from the text is simply not in the plan, so a refresh trashes it or keeps it flagged. Returns what it found, or None when the plan holds no
    pieces to compare (not read with line numbers) or nothing was made yet."""
    if not existing or not plan.chapters or any(not b.get("fountain") for c in plan.chapters for b in c.beats):
        return None
    found = {"same": 0, "reworded": 0, "new": [], "removed": []}
    for chapter in plan.chapters:
        mine = [n for n in existing if re.fullmatch(r"\d+[a-z]*", n) and (plan.single or int(re.match(r"\d+", n).group()) // 1000 == chapter.number)]
        old = sorted(mine, key=numbering.order_key)
        old_text = [_sameness(existing[n]) for n in old]
        new_text = [_sameness(b["fountain"]) for b in chapter.beats]
        taken: dict[int, str] = {}  # position of a new beat (0-based) -> the number it keeps
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_text, new_text, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    taken[j1 + k] = old[i1 + k]
                found["same"] += i2 - i1
            elif tag == "replace":
                at = i1
                for j in range(j1, j2):  # in order: each new beat takes the nearest old one that is alike enough
                    best = max(range(at, i2), key=lambda i: difflib.SequenceMatcher(None, old_text[i], new_text[j]).ratio(), default=None)
                    if best is not None and difflib.SequenceMatcher(None, old_text[best], new_text[j]).ratio() >= REWORDED:
                        taken[j] = old[best]
                        found["removed"] += old[at:best]
                        at = best + 1
                        found["reworded"] += 1
                found["removed"] += old[at:i2]
            elif tag == "delete":
                found["removed"] += old[i1:i2]
        used = set(old) | set(taken.values())
        previous = f"{chapter.number * 1000}" if not plan.single else "00"
        for j in range(len(chapter.beats)):
            if j in taken:
                number = taken[j]
            else:
                number = numbering.after(previous)
                while number in used:
                    number = numbering.after(number)
                used.add(number)
                found["new"].append(number)
            plan.renumber[(chapter.number, j + 1)] = number
            previous = number
    return found

_KEEP_ALONE = re.compile(r"^(?:THE END\.?|END\.?|(?:SUPER|TITLE|CARD|INSERT|CHYRON|TITLE CARD|INTERCUT)\b.*|.*\bFADE\b.*|.*\bCUT\b.*|.*\bDISSOLVE\b.*)$")
"""Capitals standing alone that say what they are: a card, a title over the picture, an editing word. `INTERCUT WITH:` and `INTERCUT HALLWAY /
BEDROOM` end in no TO:, so the Fountain format reads them as action (they say how two scenes alternate, not how one picture changes into the
next): their words stay in the picture, with nothing to check."""
_HEADING_LIKE = re.compile(r"^[A-Z0-9][A-Z0-9 .'’,()/&\-]*\s-\s[A-Z][A-Z0-9 .'’,()/\-]*?(?:\s+#[\w.-]+#)?$")
_KIND_WORD = r"(?:INT(?:ERIOR)?|EXT(?:ERIOR)?|EST(?:ABLISHING)?)"
_MISWRITTEN_START = re.compile(rf"^((?:{_KIND_WORD}|[IE])\.?\s*(?:[/&+\-–,.]|AND)\s*(?:{_KIND_WORD}|[IE])\.?|{_KIND_WORD}\.?)[\s.:,\-–]+(?=\S)(?!(?:{_KIND_WORD}|[IE])(?![A-Z]))", re.I)
"""A heading started in a way the format does not know (`EXTERIOR`, `INT-EXT`, `EXT / INT.`): the start to put in its place is said from it."""
MAX_LINT = 12


def _heading_advice(first: str) -> str:
    """What a capitals line that names a place and a time should start with to be a scene: its own start written the way the format knows it
    (`EXTERIOR SWAMP SHACK - DAY` -> `EXT. SWAMP SHACK - DAY`, `INT-EXT …` -> `INT./EXT. …`), or EXT. put in front when it has no start at all.
    Never a second start in front of one that is there (`EXT. EXT/INT. …`)."""
    m = _MISWRITTEN_START.match(first)
    if not m and re.match(r"(?:INT|EXT|EST|[IE][./])", first, re.I):
        return "write its start as INT., EXT. or INT./EXT. (one of them, in place of the one written)"
    if not m:
        return f"write `EXT. {first}` (or `INT. …`)"
    start, rest = m.group(1).upper(), first[m.end() :]
    inside = bool(re.search(r"INT|(?<![A-Z])I(?![A-Z])", start))
    outside = bool(re.search(r"EXT|EST|(?<![A-Z])E(?![A-Z])", start))
    kind = "INT./EXT." if inside and outside else "INT." if inside else "EST." if start.startswith("EST") else "EXT."
    return f"write `{kind} {rest}`"


def _blank_out(match: "re.Match[str]") -> str:
    return "\n" * match.group(0).count("\n")  # the writer's notes and boneyards removed, the line numbers kept


def lint(text: str, limit: "int | None" = MAX_LINT) -> list[str]:
    """What in a Fountain the import will read differently from what the writer meant, in words that say the line and how to fix it:
    a capitals line standing alone or ending in a full stop, which is read as a speaker (`CRUNCH.`), and a line that is a place and a time in capitals
    but does not start with INT. or EXT., which is not a scene. It reads the text only: nothing is changed. The split report lists the first
    `limit` and says how many more; the Fountain check (`limit=None`) lists them all."""
    plain = _NOTE.sub(_blank_out, _cues_marked(_BONEYARD.sub(_blank_out, _nudge_marked(_readable(_normal(text))))))
    found: list[str] = []
    for index, (start, block) in enumerate(_blocks_at(plain)):
        first = block[0].strip()
        if index == 0 and _ANY_KEY.match(first) and not first.isupper():
            continue  # the title page
        if first.startswith(("!", "#", "=", "~", ">", ".", "@", "[", "(", "/")) or _is_scene(first) or _is_transition(first):
            continue
        letters = re.sub(r"[^A-Za-z]", "", first)
        if not letters or first != first.upper():
            continue
        name = _cue_name(first)
        row = start + 1
        if (_HEADING_LIKE.match(first) and _TIME_WORDS.search(first)) or (len(block) == 1 and _MISWRITTEN_START.match(first)):
            found.append(f"line {row}: `{first}` looks like a scene heading but does not start with INT. or EXT., so it is not a scene: {_heading_advice(first)}, or start it with a dot (`.{first}`) to keep it as written")
        elif _KEEP_ALONE.match(first):
            continue
        elif len(block) == 1:
            found.append(f"line {row}: `{first}` stands alone in capitals, so it is read as action, not as a speaker (a speaker's name needs their words on the line under it): if it is a sound, write it as a note (`[[Sound: {first.rstrip('.!?').lower()}]]`); if it is action, start it with ! (`!{first}`) to say so")
        elif name.endswith((".", "!", "?")) or len(name.split()) > 4:
            found.append(f"line {row}: `{first}` is in capitals above text, so it is read as a speaker and the text after it as spoken: if it is action, start it with ! (`!{first}`) or write it in ordinary case")
    if limit is not None and len(found) > limit:
        found = found[:limit] + [f"and {len(found) - limit} more like these"]
    return found


def cut(elements: list[dict], chapter_pages: float = CHAPTER_PAGES, max_pages: float = MAX_CHAPTER_PAGES, text: "str | None" = None, speakers: "set[str] | None" = None) -> Plan:
    """The chapters, beats and lines of a screenplay. Given the `text` it was read from (and the elements read with `lines=True`), each beat and each
    speech also holds its own piece of the writer's text, as written (`fountain`), and the plan holds what comes before the first beat (`front`):
    nothing the writer wrote is dropped, it stays with the beat it was written for. `speakers` is the handles the story's records already use
    (see `handles`)."""
    positioned = text is not None and bool(elements) and "line" in elements[0]
    all_lines = _normal(text).split("\n") if positioned and text is not None else []
    if positioned:
        for i, el in enumerate(elements):
            el["end"] = elements[i + 1]["line"] if i + 1 < len(elements) else len(all_lines)
    scenes = _scenes(elements)
    warnings: list[str] = []
    if not scenes:
        return Plan([], {}, ["no scenes found: is this Fountain? A scene starts with a heading like `INT. KITCHEN - DAY`"], {}, True)
    if len(scenes) == 1 and not scenes[0].heading:
        warnings.append("no scene headings found (one looks like `INT. KITCHEN - DAY`): the whole text is treated as a single scene")
    if text is not None:
        warnings.extend(lint(text))
    raw_names = sorted({e["name"] for e in elements if e["t"] == "dialogue"})
    names = handles(raw_names, speakers)
    groups = _chapters(scenes, chapter_pages, max_pages)
    numbered = [(_LEADING_NUMBER.match(t) if t else None) for t, _g in groups]
    explicit = [int(m.group(1)) for m in numbered if m]
    use_titles = len(explicit) == len(groups) and len(set(explicit)) == len(groups) and explicit == sorted(explicit)
    chapters = []
    carry: dict = {"held": [], "held_at": None}
    for i, (title, group) in enumerate(groups, 1):
        m = numbered[i - 1]
        n = int(m.group(1)) if use_titles and m else i
        shown = (m.group(2).strip() or title) if use_titles and m else title
        chapters.append(Chapter(n, shown or f"Chapter {n}", group, _beats_for(group, names, carry)))
    single = len(chapters) == 1
    for ch in chapters:
        pg = sum(s.pages() for s in ch.scenes)
        if len(ch.beats) > 999:
            warnings.append(f"chapter {ch.number} has {len(ch.beats)} beats: more than 999 cannot be numbered; add a section line to split it")
        if pg > max_pages and len(ch.scenes) == 1:
            warnings.append(f"chapter {ch.number} is one scene of about {pg:.0f} pages; it cannot be split between scenes")
        elif pg > max_pages:
            warnings.append(f"chapter {ch.number} is about {pg:.0f} pages: add a `#` section line inside it to split it")
        if not ch.beats:
            warnings.append(f"chapter {ch.number} ({ch.title}) has no beats")
    short = {raw: h for raw, h in names.items() if _title(raw) != h}
    if short:
        warnings.append("speaker names shortened to one word: " + ", ".join(f"{_title(r)} → {h}" for r, h in sorted(short.items())))
    source = {
        "scenes": len(scenes),
        "dialogue": sum(1 for e in elements if e["t"] == "dialogue"),
        "dialogue_words": sum(_words(e["text"]) for e in elements if e["t"] == "dialogue"),
        "actions": [e["text"] for e in elements if e["t"] == "action"],
    }
    front = ""
    if positioned:
        flat = [b for ch in chapters for b in ch.beats if "at" in b]
        for i, b in enumerate(flat):
            stop = flat[i + 1]["at"] if i + 1 < len(flat) else len(all_lines)
            b["fountain"] = _piece(all_lines, b["at"], stop)
            for ln in b["lines"]:
                if ln.get("at") is not None:
                    ln["fountain"] = _piece(all_lines, ln["at"], ln.get("end") or stop)
            if not b.get("card") and _SHOWS_NOTE.search(" ".join(re.findall(r"\[\[(.*?)\]\]", b["fountain"], re.S))):
                b["card"] = {"title": "", "text": ""}  # a blank hold: a plain card with no words, said in a note
        front = _piece(all_lines, 0, flat[0]["at"]) if flat else ""
    plan = Plan(chapters, {r: h for r, h in names.items()}, warnings, source, single, front)
    if carry["held"]:  # a transition with no beat after it is how the film ends
        plan.end_transition_text = carry["held"][-1]
        plan.end_transition = "fade" if transition_kind(plan.end_transition_text) == "fade" else ""
    plan.characters = characters(elements, names)
    plan.places = places_of(scenes)
    by_place: dict[str, list[dict]] = {}
    for ch in chapters:
        for b in ch.beats:
            b["sounds"] = sound_cues(b)
            if place_of(b.get("place", "")):
                by_place.setdefault(place_of(b["place"])["slug"], []).append(b)
    for key, beats_here in by_place.items():
        bed = ambience_of(beats_here, plan.places[key]["name"])
        if bed:
            plan.ambience[key] = bed
    return plan


def check(plan: Plan) -> list[str]:
    """Read the sheet back the way the importer will and say what did not survive: every spoken line, every word of it, and every action
    paragraph must be in the beats. Empty means the cut lost nothing."""
    kind, rows = beat_import.parse_any(plan.sheet())
    problems: list[str] = []
    if not rows:
        return ["the sheet reads back as no beats"] if plan.chapters else []
    lines = [ln for r in rows for ln in r["lines"]]
    if len(lines) != plan.source["dialogue"]:
        problems.append(f"{plan.source['dialogue']} speeches in the screenplay but {len(lines)} lines read back from the sheet")
    got = sum(_words(ln["text"]) for ln in lines)
    if got != plan.source["dialogue_words"]:
        problems.append(f"{plan.source['dialogue_words']} spoken words in the screenplay but {got} read back from the sheet")
    pictures = " ".join(re.sub(r"\s+", " ", r["picture"]) for r in rows)
    lost = [a for a in plan.source["actions"] if re.sub(r"\s+", " ", a.replace("|", "/")).strip() not in pictures]
    if lost:
        problems.append(f"{len(lost)} action paragraph(s) did not reach a picture, the first: “{lost[0][:60]}”")
    return problems


# --- the writer's own text, a chapter at a time ------------------------------------------------------------------------------------------


def _blank_comments(text: str) -> str:
    """The text with each note and boneyard replaced by as many line breaks as it held, so every line keeps its number."""
    keep = lambda m: "\n" * m.group().count("\n")  # noqa: E731
    return _notes_out(_cues_marked(_BONEYARD.sub(keep, _nudge_marked(text))), keep)  # (a nudge note stays a line of its own: a speech with one is still one speech)


def chapter_texts(text: str, plan: Plan) -> "dict[int, str] | None":
    """Each chapter's own slice of the Fountain text, as the writer wrote it (notes, boneyard and layout kept): from the section or scene heading that
    starts the chapter to the one that starts the next. The title page is not in any slice. Chapter numbers are the keys.
    None when the text cannot be matched to the chapters the plan found, scene heading for scene heading: better no slice than a wrong one."""
    norm = _normal(text)
    scenes = _scenes(parse(_blank_comments(norm), lines=True))
    if [s.heading for s in scenes] != [s.heading for ch in plan.chapters for s in ch.scenes]:
        return None
    lines = norm.split("\n")
    starts: list[int] = []
    at = 0
    for ch in plan.chapters:
        starts.append(scenes[at].start)
        at += len(ch.scenes)
    ends = [*starts[1:], len(lines)]
    return {ch.number: "\n".join(lines[a:b]).strip("\n") + "\n" for ch, a, b in zip(plan.chapters, starts, ends, strict=True)}


_TITLE_ENTRY = re.compile(r"^([A-Za-z][A-Za-z0-9 ]*?)\s*:\s*(.*?)\s*$")


def title_page(text: str) -> dict[str, str]:
    """The title page's entries (`Title: THE DEVIL'S SHOALS`), keys in lower case with underscores (`draft_date`), in the order written. An entry
    with its value on the lines below (`Contact:` then indented lines) holds them joined by line breaks. Empty when the text has no title page."""
    lines = _normal(text).split("\n")
    block: list[str] = []
    for ln in lines:
        if not ln.strip():
            break
        block.append(ln)
    if not block or not _TITLE_KEY.match(block[0]) or not all(_ANY_KEY.match(ln) or ln.startswith((" ", "\t")) for ln in block):
        return {}
    entries: dict[str, str] = {}
    key = ""
    for ln in block:
        m = None if ln.startswith((" ", "\t")) else _TITLE_ENTRY.match(ln)
        if m:
            key = re.sub(r"\s+", "_", m.group(1).strip().lower())
            entries[key] = m.group(2)
        elif key:
            entries[key] = (entries[key] + "\n" + ln.strip()).strip()
    return entries


SETTING_KEYS = ("title_card", "end_card", "card_colours", "transition")
"""Title page entries that are settings of the story, not credits: the complete script writes them (`script.fountain_complete`) and `story_settings` reads them."""
_CARD_ENTRY = re.compile(r"^(?P<title>.+?)(?:\s+—\s+(?P<subtitle>.+?))?(?:\s*\((?P<seconds>\d+(?:\.\d+)?)s\))?$")  # `TIDE — A Storyworld film (4s)`
_CARD_COLOURS = re.compile(r"^(?P<card>#[0-9a-fA-F]{6})?,?\s*(?:text\s+(?P<text>#[0-9a-fA-F]{6}))?$")  # `#2b1b12, text #ffeedd`
_TRANSITION_ENTRY = re.compile(r"^(?P<kind>cut|fade|dissolve)(?:\s*\((?P<seconds>\d+(?:\.\d+)?)s\))?$", re.I)  # `dissolve (0.8s)`
MAX_CARD_SECONDS = 30.0


def story_settings(meta: dict[str, str]) -> dict:
    """The story fields a title page's own entries say (see `title_page`): `Title card:` and `End card:` (the words, a second line after a dash, a
    length), `Card colours:` and `Transition:` (between beats, with its length). Only what is written and valid; anything else is left out."""
    said = lambda key: " ".join(str(meta.get(key) or "").split())  # noqa: E731
    out: dict = {}
    for key, card in (("title_card", "intro"), ("end_card", "outro")):
        if m := _CARD_ENTRY.match(said(key)):
            out[f"{card}_title"] = m["title"]
            if m["subtitle"]:
                out[f"{card}_subtitle"] = m["subtitle"]
            if m["seconds"] and 0 < float(m["seconds"]) <= MAX_CARD_SECONDS:
                out[f"{card}_seconds"] = float(m["seconds"])
    if said("card_colours") and (m := _CARD_COLOURS.match(said("card_colours"))):
        out.update({field: m[group].lower() for field, group in (("card_color", "card"), ("card_text_color", "text")) if m[group]})
    if m := _TRANSITION_ENTRY.match(said("transition")):
        out["transition"] = m["kind"].lower()
        if m["seconds"] and TRANSITION_SECONDS[0] <= float(m["seconds"]) <= TRANSITION_SECONDS[1]:
            out["transition_seconds"] = float(m["seconds"])
    return out


def mark_cards(rows: list[dict], plan: Plan) -> None:
    """Say which rows of the plan's sheet (read back by `beat_import`) are plain cards, with their words: the sheet has a picture cell and nothing for
    a card, so a card travels beside it (`row["card"]`: {title, text}) and `beat_import.import_plan` makes the beat from that."""
    cards = {number: beat["card"] for _chapter, number, beat in plan.rows() if beat.get("card")}
    for row in rows:
        if row["beat"] in cards:
            row["card"] = cards[row["beat"]]


def attach_source(imp: dict, plan: Plan, story: str) -> None:
    """Give the records an import plan is about to make (`beat_import.import_plan`) what the screenplay said that the beat sheet cannot carry: each
    beat's own text as written (`fountain`), the transition written before it and the Shot direction of its Pic note, its Info card and Changes notes,
    each line's own text (`fountain`), whether it is spoken over the line before (`simultaneous`) and its nudge. New records only; one that exists is left as it is."""
    by_number = {n: b for _c, n, b in plan.rows()}
    numbers = {id(b): n for _c, n, b in plan.rows()}
    for _slug, _title, data in imp["beats"]:
        beat = by_number.get(str(data.get("number")))
        for key in ("fountain", "transition", "transition_text", "direction"):
            if beat and beat.get(key):
                data[key] = beat[key]
        place = place_of(beat.get("place", "")) if beat else None
        if place:
            data["scene"] = f"{story}-{place['slug']}"
            if place["time"]:
                data["time_of_day"] = place["time"]  # the heading's time as written (Night, Dawn, Continuous), so the script can write it back
        held = _HOLD_NOTE.search(" ".join(re.findall(r"\[\[(.*?)\]\]", beat.get("fountain") or "", re.S))) if beat else None
        if held and not data.get("hold_seconds"):  # a note on the beat (`[[Hold: 6s.]]`) says how long its picture stays when nobody speaks
            data["hold_seconds"] = float(held.group(1))
        if beat and (seconds := transition_seconds(beat)) and not data.get("transition_seconds"):
            data["transition_seconds"] = seconds
        if beat and (placed := own_sounds(beat, story, str(data.get("number")))):
            data["sounds"] = placed
        if beat and (cues := beat_cues(beat, story, str(data.get("number")), numbers)):
            data["cues"] = cues  # the notes among its lines' words (v211)
        if beat and beat.get("starts_during"):  # a Pic note among a line's words: this picture comes in at that word, over the beat before
            host = next((n for _c, n, b in plan.rows() if any(o is beat for o in b.get("overlays") or [])), None)
            data["starts_during"] = {"line": f"{story}-line-{host}-{beat['starts_during']['line']}", "word": beat["starts_during"]["word"]}
            data["hold_seconds"] = 0  # it adds no time of its own (a Timeline draws it at 0 s); a hold set here keeps it up past the end of the speech
        if beat:
            data.update(notes_to_fill(data, beat.get("fountain") or ""))  # `[[Info card: …]]` and `[[Changes: …]]` (a card's own words come first)
    for slug, _title, data in imp["lines"]:
        m = re.search(r"-line-(.+)-(\d+)$", slug)
        beat = by_number.get(m.group(1)) if m else None
        ln = beat["lines"][int(m.group(2)) - 1] if beat and m and 0 < int(m.group(2)) <= len(beat["lines"]) else None
        if ln and ln.get("fountain"):
            data["fountain"] = ln["fountain"]
        if ln and ln.get("dual"):
            data["simultaneous"] = True
        if ln and ln.get("nudge"):
            data["nudge"] = ln["nudge"]  # `[[Nudge: -0.4]]`: earlier (or later) than where it would start


# --- how long bringing it in takes ---------------------------------------------------------------------------------------------------------

RECORDS_PER_SECOND = 2.4  # how fast an import writes, one call to Marvin a record (a feature's 1,880 records took 13.5 minutes)


def time_to_write(records: int) -> str:
    """How long writing so many records takes at the import's speed, in words: "under a minute", "about 13 minutes"."""
    minutes = records / RECORDS_PER_SECOND / 60
    return "under a minute" if minutes < 1 else f"about {round(minutes)} minute{'s' if round(minutes) != 1 else ''}"


def records_to_make(plan: Plan) -> int:
    """The records a first import of the plan writes into a story that has none, counted from the text alone: its chapters (none for a story of
    one), beats and spoken lines, a Character for each speaker, a Scene for each place a beat is in (and the ambience bed its beats ask for), a
    Sound for each sound a beat calls for, and the score's placeholder. The import counts what it writes as it goes (it fits a story that has
    records to them); into an empty story the two counts are the same."""
    rows = plan.rows()
    scenes = {p["slug"] for _c, _n, b in rows if (p := place_of(b.get("place", ""))) and p["slug"] in plan.places}
    return (
        (0 if plan.single else sum(1 for ch in plan.chapters if ch.beats))  # a chapter is made by its first beat
        + len(rows)
        + sum(len(b["lines"]) for _c, _n, b in rows)
        + len(plan.characters)
        + len(scenes)
        + sum(1 for s in scenes if plan.ambience.get(s))
        + sum(len(b.get("sounds") or []) for _c, _n, b in rows)
        + 1  # the score
    )
