"""What a Fountain import makes of a real feature's habits (the Big Fish import of 2026-11-13): a younger self introduced before the older one,
camera words and names in capitals, speakers whose short names clash, capitals lines standing alone, and the one line each job leaves to say
how it went."""

import re

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import beat_import, beats, fountain, jobs, script, validate
from tests.test_fountain import run
from tests.test_import_guard import _check, _import, jobs_marvin  # noqa: F401  (a fixture)

TWO_EDWARDS = """INT. HOSPITAL ROOM - NIGHT

YOUNG EDWARD (10), a skinny boy with big ears, runs through the ward.

EDWARD (60s), sick in bed, smiles. He looks tired.

EDWARD
Hello, son.

YOUNG EDWARD
Who are you?
"""


# --- one character each ---------------------------------------------------------------------------------------------------------------


def test_a_name_inside_a_longer_name_does_not_take_the_longer_ones_introduction():
    plan = fountain.cut(fountain.parse(TWO_EDWARDS))
    who = {c["cue"]: c for c in plan.characters}
    assert (who["EDWARD"]["name"], who["EDWARD"]["age"]) == ("Edward", "60s")
    assert (who["YOUNG EDWARD"]["name"], who["YOUNG EDWARD"]["age"]) == ("Young Edward", "10")
    assert "skinny boy" not in who["EDWARD"]["description"] and "sick in bed" in who["EDWARD"]["description"]


def test_an_introduction_naming_exactly_the_speaker_wins_over_one_that_names_more_even_when_the_longer_one_never_speaks():
    text = TWO_EDWARDS.replace("YOUNG EDWARD\nWho are you?\n", "")
    edward = next(c for c in fountain.cut(fountain.parse(text)).characters if c["cue"] == "EDWARD")
    assert (edward["name"], edward["age"]) == ("Edward", "60s")


def test_a_partial_name_still_finds_its_introduction_when_nobody_else_fits_it_better():
    text = "INT. CABIN - NIGHT\n\nCAPTAIN VALERIE VANE (40s), sharp-eyed, studies a chart.\n\nVALERIE\nSteady.\n"
    valerie = fountain.cut(fountain.parse(text)).characters[0]
    assert valerie["age"] == "40s" and valerie["name"] == "Captain Valerie Vane"


# --- sounds come from what is written as a sound ------------------------------------------------------------------------------------------


CAMERA = """INT. BAKERY - DAY

The camera TILTS UP to the sign. CLOSE ON the door. BAKER'S WIFE waves. A deafening CRUNCH. FREEZE FRAME on her LOOK DOWN.

ANGLE ON the oven. The sound of bread cracking fills the room.

EXT. STREET - DAY

PAN across the crowd.
[[Sound: a church bell at 1.5s.]]
"""


def test_words_in_capitals_are_never_sounds_but_what_is_written_as_a_sound_is():
    plan = fountain.cut(fountain.parse(CAMERA, lines=True), text=CAMERA)
    titles = [c["title"] for _c, _n, b in plan.rows() for c in b["sounds"]]
    assert "Bread cracking" in titles and "A church bell" in titles
    junk = {"Tilts", "Close", "Baker", "Wife", "Crunch", "Freeze", "Frame", "Look", "Down", "Angle", "Pan"}
    assert not junk & set(titles), titles
    bell = next(c for _c, _n, b in plan.rows() for c in b["sounds"] if c["title"] == "A church bell")
    assert bell["at"] == 1.5


def test_a_beat_with_no_sound_written_gets_none_from_its_capitals():
    beat = {"picture": "The ship LURCHES. THE BARNACLE'S REVENGE groans.", "place": "", "sung": [], "fountain": "x"}
    assert fountain.sound_cues(beat) == []


# --- speakers: readable handles that keep their records, and capitals that are not speakers ----------------------------------------------


def test_a_clash_of_short_names_joins_the_words_with_hyphens():
    h = fountain.handles(["A DEEP VOICE", "VOICE", "DR BENNETT", "YOUNG DR BENNETT", "EDWARD AND WILL", "WILL", "OLD COOK"])
    assert h == {
        "A DEEP VOICE": "A-deep-voice", "VOICE": "Voice", "DR BENNETT": "Dr-bennett", "YOUNG DR BENNETT": "Young-dr-bennett",
        "EDWARD AND WILL": "Edward-and-will", "WILL": "Will", "OLD COOK": "Cook",
    }  # fmt: skip


def test_a_speaker_brought_in_before_under_the_squashed_handle_keeps_it():
    h = fountain.handles(["A DEEP VOICE", "VOICE", "YOUNG DR BENNETT", "DR BENNETT"], keep={"adeepvoice", "voice"})
    assert h["A DEEP VOICE"] == "Adeepvoice" and h["YOUNG DR BENNETT"] == "Young-dr-bennett" and h["VOICE"] == "Voice"
    assert fountain.handles(["A DEEP VOICE", "VOICE"], keep={"adeepvoice", "a-deep-voice"})["A DEEP VOICE"] == "A-deep-voice"  # both there: the new one


POSSESSIVE = ["A GIRL'S VOICE", "A MAN’S VOICE", "MAN'S VOICE", "WOMAN’S VOICE", "VOICE", "WILL'S DATE", "DR. BENNETT", "YOUNG DR. BENNETT"]


def test_a_possessive_drops_its_apostrophe_and_is_not_cut_into_a_word_of_its_own():
    h = fountain.handles(POSSESSIVE)
    assert h == {
        "A GIRL'S VOICE": "A-girls-voice", "A MAN’S VOICE": "A-mans-voice", "MAN'S VOICE": "Mans-voice", "WOMAN’S VOICE": "Womans-voice",
        "VOICE": "Voice", "WILL'S DATE": "Date", "DR. BENNETT": "Dr-bennett", "YOUNG DR. BENNETT": "Young-dr-bennett",
    }  # fmt: skip
    assert fountain.handles(["O'BRIEN"]) == {"O'BRIEN": "Obrien"}


def test_a_speaker_brought_in_with_the_apostrophe_cut_into_a_word_keeps_that_handle():
    h = fountain.handles(["A GIRL'S VOICE", "VOICE", "O'BRIEN"], keep={"a-girl-s-voice", "voice", "brien"})  # as #162 made them
    assert (h["A GIRL'S VOICE"], h["O'BRIEN"], h["VOICE"]) == ("A-girl-s-voice", "Brien", "Voice")
    assert fountain.handles(["A GIRL'S VOICE", "VOICE"], keep={"agirlsvoice"})["A GIRL'S VOICE"] == "Agirlsvoice"  # as it was before #162
    assert fountain.handles(["A GIRL'S VOICE", "VOICE"], keep={"a-girl-s-voice", "a-girls-voice"})["A GIRL'S VOICE"] == "A-girls-voice"  # both there: the new one


VOICES = """INT. HOSPITAL ROOM - NIGHT

Will sits by the bed.

A GIRL'S VOICE
Edward?

A MAN’S VOICE
Not now.

MAN'S VOICE
Later, then.

WOMAN’S VOICE
Hush.

WILL'S DATE
Who is that?

VOICE
Nobody.
"""


def test_possessive_handles_survive_the_sheet_and_the_script_and_the_fountain_keeps_the_name_as_written():
    plan = fountain.cut(fountain.parse(VOICES, lines=True), text=VOICES)
    assert fountain.check(plan) == []
    _kind, rows = beat_import.parse_any(plan.sheet())
    speakers = [ln["speaker"] for r in rows for ln in r["lines"]]
    assert speakers == ["A-girls-voice", "A-mans-voice", "Mans-voice", "Womans-voice", "Date", "Voice"]
    assert [script._cue(s.lower()) for s in speakers[:4]] == ["A GIRLS VOICE", "A MANS VOICE", "MANS VOICE", "WOMANS VOICE"]
    written = "".join(ln["fountain"] for _c, _n, b in plan.rows() for ln in b["lines"])
    assert "A GIRL'S VOICE\n" in written and "A MAN’S VOICE\n" in written  # the words as the writer wrote them, for the Fountain made again
    for cell, who in (("A-girls-voice: Edward?", "A-girls-voice"), ("Mans-voice: Later, then.", "Mans-voice"), ("Voice: Hush. ¶ Womans-voice: Hush.", "Voice")):
        assert beats.split_audio(cell)[0]["speaker"] == who  # a cell of one line (no ¶) as well as one of several
    again = fountain.handles([script._cue(s.lower()) for s in speakers])  # the complete script's cues read back as the same handles
    assert list(again.values()) == speakers


def test_a_reimport_finds_the_characters_made_with_the_apostrophe_cut_into_a_word(casting):
    fake, ctx = casting(VOICES)
    fake.on_hand["cast-member"]["s-a-girl-s-voice"] = {"id": "c1", "slug": "s-a-girl-s-voice", "title": "A Girl's Voice", "dataJson": {"story": "s", "speaker": "a-girl-s-voice"}}
    done = run(ctx)
    made = sorted(done["result"]["characters_made"])
    assert "s-a-girl-s-voice" not in made and "s-a-girls-voice" not in made and "s-a-mans-voice" in made
    lines = {m["dataJson"]["speaker"] for m in fake.made if m["entryTypeId"] == "T-line"}
    assert {"a-girl-s-voice", "a-mans-voice", "mans-voice", "womans-voice"} <= lines
    cast_ids = {m["dataJson"]["cast_id"] for m in fake.made if m["entryTypeId"] == "T-cast"}
    assert "a-mans-voice" in cast_ids and "womans-voice" in cast_ids  # the stable id drops the apostrophe too


CLASH = """INT. CAVE - NIGHT

A DEEP VOICE
Who goes there?

VOICE
Only me.

DR BENNETT
Hold still.
YOUNG DR BENNETT
I am holding.

EXT. RIVER - DAY

A RIVER.

The water is brown and slow.

YOUNG DR BENNETT
Cold.
"""


def test_hyphenated_handles_survive_the_sheet_and_the_check_one_line_or_several():
    plan = fountain.cut(fountain.parse(CLASH, lines=True), text=CLASH)
    assert fountain.check(plan) == []  # nothing the cut wrote is lost reading the sheet back
    _kind, rows = beat_import.parse_any(plan.sheet())
    speakers = [ln["speaker"] for r in rows for ln in r["lines"]]
    assert speakers == ["A-deep-voice", "Voice", "Dr-bennett", "Young-dr-bennett", "Young-dr-bennett"]
    lone = next(r for r in rows if len(r["lines"]) == 1 and r["lines"][0]["text"] == "Cold.")  # a cell with one line has no ¶ in it
    assert lone["lines"][0]["speaker"] == "Young-dr-bennett"


def test_the_script_writes_a_hyphenated_handle_back_as_the_name():
    assert script._cue("a-deep-voice") == "A DEEP VOICE" and script._cue("young-dr-bennett", "V.O.") == "YOUNG DR BENNETT (V.O.)"


def test_a_capitals_line_standing_alone_is_action_kept_in_the_picture_and_never_a_speaker():
    plan = fountain.cut(fountain.parse(CLASH, lines=True), text=CLASH)
    assert "A RIVER" not in plan.speakers and all(c["cue"] != "A RIVER." for c in plan.characters)
    assert any("A RIVER." in b["picture"] for _c, _n, b in plan.rows())  # its words are the picture's, not dropped
    said = fountain.lint(CLASH)
    river = next(w for w in said if "`A RIVER.`" in w)
    assert "read as action" in river and "nothing to say" not in river and "[[Sound:" in river
    found = [f for f in validate.check(CLASH) if f.code == "capitals-alone"]
    assert found and not validate.blocking(found)  # worth a look, never a stop


INTERCUT = """INT. HALLWAY - NIGHT

Will paces.

INTERCUT WITH:

INT. BEDROOM - NIGHT

Sandra waits.

INTERCUT HALLWAY / BEDROOM

WILL
Are you there?
"""


def test_an_intercut_line_is_action_kept_in_the_picture_with_nothing_to_check():
    plan = fountain.cut(fountain.parse(INTERCUT, lines=True), text=INTERCUT)
    pictures = " ".join(b["picture"] for _c, _n, b in plan.rows())
    assert "INTERCUT WITH:" in pictures and "INTERCUT HALLWAY / BEDROOM" in pictures and not any(b.get("transition") for _c, _n, b in plan.rows())
    assert not [f for f in validate.check(INTERCUT) if "INTERCUT" in f.problem]


def test_a_reimport_finds_the_characters_it_made_under_the_old_handles(casting):
    fake, ctx = casting(CLASH)
    fake.on_hand["cast-member"]["s-adeepvoice"] = {"id": "c1", "slug": "s-adeepvoice", "title": "A Deep Voice", "dataJson": {"story": "s", "speaker": "adeepvoice"}}
    fake.on_hand["cast-member"]["s-drbennett"] = {"id": "c2", "slug": "s-drbennett", "title": "Dr Bennett", "dataJson": {"story": "s", "speaker": "drbennett"}}
    done = run(ctx)
    made = sorted(done["result"]["characters_made"])
    assert made == ["s-voice", "s-young-dr-bennett"]  # the two made before are found; only the new ones are made, with readable handles
    lines = {m["dataJson"]["speaker"] for m in fake.made if m["entryTypeId"] == "T-line"}
    assert lines == {"adeepvoice", "voice", "drbennett", "young-dr-bennett"}


@pytest.fixture
def casting(monkeypatch, tmp_path):
    from tests.test_fountain import CastingMarvin

    def make(screenplay):
        fake = CastingMarvin("", {})
        fake.story["dataJson"]["fountain"] = screenplay
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")

    return make


# --- one line to say how it went ----------------------------------------------------------------------------------------------------------


def test_the_check_says_in_one_line_whether_the_import_can_go_on(jobs_marvin):  # noqa: F811
    head = "Title: T\nSetting: s\nPremise: p\n\n"
    fake, ctx = jobs_marvin(head + "INT. ROOM - DAY\n\nTHE STORM RISES.\n\nMARA\nHello.\n")
    assert _check(ctx)["result"]["summary"] == "Check: the import can go on; 1 line is worth a look. Bringing it in takes under a minute."
    fake.story["dataJson"]["fountain"] = head + "INT. ROOM - DAY\n\nMARA\nHello.\n"
    assert _check(ctx)["result"]["summary"] == "Check: nothing to fix; the import can go on. Bringing it in takes under a minute."
    fake.story["dataJson"]["fountain"] = head + "INT. ROOM - DAY\n\n[[a note never closed\n\nCUT TO\n\nTHE STORM RISES.\n"
    stops = _check(ctx)["result"]["summary"]
    assert stops.startswith("Check: the import will stop: 2 mistakes to fix first") and stops.endswith("; 1 more is worth a look. Bringing it in takes under a minute.")


def test_an_import_says_what_it_made_and_how_long_writing_takes(jobs_marvin):  # noqa: F811
    fake, ctx = jobs_marvin()
    preview = _import(ctx, dry_run="yes")
    assert preview["result"]["summary"].startswith("Preview only: nothing was made. It would make 3 chapters")
    assert any("at this speed" in n and "would write" in n for n in ctx.notes)
    ctx.notes.clear()
    done = _import(ctx)["result"]["summary"]
    assert done.startswith("Done: made 3 chapters") and "\n" not in done
    timing = [n for n in ctx.notes if "at this speed" in n]
    assert len(timing) == 1 and "records" in timing[0] and ("minute" in timing[0])
    ctx.notes.clear()
    again = _import(ctx)["result"]["summary"]
    assert again.startswith("Nothing new:") and not [n for n in ctx.notes if "at this speed" in n]  # nothing to write: no time to say


def test_a_job_that_fails_leaves_the_reason_in_one_line_on_its_result(jobs_marvin, monkeypatch):  # noqa: F811
    fake, ctx = jobs_marvin("INT. ROOM - DAY\n\n[[a note never closed\n\nMARA\nHello.\n")
    written = []
    monkeypatch.setattr(jobs.marvin_api, "update_entry", lambda creds, slug, changes: written.append((slug, changes)))
    with pytest.raises(JobError):
        _import(ctx)
    assert written == [("import-2", {"result": {"summary": "Failed: the Fountain has mistakes the import would read differently from what was meant, so nothing was made."}})]
    written.clear()
    with pytest.raises(JobError):
        jobs.check_fountain({"job": "check-9", "args": {"story": "nobody"}}, ctx)
    assert written == [("check-9", {"result": {"summary": "Failed: no story “nobody” in this workspace"}})]


def test_a_failure_summary_that_cannot_be_written_does_not_hide_the_failure(jobs_marvin, monkeypatch):  # noqa: F811
    _fake, ctx = jobs_marvin()

    def unreachable(*_a, **_k):
        raise OSError("down")

    monkeypatch.setattr(jobs.marvin_api, "update_entry", unreachable)
    with pytest.raises(JobError, match="no story"):
        jobs.import_beats({"job": "import-2", "args": {"story": "nobody"}}, ctx)


# --- scene headings written inside and outside at once (Big Fish: `EXT/INT.  SWAMP SHACK - DAY`) ------------------------------------------


@pytest.mark.parametrize(
    ("start", "kind"),
    [("EXT/INT.", "both"), ("EXT./INT.", "both"), ("INT/EXT.", "both"), ("INT./EXT.", "both"), ("I/E.", "both"), ("E/I.", "both"), ("INT/EXT", "both"), ("EXT / INT.", "both"), ("EST.", "exterior")],
)
def test_every_way_of_writing_inside_and_outside_starts_a_scene(start, kind):
    text = f"{start}  SWAMP SHACK - DAY\n\nThe door creaks open.\n\nEDWARD\nHello?\n"
    els = fountain.parse(text)
    assert els[0] == {"t": "scene", "text": f"{start}  SWAMP SHACK - DAY"}
    assert fountain.place_of(els[0]["text"]) == {"slug": "swamp-shack", "name": "Swamp Shack", "kind": kind, "time": "Day"}
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    assert list(plan.places) == ["swamp-shack"] and [c["handle"] for c in plan.characters] == ["Edward"]
    assert not [f for f in validate.check(text) if f.code in ("heading-without-kind", "capitals-alone", "capitals-above-text")]


SHACK = """EXT. SWAMP SHACK - DAY

Edward wades up to the porch.

EXT/INT.  SWAMP SHACK - NIGHT

The witch's eye glints in the doorway.

EXT/INT. SORORITY HOUSE - THE DOORWAY

Sandra waits.
"""


def test_a_heading_written_inside_and_outside_is_the_same_place_as_the_plain_one_and_keeps_its_words():
    plan = fountain.cut(fountain.parse(SHACK, lines=True), text=SHACK)
    assert list(plan.places) == ["swamp-shack", "sorority-house-the-doorway"]  # one shack, not two: the second heading names the place the first made
    assert plan.places["swamp-shack"]["kinds"] == ["exterior", "both"] and fountain.kind_of_places(plan.places["swamp-shack"]["kinds"]) == "both"
    assert fountain.lint(SHACK) == []
    beats_ = [b for _c, _n, b in plan.rows()]
    assert beats_[1]["fountain"].startswith("EXT/INT.  SWAMP SHACK - NIGHT\n")  # the piece the writer wrote, as written
    records = {"story": {"dataJson": {"fountain_front": plan.front}}, "beats": [{"dataJson": {"fountain": b["fountain"]}} for b in beats_]}
    assert script.fountain_as_written(records) == SHACK  # the Fountain made again is the one written, the heading as typed
    assert script._without_lead_heading("E/I. SWAMP SHACK - NIGHT. The eye glints.", "Swamp Shack") == "The eye glints."



def test_a_heading_written_inside_and_outside_with_its_action_right_under_it_is_a_scene_not_a_speaker():
    text = "INT. ROOM - DAY\n\nA hand.\n\nEXT/INT.  SWAMP SHACK - DAY\nThe witch looks up.\n\nEDWARD\nHello.\n"
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    assert [c["cue"] for c in plan.characters] == ["EDWARD"] and list(plan.places) == ["room", "swamp-shack"]

# --- the check's advice for a heading it does not know --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "write"),
    [
        ("EXTERIOR SWAMP SHACK - DAY", "EXT. SWAMP SHACK - DAY"),
        ("INTERIOR HOSPITAL ROOM - NIGHT", "INT. HOSPITAL ROOM - NIGHT"),
        ("INT-EXT SWAMP SHACK - DAY", "INT./EXT. SWAMP SHACK - DAY"),
        ("INTERIOR/EXTERIOR SWAMP SHACK - DAY", "INT./EXT. SWAMP SHACK - DAY"),
        ("ESTABLISHING SWAMP SHACK - DAY", "EST. SWAMP SHACK - DAY"),
        ("SWAMP SHACK - DAY", "EXT. SWAMP SHACK - DAY"),
    ],
)
def test_a_heading_the_check_does_not_know_is_told_how_to_start_without_a_second_kind_put_in_front(line, write):
    text = f"INT. ROOM - DAY\n\nA hand.\n\n{line}\n\nThe door creaks open.\n"
    said = fountain.lint(text)
    assert len(said) == 1 and f"write `{write}`" in said[0] and f"`.{line}`" in said[0], said
    assert not re.search(r"(?:INT|EXT)\.? (?:EXT|INT)", said[0])  # never `EXT. EXTERIOR …` or `EXT. INT-EXT …`
    found = [f for f in validate.check(text) if f.code == "heading-without-kind"]
    assert len(found) == 1 and found[0].fix.startswith(f"write `{write}`") and not validate.blocking(found)


# --- characters you cannot see that change nothing --------------------------------------------------------------------------------------

UNSEEN = "INT. ROOM - DAY\n\nBIG EDWARD\nHello.\n\nBIG EDWARD\nAgain.\n\nBIG EDWARD\nThird.\n\nBIG ED​WARD\nFourth.\n\nBIG EDWARD﻿\nFifth.\n"


def test_a_no_break_or_zero_width_space_is_read_as_the_space_it_looks_like_and_the_writers_text_is_kept():
    plan = fountain.cut(fountain.parse(UNSEEN, lines=True), text=UNSEEN)
    assert [c["cue"] for c in plan.characters] == ["BIG EDWARD"]  # one speaker, not four
    assert [ln["speaker"] for _c, _n, b in plan.rows() for ln in b["lines"]] == ["Edward"] * 5
    assert fountain.check(plan) == []
    assert "BIG EDWARD" in "".join(b["fountain"] for _c, _n, b in plan.rows())  # the as-written piece keeps what was typed
    assert {f.code for f in validate.check(UNSEEN)} == {"plan", "title-page"}  # nothing about the characters: it reads the way it looks


@pytest.mark.parametrize("char", ["‮", "‎", "­", "\x07"])
def test_a_character_that_changes_how_a_line_reads_or_cannot_be_read_is_still_worth_a_look(char):
    found = [f for f in validate.check(f"INT. ROOM - DAY\n\nMA{char}RA\nHello.\n") if f.code == "invisible"]
    assert len(found) == 1 and found[0].line == 3 and found[0].level == "look"


# --- how long bringing it in takes, said by the check ---------------------------------------------------------------------------------------


def test_the_time_to_write_is_said_in_minutes_or_as_under_a_minute():
    assert fountain.time_to_write(1880) == "about 13 minutes" and fountain.time_to_write(100) == "under a minute"
    assert fountain.time_to_write(144) == "about 1 minute" and fountain.RECORDS_PER_SECOND == 2.4


def test_the_check_says_how_long_bringing_it_in_takes_with_the_count_the_import_writes(jobs_marvin):  # noqa: F811
    fake, ctx = jobs_marvin()
    checked = _check(ctx)["result"]
    said = re.search(r"^Bringing it in will take (under a minute|about \d+ minutes?) \((\d+) records at about 2\.4 a second\)\.$", checked["report"], re.M)
    assert said, checked["report"].splitlines()[:4]
    assert checked["report"].splitlines()[3] == said.group(0)  # under what the import would make
    assert checked["summary"].endswith(f" Bringing it in takes {said.group(1)}.") and "\n" not in checked["summary"]
    _import(ctx, dry_run="yes")
    wrote = next(n for n in ctx.notes if "would write" in n)
    assert f"would write {said.group(2)} records" in wrote  # the check's count is the one the import writes into an empty story
