"""The script a story's records make (storyrender.script): Fountain text, and a PDF/HTML through screenplain."""

import shutil

import pytest

from storyrender import script


def _row(slug, title="", **data):
    return {"slug": slug, "title": title or slug, "dataJson": data}


RECORDS = {
    "story": _row("the-last-onion", "The Last Onion", target_seconds="146"),
    "scenes": {
        "the-last-onion-cabin": _row("the-last-onion-cabin", "The cabin", story="the-last-onion", place="The cabin: a long table.", look="Lantern light.", ambience="the-last-onion-sound-harbour"),
        "the-last-onion-galley": _row("the-last-onion-galley", "The galley", story="the-last-onion", place="The galley.", look="Steam.", ambience=""),
    },
    "sounds": {
        "the-last-onion-sound-harbour": _row("the-last-onion-sound-harbour", "Harbour ambience", prompt="gulls"),
        "the-last-onion-sound-spoon": _row("the-last-onion-sound-spoon", "Spoon on bowl", prompt="tap"),
    },
    "beats": [
        _row("the-last-onion-beat-04", "Beat 04", story="the-last-onion", number="04", scene="the-last-onion-cabin", picture="Wide shot of the cabin."),
        _row("the-last-onion-beat-05", "Beat 05", story="the-last-onion", number="05", scene="the-last-onion-cabin", picture="Close on the captain.", sounds=[{"sound": "the-last-onion-sound-spoon", "at": 1.6}]),
        _row("the-last-onion-beat-06", "Beat 06", story="the-last-onion", number="06", scene="the-last-onion-galley", picture="The cook alone."),
    ],
    "lines": {
        "the-last-onion-beat-04": [_row("l4", speaker="narrator", text="The captain ordered a feast.")],
        "the-last-onion-beat-05": [_row("l5", speaker="captain", text="Make do.", direction="Tired, a little amused.")],
    },
}


def test_the_title_page_names_the_story_and_its_length():
    text = script.fountain(RECORDS)
    assert text.startswith("Title: The Last Onion\nCredit: A Storyworld film\nNotes: about 146s long\n\n.THE CABIN")
    assert "===" not in text  # screenplain breaks the page after the title page itself; a manual break leaves a blank page


def test_a_scene_heading_appears_once_per_scene_numbered_by_its_first_beat():
    text = script.fountain(RECORDS)
    assert text.count(".THE CABIN #4#") == 1 and text.count(".THE GALLEY #6#") == 1
    assert text.index(".THE CABIN") < text.index("04 —") < text.index(".THE GALLEY")


def test_the_scene_setting_and_its_ambience_follow_the_heading():
    text = script.fountain(RECORDS)
    assert "The cabin: a long table. Lantern light." in text
    assert "SFX: harbour ambience, under the scene" in text
    assert "The galley. Steam." in text and text.count("under the scene") == 1  # the galley names no ambience


def test_an_ambience_is_named_when_it_changes_not_at_every_scene_that_shares_it():
    scenes = {**RECORDS["scenes"], "the-last-onion-deck": _row("the-last-onion-deck", "The deck", story="the-last-onion", place="Deck.", look="", ambience="the-last-onion-sound-harbour")}
    beats = [*RECORDS["beats"][:2], _row("the-last-onion-beat-07", "Beat 07", story="the-last-onion", number="07", scene="the-last-onion-deck", picture="Deck.")]
    text = script.fountain({**RECORDS, "scenes": scenes, "beats": beats})
    assert text.count("under the scene") == 1  # the cabin and the deck share one bed


def test_a_beat_is_an_action_line_with_its_number_and_a_timed_sound_cue():
    text = script.fountain(RECORDS)
    assert "05 — Close on the captain." in text
    assert "SFX 1.6s: spoon on bowl" in text


def test_the_narrator_is_a_voice_over_and_a_direction_is_the_parenthetical():
    text = script.fountain(RECORDS)
    assert "NARRATOR (V.O.)\nThe captain ordered a feast." in text
    assert "CAPTAIN\n(tired, a little amused)\nMake do." in text


def test_a_line_with_no_text_is_left_out_and_odd_whitespace_is_flattened():
    records = {**RECORDS, "lines": {"the-last-onion-beat-04": [_row("x", speaker="cook", text="   "), _row("y", speaker="cook", text="Two\n\nscraps   of pork.")]}}
    text = script.fountain(records)
    assert "COOK\nTwo scraps of pork." in text and text.count("COOK") == 1


@pytest.mark.skipif(shutil.which("screenplain") is None, reason="screenplain not installed")
def test_screenplain_makes_a_pdf_and_an_html_page(tmp_path):
    made = script.render(script.fountain(RECORDS), tmp_path, "onion")
    assert made["pdf"].read_bytes().startswith(b"%PDF") and made["pdf"].stat().st_size > 1000
    html = made["html"].read_text()
    assert "THE CABIN" in html and "NARRATOR" in html
