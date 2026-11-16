"""What a Fountain import makes of a real feature's habits (the Big Fish import of 2026-11-13): a younger self introduced before the older one,
camera words and names in capitals, speakers whose short names clash, capitals lines standing alone, and the one line each job leaves to say
how it went."""

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import beat_import, fountain, jobs, script, validate
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
    assert _check(ctx)["result"]["summary"] == "Check: the import can go on; 1 line is worth a look."
    fake.story["dataJson"]["fountain"] = head + "INT. ROOM - DAY\n\nMARA\nHello.\n"
    assert _check(ctx)["result"]["summary"] == "Check: nothing to fix; the import can go on."
    fake.story["dataJson"]["fountain"] = head + "INT. ROOM - DAY\n\n[[a note never closed\n\nCUT TO\n\nTHE STORM RISES.\n"
    stops = _check(ctx)["result"]["summary"]
    assert stops.startswith("Check: the import will stop: 2 mistakes to fix first") and stops.endswith("; 1 more is worth a look.")


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
