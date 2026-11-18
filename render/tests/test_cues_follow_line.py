"""A cue row follows its line (v221): a row names its line but is kept on the beat it was made on, so a line moved to another beat left its cues
behind. The pull and the complete script give each row to the beat that holds its line now; one whose line is gone stays put and is named."""

import json

from storyrender import lines, marvin_pull, script
from tests.test_listen_pull import _ROWS, S, _FakeMarvin, marvin  # noqa: F401

LINE_01, LINE_03 = f"{S}-line-01-1", f"{S}-line-03-1"


def _beat(slug: str, cues: list[dict]) -> dict:
    return {"slug": slug, "dataJson": {"cues": cues}}


def _line(slug: str, beat: str) -> dict:
    return {"slug": slug, "dataJson": {"story": S, "beat": beat, "speaker": "cook"}}


def test_each_row_goes_to_the_beat_that_holds_its_line_now():
    a, b = {"line": "l13", "word": 2, "sound": "clang"}, {"line": "l14", "word": 1, "camera": {"kind": "punch"}}
    gone = {"line": "lost", "word": 0, "sound": "x"}
    beats = [_beat("b13", [a, b, gone, "junk"]), _beat("b14", [])]
    rows, unknown = lines.cues_by_beat(beats, [_line("l13", "b13"), _line("l14", "b14")])
    assert rows == {"b13": [a, gone, "junk"], "b14": [b]} and unknown == [("b13", gone)]


def test_two_beats_with_their_own_cues_are_left_exactly_as_they_were():
    own13 = [{"line": "l13", "word": 2, "sound": "clang"}, {"line": "l13", "word": 2, "sound": "clang"}]  # the same row twice plays twice, as before
    own14 = [{"line": "l14", "word": 0, "look": {"kind": "flash"}}]
    beats = [_beat("b13", own13), _beat("b14", own14)]
    assert lines.cues_by_beat(beats, [_line("l13", "b13"), _line("l14", "b14")]) == ({"b13": own13, "b14": own14}, [])


def test_a_row_moved_in_after_the_beats_own_and_never_twice():
    mine, moved = {"line": "l14", "word": 0, "sound": "a"}, {"line": "l14", "word": 3, "sound": "b"}
    beats = [_beat("b13", [moved, mine]), _beat("b14", [mine])]  # `mine` was copied to b14 already: it is not added again
    assert lines.cues_by_beat(beats, [_line("l14", "b14")])[0] == {"b13": [], "b14": [mine, moved]}


def _pull(marvin, tmp_path, cues_01: list[dict], cues_03: list[dict]) -> tuple[dict, dict]:  # noqa: F811
    rows = [{**r, "dataJson": {**r["dataJson"], "cues": cues_01}} if r["slug"] == f"{S}-beat-01" else r for r in _ROWS]
    rows = [{**r, "dataJson": {**r["dataJson"], "cues": cues_03}} if r["slug"] == f"{S}-beat-03" else r for r in rows]
    rows.append({"slug": LINE_03, "dataJson": {"story": S, "beat": f"{S}-beat-03", "speaker": "narrator", "text": "Three, it said.", "audio": "asset-1"}})  # moved here
    _FakeMarvin.rows = rows
    try:
        pulled = marvin_pull.pull(S, tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    return pulled, {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}


def test_a_cue_left_on_the_old_beat_plays_in_the_shot_of_the_beat_its_line_moved_to(marvin, tmp_path):  # noqa: F811
    stale = {"line": LINE_03, "word": 1, "sound": f"{S}-sound-waves", "camera": {"kind": "punch"}, "look": {"kind": "flash"}}
    pulled, shots = _pull(marvin, tmp_path, [stale], [])
    assert [fx["line"] for fx in shots["b03"]["sfx"] if fx.get("line")] == [LINE_03]
    assert [c["line"] for c in shots["b03"]["camera_cues"]] == [LINE_03] and [c["line"] for c in shots["b03"]["look_cues"]] == [LINE_03]
    assert not any(fx.get("line") for fx in shots["b01"].get("sfx", [])) and "camera_cues" not in shots["b01"] and "cues_left_out" not in pulled


def test_a_cue_on_a_line_that_no_longer_exists_is_left_out_and_named(marvin, tmp_path):  # noqa: F811
    pulled, shots = _pull(marvin, tmp_path, [{"line": f"{S}-line-01-9", "word": 2, "sound": f"{S}-sound-waves"}], [])
    assert not any(fx.get("line") for s in shots.values() for fx in s.get("sfx", []))
    assert pulled["cues_left_out"] == [f"beat 01: a cue on {S}-line-01-9 word 2, a line no beat holds"]


def test_two_beats_with_their_own_cues_pull_as_before(marvin, tmp_path):  # noqa: F811
    pulled, shots = _pull(marvin, tmp_path, [{"line": LINE_01, "word": 1, "camera": {"kind": "shake"}}], [{"line": LINE_03, "word": 2, "camera": {"kind": "punch"}}])
    assert [c["kind"] for c in shots["b01"]["camera_cues"]] == ["shake"] and [c["kind"] for c in shots["b03"]["camera_cues"]] == ["punch"]
    assert "cues_left_out" not in pulled


def test_the_complete_script_writes_a_cue_with_its_line_wherever_the_row_was_left():
    stale = {"line": "s-line-02-1", "word": 1, "camera": {"kind": "punch"}}
    records = {
        "story": {"slug": "s", "title": "T", "dataJson": {}},
        "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Sparks.", "cues": [stale]}}, {"slug": "s-beat-02", "dataJson": {"number": "02", "picture": "Embers."}}],
        "lines": {"s-beat-01": [{"slug": "s-line-01-1", "dataJson": {"speaker": "smith", "text": "Strike it."}}], "s-beat-02": [{"slug": "s-line-02-1", "dataJson": {"speaker": "smith", "text": "Now cool it."}}]},
        "scenes": {}, "sounds": {}, "chapters": {}, "characters": [], "revisions": [],
    }  # fmt: skip
    text = script.fountain_complete(records)
    assert "Now [[Camera: punch]] cool it." in text and "Strike it." in text and text.count("[[Camera: punch]]") == 1
