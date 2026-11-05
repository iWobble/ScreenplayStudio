"""A story's beats, lines and chapters written back out as the sheet they came from (the reverse of `beat_import`), and a *signature* that says
whether the script and the records still say the same thing.

The script is where the content is edited; the records follow it. When a beat is edited by hand, `sync-sheet` rewrites the script's table from
the records. That is only safe if nothing is lost on the way round, so what the sheet says that a record cannot hold lives on the beat
(`audio_notes`: a direction such as "Hold on the smile", and the `Sound:` cues), and the text above the first scene heading is kept as it is.

A signature is a hash of what matters: for each beat its number, chapter, picture, the length of a silent one, its notes and its lines.
Times are left out (a spoken beat lasts as long as its recording, so they drift as recordings arrive), as is formatting. The story keeps the
signature of the last time the script and the records agreed (`sheet_base`): script differs from it, the script was edited; records differ,
beats were edited; both, a conflict that is reported and not resolved by overwriting.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import beat_import
from .beat_import import notes_of  # noqa: F401  (the sheet's notes live with the importer that reads them)

WORDS_PER_SECOND = 2.5
LEAD_TAIL = 1.0
DEFAULT_SILENT = 4.0


def _chapter_number(chapter) -> str | None:
    if not chapter:
        return None
    return chapter["number"] if isinstance(chapter, dict) else str(chapter).rsplit("-chapter-", 1)[-1]


def _beat_signature(number, chapter, picture, hold, notes, lines) -> dict:
    return {"beat": number, "chapter": chapter, "picture": (picture or "").strip(), "hold": float(hold or 0) if not lines else 0.0, "notes": (notes or "").strip(), "lines": [(s, t.strip()) for s, t in lines]}


def signature_of_rows(rows: list[dict]) -> dict[str, dict]:
    """Per beat, what matters in parsed script rows (see `beat_import.parse_any`)."""
    return {
        r["beat"]: _beat_signature(r["beat"], _chapter_number(r.get("chapter")), r.get("picture"), r.get("hold"), notes_of(r), [(ln["speaker"].lower(), ln["text"]) for ln in r["lines"]])
        for r in rows
    }


def signature_of_records(story: str, beat_records: list[dict], line_records: list[dict]) -> dict[str, dict]:
    """The same, from the story's records."""
    by_beat: dict[str, list[tuple[str, str, str]]] = {}
    for rec in line_records:
        d = rec.get("dataJson") or {}
        by_beat.setdefault(str(d.get("beat")), []).append((rec["slug"], str(d.get("speaker") or ""), str(d.get("text") or "")))
    out = {}
    for rec in beat_records:
        d = rec.get("dataJson") or {}
        number = beat_import.beat_number(str(d.get("number") or rec["slug"].rsplit("-beat-", 1)[-1]))
        lines = [(s, t) for _slug, s, t in sorted(by_beat.get(rec["slug"], []), key=lambda x: _line_order(x[0]))]
        out[number] = _beat_signature(number, _chapter_number(d.get("chapter")), d.get("picture"), d.get("hold_seconds"), d.get("audio_notes"), lines)
    return out


def digest(signature: dict[str, dict]) -> str:
    return hashlib.sha1(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def differing_beats(a: dict[str, dict], b: dict[str, dict]) -> list[str]:
    """The beat numbers that are in one and not the other, or differ."""
    return sorted((n for n in a.keys() | b.keys() if a.get(n) != b.get(n)), key=_beat_order)


def _beat_order(number: str):
    m = re.fullmatch(r"(\d+)([a-z]?)", number)
    return (int(m.group(1)), m.group(2)) if m else (10**9, number)


def _line_order(slug: str):
    m = re.search(r"-line-(\d+[a-z]?)-(\d+)$", slug)
    return (_beat_order(m.group(1)), int(m.group(2))) if m else ((10**9, slug), 0)


def preamble_of(script: str) -> str:
    """Everything above the first scene heading or table row, kept as it is (a title, a speakers list)."""
    kept: list[str] = []
    for line in script.splitlines():
        if beat_import._HEADING.match(line) or re.match(r"^\s*\|\s*(?:Beat|\d)", line):
            break
        kept.append(line)
    return "\n".join(kept).rstrip()


def _estimate(row_lines: list[tuple[str, dict]], beat_data: dict) -> float:
    if not row_lines:
        return float(beat_data.get("hold_seconds") or DEFAULT_SILENT)
    seconds = 0.0
    for _speaker, d in row_lines:
        seconds += float(d.get("duration_seconds") or len(str(d.get("text") or "").split()) / WORDS_PER_SECOND)
    return seconds + LEAD_TAIL


def _cell(text: str) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def render_sheet(story: str, chapters: list[dict], beat_records: list[dict], line_records: list[dict], preamble: str = "") -> str:
    """The sheet: the preamble, then a `## Scene N - Title` heading and a table per chapter (beats with no chapter first, with no heading), the
    beats in order, the Audio cell the lines as `Speaker: words.` followed by the beat's notes, and running times from 0s."""
    titles = {_chapter_number(c["slug"]): (c.get("title") or "") for c in chapters}
    lines_by_beat: dict[str, list[tuple[str, dict]]] = {}
    for rec in sorted(line_records, key=lambda r: _line_order(r["slug"])):
        d = rec.get("dataJson") or {}
        lines_by_beat.setdefault(str(d.get("beat")), []).append((str(d.get("speaker") or "narrator"), d))
    ordered = sorted(beat_records, key=lambda r: _beat_order(beat_import.beat_number(str((r.get("dataJson") or {}).get("number") or r["slug"].rsplit("-beat-", 1)[-1]))))
    groups: dict[str | None, list[dict]] = {}
    for rec in ordered:
        groups.setdefault(_chapter_number((rec.get("dataJson") or {}).get("chapter")), []).append(rec)
    out = [preamble] if preamble.strip() else []
    clock = 0.0
    header = ["| Beat | Time | Audio | Single still / composition |", "|---|---|---|---|"]
    for chapter in [None, *sorted((c for c in groups if c), key=lambda c: _beat_order(c))]:
        if chapter not in groups:
            continue
        out += ["", f"## Scene {int(chapter) if chapter.isdigit() else chapter} - {titles.get(chapter, '')}".rstrip(" -"), ""] if chapter else [""]
        out += header
        for rec in groups[chapter]:
            d = rec.get("dataJson") or {}
            number = beat_import.beat_number(str(d.get("number") or rec["slug"].rsplit("-beat-", 1)[-1]))
            spoken = lines_by_beat.get(rec["slug"], [])
            seconds = _estimate(spoken, d)
            start, clock = clock, clock + seconds
            parts = []
            for i, (speaker, ld) in enumerate(spoken):
                words = _cell(ld.get("text"))
                if i < len(spoken) - 1 and not re.search(r"[.?!]$", words):
                    words += "."  # a label is only seen after a sentence end
                parts.append(f"{speaker.capitalize()}: {words}")
            notes = _cell(d.get("audio_notes"))
            audio = " ".join(parts + ([notes] if notes else [])) if parts else (notes or "No speech.")
            out.append(f"| {number} | {start:g}–{clock:g}s | {audio} | {_cell(d.get('picture'))} |")
    return "\n".join(out).strip() + "\n"
