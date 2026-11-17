"""The complete script drops nothing (v204): the writer's own notes, in the front matter and in each picture, are written back where they stood, a
picture with a Pic note has no page break above it (the note starts it), and what the export says of a scene and a beat in its own notes is read
back. Measured on The Flash as the owner brought it in (data/flash_imported.fountain)."""

import re
from pathlib import Path

from storyrender import fountain, script, validate
from tests.test_beat_notes import _made
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)

FLASH = (Path(__file__).parent / "data" / "flash_imported.fountain").read_text(encoding="utf-8")
WRITERS = ("Production", "Visual style", "Continuity", "Timing", "Sentence", "Silent on purpose")


def _records(fake) -> dict:
    """The records the import made, with what it wrote on the story (its front matter, as written)."""
    records = _made(fake)
    for slug, body in fake.patched:
        if slug == "e0":
            records["story"]["dataJson"].update(body["dataJson"])
    return records


def _cut(text: str) -> fountain.Plan:
    return fountain.cut(fountain.parse(text, lines=True), text=text, speakers=set())


def _own_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if re.fullmatch(r"\s*\[\[(?:(?!\]\]).)*\]\]\s*", ln)]


def _exported(casting) -> tuple[dict, str]:
    fake, ctx = casting(FLASH)
    run(ctx)
    records = _records(fake)
    return records, script.fountain_complete(records)


def test_the_flash_as_brought_in_has_the_notes_this_release_is_about():
    notes = _own_lines(FLASH)
    counts = {kind: sum(1 for n in notes if n.startswith(f"[[{kind}:")) for kind in (*WRITERS, "Pic", "Hold")}
    assert counts == {"Production": 1, "Visual style": 1, "Continuity": 1, "Timing": 1, "Sentence": 16, "Silent on purpose": 6, "Pic": 22, "Hold": 6}


def test_every_note_the_writer_wrote_is_in_the_complete_script_with_its_words(casting):
    _records_, text = _exported(casting)
    written = _own_lines(text)
    for note in _own_lines(FLASH):
        if note.startswith(tuple(f"[[{kind}:" for kind in WRITERS)) or note.startswith("[[Pic:"):
            assert written.count(note) == 1, note  # once each, as written
    holds = sorted(re.search(r"Hold: ([\d.]+s)", n)[1] for n in _own_lines(FLASH) if n.startswith("[[Hold:"))
    assert sorted(h for n in written if n.startswith("[[Beat ") for h in re.findall(r"\bHold: ([\d.]+s)\.", n)) == holds  # the export's own, once each
    assert not [n for n in written if n.startswith("[[Hold:")]
    front = text.split("\n\n", 2)[1]  # the notes under the title page, in their order
    assert front.split("\n") == [n for n in _own_lines(FLASH)[:4]]


def test_each_note_stays_in_its_own_picture_in_its_place_and_the_pictures_cut_the_same(casting):
    _records_, text = _exported(casting)
    before, after = _cut(FLASH), _cut(text)
    shape = lambda plan: [(b["picture"], b.get("direction"), [ln["text"] for ln in b["lines"]]) for _c, _n, b in plan.rows()]  # noqa: E731
    assert shape(after) == shape(before)
    keep = lambda plan: [[n for n in _own_lines(b.get("fountain") or "") if n.startswith(tuple(f"[[{k}:" for k in WRITERS))] for _c, _n, b in plan.rows()]  # noqa: E731
    assert keep(after) == keep(before)  # each in the same picture, in the same order
    third = next(b for _c, n, b in after.rows() if n == "03")["fountain"]
    assert re.search(r"\[\[Pic: Medium side view[^\n]*\]\]\n\[\[Silent on purpose: the ships have crossed the edge", third)  # under its Pic note, as written


def test_no_page_break_above_a_picture_with_a_pic_note_and_one_above_a_picture_without(casting):
    records, text = _exported(casting)
    assert "===" not in text  # every picture of The Flash has its Pic note: 21 page breaks in v203
    records["beats"][4]["dataJson"].pop("direction")
    lines = script.fountain_complete(records).split("\n")
    breaks = [i for i, ln in enumerate(lines) if ln == "==="]
    assert len(breaks) == 1 and not lines[breaks[0] + 2].startswith("[[Pic:")  # the one picture with no direction keeps its page break


def test_a_complete_script_brought_in_again_gives_the_same_beats_scenes_holds_cards_and_changes(casting):
    records, _text = _exported(casting)
    beats = [b["dataJson"] for b in records["beats"]]
    beats[0].update(focus="The red-striped ship.", expression="", info_label="CHAPTER 4", info_title="2302")
    beats[3].update(focus="The rocket's flame.", expression="Nobody is in frame.", changes="The Hesperos is gone from here on.")
    slug, scene = next((s, r["dataJson"]) for s, r in records["scenes"].items())
    scene.update(look="Cold starlight from one side.", set_dressing="Three ships, a far blue Neptune.", continuity="Stripes: red Hesperos, two orange.")
    text = script.fountain_complete(records)
    again, ctx = casting(text)
    run(ctx)
    got = _made(again)
    keys = ("picture", "direction", "hold_seconds", "info_label", "info_title", "info_text", "changes", "focus", "expression")
    assert [{k: b["dataJson"].get(k) or None for k in keys} for b in got["beats"]] == [{k: d.get(k) or None for k in keys} for d in beats]
    made = got["scenes"][slug]
    assert len(got["scenes"]) == len(records["scenes"])
    assert {k: made["dataJson"].get(k) for k in ("look", "set_dressing", "continuity")} == {k: scene[k] for k in ("look", "set_dressing", "continuity")}
    assert _own_lines(script.fountain_complete(_records(again)))[:4] == _own_lines(FLASH)[:4]  # and the front matter's notes once more


def test_a_scene_note_fills_only_an_empty_field_of_the_scene_it_names(casting):
    from tests.test_fountain_transitions import _settle

    records, _text = _exported(casting)
    scene = next(iter(records["scenes"].values()))
    scene["dataJson"].update(set_dressing="Three ships.", continuity="Stripes.")
    text = script.fountain_complete(records)
    fake, ctx = casting(text)
    run(ctx)
    _settle(fake)
    fake.on_hand["scene"][scene["slug"]]["dataJson"].update(continuity="Set by hand.", set_dressing="")
    run(ctx, mode="refresh")
    patched = {slug: body["dataJson"] for slug, body in fake.patched if slug == f"id-{scene['slug']}"}
    assert patched[f"id-{scene['slug']}"]["set_dressing"] == "Three ships." and patched[f"id-{scene['slug']}"]["continuity"] == "Set by hand."
    assert fountain.scene_note("[[Scene Bridge. Light: Night.]]") == ("Bridge", {"look": "Night."})
    named = "EXT. INTERSTELLAR SPACE - 2302\n\n[[Scene The Bridge. Light: Dim.]]\n\nShips.\n"
    assert fountain.scenes_said(_cut(named)) == {}  # a note naming another scene is not read into this one


def test_a_beat_or_scene_note_that_does_not_read_exactly_is_only_a_note_and_the_check_says_so():
    assert fountain.labelled("Hold: 2s. Focus: the coin. Expression: proud.", fountain.BEAT_LABELS) == {"Hold": "2s.", "Focus": "the coin.", "Expression": "proud."}
    assert fountain.labelled("Focus: a. Focus: b.", fountain.BEAT_LABELS) is None  # twice
    assert fountain.labelled("Expression: a. Focus: b.", fountain.BEAT_LABELS) is None  # out of order
    assert fountain.labelled("Look at this. Focus: b.", fountain.BEAT_LABELS) is None  # words before the first
    assert fountain.beat_note_fields("[[Beat 07. Focus: a. Focus: b.]]") == {}
    text = "Title: X\n\nEXT. DECK - NIGHT\n\n[[Scene Deck. Light: Night. Place: Deck.]]\n\nRain.\n\n[[Beat 01. Expression: wet. Focus: rain.]]\n\n[[Beat 02. Cast: s-a.]]\n"
    found = [(f.line, f.code, f.level) for f in validate.check(text) if f.code.endswith("note-unread")]
    assert found == [(5, "scene-note-unread", "look"), (9, "beat-note-unread", "look")]
    assert not [f for f in validate.check(FLASH) if f.code.endswith("note-unread")]


def test_a_story_with_no_text_of_its_own_and_no_directions_exports_as_before():
    from tests.test_beat_notes import DATA
    from tests.test_script import RECORDS

    assert script.fountain_complete(RECORDS) == (DATA / "records.fountain").read_text(encoding="utf-8")  # as v200 to v203 wrote it
