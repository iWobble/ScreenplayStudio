"""A story's beats and spoken lines, read out of text and planned as the records Marvin holds (`beat`, `speech-line`).

Two ways of writing a story are read, and neither needs to be told which:

    **01** — Narrator: The captain ordered a feast. At dawn, they would attack.      numbered lines (what a story's `script` field holds)
    **07** — Narrator: Then he noticed the letters. Cook: Your feast.                 a beat with two speakers on one line

    | Beat | Time | Audio | Single still / composition |                              a beat-sheet table (see beats.py)
    | 01 | 0–8s | Narrator: The captain ordered a feast. | Low-angle medium: captain on the deck |

A beat is a number (`04a` slots one between 04 and 05, so nothing is renumbered); its audio is `Speaker: words` for each voice. In the numbered form
words with no speaker are the narrator's. A table row also carries the picture and a time (kept as the beat's hold); a `Sound:` cue is a note
for the library's sounds and is reported, not imported. `import_plan` turns the rows into what would be created, and leaves alone whatever
already exists, so running it twice, or after a beat has been edited, changes nothing that is there.
"""

from __future__ import annotations

import re

from . import beats

_NUMBERED = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?(\d{1,3}[a-z]*)(?:\*\*)?\s*(?:—|–|-|\.|:|\))\s*(.+?)\s*$", re.IGNORECASE)
_STARTS_WITH_SPEAKER = re.compile(r"^[A-Z][A-Za-z]+:\s")
_SPEAKER = re.compile(r"^\s*(?:[-*+]\s*)?[A-Z][A-Za-z]+:\s+\S")
_NO_SPEECH = re.compile(r"^no speech\.?$", re.IGNORECASE)
TITLE_CHARS = 48
_NOT_SPOKEN = re.compile(r"^\(?\s*(?:no (?:speech|narration|dialogue|voice)\b|silence\)?[.!]?\s*$)", re.IGNORECASE)
""""No speech. Hold on the smile." or a lone "Silence." is a direction for a held beat, not something a voice says (narration that merely starts with the word, "Silence fell.", is kept)."""


def beat_number(raw: str) -> str:
    """`4` -> `04`, `04A` -> `04a`: the form beats are numbered in, so they sort and match."""
    m = re.fullmatch(r"(\d+)([a-z]*)", raw.strip().lower())
    return f"{int(m.group(1)):02d}{m.group(2)}" if m else raw.strip().lower()


def parse_numbered(markdown: str) -> list[dict]:
    """Numbered lines as rows shaped like `beats.parse`'s (no picture, no time). A line that does not start with a number but starts `Name: words`
    continues the beat before it, so a beat's speakers may sit on their own lines."""
    rows: list[dict] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("|"):
            continue
        m = _NUMBERED.match(line)
        if m:
            rows.append({"beat": beat_number(m.group(1)), "cell": m.group(2)})
        elif rows and _SPEAKER.match(line):
            rows[-1]["cell"] += " " + line.lstrip("-*+ ").strip()
    out = []
    for r in rows:
        if not _STARTS_WITH_SPEAKER.match(r["cell"]):
            r["cell"] = "Narrator: " + r["cell"]  # words before any speaker is named are the narrator's
        parts = beats.split_audio(r["cell"])
        out.append(
            {
                "beat": r["beat"],
                "start": 0.0,
                "end": 0.0,
                "hold": 0.0,
                "audio_cell": r["cell"],
                "picture": "",
                "lines": [p for p in parts if p["kind"] == "speech"],
                "sounds": [p for p in parts if p["kind"] == "sound"],
            }
        )
    return out


def notes_of(row: dict) -> str:
    """What a row's Audio cell says that is not speech: the words before the first speaker (`No speech. Hold on the smile.`), any direction that
    was dropped from the lines, and the `Sound:` cues. A bare `No speech.` is nothing (it is what an empty beat is written as)."""
    cell = row.get("audio_cell") or ""
    first = (beats._LABEL_FENCED if "¶" in cell else beats._LABEL).search(cell)  # a cell the Fountain import wrote divides its speakers with ¶
    lead = cell[: first.start()].strip() if first else cell.strip()
    parts = [lead, *row.get("dropped", []), *[f"Sound: {s['text']}" for s in row.get("sounds", [])]]
    text = " ".join(p.strip() for p in parts if p and p.strip())
    text = re.sub(r"^no speech\.?\s*¶?\s*(?=\S)", "", text, flags=re.IGNORECASE)  # a bare `No speech.` in front of a cue is only the empty beat's placeholder
    return "" if _NO_SPEECH.match(text) else text


def _drop_directions(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["dropped"] = [ln["text"] for ln in row["lines"] if _NOT_SPOKEN.match(ln["text"])]  # a direction is kept as a note on the beat
        row["lines"] = [ln for ln in row["lines"] if not _NOT_SPOKEN.match(ln["text"])]
    return rows


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?:scene|chapter|part)\s+(\d+[a-z]?)\s*[-–—:.]\s*(.+?)\s*$", re.IGNORECASE)


def _chunks(markdown: str) -> list[tuple[dict | None, str]]:
    """The text cut at its `## Scene 3 - Title` (or Chapter / Part) headings: [(chapter or None, the text under it)]. A heading starts a chapter."""
    chunks: list[tuple[dict | None, str]] = []
    current, buffer = None, []
    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m:
            chunks.append((current, "\n".join(buffer)))
            current, buffer = {"number": beat_number(m.group(1)), "title": m.group(2).strip()}, []
        else:
            buffer.append(line)
    chunks.append((current, "\n".join(buffer)))
    return chunks


def parse_any(markdown: str) -> tuple[str, list[dict]]:
    """("table" | "numbered", rows): a beat-sheet table if the text has one, otherwise numbered lines. ("", []) when it is neither. Each row carries
    `chapter`: {number, title} of the heading above it, or None."""
    chunks = _chunks(markdown)
    tables = [(chapter, beats.parse(text)) for chapter, text in chunks]
    if any(rows for _, rows in tables):
        kind, found = "table", tables
    else:
        kind, found = "numbered", [(chapter, parse_numbered(text)) for chapter, text in chunks]
    rows: list[dict] = []
    for chapter, chunk_rows in found:
        for row in chunk_rows:
            row["beat"] = beat_number(row["beat"])
            row["chapter"] = chapter
            rows.append(row)
    return (kind, _drop_directions(rows)) if rows else ("", [])


_HEADING_LEAD = re.compile(r"^(?:Interior and exterior|Interior|Exterior): [^.]*\.\s+")  # a first picture of a scene begins with its heading in words


def _action_of(picture: str) -> str:
    """The picture without the place heading it may begin with (`Interior: Captain's Cabin. A lantern hangs…` -> `A lantern hangs…`), for a title; the
    whole picture when nothing follows the heading."""
    m = _HEADING_LEAD.match(picture or "")
    return (picture[m.end() :] or picture) if m else (picture or "")


def _short(text: str) -> str:
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS].rstrip()


def _worked_on_beat(data: dict) -> bool:
    """A beat that has a picture made or being made (a still, a move, or any status past draft) is not rewritten."""
    return bool(data.get("still") or data.get("move")) or str(data.get("status") or "draft") != "draft"


def _worked_on_line(data: dict) -> bool:
    """A line that has a recording, or any status past draft, is not rewritten."""
    return bool(data.get("audio")) or str(data.get("status") or "draft") != "draft"


META = {"chapter", "audio_notes"}
"""Fields that only say where a beat sits. Nothing is made from them, so they may change on a beat that has a picture."""


def _refresh(plan: dict, slug: str, record: dict, title: str, data: dict, worked_on) -> None:
    """An existing record, when refreshing: bring it in line with the sheet if nothing has been made from it, otherwise keep it and say why."""
    current = record.get("dataJson") or {}
    same = lambda a, b: (a if a not in (None, "") else "") == (b if b not in (None, "") else "")  # noqa: E731  nothing and an empty text are the same
    changed = {k: v for k, v in data.items() if k != "status" and not same(current.get(k), v)}
    title_differs = bool(record.get("title")) and record.get("title") != title
    if not changed and not title_differs:
        plan["same"] += 1
    elif worked_on(current):
        content = {k for k in changed if k not in META}
        if content:  # a different title alone is cosmetic and not worth a line
            plan["kept"].append((slug, "already worked on; the sheet differs in " + ", ".join(sorted(content))))
        elif changed:
            plan["updates"].append((slug, record.get("id"), record.get("title") or title, {**current, **changed}))  # only where it sits, and the title stays
        else:
            plan["same"] += 1
    else:
        plan["updates"].append((slug, record.get("id"), title, {**current, **changed}))


def import_plan(story: str, rows: list[dict], existing: "dict[str, dict] | set[str]", refresh: bool = False, chapters: "dict[str, dict] | None" = None) -> dict:
    """What to do for `rows`, given the story's records that already exist (`slug -> record`, or just their slugs; `chapters` the same for its chapters):
    {"beats": [(slug, title, data)], "lines": [...], "chapters": [...]} to create; with `refresh`, {"updates": [(slug, id, title, merged data)]} for
    existing ones nothing has been made from, and {"kept": [(slug, why)]} for ones that have a still or a recording and differ from the sheet.
    A beat under a heading gets that chapter (and an existing beat with no chapter is given one, even without `refresh`). `have` counts what
    exists, `same` what already matches, `gone` is what exists for the story but is not in the sheet (never touched). A beat number used twice is
    a problem, and only its first is used."""
    records = existing if isinstance(existing, dict) else {slug: {} for slug in existing}
    known_chapters = chapters or {}
    plan: dict = {
        "beats": [], "lines": [], "chapters": [], "updates": [], "kept": [], "same": 0,
        "have": {"beats": 0, "lines": 0, "chapters": 0}, "sounds": [], "problems": [], "gone": [],
    }  # fmt: skip
    seen: set[str] = set()
    wanted: set[str] = set()
    planned_chapters: set[str] = set()
    for row in rows:
        number = row["beat"]
        if number in seen:
            plan["problems"].append(f"beat {number} appears more than once; only the first is used")
            continue
        seen.add(number)
        slug = f"{story}-beat-{number}"
        wanted.add(slug)
        heading = row.get("chapter")
        chapter_slug = f"{story}-chapter-{heading['number']}" if heading else None
        if chapter_slug and chapter_slug not in planned_chapters:
            planned_chapters.add(chapter_slug)
            if chapter_slug in known_chapters:
                plan["have"]["chapters"] += 1
                if refresh and known_chapters[chapter_slug].get("title") not in (None, heading["title"]):
                    record = known_chapters[chapter_slug]
                    plan["updates"].append((chapter_slug, record.get("id"), heading["title"], {**(record.get("dataJson") or {}), "story": story, "number": heading["number"]}))
            else:
                plan["chapters"].append((chapter_slug, heading["title"], {"story": story, "number": heading["number"]}))
        first = row["lines"][0] if row["lines"] else None
        title = f"Beat {number}: {_short((first['speaker'] + ': ' + first['text']) if first else _action_of(row['picture']) or 'held picture')}"
        data = {"story": story, "number": number, "status": "draft"}
        if row["picture"]:
            data["picture"] = row["picture"]
        if row["hold"] and not row["lines"]:
            data["hold_seconds"] = row["hold"]  # only a silent beat lasts as long as its time; a spoken one lasts as long as its recording
        data["audio_notes"] = notes_of(row)
        if chapter_slug:
            data["chapter"] = chapter_slug
        if slug in records:
            plan["have"]["beats"] += 1
            current = records[slug].get("dataJson") or {}
            if refresh:
                _refresh(plan, slug, records[slug], title, data, _worked_on_beat)
            elif chapter_slug and not current.get("chapter"):  # a beat with no chapter is given one: it is only where it sits
                plan["updates"].append((slug, records[slug].get("id"), records[slug].get("title") or title, {**current, "chapter": chapter_slug}))
        else:
            plan["beats"].append((slug, title, data))
        for n, line in enumerate(row["lines"], 1):
            lslug = f"{story}-line-{number}-{n}"
            wanted.add(lslug)
            ltitle = f"{number} {_short(line['speaker'] + ': ' + line['text'])}"
            ldata = {"story": story, "beat": slug, "speaker": line["speaker"].lower(), "text": line["text"], "status": "draft"}
            if lslug in records:
                plan["have"]["lines"] += 1
                if refresh:
                    _refresh(plan, lslug, records[lslug], ltitle, ldata, _worked_on_line)
            else:
                plan["lines"].append((lslug, ltitle, {**ldata, "order": n}))  # new lines are numbered in the order written; a refresh never renumbers one a person has moved
        plan["sounds"] += [f"beat {number}: {s['text']}" for s in row["sounds"]]
    plan["gone"] = sorted(slug for slug in records if slug not in wanted)
    plan["trash"], plan["orphans_kept"] = [], []
    if refresh:
        _retire(plan, story, records, known_chapters, wanted, planned_chapters)
    return plan


def _retire(plan: dict, story: str, records: dict, chapters: dict, wanted: set, planned_chapters: set) -> None:
    """Refresh only. What is in Marvin for the story but no longer in the text: **trash** it (the Trash is reversible) when nothing was made from
    it, keep and flag it when a picture or a recording was. A beat goes with its lines, and only if none of them has a recording; a line that
    is gone from a beat that stays goes on its own; a chapter goes when no beat that remains is in it."""
    beat_prefix, line_prefix = f"{story}-beat-", f"{story}-line-"
    data_of = lambda slug: (records[slug].get("dataJson") or {})  # noqa: E731
    lines_of: dict[str, list[str]] = {}
    for slug in records:
        if slug.startswith(line_prefix):
            lines_of.setdefault(str(data_of(slug).get("beat")), []).append(slug)
    trash: list[str] = []
    gone_beats = sorted(s for s in records if s.startswith(beat_prefix) and s not in wanted)
    for slug in gone_beats:
        if _worked_on_beat(data_of(slug)):
            plan["orphans_kept"].append((slug, "a picture was made"))
        elif any(_worked_on_line(data_of(line)) for line in lines_of.get(slug, [])):
            plan["orphans_kept"].append((slug, "a line of it was recorded"))
        else:
            trash += [slug, *lines_of.get(slug, [])]
    kept_beats = {s for s, _ in plan["orphans_kept"]}
    for slug in sorted(s for s in records if s.startswith(line_prefix) and s not in wanted):
        if slug in trash or str(data_of(slug).get("beat")) in set(gone_beats):
            continue  # it went with its beat, or stays with a beat that is kept
        if _worked_on_line(data_of(slug)):
            plan["orphans_kept"].append((slug, "it was recorded"))
        else:
            trash.append(slug)
    # chapters: which does a beat that remains sit in, after this run's changes?
    after = {slug: data_of(slug).get("chapter") for slug in records if slug.startswith(beat_prefix) and slug not in trash}
    for slug, _id, _title, merged in plan["updates"]:
        if slug in after:
            after[slug] = merged.get("chapter")
    after.update({slug: data.get("chapter") for slug, _t, data in plan["beats"]})
    for slug in sorted(chapters):
        if slug not in planned_chapters:
            if slug in set(after.values()):
                plan["orphans_kept"].append((slug, "a beat that is kept is still in it"))
            else:
                trash.append(slug)
    ids = {slug: rec.get("id") for slug, rec in {**records, **chapters}.items()}
    plan["trash"] = [(slug, ids.get(slug)) for slug in trash]
