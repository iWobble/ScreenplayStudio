"""How a line is said, kept on the line so the script can be made again from the records.

A Fountain writes it three ways, and each has a field of its own on a Speech Line:

- a parenthetical under the cue, `(without looking up)`, is the line's **direction**;
- an extension on the cue, `MARA (V.O.)`, is the line's **extension**;
- a tag inside the speech, `Fine. [sighs] Go on.`, is **delivery**: the voice reads it (ElevenLabs v3) and the caption never shows it, so the
  line keeps the clean words in `text` and the same words with their tags in `delivery_text`.

The importer carries the first two through the beat's picture as a note (`Delivery: Mara (without looking up); Narrator (V.O.).`), which is what
`from_note` reads back. A line made before the fields existed is filled from that note too.
"""

from __future__ import annotations

import re

EXTENSION = re.compile(r"^(?:V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT[’']?D)$", re.IGNORECASE)  # a speaker's extension (V.O.), not a parenthetical
TAG = re.compile(r"\s*(?<!\[)\[(?!\[)[^\[\]]+\](?!\])\s*")  # one tag: [sighs], [whispers], [pause]; a note is [[ ]] and never reaches a line


def from_note(picture: str) -> list[tuple[str, list[str]]]:
    """How the beat's lines are said, from the note its picture ends with (`... Delivery: Mara (without looking up); Narrator (V.O.).`):
    [(speaker, [what was written with them: parentheticals and an extension])], in the order of the lines they belong to."""
    tail = picture.split(" Delivery:", 1)[1] if " Delivery:" in picture else ""
    out: list[tuple[str, list[str]]] = []
    for item in [x.strip() for x in tail.strip().rstrip(".").split("; ") if x.strip()]:
        m = re.match(r"^(.*?) \((.*)\)$", item)
        if m:
            out.append((m.group(1).strip().lower(), [t.strip() for t in m.group(2).split(", ") if t.strip()]))
    return out


def split_tokens(tokens: list[str]) -> tuple[str, str]:
    """(extension, direction) from what was written with a speaker: the extension is V.O. / O.S. / O.C. / CONT'D, the rest is the direction."""
    extension = next((t for t in tokens if EXTENSION.match(t)), "")
    return extension, ", ".join(t for t in tokens if not EXTENSION.match(t))


def for_lines(picture: str, speakers: list[str]) -> list[tuple[str, str]]:
    """(extension, direction) for each of a beat's lines, given their speakers in order. The note names a speaker once for each line that had
    something written with it, in order, so each line takes the first unused entry that is its speaker's."""
    left = from_note(picture)
    out: list[tuple[str, str]] = []
    for who in speakers:
        found = next((x for x in left if x[0] == who.strip().lower()), None)
        if found is None:
            out.append(("", ""))
            continue
        left.remove(found)
        out.append(split_tokens(found[1]))
    return out


def split_tags(text: str) -> tuple[str, str]:
    """(clean words, the same words with their tags) for a line's speech: ("Fine. Go on.", "Fine. [sighs] Go on."), or (text, "") when it has no tag."""
    if not TAG.search(text or ""):
        return (text or "").strip(), ""
    clean = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", TAG.sub(" ", text))).strip()  # no space left in front of a full stop
    return clean, re.sub(r"\s{2,}", " ", text).strip()
