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
_NOTE = re.compile(r"\[\[.*?\]\]", re.S)
_SCENE = re.compile(r"^(?:INT|EXT|EST|INT\.?/EXT|INT/EXT|I/E)(?:\.|\s)", re.I)
_SCENE_NUMBER = re.compile(r"\s+#[\w.-]+#\s*$")
_TRANSITION = re.compile(r"^(?:[A-Z0-9 .'\-]+ TO:|FADE (?:IN|OUT)[.:]?|FADE TO BLACK[.:]?|CUT TO BLACK[.:]?|SMASH CUT TO BLACK[.:]?)$")
_SECTION = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
_TITLE_KEY = re.compile(r"^\s*(title|credit|author|authors|source|notes|draft date|date|contact|copyright|revision)\s*:", re.I)
_EXTENSION = re.compile(r"\s*\(([^)]*)\)\s*$")
_LEADING_NUMBER = re.compile(r"^(?:chapter|part|sequence|act|scene)?\s*(\d{1,3})\b\s*[-–—:.]?\s*(.*)$", re.I)


def _title(text: str) -> str:
    """`EXT. GRANNY'S PORCH - DUSK` -> `Ext. Granny's Porch - Dusk` (str.title() would make it Granny'S)."""
    return " ".join(w.capitalize() for w in text.split())


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


# --- reading ------------------------------------------------------------------------------------------------------------------------


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    return _NOTE.sub("", _BONEYARD.sub("", text))  # a boneyard and a note are the writer's, not the story's


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
    return _EXTENSION.sub("", s.lstrip("@").rstrip("^").strip()).strip()


def _is_character(s: str) -> bool:
    s = s.strip()
    if s.startswith("@"):
        return len(s) > 1
    if not s or _is_scene(s) or _is_transition(s) or s.startswith(("!", "#", "=", "~", ">")):
        return False
    name = _cue_name(s)
    return bool(re.search(r"[A-Z]", name)) and name == name.upper() and not name.endswith(".") or (bool(re.search(r"[A-Z]", name)) and name == name.upper() and len(name.split()) <= 4)


def _block_elements(block: list[str]) -> list[dict]:
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
        ext = _EXTENSION.search(first.lstrip("@").rstrip("^").strip())
        paren, speech = [], []
        for ln in block[1:]:
            s = ln.strip()
            (paren if s.startswith("(") and s.endswith(")") else speech).append(s.strip("()") if s.startswith("(") and s.endswith(")") else s)
        if speech:
            return [{"t": "dialogue", "name": _cue_name(first), "ext": (ext.group(1) if ext else ""), "paren": paren, "text": " ".join(speech).strip()}]
    text_ = " ".join(ln.strip().lstrip("!~") for ln in block).strip()
    text_ = re.sub(r"^>\s*(.*?)\s*<$", r"\1", text_)  # centred text is action
    return [{"t": "action", "text": text_}] if text_ else []


def parse(text: str, *, lines: bool = False) -> list[dict]:
    """The screenplay's elements in order: {t: scene|action|dialogue|transition|section, ...}. A title page, page breaks and synopses are left out.
    With `lines`, each element also says the line (counting from 0) of the text it starts on."""
    blocks = _blocks_at(_clean(text))
    if blocks and all(_TITLE_KEY.match(ln) or ln.startswith((" ", "\t")) for ln in blocks[0][1]) and _TITLE_KEY.match(blocks[0][1][0]):
        blocks = blocks[1:]
    out: list[dict] = []
    for start, block in blocks:
        for el in _block_elements(block):
            out.append({**el, "line": start} if lines else el)
    return out


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
    if t == "action":
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

    def pages(self) -> float:
        return pages(self.elements) + 2 / LINES_PER_PAGE


def _scenes(elements: list[dict]) -> list[Scene]:
    scenes: list[Scene] = []
    pending: list[tuple[int, str]] = []
    pending_at: int | None = None  # the line of the first section written above the next scene
    for el in elements:
        if el["t"] == "section":
            pending.append((el["depth"], el["title"]))
            pending_at = el.get("line", 0) if pending_at is None else pending_at
            continue
        if el["t"] == "scene":
            scenes.append(Scene(el["text"], [], pending, el.get("line", 0) if pending_at is None else pending_at))
            pending, pending_at = [], None
        else:
            if not scenes:
                scenes.append(Scene("", [], pending, el.get("line", 0) if pending_at is None else pending_at))
                pending, pending_at = [], None
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


def _beats_for(scenes: list[Scene], names: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    for scene in scenes:
        cur = None
        fresh_scene = True
        for el in scene.elements:
            t = el["t"]
            if t == "scene":
                cur = {"picture": el["text"], "lines": [], "notes": []}
                out.append(cur)
                fresh_scene = True
            elif t == "action":
                # Action with no speech between it and the last action is the same picture (up to a paragraph's worth); after speech it is a new one.
                if cur is not None and not cur["lines"] and (cur["picture"] == scene.heading or len(cur["picture"]) + len(el["text"]) <= PICTURE_CHARS):
                    joined = f"{cur['picture']}. {el['text']}" if fresh_scene else f"{cur['picture']} {el['text']}"
                    cur["picture"] = joined
                else:
                    cur = {"picture": el["text"], "lines": [], "notes": []}
                    out.append(cur)
                fresh_scene = False
            elif t == "dialogue":
                if cur is None:
                    cur = {"picture": scene.heading or "Continues", "lines": [], "notes": []}
                    out.append(cur)
                if len(cur["lines"]) >= LINES_PER_BEAT:
                    cur = {"picture": f"(continued) {cur['picture'][:80]}", "lines": [], "notes": []}
                    out.append(cur)
                who = names.get(el["name"], el["name"].capitalize())
                cur["lines"].append({"speaker": who, "text": el["text"]})
                note = ", ".join(el["paren"] + ([el["ext"]] if el["ext"] else []))
                if note:
                    cur["notes"].append(f"{who} ({note})")
                fresh_scene = False
            elif t == "transition":
                cur = None
    for b in out:
        if b["notes"]:
            b["picture"] = f"{b['picture']} Delivery: {'; '.join(b['notes'])}."
    return out


def cut(elements: list[dict], chapter_pages: float = CHAPTER_PAGES, max_pages: float = MAX_CHAPTER_PAGES) -> Plan:
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
    for i, (title, group) in enumerate(groups, 1):
        m = numbered[i - 1]
        n = int(m.group(1)) if use_titles and m else i
        shown = (m.group(2).strip() or title) if use_titles and m else title
        chapters.append(Chapter(n, shown or f"Chapter {n}", group, _beats_for(group, names)))
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
    return Plan(chapters, {r: h for r, h in names.items()}, warnings, source, single)


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
    norm = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
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
