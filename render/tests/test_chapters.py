"""Chapters: the chapter list a story's beats name, where each starts on the plan, and the YouTube description lines."""

import json

from storyrender import chapters, manifest, marvin_pull


def _manifest(tmp_path, shots, chapter_list=None):
    raw = {"shots": shots, **({"chapters": chapter_list} if chapter_list else {})}
    (tmp_path / "manifest.json").write_text(json.dumps(raw))
    return manifest.load(tmp_path / "manifest.json", probe=lambda _p: 0.0, need_stills=False)


def _shot(id, chapter=None, hold=10.0):
    return {"id": id, "hold": hold, "lines": [], **({"chapter": chapter} if chapter else {})}


def test_the_manifest_carries_the_chapter_list_and_each_shots_chapter(tmp_path):
    m = _manifest(tmp_path, [_shot("b01", "s-chapter-1"), _shot("b02")], [{"id": "s-chapter-1", "title": "The Voyage"}])
    assert [(c.id, c.title) for c in m.chapters] == [("s-chapter-1", "The Voyage")]
    assert [s.chapter for s in m.shots] == ["s-chapter-1", None]


def test_a_chapter_starts_at_its_first_shot_and_runs_to_the_next(tmp_path):
    shots = [_shot("b01", "c1"), _shot("b02", "c1"), _shot("b03", "c2", 20), _shot("b04", "c2")]
    found = chapters.markers(_manifest(tmp_path, shots, [{"id": "c1", "title": "One"}, {"id": "c2", "title": "Two"}]))
    assert [(x.title, x.start, x.end) for x in found] == [("One", 0.0, 20.0), ("Two", 20.0, 50.0)]


def test_a_story_without_chapters_has_no_markers(tmp_path):
    assert chapters.markers(_manifest(tmp_path, [_shot("b01"), _shot("b02")])) == []


def test_youtube_lines_start_at_zero_use_hours_from_an_hour_and_say_what_would_stop_them(tmp_path):
    shots = [_shot("b01"), _shot("b02", "c1", 30), _shot("b03", "c2", 4000), _shot("b04", "c3", 5)]
    found = chapters.markers(_manifest(tmp_path, shots, [{"id": "c1", "title": "A"}, {"id": "c2", "title": "B"}, {"id": "c3", "title": "C"}]))
    text, notes = chapters.youtube(found)
    assert text.splitlines() == ["0:00 Intro", "0:10 A", "0:40 B", "1:07:20 C"]
    assert len(notes) == 1 and "“C” is 5 s" in notes[0]
    assert chapters.youtube(found[:1])[1][0].startswith("YouTube needs at least 3 chapters")
    assert chapters.youtube([]) == ("", [])


def test_chapter_rows_are_this_storys_in_number_order():
    data = lambda e: e["d"]  # noqa: E731
    rows = [
        {"slug": "s-chapter-10", "title": "Ten", "d": {"story": "s", "number": "10"}},
        {"slug": "s-chapter-2", "title": "Two", "d": {"story": "s", "number": "2"}},
        {"slug": "t-chapter-1", "title": "Other story", "d": {"story": "t", "number": "1"}},
        {"slug": "s-beat-1", "title": "A beat", "d": {"story": "s", "number": "1"}},
    ]
    assert marvin_pull.chapter_rows(rows, "s", data) == [{"id": "s-chapter-2", "title": "Two"}, {"id": "s-chapter-10", "title": "Ten"}]
