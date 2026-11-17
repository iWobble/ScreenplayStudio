"""A picture's info card and what stays changed from it on travel in the Fountain as notes the import reads (v201): `[[Info card: label | title |
sentence]]` and `[[Changes: …]]`, each on a line of its own inside the picture's text. The complete script writes them, and no longer writes a
beat's heading as its action when the heading is all its picture says, so a story exported and brought in again is the same story."""

from pathlib import Path

import pytest

from storyrender import fountain, numbering, script, validate
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)

DATA = Path(__file__).parent / "data" / "complete-v200"

FLASH = """Title: The Flash
Credit: Written by
Author: A Writer

EXT. INTERSTELLAR SPACE - 2302

[[Info card: CHAPTER 4 | 2302]]
[[Pic: Wide on three generation ships against the stars.]]

NARRATOR (V.O.)
Three ships left the old sun behind.

[[Pic: Close on the lead ship's hull.]]

NARRATOR (V.O.)
The first carried the seed vaults.

[[Changes: The lead ship's hull is scorched black.]]

[[Pic: A flash of white light.]]
A white flash swallows the stars.

[[Info card: | Day one | The fleet is alone.]]

INT. BRIDGE - 2302

[[Pic: Medium on the empty bridge.]]

NARRATOR (V.O.)
Nobody was at the helm.

> THE END <
"""
FIELDS = ("picture", "direction", "info_label", "info_title", "info_text", "changes", "shows")


def _made(fake) -> dict:
    """The records an import made, as the complete script reads them."""
    made = lambda t: [{"slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]} for m in fake.made if m["entryTypeId"] == t]  # noqa: E731
    lines: dict = {}
    for m in made("T-line"):
        lines.setdefault(m["dataJson"].get("beat"), []).append(m)
    beats = sorted(made("T-beat"), key=lambda m: numbering.order_key(m["dataJson"].get("number")))
    return {"story": {"slug": "s", "title": "The Flash", "dataJson": {}}, "beats": beats, "lines": lines, "scenes": {m["slug"]: m for m in made("T-scene")},
            "sounds": {m["slug"]: m for m in made("T-sound")}, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip


def _beats(records: dict) -> list[tuple]:
    return [tuple(b["dataJson"].get(k) for k in FIELDS) for b in records["beats"]]


def test_the_import_reads_the_info_card_and_the_changes_into_the_picture_they_sit_in(casting):
    fake, ctx = casting(FLASH)
    run(ctx)
    beats = {b["dataJson"]["number"]: b["dataJson"] for b in _made(fake)["beats"]}
    assert [n for n in beats] == ["01", "02", "03", "04", "05"]  # the notes start and end no picture
    assert {k: beats["01"].get(k) for k in fountain.INFO_CARD_FIELDS} == {"info_label": "CHAPTER 4", "info_title": "2302", "info_text": None}
    assert beats["02"]["changes"] == "The lead ship's hull is scorched black." and "changes" not in beats["01"] and "changes" not in beats["03"]
    assert (beats["03"].get("info_label"), beats["03"]["info_title"], beats["03"]["info_text"]) == (None, "Day one", "The fleet is alone.")
    assert beats["05"]["shows"] == "Plain card" and beats["05"]["info_title"] == "THE END"
    assert all("Info card" not in d.get("picture", "") and "Changes" not in d.get("picture", "") for d in beats.values())


def test_one_slot_is_the_title_two_are_the_label_and_title_and_a_card_with_no_words_is_none():
    assert fountain.info_card("2302") == {"info_title": "2302"}
    assert fountain.info_card(" CHAPTER 4 |  2302 ") == {"info_label": "CHAPTER 4", "info_title": "2302"}
    assert fountain.info_card("| | The fleet is alone | for good") == {"info_text": "The fleet is alone | for good"}  # a bar after the second is the sentence's
    assert fountain.info_card(" | | ") == {} and fountain.info_card("") == {}


def test_a_note_inside_a_speech_inline_or_with_no_words_is_only_a_note_and_the_check_says_so():
    text = FLASH.replace("Three ships left the old sun behind.", "Three ships left the old sun behind.\n[[Changes: said inside the speech]]").replace(
        "A white flash swallows the stars.", "A white flash swallows the stars. [[Info card: inline]]\n\n[[Info card: | ]]\n\n[[Changes:   ]]"
    )
    plan = fountain.cut(fountain.parse(text, lines=True), text=text, speakers=set())
    noted = [fountain.beat_notes(b.get("fountain") or "") for _c, _n, b in plan.rows()]
    assert noted[0] == {"info_label": "CHAPTER 4", "info_title": "2302"} and noted[2] == {"info_title": "Day one", "info_text": "The fleet is alone."}
    found = [(f.code, f.level) for f in validate.check(text) if f.code in ("info-card-unread", "changes-unread")]
    assert sorted(found) == [("changes-unread", "look"), ("changes-unread", "look"), ("info-card-unread", "look"), ("info-card-unread", "look")]
    assert not [f for f in validate.check(FLASH) if f.code.endswith("-unread")] and not validate.blocking(validate.check(text))
    lines = text.split("\n")
    assert {f.line for f in validate.check(text) if f.code == "changes-unread"} == {lines.index("[[Changes: said inside the speech]]") + 1, lines.index("[[Changes:   ]]") + 1}


def test_the_import_fills_an_empty_field_and_never_writes_over_one_set_by_hand(casting):
    from tests.test_fountain_transitions import _patched, _settle

    fake, ctx = casting(FLASH)
    run(ctx)
    _settle(fake)
    fake.records["s-beat-01"]["dataJson"]["info_text"] = "Set by hand."  # a card a person changed: the note's card is not mixed into it
    for key in fountain.INFO_CARD_FIELDS:
        fake.records["s-beat-03"]["dataJson"].pop(key, None)  # made before the import read Info card notes
    fake.records["s-beat-02"]["dataJson"]["changes"] = "The hull is gone."  # by hand
    fake.story["dataJson"]["fountain"] = FLASH.replace("Nobody was at the helm.", "Nobody at all was at the helm.")
    run(ctx, mode="refresh")
    changed = _patched(fake)
    assert not set(fountain.INFO_CARD_FIELDS) & set(changed.get("01", {})) and "changes" not in changed.get("02", {})
    assert (changed["03"]["info_title"], changed["03"]["info_text"]) == ("Day one", "The fleet is alone.")
    assert fountain.notes_to_fill({"changes": ""}, "[[Changes: Scorched.]]") == {"changes": "Scorched."}
    assert fountain.notes_to_fill({"shows": "Plain card", "info_title": "THE END"}, "[[Info card: X | Y]]") == {}  # a card's own words come first


def test_the_complete_script_writes_the_two_notes_once_and_reads_back_as_the_same_beats(casting):
    fake, ctx = casting(FLASH)
    run(ctx)
    records = _made(fake)
    text = script.fountain_complete(records)
    assert text.count("[[Info card: CHAPTER 4 | 2302]]") == 1 and text.count("[[Info card: | Day one | The fleet is alone.]]") == 1
    assert text.count("[[Changes: The lead ship's hull is scorched black.]]") == 1
    assert "Info card:" not in "".join(ln for ln in text.split("\n") if ln.startswith("[[Beat "))  # one place, not two
    assert "> THE END <" in text and text.count("[[Info card:") == 2  # a plain card's words are centred, with no note
    again, ctx2 = casting(text)
    run(ctx2)
    assert _beats(_made(again)) == _beats(records)


def test_a_beat_whose_picture_is_only_its_heading_writes_no_action_and_comes_back_the_same(casting):
    fake, ctx = casting(FLASH)
    run(ctx)
    records = _made(fake)
    pictures = [b["dataJson"].get("picture") for b in records["beats"]]
    assert pictures[0].startswith("Exterior: Interstellar Space - 2302") and pictures[1].startswith("EXT. INTERSTELLAR SPACE - 2302")  # as the import makes them
    text = script.fountain_complete(records)
    actions = [ln for ln in text.split("\n") if ln and not ln.startswith(("[[", "EXT.", "INT.", "NARRATOR", ">", "===", "Title:", "Credit:", "Author:", "("))]
    assert sorted(actions) == sorted(["A white flash swallows the stars.", "Three ships left the old sun behind.", "The first carried the seed vaults.", "Nobody was at the helm."])
    assert "!EXT." not in text and "Exterior:" not in text
    again, ctx2 = casting(text)
    run(ctx2)
    assert [b["dataJson"].get("picture") for b in _made(again)["beats"]] == pictures


SCENE = {"slug": "s-interstellar-space-2302", "title": "Interstellar Space - 2302", "dataJson": {}}


@pytest.mark.parametrize("picture", [
    "Exterior: Interstellar Space - 2302", "exterior: interstellar space - 2302.", "EXT. INTERSTELLAR SPACE - 2302", "EXT. INTERSTELLAR SPACE - 2302 #3#",
    ".INTERSTELLAR SPACE - 2302", "ext interstellar space - 2302", "Interior and exterior: Interstellar  Space - 2302",
])  # fmt: skip
def test_the_heading_in_any_of_its_forms_is_only_a_heading(picture):
    assert script._heading_only(picture, SCENE, SCENE["slug"])


@pytest.mark.parametrize("picture", ["EXT. INTERSTELLAR SPACE - 2302, a wide shot of the fleet", "Exterior: the fleet burns", "Interstellar Space - 2302",
                                     "EXT. DECK - NIGHT", "Three ships cross interstellar space."])  # fmt: skip
def test_a_picture_with_words_of_its_own_or_another_place_is_kept(picture):
    assert not script._heading_only(picture, SCENE, SCENE["slug"])


def test_the_heading_with_a_time_of_day_in_words_is_only_a_heading():
    hold = {"slug": "s-hold", "title": "Hold", "dataJson": {}}
    assert script._heading_only("Interior: Hold, night", hold, "s-hold") and script._heading_only("INT. HOLD - NIGHT", hold, "s-hold")
    assert script._heading_only("Interior: Captain's Cabin, night", {"title": "Captain’s Cabin"}, "s-captains-cabin")


@pytest.mark.parametrize(("card", "note"), [
    ({"info_title": "2302"}, "[[Info card: 2302]]"),
    ({"info_label": "CHAPTER 4", "info_title": "2302"}, "[[Info card: CHAPTER 4 | 2302]]"),
    ({"info_label": "CHAPTER 4", "info_title": "2302", "info_text": "The fleet is alone."}, "[[Info card: CHAPTER 4 | 2302 | The fleet is alone.]]"),
    ({"info_text": "The fleet is alone."}, "[[Info card: | | The fleet is alone.]]"),
    ({"info_label": "CHAPTER 4"}, "[[Info card: CHAPTER 4 |]]"),
    ({"info_label": "A|B", "info_title": "x]]y"}, "[[Info card: A/B | x]y]]"),
    ({}, ""),
    ({"shows": "Plain card", "info_title": "THE END"}, ""),
])  # fmt: skip
def test_the_info_card_note_is_written_so_it_reads_back_as_the_same_card(card, note):
    assert script._info_card_note(card) == note
    if note:
        assert fountain.beat_notes(note) == {k: v.replace("|", "/").replace("]]", "]") if k != "info_text" else v for k, v in card.items()}


# ── a story with none of the new fields exports byte for byte as v200 did ─────────────────────────────────────────────────────────
def exports(casting) -> dict[str, str]:
    """The complete scripts of four stories with no info card and no changes, made by this code. The files in data/complete-v200 are the same four
    made by v200's storyrender (main at dccfd09), run through this same function."""
    from tests import test_pic_notes, test_plain_cards, test_script, test_script_roundtrip

    out = {"records": script.fountain_complete(test_script.RECORDS)}
    for name, text in (("directed", test_pic_notes.DIRECTED), ("max", test_script_roundtrip.MAX_TEXT), ("ending", test_plain_cards.ENDING)):
        fake, ctx = casting(text)
        run(ctx)
        out[name] = script.fountain_complete(_made(fake))
    return out


def test_a_story_with_none_of_the_new_fields_exports_exactly_as_before(casting):
    made = exports(casting)
    for name in ("records", "max", "ending"):  # no info card, no changes, no picture that is only its heading: byte for byte
        assert made[name] == (DATA / f"{name}.fountain").read_text(encoding="utf-8"), name
    # DIRECTED's third picture is only its heading (a Pic note and a speech): v200 wrote it as forced action (v201 writes none), and its pictures
    # with a Pic note had a page break above them, which the Pic note already is (v204): those are the only differences
    before = (DATA / "directed.fountain").read_text(encoding="utf-8")
    assert before.count("!EXT. DECK - NIGHT\n\n") == 1 and before.count("===\n\n[[Pic:") == 3
    assert made["directed"] == before.replace("!EXT. DECK - NIGHT\n\n", "").replace("===\n\n[[Pic:", "[[Pic:")
