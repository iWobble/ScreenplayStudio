"""A Pic note on a line of its own (`[[Pic: Close on the coin in her fist.]]`) starts the next picture as a page break does, and its words are that
beat's Shot direction. Every other Fountain app reads it as a note and ignores it."""

import shutil

import pytest

from storyrender import fountain, script, validate
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_fountain_transitions import _beats, _patched, _records, _settle

BROKEN = """Title: Coin

EXT. DECK - NIGHT

Rain lashes the deck.

VALERIE
Hold the wheel.

===

Chet grips the wheel.

CHET
I've got it.

===

VALERIE
Then hold it.

===

A gold coin glints in her fist.
"""

DIRECTED = """Title: Coin

EXT. DECK - NIGHT

[[Pic: Wide on the deck in the rain.]]
Rain lashes the deck.

VALERIE
Hold the wheel.

[[Pic: Medium on Chet at the wheel.]]
Chet grips the wheel.

CHET
I've got it.

[[Pic: Close on Valerie.]]
VALERIE
Then hold it.

[[pic: close on the coin in her fist.]]
A gold coin glints in her fist.
"""


def _cut(text: str) -> fountain.Plan:
    return fountain.cut(fountain.parse(text, lines=True), text=text, speakers=set())


def _shape(plan: fountain.Plan) -> list:
    return [(n, b["picture"], [ln["text"] for ln in b["lines"]]) for _c, n, b in plan.rows()]


def _directions(text: str) -> list:
    return [b.get("direction") for _c, _n, b in _cut(text).rows()]


def test_pic_notes_alone_cut_the_same_pictures_and_lines_as_page_breaks():
    assert _shape(_cut(DIRECTED)) == _shape(_cut(BROKEN))
    assert len(_cut(DIRECTED).rows()) == 4
    assert _shape(fountain.cut(fountain.parse(DIRECTED))) == _shape(fountain.cut(fountain.parse(BROKEN)))  # read without line numbers too


def test_each_picture_takes_its_own_notes_words_as_its_shot_direction_and_its_own_text_keeps_the_note():
    plan = _cut(DIRECTED)
    assert _directions(DIRECTED) == ["Wide on the deck in the rain.", "Medium on Chet at the wheel.", "Close on Valerie.", "close on the coin in her fist."]
    pieces = [b["fountain"] for _c, _n, b in plan.rows()]
    assert pieces[1].startswith("[[Pic: Medium on Chet at the wheel.]]\nChet grips")  # the note opens the beat it directs, as written
    assert pieces[3].startswith("[[pic: close on the coin in her fist.]]")
    assert all(b.get("direction") is None for _c, _n, b in _cut(BROKEN).rows())  # a page break directs nothing


def test_shot_words_in_capitals_stay_in_the_picture_beside_a_pic_direction():
    text = DIRECTED.replace("Chet grips the wheel.", "UNDER THE WHEEL\n\nChet grips the wheel.")
    beat = _cut(text).rows()[1][2]
    assert beat["direction"] == "Medium on Chet at the wheel."
    assert beat["picture"].startswith("UNDER THE WHEEL Chet grips")  # read as action, as before: nothing fills Shot direction from capitals


def test_a_pic_note_and_a_page_break_together_are_one_break_in_either_order():
    for together in ("===\n\n[[Pic: Medium on Chet at the wheel.]]", "[[Pic: Medium on Chet at the wheel.]]\n\n===\n"):
        text = DIRECTED.replace("[[Pic: Medium on Chet at the wheel.]]", together)
        assert _shape(_cut(text)) == _shape(_cut(BROKEN))
        assert _directions(text)[1] == "Medium on Chet at the wheel."


def test_two_pic_notes_together_make_one_picture_that_takes_the_first_and_the_check_says_the_second_is_ignored():
    text = DIRECTED.replace("[[Pic: Medium on Chet at the wheel.]]", "[[Pic: Medium on Chet at the wheel.]]\n\n[[Pic: Over his shoulder.]]")
    assert _shape(_cut(text)) == _shape(_cut(BROKEN))
    assert _directions(text)[1] == "Medium on Chet at the wheel."
    twice = [f for f in validate.check(text) if f.code == "pic-twice"]
    assert [(f.line, f.level) for f in twice] == [(text.split("\n").index("[[Pic: Over his shoulder.]]") + 1, "look")]
    assert not [f for f in validate.check(DIRECTED) if f.code.startswith("pic")]


def test_a_pic_note_under_a_heading_or_above_it_directs_the_scenes_first_picture_and_makes_no_empty_one():
    plan = _cut(DIRECTED)
    assert plan.rows()[0][2]["picture"] == "Exterior: Deck, night. Rain lashes the deck."  # the heading and its first action, as with no note
    above = "# 01 Storm\n\n[[Pic: Wide on the deck in the rain.]]\n\nEXT. DECK - NIGHT\n\nRain lashes the deck.\n\n# 02 Calm\n\n[[Pic: Wide on still water.]]\nEXT. SEA - DAWN\n\nThe sea lies flat.\n"
    plan = _cut(above)
    assert [(c.number, c.title, len(c.beats)) for c in plan.chapters] == [(1, "Storm", 1), (2, "Calm", 1)]  # the sections still start the chapters
    assert [b["direction"] for _c, _n, b in plan.rows()] == ["Wide on the deck in the rain.", "Wide on still water."]
    assert fountain.chapter_texts(above, plan) is not None
    first = "[[Pic: Wide on the deck in the rain.]]\n\nEXT. DECK - NIGHT\n\nRain lashes the deck.\n"
    assert [b["direction"] for _c, _n, b in _cut(first).rows()] == ["Wide on the deck in the rain."] and len(_cut(first).rows()) == 1


def test_a_pic_note_with_nothing_after_it_or_before_a_fade_out_makes_no_picture():
    for end in ("\n[[Pic: The sea, empty.]]\n", "\n[[Pic: The sea, empty.]]\n\nFADE OUT.\n"):
        plan = _cut(DIRECTED + end)
        assert _shape(plan) == _shape(_cut(DIRECTED))
    assert _cut(DIRECTED + "\n[[Pic: The sea, empty.]]\n\nFADE OUT.\n").end_transition == "fade"


def test_a_pic_note_after_a_speech_and_its_blank_line_is_the_one_boundary_before_the_action():
    text = "EXT. DECK - NIGHT\n\nRain.\n\nVALERIE\nHold the wheel.\n\n[[Pic: Close on the wheel.]]\nChet grips the wheel.\n"
    plan = _cut(text)
    assert [(b["picture"], b.get("direction")) for _c, _n, b in plan.rows()] == [("Exterior: Deck, night. Rain.", None), ("Chet grips the wheel.", "Close on the wheel.")]


def test_a_pic_note_inside_a_speech_is_a_picture_that_comes_in_at_that_word_and_is_never_spoken():
    # (until v211 it stayed a note and the check said so; now it is a cue on the word: see test_word_cues.py)
    text = "EXT. DECK - NIGHT\n\nRain.\n\nVALERIE\nHold the wheel.\n[[Pic: Close on her.]]\n\nChet grips the wheel.\n"
    plan = _cut(text)
    assert [(n, len(b["lines"]), b.get("direction"), b.get("starts_during")) for _c, n, b in plan.rows()] == [("01", 1, None, None), ("01a", 0, "Close on her.", {"line": 1, "word": 3}), ("02", 0, None, None)]
    assert plan.rows()[0][2]["lines"][0]["text"] == "Hold the wheel."  # never spoken
    assert not [f for f in validate.check(text) if f.code == "pic-unread"]


def test_other_notes_are_still_only_notes_and_hold_and_sound_still_act():
    text = DIRECTED.replace("Rain lashes the deck.", "Rain lashes the deck. [[Pic: inline, not on its own line]]\n[[One picture: the whole storm.]]\n[[Silent on purpose: no music.]] [[Hold: 4s.]] [[Sound: thunder.]]")
    plan = _cut(text)
    assert _shape(plan) == _shape(_cut(DIRECTED))
    first = plan.rows()[0][2]
    assert first["direction"] == "Wide on the deck in the rain."
    assert [s["prompt"] for s in first["sounds"]] == ["thunder"]
    assert "One picture" not in first["picture"] and "Pic" not in first["picture"]
    assert [f.code for f in validate.check(text) if f.code.startswith("pic")] == ["pic-unread"]  # the one written inside a line


def test_the_check_accepts_pic_notes_and_only_looks_at_a_long_or_unreadable_one():
    assert not validate.blocking(validate.check(DIRECTED))
    long_ = DIRECTED.replace("Close on Valerie.", "Close on Valerie " + "and the rain " * 40 + ".")
    found = validate.check(long_)
    assert [f.level for f in found if f.code == "pic-long"] == ["look"] and not validate.blocking(found)
    assert _directions(long_)[2].startswith("Close on Valerie and the rain")  # still read: only said
    open_ = DIRECTED.replace("[[Pic: Close on Valerie.]]", "[[Pic: Close on\n\nValerie.]]")
    codes = {(f.code, f.level) for f in validate.check(open_)}
    assert ("pic-unread", "look") in codes and ("note-open", "error") in codes  # a note left open has always stopped the import; the Pic adds only a look


def test_rewording_only_a_pic_note_is_no_revision_and_adding_one_cuts_a_picture_as_a_page_break_does():
    made = {n: b["fountain"] for _c, n, b in _cut(DIRECTED).rows()}
    reworded = _cut(DIRECTED.replace("Medium on Chet at the wheel.", "Low angle on Chet, hands white on the spokes."))
    assert fountain.align(reworded, made) == {"same": 4, "reworded": 0, "new": [], "removed": []}
    added = DIRECTED.replace("A gold coin glints in her fist.", "A gold coin glints in her fist.\n\n[[Pic: The sea.]]\nThe sea swallows the light.")
    found = fountain.align(_cut(added), made)
    assert found["same"] == 4 and found["new"] == ["04a"]  # numbered after the beat before it, as a new picture always is


def test_the_import_gives_a_new_beat_its_direction_fills_an_empty_one_and_keeps_one_set_by_hand(casting):
    fake, ctx = casting(DIRECTED)
    run(ctx)
    assert [b.get("direction") for b in _beats(fake).values()] == _directions(DIRECTED)
    _settle(fake)
    fake.records["s-beat-01"]["dataJson"]["direction"] = "Crane down onto the deck."  # by hand
    fake.records["s-beat-02"]["dataJson"].pop("direction")  # made before the import read Pic notes
    fake.story["dataJson"]["fountain"] = DIRECTED.replace("Close on Valerie.", "Close on Valerie, soaked.")
    run(ctx, mode="refresh")
    changed = _patched(fake)
    assert "direction" not in changed.get("01", {}) and changed["02"]["direction"] == "Medium on Chet at the wheel."
    assert "direction" not in changed.get("03", {})  # a direction the beat holds is never written over


def test_a_story_brought_in_with_page_breaks_gets_the_directions_when_the_pic_version_comes_in(casting):
    fake, ctx = casting(BROKEN)
    run(ctx)
    _settle(fake)
    fake.story["dataJson"]["fountain"] = DIRECTED
    done = run(ctx)
    assert done["result"]["beats_made"] == 0  # the same pictures: nothing new, nothing renumbered
    assert {n: d.get("direction") for n, d in _patched(fake).items()} == dict(zip(["01", "02", "03", "04"], _directions(DIRECTED), strict=True))


def test_a_beat_reworded_and_given_a_direction_in_one_refresh_keeps_both(casting):
    fake, ctx = casting(DIRECTED)
    run(ctx)
    _settle(fake)
    fake.records["s-beat-02"]["dataJson"].pop("direction")
    fake.story["dataJson"]["fountain"] = DIRECTED.replace("Chet grips the wheel.", "Chet grips the wheel hard.")
    run(ctx, mode="refresh")
    last = [body["dataJson"] for slug, body in fake.patched if slug == "id-s-beat-02"][-1]
    assert last["picture"].startswith("Chet grips the wheel hard.") and last["direction"] == "Medium on Chet at the wheel."


def test_the_complete_script_writes_each_direction_as_a_pic_note_and_comes_back_as_the_same_pictures(casting):
    fake, ctx = casting(DIRECTED)
    run(ctx)
    _settle(fake)
    text = script.fountain_complete(_records(fake))
    assert "[[Pic: Medium on Chet at the wheel.]]" in text and text.count("[[Pic:") == 4
    again, ctx2 = casting(text)
    run(ctx2)
    before = [(r["dataJson"]["picture"], r["dataJson"].get("direction")) for r in _records(fake)["beats"]]
    assert [(b["picture"], b.get("direction")) for b in _beats(again).values()] == before


@pytest.mark.skipif(shutil.which("screenplain") is None, reason="screenplain not installed")
def test_a_pic_note_never_prints_in_the_script(tmp_path):
    made = script.render(DIRECTED, tmp_path, "coin")
    html = made["html"].read_text()
    assert "Pic" not in html and "Medium on Chet" not in html
    assert "VALERIE" in html and "Then hold it." in html  # the speech under a note is still a speech
