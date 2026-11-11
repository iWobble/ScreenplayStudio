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

import math
import re
from dataclasses import dataclass, field

from . import beat_import, beats

LINE_SEP = "¶"
"""Between two speakers in an audio cell: the importer reads a name after it as the next speaker, whatever the words before it end in."""
LINES_PER_BEAT = 6
CHAPTER_PAGES = 12
MAX_CHAPTER_PAGES = 25
LINES_PER_PAGE = 55
PICTURE_CHARS = 420

_BONEYARD = re.compile(r"/\*.*?\*/", re.S)
_NOTE = re.compile(r"\[\[(?:(?!\]\]|\n[ \t]*\n).)*(?:\]\]|(?=\n[ \t]*\n)|\Z)", re.S)  # a note ends at its `]]`, or at a blank line: one never closed cannot swallow what follows
_SCENE = re.compile(r"^(?:INT|EXT|EST|INT\.?/EXT|INT/EXT|I/E)(?:\.|\s)", re.I)
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


def _clean(text: str) -> str:
    return _NOTE.sub("", _BONEYARD.sub("", _normal(text)))  # a boneyard and a note are the writer's, not the story's


def _blocks_at(text: str) -> list[tuple[int, list[str]]]:
    """The text's paragraphs (runs of lines between blank ones), each with the line it starts on."""
    blocks: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    start = 0
    for n, raw in enumerate(text.split("\n")):
        if not raw.strip() and not (cur and raw == "  " and _is_character(cur[0])):  # two spaces keep a gap inside a speech
            if cur:
                blocks.append((start, cur))
            cur = []
        elif raw == "  " and cur and _is_character(cur[0]):
            continue
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
        if el["t"] == "action":
            el["text"] = _plain(el["text"])
        elif el["t"] == "dialogue":
            el["text"] = _plain(el["text"])
            el["paren"] = [_plain(x) for x in el["paren"]]
    return els


_SYNOPSIS_LINE = re.compile(r"^=(?!=)")
_EMPTY_CENTRE = re.compile(r"^>\s*<$")


def _block_elements(block: list[str]) -> list[dict]:
    # A synopsis (`= text`) is the writer's note even when it sits right under a scene heading, and a centred block an AI wrote as `> <`, the text,
    # `> <` has empty markers round the words: neither belongs in a beat's picture.
    synopses = [{"t": "synopsis", "text": ln.strip()[1:].strip()} for ln in block if _SYNOPSIS_LINE.match(ln.strip()) and ln.strip()[1:].strip()]
    block = [ln for ln in block if not _SYNOPSIS_LINE.match(ln.strip()) and not _EMPTY_CENTRE.match(ln.strip())]
    return [*_block_content(block), *synopses] if block else synopses


def _block_content(block: list[str]) -> list[dict]:
    first = block[0].strip()
    if first.startswith("==="):
        return []
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
    if len(block) >= 2 and _is_character(first):
        ext = _EXTENSION.search(_CONTD.sub("", first).lstrip("@").rstrip("^").strip())
        paren, speech = [], []
        for ln in block[1:]:
            s = ln.strip()
            (paren if s.startswith("(") and s.endswith(")") else speech).append(s.strip("()") if s.startswith("(") and s.endswith(")") else s.lstrip("~").strip())  # a sung line of a speech is the words, not the mark
        if speech:
            return [{"t": "dialogue", "name": _cue_name(first), "ext": (ext.group(1) if ext else ""), "paren": paren, "text": " ".join(speech).strip(), "dual": first.rstrip().endswith("^")}]
    if all(ln.strip().startswith("~") for ln in block):  # lyrics: words that are sung, not described and not (yet) anyone's line
        return [{"t": "lyrics", "text": " ".join(ln.strip().lstrip("~").strip() for ln in block).strip()}]
    text_ = " ".join(ln.strip().lstrip("!~") for ln in block).strip()
    text_ = re.sub(r"^>\s*(.*?)\s*<$", r"\1", text_)  # centred text is action
    return [{"t": "action", "text": text_}] if text_ else []


def parse(text: str, *, lines: bool = False) -> list[dict]:
    """The screenplay's elements in order: {t: scene|action|dialogue|transition|section, ...}. A title page, page breaks and synopses are left out.
    With `lines`, each element also says the line (counting from 0) of the text it starts on."""
    blocks = _blocks_at(_blank_comments(_normal(text)) if lines else _clean(text))  # to say where each element is, a note or boneyard keeps its line breaks
    if blocks and all(_ANY_KEY.match(ln) or ln.startswith((" ", "\t")) for ln in blocks[0][1]) and _TITLE_KEY.match(blocks[0][1][0]):
        blocks = blocks[1:]  # a title page: it starts with a key Fountain knows, and every line is a key or the rest of one
    known = {_cue_name(block[0]) for _start, block in blocks if len(block) >= 2 and _is_character(block[0])}
    out: list[dict] = []
    for start, block in blocks:
        pieces = _split_cues(start, block, known)
        for n, (at, piece) in enumerate(pieces):
            for el in _plain_elements(_block_elements(piece)):
                if n == 0 and len(pieces) > 1 and el["t"] == "dialogue":
                    el["dual"] = False  # written together with no blank line, only the second can be the one that speaks over the first
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


def handles(names: list[str]) -> dict[str, str]:
    """Character cue -> the one-word handle the importer reads (a capital then lower case: Granny, Cook). A name of several words takes its last
    (`OLD COOK` -> Cook); two different names that would share one keep all their words (`MRS HALE` -> Mrshale, `DR HALE` -> Drhale)."""
    clean = lambda n: [w for w in re.sub(r"[^A-Za-z ]", " ", n).split() if w]  # noqa: E731
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
                    chosen[other] = "".join(clean(other)).capitalize()
            short = "".join(words).capitalize()
        seen.setdefault(short, name)
        chosen[name] = short
    return chosen


# --- cutting ------------------------------------------------------------------------------------------------------------------------


def _lines_of(el: dict) -> int:
    t = el["t"]
    if t == "scene":
        return 2
    if t in ("action", "lyrics"):
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
    for el in elements:
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
            scenes[-1].elements.append(el)
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

    def number(self, chapter: Chapter, i: int) -> str:
        return f"{i:02d}" if self.single else str(chapter.number * 1000 + i)

    def rows(self) -> list[tuple[Chapter | None, str, dict]]:
        out = []
        for ch in self.chapters:
            for i, b in enumerate(ch.beats, 1):
                out.append((None if self.single else ch, self.number(ch, i), b))
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
            for i, b in enumerate(ch.beats, 1):
                audio = f" {LINE_SEP} ".join(f"{ln['speaker']}: {cell(ln['text'])}" for ln in b["lines"]) or "No speech."
                if b.get("sung"):  # sung words are a cue for the sound library (a song, a hummed tune), kept with the beat as a note
                    audio += f" {LINE_SEP} Sound: sung: " + cell(" / ".join(b["sung"]))
                out.append(f"| {self.number(ch, i)} | — | {audio} | {cell(b['picture'])} |")
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
    """How a transition line asks the picture to change: `dissolve`, `fade` or `cut`, or None for one the video has no word for (WIPE TO:)."""
    return next((kind for pattern, kind in _TRANSITION_KINDS if pattern.search(text)), None)


def _beats_for(scenes: list[Scene], names: dict[str, str], carry: "dict | None" = None) -> list[dict]:
    """The beats of some scenes. `carry` is shared by all the chapters of a story: a transition written at the end of one chapter belongs to the
    first beat of the next, and only the story's very first beat has nothing before it to change from."""
    out: list[dict] = []
    carry = carry if carry is not None else {"held": [], "seen": False}
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
        if held:
            beat["transition_text"] = held[-1]
            kind = transition_kind(held[-1])
            if kind and carry["seen"]:  # the first beat has nothing before it to change from
                beat["transition"] = kind
            held.clear()
        carry["seen"] = True
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
                cur = start(el["text"], ln, sc)
                fresh_scene = True
            elif t == "action":
                # Action with no speech between it and the last action is the same picture (up to a paragraph's worth); after speech it is a new one.
                if cur is not None and not cur["lines"] and (cur["picture"] == scene.heading or len(cur["picture"]) + len(el["text"]) <= PICTURE_CHARS):
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
                cur["lines"].append({"speaker": who, "text": el["text"], "at": ln, "end": el.get("end"), "dual": bool(el.get("dual"))})
                note = ", ".join(el["paren"] + ([el["ext"]] if el["ext"] else []))
                if note:
                    cur["notes"].append(f"{who} ({note})")
                fresh_scene = False
            elif t == "lyrics":
                if cur is None:
                    cur = start(scene.heading or "Continues", ln, sc)
                cur["sung"].append(el["text"])
            elif t == "transition":
                held.append(el["text"])
                if ln is not None and carry["held_at"] is None:
                    carry["held_at"] = ln
                cur = None
    for b in out:
        if b["notes"]:
            b["picture"] = f"{b['picture']} Delivery: {'; '.join(b['notes'])}."
    return out


def _piece(lines: list[str], start: int, stop: int) -> str:
    text = "\n".join(lines[start:stop]).strip("\n")
    return text + "\n" if text else ""


# --- characters and places ----------------------------------------------------------------------------------------------------------


_NAMEWORD = r"""(?:[A-Z][A-Z0-9'’.\-]*|"[^"]+"|“[^”]+”)"""
_INTRO = re.compile(rf"({_NAMEWORD}(?:\s+{_NAMEWORD})*)\s*\(((?:early |mid-?|late )?\d{{1,3}}s?)\)")  # `CAPTAIN VALERIE "THE VULTURE" VANE (40s)`
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_FEMALE = re.compile(r"\b(?:she|herself|woman|girl|lady|madam)\b", re.I)  # who a sentence is about, not whom it is done to: `frowns at her` says nothing of the one who frowns
_MALE = re.compile(r"\b(?:he|himself|man|boy|gentleman|lad)\b", re.I)
_FEMALE_POSSESSIVE = re.compile(r"\b(?:her|hers)\b", re.I)
_MALE_POSSESSIVE = re.compile(r"\b(?:his|him)\b", re.I)
_PRONOUN_FIRST = re.compile(r"^(?:she|he|her|his|their|they)\b", re.I)
_ARTICLES = {"A", "AN", "THE", "AND", "OR", "IN", "ON", "AT", "WITH"}


def _introduction(text: str, cue: str, others_cues: "list[str] | None" = None) -> "dict | None":
    """How an action paragraph introduces the character who speaks as `cue`: `NAME (age), what they are and wear.` Their name as written, the age, the
    sentence that introduces them and the sentences after it that go on about them (those that begin with she, he, her, his or their)."""
    others_cues = others_cues or []
    want = {w for w in re.sub(r"[^A-Z0-9 ]", " ", cue.upper()).split() if w}
    want_lower = {w.lower() for w in want}
    for m in _INTRO.finditer(text):
        words = m.group(1).split()
        while words and words[0] in _ARTICLES:
            words = words[1:]
        plain = {w for w in re.sub(r"[^A-Z0-9 ]", " ", " ".join(words).upper()).split() if w}
        if not want or not want <= plain:
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
        return {"name": " ".join(words), "age": m.group(2), "sex": "female" if she > he else "male" if he > she else "", "description": said}
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
        found = next((i for i in (_introduction(a, cue, list(names)) for a in actions) if i), None)
        out.append({"cue": cue, "handle": handle, **(found or {"name": _nice(cue), "age": "", "sex": "", "description": ""})})
    for c in out:
        c["name"] = _nice(c["name"])
    return out


_TIME_WORDS = re.compile(r"\b(?:day|night|dawn|dusk|evening|morning|afternoon|sunset|sunrise|twilight|noon|midnight|continuous|later|same|moments?|minutes|hours|days)\b", re.I)
_HEADING_KIND = re.compile(r"^(INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?|EST\.?)\s+", re.I)
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
            if p["time"] and not re.search(r"later|continuous|same", p["time"], re.I) and p["time"] not in rec["times"]:
                rec["times"].append(p["time"])
    return out


# --- sounds ---------------------------------------------------------------------------------------------------------------------------

_SOUND_OF = re.compile(r"\bsounds? of ([^.,;!?]+)", re.I)  # `The sound of wood splintering echoes from deep below.`
_A_SOUND = re.compile(r"\b(?:an?|the) ((?:[A-Za-z-]+ ){0,2}[A-Za-z-]+) sound\b")  # `a splashing sound nearby`
_LOUD = re.compile(r"\b[A-Z]{4,}\b")  # `a deafening CRUNCH`
_SINGING = re.compile(r"\b(?:melody|song|tune|hum|humming|sing|sings|singing|chant|lullaby)\b", re.I)
_WEATHER = re.compile(r"\b(?:rain|rains|thunder\w*|storm\w*|waves?|wind|surf|lapping|crickets|cicadas|rustl\w+)(?![-\w])", re.I)  # not `rain-soaked`


def _sentences(text: str) -> list[str]:
    return [x for x in _SENTENCES.split(text) if x.strip()]


def _short(text: str, words: int = 4) -> str:
    return " ".join(re.sub(r"[^A-Za-z' -]", "", text).split()[:words]).strip().capitalize()


def sound_cues(beat: dict, avoid: "set[str]") -> list[dict]:
    """The sounds a beat's own words call for, as placeholders for a Sound each: sung words (`~` lyrics) as music; `the sound of X`, `a X sound` and
    a loud word in capitals (`CRUNCH`) as effects. Each keeps the sentence it came from as its prompt. Names, places and the scene heading are not sounds;
    nothing here is made or paid for: a Sound is a draft until someone uploads a recording or asks for one to be generated."""
    cues: list[dict] = []
    picture = (beat.get("picture") or "").split(" Delivery:")[0]
    here = beat.get("place", "")
    if here:
        picture = picture.replace(here, "", 1)
    picture = re.sub(r"^[\s.]+", "", picture)
    sentences = _sentences(picture)
    if beat.get("sung"):
        about = next((x for x in sentences if _SINGING.search(x)), "")
        cues.append({"kind": "music", "title": "Sung: " + _short(beat["sung"][0]), "prompt": "Sung, as written: " + " / ".join(beat["sung"]) + (f". {about}" if about else "")})
    seen: set[str] = set()
    for sentence in sentences:
        found = []
        m = _SOUND_OF.search(sentence)
        if m:
            found.append(_short(m.group(1), 2))
        m = _A_SOUND.search(sentence)
        if m and m.group(1).lower() not in ("the", "a", "an"):
            found.append(_short(m.group(1) + " sound", 3))
        first_lower = next((i for i, c in enumerate(sentence) if c.islower()), None)
        if first_lower is not None:  # capitals before the first lower case letter are a heading or a title, not a sound
            found += [_short(w, 1) for w in _LOUD.findall(sentence[first_lower:]) if w not in avoid]
        for title in found:
            if title and title.lower() not in seen:
                seen.add(title.lower())
                cues.append({"kind": "effect", "title": title, "prompt": sentence.strip()})
    return cues


def ambience_of(beats: list[dict], name: str) -> "dict | None":
    """The bed under a place: what its beats' action says of the weather and water (rain, thunder, waves, wind), as one placeholder for an ambience Sound."""
    said: list[str] = []
    for b in beats:
        picture = re.sub(r"^[\s.]+", "", (b.get("picture") or "").split(" Delivery:")[0].replace(b.get("place", ""), "", 1) if b.get("place") else (b.get("picture") or ""))
        said += [x for x in _sentences(picture) if _WEATHER.search(x) and x not in said]
    if not said:
        return None
    return {"kind": "ambience", "title": f"{name} ambience", "prompt": f"Ambience for {name}: " + " ".join(said[:3])}


def cut(elements: list[dict], chapter_pages: float = CHAPTER_PAGES, max_pages: float = MAX_CHAPTER_PAGES, text: "str | None" = None) -> Plan:
    """The chapters, beats and lines of a screenplay. Given the `text` it was read from (and the elements read with `lines=True`), each beat and each
    speech also holds its own piece of the writer's text, as written (`fountain`), and the plan holds what comes before the first beat (`front`):
    nothing the writer wrote is dropped, it stays with the beat it was written for."""
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
    raw_names = sorted({e["name"] for e in elements if e["t"] == "dialogue"})
    names = handles(raw_names)
    groups = _chapters(scenes, chapter_pages, max_pages)
    numbered = [(_LEADING_NUMBER.match(t) if t else None) for t, _g in groups]
    explicit = [int(m.group(1)) for m in numbered if m]
    use_titles = len(explicit) == len(groups) and len(set(explicit)) == len(groups) and explicit == sorted(explicit)
    chapters = []
    carry: dict = {"held": [], "seen": False, "held_at": None}
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
        front = _piece(all_lines, 0, flat[0]["at"]) if flat else ""
    plan = Plan(chapters, {r: h for r, h in names.items()}, warnings, source, single, front)
    plan.characters = characters(elements, names)
    plan.places = places_of(scenes)
    avoid = {w for c in plan.characters for w in re.sub(r"[^A-Z0-9 ]", " ", f"{c['name']} {c['cue']}".upper()).split()}
    avoid |= {w for p in plan.places.values() for w in re.sub(r"[^A-Z0-9 ]", " ", p["name"].upper()).split()}
    by_place: dict[str, list[dict]] = {}
    for ch in chapters:
        for b in ch.beats:
            b["sounds"] = sound_cues(b, avoid)
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
    return _NOTE.sub(keep, _BONEYARD.sub(keep, text))


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


def attach_source(imp: dict, plan: Plan, story: str) -> None:
    """Give the records an import plan is about to make (`beat_import.import_plan`) what the screenplay said that the beat sheet cannot carry: each
    beat's own text as written (`fountain`) and the transition written before it, each line's own text (`fountain`) and whether it is spoken over
    the line before (`simultaneous`). New records only; one that exists is left as it is."""
    by_number = {n: b for _c, n, b in plan.rows()}
    for _slug, _title, data in imp["beats"]:
        beat = by_number.get(str(data.get("number")))
        for key in ("fountain", "transition", "transition_text"):
            if beat and beat.get(key):
                data[key] = beat[key]
        place = place_of(beat.get("place", "")) if beat else None
        if place:
            data["scene"] = f"{story}-{place['slug']}"
        if beat and beat.get("sounds"):
            data["sounds"] = [{"sound": f"{story}-sound-{data.get('number')}-{i}", "at": 0} for i, _c in enumerate(beat["sounds"], 1)]
    for slug, _title, data in imp["lines"]:
        m = re.search(r"-line-(.+)-(\d+)$", slug)
        beat = by_number.get(m.group(1)) if m else None
        ln = beat["lines"][int(m.group(2)) - 1] if beat and m and 0 < int(m.group(2)) <= len(beat["lines"]) else None
        if ln and ln.get("fountain"):
            data["fountain"] = ln["fountain"]
        if ln and ln.get("dual"):
            data["simultaneous"] = True
