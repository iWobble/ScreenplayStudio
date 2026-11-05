"""Chapters: where each one starts on the finished timeline, and the list YouTube reads from a video's description.

A long story is cut into chapters (Marvin's `chapter` entries; a beat names its own). A chapter starts at its first shot, so its marker is that
shot's start on the plan (`manifest.plan`), which is the same clock the render, the cut and the filmstrip use.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import manifest

YOUTUBE_MIN_CHAPTERS = 3
YOUTUBE_MIN_SECONDS = 10.0
"""YouTube turns the description's timestamps into chapters only for: a list starting at 0:00, at least three, each at least ten seconds."""


@dataclass
class Marker:
    id: str
    title: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return self.end - self.start


def markers(m: manifest.Manifest, timeline: manifest.Timeline | None = None) -> list[Marker]:
    """Each chapter, in the order it first appears, from its first shot to where the next chapter starts (or the video ends). Shots that
    name no chapter belong to the chapter before them; ones before the first chapter belong to none and are left out."""
    timeline = timeline or manifest.plan(m)
    titles = {c.id: c.title for c in m.chapters}
    found: list[Marker] = []
    for planned in timeline.shots:
        chapter = planned.shot.chapter
        if chapter and (not found or found[-1].id != chapter):
            if any(x.id == chapter for x in found):  # a chapter's beats must be together; a stray beat does not start it again
                continue
            if found:
                found[-1].end = planned.start
            found.append(Marker(chapter, titles.get(chapter, chapter), planned.start, timeline.duration))
    return found


def stamp(seconds: float) -> str:
    """YouTube's form: m:ss, or h:mm:ss from an hour."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def youtube(found: list[Marker], intro: str = "Intro") -> tuple[str, list[str]]:
    """The description lines ("0:00 Title"), and what would stop YouTube using them as chapters (empty when it will). A video whose first
    chapter starts after 0:00 gets an `intro` line at 0:00, because the list has to start there."""
    if not found:
        return "", []
    rows = [(x.start, x.title, x.seconds) for x in found]
    if rows[0][0] > 0:
        rows.insert(0, (0.0, intro, rows[0][0]))
    notes = []
    if len(rows) < YOUTUBE_MIN_CHAPTERS:
        notes.append(f"YouTube needs at least {YOUTUBE_MIN_CHAPTERS} chapters (this has {len(rows)}).")
    for _, title, length in rows:
        if length < YOUTUBE_MIN_SECONDS:
            notes.append(f"“{title}” is {length:.0f} s; YouTube wants each chapter to be at least {YOUTUBE_MIN_SECONDS:.0f} s.")
    return "\n".join(f"{stamp(start)} {title}" for start, title, _ in rows), notes
