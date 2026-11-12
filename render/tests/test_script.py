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


def test_the_title_page_is_read_from_the_fountain_header():
    assert script.title_page(script.fountain(RECORDS)) == {"title": "The Last Onion", "credit": "A Storyworld film", "notes": "about 146s long"}
    assert script.title_page(".A SCENE\n\nAction: not a title") == {}


def test_the_html_gets_a_title_page_and_the_story_as_its_tab_name():
    page = script.with_title_page("<html><head><title>Screenplay</title></head><body><div>x</div></body></html>", script.fountain(RECORDS))
    assert "<title>The Last Onion: script</title>" in page
    assert page.index("titlepage") < page.index("<div>x</div>")
    assert "A Storyworld film" in page and "about 146s long" in page


def test_a_title_with_markup_is_escaped_and_a_script_without_one_is_left_alone():
    assert "&lt;b&gt;" in script.with_title_page("<title>Screenplay</title><body>", "Title: <b>\n\n.X")
    plain = "<title>Screenplay</title><body>"
    assert script.with_title_page(plain, ".X\n\nhi") == plain


@pytest.mark.skipif(shutil.which("screenplain") is None, reason="screenplain not installed")
def test_the_rendered_html_opens_on_the_title_page(tmp_path):
    made = script.render(script.fountain(RECORDS), tmp_path, "onion")
    page = made["html"].read_text()
    assert "<title>The Last Onion: script</title>" in page and "A Storyworld film" in page
    assert page.index("titlepage") < page.index("THE CABIN")


BREAKDOWN_RECORDS = {
    **RECORDS,
    "beats": [
        _row("the-last-onion-beat-04", "Beat 04", story="the-last-onion", number="04", scene="the-last-onion-cabin", cast="captain, cook", picture="Wide."),
        _row("the-last-onion-beat-05", "Beat 05", story="the-last-onion", number="05", scene="the-last-onion-cabin", cast="captain", picture="Close.", sounds=[{"sound": "the-last-onion-sound-spoon", "at": 1.6}]),
        _row("the-last-onion-beat-06", "Beat 06", story="the-last-onion", number="06", scene="the-last-onion-galley", cast="cook", picture="Alone."),
    ],
    "lines": {
        "the-last-onion-beat-04": [_row("l4", speaker="narrator", text="The captain ordered a feast.", duration_seconds=2.5)],
        "the-last-onion-beat-05": [_row("l5", speaker="captain", text="Make do.", duration_seconds=0.75)],
    },
}


def test_the_breakdown_counts_who_speaks_and_appears_in_which_beats():
    info = script.breakdown(BREAKDOWN_RECORDS)
    by = {c["id"]: c for c in info["characters"]}
    assert by["captain"]["speaks"] == 1 and by["captain"]["words"] == 2 and by["captain"]["beats"] == ["04", "05"]
    assert by["cook"]["speaks"] == 0 and by["cook"]["beats"] == ["04", "06"]  # on screen without a line is still in the cast
    assert by["narrator"]["seconds"] == 2.5 and info["seconds_spoken"] == 3.25 and info["beats"] == 3
    assert info["characters"][0]["id"] in ("captain", "narrator")  # most lines first, ties by name


def test_the_breakdown_lists_each_location_once_with_its_beats_and_the_sounds():
    info = script.breakdown(BREAKDOWN_RECORDS)
    cabin, galley = info["locations"]
    assert cabin["beats"] == ["04", "05"] and cabin["ambience"] == "Harbour ambience" and galley["beats"] == ["06"]
    assert info["sounds"] == [{"id": "the-last-onion-sound-spoon", "title": "Spoon on bowl", "beats": ["05"]}]


def test_the_breakdown_page_is_a_whole_page_and_escapes_what_the_records_say():
    records = {**BREAKDOWN_RECORDS, "story": _row("the-last-onion", "<b>Onion", target_seconds="146")}
    page = script.breakdown_html(script.breakdown(records))
    assert page.startswith("<!DOCTYPE html>") and "&lt;b&gt;Onion: script breakdown" in page and "<b>Onion" not in page
    assert "<h2>Characters</h2>" in page and "aimed at 146s" in page


def test_a_long_run_of_beats_is_shortened_to_a_range():
    assert script._range(["01", "02", "03"]) == "01, 02, 03"
    assert script._range([f"{n:02d}" for n in range(1, 10)]) == "01–09 (9 beats)"


CHARACTERS = [
    _row("pirate-captain", cast_id="pirate-captain", story="the-last-onion", role="captain", actor="actor-captain", speaker="captain", profile={}),
    _row("old-ship-cook", cast_id="old-ship-cook", story="the-last-onion", role="ship's cook", actor="actor-cook", speaker="cook", profile={}),
]


def test_a_speaker_and_a_beats_cast_id_are_one_character_with_their_role_and_actor():
    records = {**BREAKDOWN_RECORDS, "characters": CHARACTERS, "beats": [_row("the-last-onion-beat-04", "Beat 04", story="the-last-onion", number="04", scene="the-last-onion-cabin", cast="pirate-captain, old-ship-cook")]}
    records["lines"] = {"the-last-onion-beat-04": [_row("l1", speaker="captain", text="Make do.", duration_seconds=1), _row("l2", speaker="cook", text="Aye.", duration_seconds=1)]}
    by = {c["id"]: c for c in script.breakdown(records)["characters"]}
    assert sorted(by) == ["old-ship-cook", "pirate-captain"]  # not four rows: captain/cook are their speaker names
    assert by["pirate-captain"]["speaks"] == 1 and by["pirate-captain"]["beats"] == ["04"] and by["pirate-captain"]["actor"] == "actor-captain"
    assert by["old-ship-cook"]["role"] == "ship's cook"


def test_someone_cast_in_the_story_is_listed_even_with_no_line_and_the_narrator_stays_separate():
    info = script.breakdown({**BREAKDOWN_RECORDS, "characters": CHARACTERS})
    ids = [c["id"] for c in info["characters"]]
    assert "pirate-captain" in ids and "narrator" in ids and "captain" not in ids and "cook" not in ids
    assert next(c for c in info["characters"] if c["id"] == "narrator")["role"] == ""


def test_pulling_a_story_takes_its_characters_but_not_its_castings(monkeypatch):
    import marvin_worker.marvin_api as api

    rows = [
        _row("the-last-onion", "The Last Onion"),
        _row("pirate-captain", cast_id="pirate-captain", story="the-last-onion", profile={}),
        _row("casting-1", cast_id="pirate-captain", story="the-last-onion", character="pirate-captain", fit="good"),
        _row("other", cast_id="x", story="another-story", profile={}),
    ]
    monkeypatch.setattr(api, "entries", lambda creds: rows)
    got = script.pull_records("the-last-onion", ("u", "t"))
    assert [c["slug"] for c in got["characters"]] == ["pirate-captain"]


def test_a_scene_that_says_inside_or_outside_is_written_with_INT_or_EXT_and_one_that_does_not_keeps_its_forced_heading():
    def scene(kind):
        return {"dataJson": {"inside_outside": kind}} if kind is not None else {"dataJson": {}}

    assert script._heading_line("CAPTAIN'S CABIN", " #2#", scene("interior")) == "INT. CAPTAIN'S CABIN #2#"
    assert script._heading_line("THE REEF", " #3#", scene("exterior")) == "EXT. THE REEF #3#"
    assert script._heading_line("DOORWAY", "", scene("both")) == "INT./EXT. DOORWAY"
    assert script._heading_line("THE MESS", " #5#", scene(None)) == ".THE MESS #5#"
    assert script._heading_line("THE MESS", " #5#", scene("sideways")) == ".THE MESS #5#"


@pytest.mark.parametrize(
    ("picture", "name", "action"),
    [
        ("EXT. THE DEVIL'S SHOALS - NIGHT. Black rocks break the surface.", "The Devil's Shoals", "Black rocks break the surface."),
        ("Interior: Captain's Cabin. A lantern hangs.", "Captain's Cabin", "A lantern hangs."),
        ("Interior and exterior: Doorway, day. A cat waits.", "Doorway", "A cat waits."),
        ("INT. HOLD - NIGHT. Water rushes in.", "Hold", "Water rushes in."),
        ("A cook enters.", "Galley", "A cook enters."),
        ("EXT. THE GALLEY, a wide shot of a pot.", "Galley", "EXT. THE GALLEY, a wide shot of a pot."),  # only begins like a heading: still a picture
        ("INT. HOLD - NIGHT. Water rushes in.", "Cabin", "INT. HOLD - NIGHT. Water rushes in."),  # another scene's heading is not this one's
    ],
)
def test_the_exported_action_does_not_say_the_scenes_own_heading_again(picture, name, action):
    assert script._without_lead_heading(picture, name) == action
