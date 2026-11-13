"""Check a Fountain before it is read. Reads the text only: nothing is made, changed or paid for, and no Marvin is needed.

The import reads a Fountain the way the format says, and a slip in the writing is not an error to it: a speaker written in lower case is action, a note
left open is ignored, two scenes with one number are one, a transition without its colon is a line of the story. Each reads fine and means something
else. `check` finds those, each with the line it is on and what to write instead; `report` puts them in words. Lines are counted as the import counts
them (after a code fence round the text is taken off).

A finding is an `error` when the import would read it differently from what was meant (or ignore part of it), a `look` when it is worth a glance. The
import stops on errors unless it is told to go on; a `soft` error is one the import has always only warned about.
"""

import re
import unicodedata
from dataclasses import dataclass

from . import fountain as F

# findings the import has always shown as warnings and still does not stop for (see `blocking`)
SOFT = {"capitals-alone", "capitals-above-text", "heading-without-kind"}


@dataclass(frozen=True)
class Finding:
    line: int  # 1-based; 0 is the file as a whole
    level: str  # "error" or "look"
    code: str
    problem: str
    fix: str


def blocking(findings: list[Finding]) -> list[Finding]:
    """The errors the import stops for: the ones that lose or change what the writer wrote and have no old warning of their own."""
    return [f for f in findings if f.level == "error" and f.code not in SOFT]


def _row(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# --- the characters themselves ---------------------------------------------------------------------------------------------------------


def _invisible(lines: list[str]) -> list[Finding]:
    """Characters that cannot be seen and still change how a line reads (a non-breaking space in a cue, a zero-width mark pasted in with a name)."""
    out = []
    for n, ln in enumerate(lines, 1):
        bad = [c for c in ln if c != "\t" and (unicodedata.category(c) in ("Cc", "Cf") or (unicodedata.category(c) == "Zs" and c != " "))]
        if bad:
            names = ", ".join(sorted({f"U+{ord(c):04X} {unicodedata.name(c, 'unnamed')}" for c in bad}))
            out.append(Finding(n, "look", "invisible", f"has a character you cannot see ({names})", "delete the line's invisible characters (retype the line, or paste it as plain text)"))
    return out


# --- notes and boneyards ---------------------------------------------------------------------------------------------------------------

_HOLD = re.compile(r"hold\s*:\s*\d+(?:\.\d+)?\s*s?\s*\.?$", re.I)
_AT = re.compile(r"\bat\s+(\S+)", re.I)
_AT_OK = re.compile(r"\d+(?:\.\d+)?s?[.,;]?$", re.I)


def _notes(text: str) -> list[Finding]:
    out = []
    for m in F._NOTE.finditer(text):
        row = _row(text, m.start())
        body = m.group(0)
        if not body.endswith("]]"):
            out.append(Finding(row, "error", "note-open", "a note is opened with [[ and never closed, so it is ignored (a note ends at its ]] or at a blank line)", "close it with ]] on the same paragraph"))
            continue
        inner = body[2:-2].strip()
        if re.match(r"hold\s*:", inner, re.I) and not _HOLD.match(inner):
            out.append(Finding(row, "error", "hold-value", f"`[[{inner}]]` does not say how long, so the hold is ignored", "write the seconds: `[[Hold: 1.5s.]]`"))
        elif re.match(r"sound\s*:", inner, re.I):
            at = _AT.search(inner)
            if at and not _AT_OK.match(at.group(1)):
                out.append(Finding(row, "error", "sound-at", f"`at {at.group(1)}` is not a time, so the sound is placed at the start", "write the seconds into the beat: `at 1.5s`"))
    rest = F._NOTE.sub(F._blank_out, text)
    if "]]" in rest:
        out.append(Finding(_row(rest, rest.index("]]")), "look", "note-close", "a ]] closes a note that was never opened", "open it with [[ or delete the ]]"))
    plain = F._BONEYARD.sub(F._blank_out, text)
    if "/*" in plain:
        out.append(Finding(_row(plain, plain.index("/*")), "error", "boneyard-open", "a /* comment is opened and never closed with */", "close it with */"))
    return out


# --- the title page --------------------------------------------------------------------------------------------------------------------


def _title(text: str) -> list[Finding]:
    page = F.title_page(text)
    if not page:
        return [Finding(1, "look", "title-page", "there is no title page (Title:, Credit:, Author: … then a blank line)", "start the file with `Title: …`; the story keeps its own name without one")]
    out = []
    if "title" not in page:
        out.append(Finding(1, "look", "title-missing", "the title page has no Title:", "add a `Title:` line"))
    for key, label in (("setting", "Setting"), ("premise", "Premise")):
        if not page.get(key, "").strip():
            out.append(Finding(1, "look", f"title-{key}", f"the title page has no {label}:, which the pictures read", f"add a `{label}:` line (or fill the story's {label} field in Marvin)"))
    return out


# --- the paragraphs --------------------------------------------------------------------------------------------------------------------

_EMPTY_HEADING = re.compile(r"^(?:INT|EXT|EST|INT\.?/EXT\.?|EXT\.?/INT\.?|I/E)\.?\s*(?:#[^#]+#)?\s*$", re.I)
_NO_COLON = re.compile(r"^[A-Z][A-Z0-9 .'\-]* TO$")
_NUMBER = re.compile(r"#([^#]+)#\s*$")
_ONE_WORD = re.compile(r"^[A-Za-z][A-Za-z'’-]{2,24}$")


def _is_cue(first: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", first)
    if not letters or first != first.upper():
        return False
    if first.startswith(("!", "#", "=", "~", ">", ".", "@", "[", "(", "/", "{")) or F._is_scene(first) or F._is_transition(first):
        return False
    return True


def _blocks(text: str) -> tuple[list[Finding], dict[str, list[int]], list[tuple[int, str]]]:
    """The findings of each paragraph, the speakers it saw (name -> the lines they speak on), and the single lower-case words that sit above text."""
    out: list[Finding] = []
    speakers: dict[str, list[int]] = {}
    lower: list[tuple[int, str]] = []
    numbers: dict[str, list[tuple[int, str]]] = {}
    previous_break = False
    seen_content = False
    for index, (start, block) in enumerate(F._blocks_at(text)):
        first = block[0].strip()
        row = start + 1
        if index == 0 and F._ANY_KEY.match(first) and not first.isupper():
            continue  # the title page
        if re.fullmatch(r"={3,}", first):
            if previous_break or not seen_content:
                out.append(Finding(row, "look", "empty-picture", "a page break with no picture before it (it makes an empty beat, or none)", "delete the extra ==="))
            previous_break = True
            continue
        previous_break = False
        seen_content = True
        if first.startswith("#") and not _NUMBER.match(first):
            if not re.sub(r"^#+", "", first).strip():
                out.append(Finding(row, "error", "section-empty", "a # section line has no title", "write the chapter's title after the #: `# ACT I: THE WRECK`"))
            continue
        if first.startswith(">") and first.rstrip().endswith("<"):
            if all(F._CENTRED.match(ln.strip()) for ln in block):
                out.append(Finding(row, "look", "centered", f"`{first}` is centered text standing alone, so it is a plain card: a beat of its own that shows the words on the story's card colour, with no picture made for it", "nothing if a card is what you want; to have the words in a picture instead, write them as an action line (or `SUPER: …` for a title over the picture)"))
            else:
                out.append(Finding(row, "look", "centered", f"`{first}` is centered text inside a paragraph, which is read as action", "write it as an action line, or give it a paragraph of its own to make it a plain card"))
            continue
        if F._is_scene(first) and not first.startswith("."):
            if _EMPTY_HEADING.match(first):
                out.append(Finding(row, "error", "heading-empty", f"`{first}` names no place, so it is not a scene", "write the place: `INT. LAMP ROOM - NIGHT`"))
            m = _NUMBER.search(first)
            place = F.place_of(first)
            if m and place:
                numbers.setdefault(m.group(1), []).append((row, place["slug"]))
            continue
        if _NO_COLON.match(first) and not F._is_scene(first):
            out.append(Finding(row, "error", "transition-colon", f"`{first}` has no colon, so it is read as a line of the story, not a transition", f"write `{first}:`"))
            continue
        if first.startswith("("):
            out.append(Finding(row, "look", "paren-alone", "a direction in brackets with no speaker above it (it is read as action)", "put it on the line under the speaker's name, or write it as a sentence"))
            continue
        if _is_cue(first) and len(block) >= 2:
            name = F._cue_name(first)
            speakers.setdefault(name, []).append(row)
            spoken = False
            for k, line in enumerate(block[1:], 1):
                s = line.strip()
                if s.startswith("(") and ")" not in s:
                    out.append(Finding(row + k, "error", "paren-open", f"`{s}` is opened with ( and never closed, so it is read as the line", "close it with ): `(without looking up)`"))
                    spoken = True
                elif not s.startswith("("):
                    spoken = True
            if not spoken:
                out.append(Finding(row, "error", "cue-empty", f"`{first}` is followed only by a direction: there are no words for the speaker", "add the line below the direction, or delete the speaker"))
            continue
        if 2 <= len(block) <= 8 and _ONE_WORD.match(first) and first == first.lower() and re.match(r"[A-Z(]", block[1].strip() or " "):
            lower.append((row, first))
    for number, uses in numbers.items():
        places = {slug for _r, slug in uses}
        if len(places) > 1:
            where = ", ".join(f"line {r}" for r, _s in uses)
            for r, _s in uses[1:]:
                out.append(Finding(r, "error", "scene-number", f"scene number #{number}# is used for different places ({where}), so they are read as one scene", "give each place its own number, or leave the numbers off"))
    return out, speakers, lower


def _one_apart(a: str, b: str) -> bool:
    """Whether two names differ by one letter added, left out or changed."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


def _speakers(speakers: dict[str, list[int]], lower: list[tuple[int, str]]) -> list[Finding]:
    out = []
    known = {n.upper(): n for n in speakers}
    for row, word in lower:
        if word.upper() in known:
            out.append(Finding(row, "error", "cue-lowercase", f"`{word}` is written like the speaker {known[word.upper()]} but not in capitals, so the words below it are read as action", f"write the speaker in capitals: `{word.upper()}`"))
        else:
            out.append(Finding(row, "look", "cue-lowercase-maybe", f"`{word}` stands alone above a line: if it is a speaker, it is read as action because it is not in capitals", f"write it `{word.upper()}`, or join it to the sentence"))
    names = sorted(speakers)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if _one_apart(a, b) and len(a) >= 4 and len(b) >= 4:
                few, many = sorted((a, b), key=lambda n: len(speakers[n]))
                if len(speakers[few]) <= 2 and len(speakers[few]) < len(speakers[many]):
                    out.append(Finding(speakers[few][0], "look", "speaker-typo", f"`{few}` ({len(speakers[few])} line{'s' if len(speakers[few]) != 1 else ''}) is spelled like `{many}` ({len(speakers[many])}): a typo would make them two characters", f"if they are one person, write `{many}`"))
    return out


# --- the check -------------------------------------------------------------------------------------------------------------------------


def check(text: str) -> list[Finding]:
    """Everything wrong or doubtful in the Fountain, in the order of the file. Nothing is read into records and nothing is changed."""
    plain = F._normal(text)
    lines = plain.split("\n")
    out: list[Finding] = []
    out += _invisible(lines)
    out += _notes(plain)
    out += _title(plain)
    stripped = F._NOTE.sub(F._blank_out, F._BONEYARD.sub(F._blank_out, plain))
    found, speakers, lower = _blocks(stripped)
    out += found + _speakers(speakers, lower)
    for message in F.lint(text, limit=None):  # the capitals rules the import has always warned about, every one of them, with a place in this list
        m = re.match(r"line (\d+): (.*)$", message, re.S)
        if not m:
            continue
        code = "heading-without-kind" if "does not start with INT. or EXT." in message else "capitals-alone" if "stands alone in capitals" in message else "capitals-above-text"
        problem, _, fix = m.group(2).partition(": if ")
        out.append(Finding(int(m.group(1)), "error", code, problem.strip(), ("if " + fix) if fix else "see the line"))
    try:
        plan = F.cut(F.parse(text, lines=True), text=text)
        for w in plan.warnings:
            if not w.startswith("line ") and not re.match(r"and \d+ more like these", w):
                out.append(Finding(0, "look", "plan", w, "see the import's preview"))
    except Exception as e:  # a text the reader cannot make anything of is the one thing to say first
        out.append(Finding(0, "error", "unreadable", f"the file could not be read as a screenplay ({type(e).__name__}: {e})", "check it is Fountain text"))
    out.sort(key=lambda f: (f.line, f.level != "error", f.code))
    return out


def summary(text: str) -> str:
    """What the import would make of the text, in one line (no records are made)."""
    try:
        plan = F.cut(F.parse(text, lines=True), text=text)
    except Exception:
        return "It could not be read."
    beats = sum(len(c.beats) for c in plan.chapters)
    lines = sum(len(b["lines"]) for c in plan.chapters for b in c.beats)
    return f"It reads as {len(plan.chapters)} chapter{'s' if len(plan.chapters) != 1 else ''}, {beats} beats, {lines} spoken lines, {len(plan.characters)} characters and {len(plan.places)} places."


def verdict(findings: list[Finding]) -> str:
    """The report's first line: whether the import will stop, and what else there is to read."""
    stops = blocking(findings)
    rest = len(findings) - len(stops)
    if stops:
        also = f" The other {rest} {'are' if rest != 1 else 'is'} worth a look." if rest else ""
        return f"The import will stop: {len(stops)} mistake{'s' if len(stops) != 1 else ''} to fix first (under “Fix before importing”).{also}"
    if rest:
        return f"The import will go ahead: nothing stops it. {rest} line{'s are' if rest != 1 else ' is'} worth a look (below)."
    return "The import will go ahead: nothing to fix."


def report(findings: list[Finding], text: str = "") -> tuple[str, int, int]:
    """The findings in words, and how many are errors and how many are worth a look. It opens with whether the import will stop; what the
    import stops for is under "Fix before importing", and everything else (the capitals it has always only warned about too) under "Worth a
    look". Every finding is listed: the count is the real one."""
    errors = [f for f in findings if f.level == "error"]
    looks = [f for f in findings if f.level == "look"]
    stops = blocking(findings)
    head = [verdict(findings), "Checked the Fountain" + (f" ({len(F._normal(text).splitlines())} lines)." if text else ".")]
    if text:
        head.append(summary(text))
    if not findings:
        return "\n".join(head + ["Nothing to fix: it reads the way it is written."]), 0, 0
    out = list(head)
    worth = [f for f in findings if f not in stops]
    for title, said, group in (
        ("Fix before importing", "the import stops until these are fixed", stops),
        ("Worth a look", "the import goes ahead with these; change one only if it is not what you meant", worth),
    ):
        if group:
            out += ["", f"{title} ({len(group)}): {said}."]
            for f in group:
                where = f"line {f.line}: " if f.line else ""
                out.append(f"  {where}{f.problem}. {f.fix[:1].upper() + f.fix[1:]}.")
    return "\n".join(out), len(errors), len(looks)
