"""validate: the slips in a Fountain the import would read differently from what was meant, found before it is read."""

import json

import pytest
from marvin_worker.jobs import Context, JobError

from storyrender import cli, jobs, validate
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_script_roundtrip import MAX_TEXT

BROKEN = """Title: BROKEN TEST
Author: Me

# ACT I

LAMP ROOM - NIGHT

Mara trims the wick. A deafening CRUNCH of timber.

THE STORM RISES.

MARA
(without looking up
You're late.

jonah
The path is gone.

INT. LAMP ROOM - DAWN #2#

[[Sound: wind howling at 0.5s.

Mara smiles.

INT. COAST - DAY #2#

CUT TO

MARA
Hello.

[[Hold: soon.]]

MARAH
We kept it burning.
"""


def codes(text):
    return {f.code: f for f in validate.check(text)}


def test_every_slip_in_a_broken_file_is_found_with_its_line_and_what_to_write():
    found = {f.code: f for f in validate.check(BROKEN)}
    assert found["heading-without-kind"].line == 6 and found["capitals-alone"].line == 10
    assert found["paren-open"].line == 13 and "(without looking up)" in found["paren-open"].fix
    assert found["note-open"].line == 21 and found["scene-number"].line == 25 and "#2#" in found["scene-number"].problem
    assert found["transition-colon"].line == 27 and found["transition-colon"].fix == "write `CUT TO:`"
    assert found["hold-value"].line == 32 and "Hold: 1.5s." in found["hold-value"].fix
    assert found["cue-lowercase-maybe"].line == 16 and found["cue-lowercase-maybe"].level == "look" and "JONAH" in found["cue-lowercase-maybe"].fix
    assert found["speaker-typo"].line == 34 and "MARAH" in found["speaker-typo"].problem and found["speaker-typo"].level == "look"
    assert {"title-premise", "title-setting"} <= set(found)
    assert [f.line for f in validate.check(BROKEN)] == sorted(f.line for f in validate.check(BROKEN))  # in the order of the file


def test_a_lower_case_cue_is_an_error_when_the_same_speaker_is_written_in_capitals_elsewhere():
    text = "Title: T\n\nINT. ROOM - DAY\n\nJONAH\nHello.\n\njonah\nAgain.\n"
    found = codes(text)
    assert found["cue-lowercase"].level == "error" and found["cue-lowercase"].line == 8 and found["cue-lowercase"].fix == "write the speaker in capitals: `JONAH`"
    assert validate.blocking(validate.check(text))  # the import stops for it


@pytest.mark.parametrize(
    ("text", "code", "line"),
    [
        ("INT. ROOM - DAY\n\nMARA\n(softly)\n\nA hand.\n", "cue-empty", 3),
        ("INT. ROOM - DAY\n\nA hand.\n\n/* a comment never closed\n\nMore.\n", "boneyard-open", 5),
        ("INT. ROOM - DAY\n\nA hand. ]] oops\n", "note-close", 3),
        ("INT. ROOM - DAY\n\n[[Sound: a bell at soon.]]\n\nA hand.\n", "sound-at", 3),
        ("INT.\n\nA hand.\n", "heading-empty", 1),
        ("INT. ROOM - DAY\n\n#\n\nA hand.\n", "section-empty", 3),
        ("INT. ROOM - DAY\n\n===\n\n===\n\nA hand.\n", "empty-picture", 5),
        ("INT. ROOM - DAY\n\n> THE END <\n", "centered", 3),
        ("INT. ROOM - DAY\n\n(softly) she says\n\nA hand.\n", "paren-alone", 3),
        ("INT. ROOM - DAY\n\nMARA \nHello.\n", "invisible", 3),
    ],
)
def test_each_rule_finds_its_slip_on_the_right_line(text, code, line):
    found = codes(text)
    assert code in found, (code, list(found))
    assert found[code].line == line


def test_a_clean_screenplay_has_nothing_to_fix_and_the_one_the_importer_is_tested_with_is_clean():
    assert not [f for f in validate.check(MAX_TEXT) if f.level == "error"]
    body, errors, looks = validate.report(validate.check(MAX_TEXT), MAX_TEXT)
    assert errors == 0 and "It reads as 2 chapters" in body
    clean = "Title: T\nSetting: A house.\nPremise: A story.\n\nINT. ROOM - DAY\n\nMARA\n(softly)\nHello.\n\nNARRATOR (V.O.)\nLater.\n\nCUT TO:\n\nEXT. YARD - NIGHT\n\nRain.\n"
    assert validate.check(clean) == []
    assert "Nothing to fix" in validate.report([], clean)[0]


def test_things_that_look_odd_but_are_fine_are_not_flagged():
    text = "Title: T\nSetting: s\nPremise: p\n\nINT. ROOM - DAY #1#\n\nSilence.\n\nMARA (O.S.)\nHello.\n\n!THE STORM RISES.\n\nINT. ROOM - NIGHT #1#\n\nMARA\nBye.\n\nMARA\nBye again.\n"
    assert validate.check(text) == []  # one-word action, an extension, a forced action, the same place at another time under one number


def test_the_errors_the_import_has_always_only_warned_about_do_not_stop_it():
    soft = validate.check("INT. ROOM - DAY\n\nTHE STORM RISES.\n")
    assert [f.code for f in soft if f.level == "error"] == ["capitals-alone"] and validate.blocking(soft) == []


def test_the_check_job_takes_the_text_and_reports_what_it_found_without_marvin(tmp_path):
    ctx = Context(creds=("http://m", "t"), work=tmp_path, name="check-1")
    out = jobs.check_fountain({"job": "j", "args": {"text": BROKEN}}, ctx)
    assert out["result"]["errors"] == 7 and out["result"]["looks"] == 4 and out["result"]["import_stops"] >= 5
    assert "line 13: `(without looking up` is opened with (" in out["result"]["report"] and out["log"].startswith("Checked the Fountain")
    assert {f["code"] for f in out["result"]["findings"]} >= {"note-open", "scene-number", "transition-colon"}
    with pytest.raises(JobError, match="a story, the text, or an uploaded file"):
        jobs.check_fountain({"job": "j", "args": {}}, ctx)


def test_the_import_stops_on_a_mistake_it_would_misread_and_goes_on_when_told_to_or_when_only_previewing(casting):
    fake, ctx = casting("INT. ROOM - DAY\n\nMARA\nHi.\n\n[[Sound: a bell at 1s.\n\nA hand.\n")
    with pytest.raises(JobError, match="nothing was made") as e:
        run(ctx)
    assert "line 6" in str(e.value) and "accept_errors" in str(e.value) and not fake.made
    assert run(ctx, dry_run="yes")["result"]["dry_run"] is True and not fake.made  # a preview only says
    run(ctx, accept_errors="yes")
    assert fake.made  # told to go on


def test_the_command_line_check_exits_with_the_answer(tmp_path, capsys):
    bad, good = tmp_path / "bad.fountain", tmp_path / "good.fountain"
    bad.write_text(BROKEN, encoding="utf-8")
    good.write_text("Title: T\nSetting: s\nPremise: p\n\nINT. ROOM - DAY\n\nMARA\nHello.\n", encoding="utf-8")
    assert cli.main(["check", str(bad)]) == 1 and "Fix before importing (7)" in capsys.readouterr().out
    assert cli.main(["check", str(good)]) == 0 and "Nothing to fix" in capsys.readouterr().out
    cli.main(["check", str(bad), "--json"])
    assert json.loads(capsys.readouterr().out)["errors"] == 7


def test_centred_text_is_said_to_be_a_card_when_it_stands_alone_and_action_inside_a_paragraph():
    alone = codes("INT. ROOM - DAY\n\n> THE END <\n> A film <\n")["centered"]
    assert alone.level == "look" and "plain card" in alone.problem and "no picture" in alone.problem
    inside = codes("INT. ROOM - DAY\n\n> KEEP OUT <\nThe door creaks.\n")["centered"]
    assert inside.level == "look" and "read as action" in inside.problem and "plain card" not in inside.problem
