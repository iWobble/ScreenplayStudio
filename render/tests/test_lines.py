"""A beat's lines: found by what they are, played by their order number, and set aside without being deleted."""

import json
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

from storyrender import lines, marvin_pull, ready
from tests.test_listen_pull import S, _FakeMarvin, _ROWS


def row(slug: str, **data) -> dict:
    return {"slug": slug, "dataJson": {"story": "s", "beat": "s-beat-01", "speaker": "narrator", **data}}


def test_a_line_is_a_record_of_the_story_with_a_beat_and_a_speaker_whatever_its_slug():
    assert lines.is_line(row("s-line-01-1"), "s")
    assert lines.is_line(row("beat-1-narrator-hello"), "s")  # a line added by hand has a slug Marvin made from its title
    assert not lines.is_line(row("x", story="other"), "s")  # another story's
    assert not lines.is_line({"slug": "s-beat-01", "dataJson": {"story": "s", "number": "01"}}, "s")  # a beat has no speaker
    assert not lines.is_line({"slug": "take", "dataJson": {"story": "s", "line": "s-line-01-1", "speaker": "x", "beat": "b"}}, "s")  # a take names its line


@pytest.mark.parametrize("value", [True, "true", "TRUE", "yes"])
def test_a_ticked_line_is_left_out(value):
    assert lines.is_left_out(row("a", leave_out=value))


@pytest.mark.parametrize("value", [False, "false", "", None, "no", 0])
def test_an_unticked_line_is_not(value):
    assert not lines.is_left_out(row("a", leave_out=value))


def test_numbered_lines_play_by_their_number_and_the_rest_follow_in_slug_order():
    rows = [row("s-line-01-3", text="c"), row("s-line-01-1", text="a"), row("new-one", order=1.5, text="mid"), row("s-line-01-2", order=2, text="two"), row("zz", order=1, text="one")]
    assert [r["dataJson"]["text"] for r in lines.of_story(rows, "s")] == ["one", "mid", "two", "a", "c"]


def test_a_number_that_is_not_one_counts_as_none():
    rows = [row("b", order="soon"), row("a", order=""), row("c", order=1)]
    assert [r["slug"] for r in lines.of_story(rows, "s")] == ["c", "a", "b"]


def test_a_line_set_aside_is_left_out_unless_asked_for():
    rows = [row("a"), row("b", leave_out=True)]
    assert [r["slug"] for r in lines.of_story(rows, "s")] == ["a"]
    assert [r["slug"] for r in lines.of_story(rows, "s", include_left_out=True)] == ["a", "b"]


def test_the_readiness_check_does_not_ask_for_a_voice_for_a_line_set_aside():
    story = {"world": "w", "setting": "x", "premise": "y"}
    base = dict(worlds={"w"}, characters=[], actors={}, voices={}, beats=[{"number": "01", "cast": "c"}], scenes=[], sounds=[])
    noisy = ready.check(story, lines=[{"speaker": "cook", "text": "Hi", "slug": "l"}], **base)
    quiet = ready.check(story, lines=[{"speaker": "cook", "text": "Hi", "slug": "l", "leave_out": True}], **base)
    assert any("cook" in text for _lv, _a, text in noisy) and not any("cook" in text for _lv, _a, text in quiet)


def test_pull_finds_a_line_added_by_hand_plays_numbered_lines_in_order_and_leaves_out_the_set_aside(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _FakeMarvin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rows = [dict(r) for r in _ROWS]
    beat = f"{S}-beat-01"
    rows += [
        {"slug": "a-line-made-by-hand", "dataJson": {"story": S, "beat": beat, "speaker": "cook", "text": "Made by hand.", "audio": "asset-1", "order": 0.5}},
        {"slug": f"{S}-line-01-2", "dataJson": {"story": S, "beat": beat, "speaker": "cook", "text": "Set aside.", "audio": "asset-1", "leave_out": True}},
    ]
    _FakeMarvin.rows = rows
    try:
        marvin_pull.pull(S, tmp_path, creds=(f"http://127.0.0.1:{server.server_port}", "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
        server.shutdown()
    shot = {s["id"]: s for s in json.loads((Path(tmp_path) / "manifest.json").read_text())["shots"]}["b01"]
    assert [ln["text"] for ln in shot["lines"]] == ["Made by hand.", "One."]  # the hand-made line (order 0.5) first, the numberless import line after; the one set aside is gone


def test_the_exported_fountain_has_a_hand_made_line_in_its_place_and_not_the_one_set_aside(tmp_path):
    from storyrender import script

    server = HTTPServer(("127.0.0.1", 0), _FakeMarvin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rows = [dict(r) for r in _ROWS]
    beat = f"{S}-beat-01"
    rows += [
        {"slug": "a-line-made-by-hand", "dataJson": {"story": S, "beat": beat, "speaker": "cook", "text": "Made by hand.", "order": 0.5}},
        {"slug": f"{S}-line-01-2", "dataJson": {"story": S, "beat": beat, "speaker": "cook", "text": "Set aside.", "leave_out": True}},
    ]
    _FakeMarvin.rows = rows
    try:
        records = script.pull_records(S, (f"http://127.0.0.1:{server.server_port}", "tok"))
        text = script.fountain(records)
    finally:
        _FakeMarvin.rows = _ROWS
        server.shutdown()
    assert "Made by hand." in text and "Set aside." not in text
    assert text.index("Made by hand.") < text.index("One.")  # numbered ahead of the import's own line, as it plays
