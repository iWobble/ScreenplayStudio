"""A Fountain screenplay cut into chapters and beats (no AI), read back by the importer, and brought in a piece at a time by the job."""

import json
import re

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import beat_import, beats, fountain, jobs, numbering
from tests.test_beat_import import FakeMarvin

GRANNY = """Title: Granny Advice
Credit: Episode 1
Author: Low Burn Studio

EXT. GRANNY'S FRONT PORCH - DUSK

A lavender sky settles over a quiet Southern yard.

Her DOG sits at her feet. /* cut this later */ Crickets hum. [[ask about the dog]]

GRANNY (V.O.)
(dryly)
People say you should never go to bed angry. Wait: stop, listen—

DOG
Woof.

CUT TO:

A CLOSER VIEW OF GRANNY
"""


def kinds(text):
    return [(e["t"], e.get("name") or e.get("text") or e.get("title")) for e in fountain.parse(text)]


def test_it_reads_scenes_action_dialogue_and_transitions_and_drops_what_is_the_writers():
    got = kinds(GRANNY)
    assert got[0] == ("scene", "EXT. GRANNY'S FRONT PORCH - DUSK")
    assert [t for t, _ in got] == ["scene", "action", "action", "dialogue", "dialogue", "transition", "action"]
    action = fountain.parse(GRANNY)[2]["text"]
    assert "cut this later" not in action and "ask about the dog" not in action and action.startswith("Her DOG sits")
    granny = fountain.parse(GRANNY)[3]
    assert (granny["name"], granny["ext"], granny["paren"]) == ("GRANNY", "V.O.", ["dryly"])


def test_sections_forced_elements_and_page_breaks():
    text = "# Act One\n\n= a synopsis\n\n.OPENING\n\n@McCLANE\nYippee.\n\n===\n\n!INT. NOT A HEADING\n\n> THE END <\n"
    got = kinds(text)
    assert got[0] == ("section", "Act One")
    assert ("scene", "OPENING") in got and ("dialogue", "McCLANE") in got
    assert ("action", "INT. NOT A HEADING") in got and ("centred", "THE END") in got  # centred text alone is words for a card, not action
    assert ("synopsis", "a synopsis") in got  # the writer's one-line summary, kept apart from the action


def test_a_one_line_shout_is_action_not_a_speaker():
    assert ("action", "BOOM") in kinds("INT. ROOM - DAY\n\nBOOM\n\nShe ducks.\n")


def test_speaker_names_become_one_word_handles_and_a_clash_keeps_all_the_words():
    assert fountain.handles(["GRANNY", "OLD COOK"]) == {"GRANNY": "Granny", "OLD COOK": "Cook"}
    h = fountain.handles(["MRS. HALE", "DR. HALE"])
    assert h["MRS. HALE"] != h["DR. HALE"] and all(beats._LABEL.match(v + ": x") for v in h.values())


def test_a_short_story_is_one_chapter_with_plain_numbers_and_what_is_spoken_survives_the_round_trip():
    plan = fountain.cut(fountain.parse(GRANNY))
    assert plan.single and fountain.check(plan) == []
    kind, rows = beat_import.parse_any(plan.sheet())
    assert [r["beat"] for r in rows] == ["01", "02"] and all(r["chapter"] is None for r in rows)
    spoken = [(ln["speaker"], ln["text"]) for r in rows for ln in r["lines"]]
    assert spoken == [("Granny", "People say you should never go to bed angry. Wait: stop, listen—"), ("Dog", "Woof.")]
    assert "Delivery: Granny (dryly, V.O.)" in rows[0]["picture"]


def test_a_colon_or_a_pipe_in_the_words_does_not_break_the_sheet():
    text = "INT. ROOM - DAY\n\nANN\nListen. Bob: is not a speaker | really.\n\nBOB\nWell,\n\nANN\nYes.\n"
    plan = fountain.cut(fountain.parse(text))
    assert fountain.check(plan) == []
    _, rows = beat_import.parse_any(plan.sheet())
    assert [(ln["speaker"], ln["text"]) for r in rows for ln in r["lines"]][0] == ("Ann", "Listen. Bob: is not a speaker / really.")


def scenes(n, lines_each=14):
    out = []
    for i in range(1, n + 1):
        out.append(f"INT. PLACE {i} - DAY\n\n" + " ".join(f"Something happens here, number {k}." for k in range(lines_each)) + f"\n\nANN\nLine in scene {i}.\n")
    return "\n".join(out)


def test_sections_make_the_chapters_and_a_leading_number_in_the_title_is_the_chapter_number():
    text = "## 02 The heist\n\n" + scenes(2) + "\n## 05 The getaway\n\n" + scenes(2)
    plan = fountain.cut(fountain.parse(text))
    assert [c.number for c in plan.chapters] == [2, 5] and [c.title for c in plan.chapters] == ["The heist", "The getaway"]
    _, rows = beat_import.parse_any(plan.sheet())
    assert {r["chapter"]["number"] for r in rows} == {"02", "05"}
    assert all(int(r["beat"]) // 1000 in (2, 5) for r in rows)


def test_without_sections_chapters_are_of_whole_scenes_near_the_target_size():
    plan = fountain.cut(fountain.parse(scenes(60)), chapter_pages=4)
    assert len(plan.chapters) >= 4
    assert sum(len(c.scenes) for c in plan.chapters) == 60
    for c in plan.chapters[:-1]:
        assert 2 <= sum(s.pages() for s in c.scenes) <= 7
    assert [c.number for c in plan.chapters] == list(range(1, len(plan.chapters) + 1))


def test_a_long_act_is_cut_again_by_the_sequences_written_inside_it():
    text = "# Act One\n\n## Sequence A\n\n" + scenes(20, 60) + "\n## Sequence B\n\n" + scenes(20, 60) + "\n# Act Two\n\n" + scenes(1)
    plan = fountain.cut(fountain.parse(text), max_pages=25)
    titles = [c.title for c in plan.chapters]
    assert any("Sequence A" in t for t in titles) and any("Sequence B" in t for t in titles)


def test_a_scene_too_long_for_a_chapter_is_said_not_split():
    text = "INT. ROOM - DAY\n\n" + " ".join(["Words go on and on."] * 900) + "\n\nANN\nHi.\n"
    plan = fountain.cut(fountain.parse(text), max_pages=5)
    assert any("one scene" in w for w in plan.warnings)


def test_the_report_names_each_chapter_with_its_size_and_speakers():
    plan = fountain.cut(fountain.parse("# One\n\n" + scenes(2) + "\n# Two\n\n" + scenes(2)))
    report = plan.report()
    assert "2 chapters" in report and "One" in report and "Two" in report and "Ann" in report and "beats" in report


def test_text_that_is_not_fountain_says_so():
    plan = fountain.cut(fountain.parse("just some words, no scene heading"))
    assert any("no scene headings" in w for w in plan.warnings)


# --- the job --------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def marvin(monkeypatch, tmp_path):
    def make(screenplay, have=None, script=""):
        fake = FakeMarvin(script, have or {})
        fake.story["dataJson"]["fountain"] = screenplay
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")

    return make


def run(ctx, **args):
    return jobs.import_beats({"job": "import-beats-1", "args": {"story": "s", **args}}, ctx)


THREE = "# 01 One\n\n" + scenes(2) + "\n# 02 Two\n\n" + scenes(2) + "\n# 03 Three\n\n" + scenes(2)


def test_the_job_cuts_the_fountain_into_chapters_beats_and_lines(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx)
    assert len(done["result"]["chapters_made"]) == 3
    assert "3 chapters" in done["log"]
    slugs = {m["slug"] for m in fake.made}
    assert "s-chapter-01" in slugs and "s-beat-1001" in slugs and "s-beat-3001" in slugs and "s-line-1001-1" in slugs or "s-line-1002-1" in slugs
    story_patch = [p for p in fake.patched if p[0] == "e0"]
    assert all("sheet_base" not in p[1]["dataJson"] for p in story_patch)
    assert story_patch and "from the Fountain" in story_patch[0][1]["dataJson"]["sheet_log"]


def test_a_preview_reports_the_split_and_writes_nothing(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx, dry_run="yes")
    assert fake.made == [] and "3 chapters" in done["log"] and done["result"]["dry_run"] is True
    story = [p for p in fake.patched if p[0] == "e0"]  # only the report is written, to the story's split_plan: no records, and no entry in its log
    assert len(fake.patched) == 1 and "Preview only: nothing was made" in story[0][1]["dataJson"]["split_plan"] and "3 chapters" in story[0][1]["dataJson"]["split_plan"]
    assert "sheet_log" not in story[0][1]["dataJson"]


def test_one_part_makes_only_that_chapter(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx, part="2")
    assert done["result"]["chapters_made"] == ["s-chapter-02"]
    assert all(("-2" in m["slug"] or "chapter-02" in m["slug"]) for m in fake.made)


def test_refreshing_one_part_never_touches_the_others(marvin):
    other = {f"s-beat-{n}": {"id": f"id-{n}", "slug": f"s-beat-{n}", "title": "x", "dataJson": {"story": "s", "number": str(n)}} for n in (1001, 3001)}
    other["s-chapter-03"] = {"id": "id-ch3", "slug": "s-chapter-03", "title": "Three", "dataJson": {"story": "s", "number": "03"}}
    fake, ctx = marvin(THREE, have=other)
    done = run(ctx, part="2", mode="refresh")
    assert fake.deleted == [] and done["result"]["trashed"] == []


def test_a_part_the_screenplay_does_not_have_is_refused_with_the_chapters_it_has(marvin):
    fake, ctx = marvin(THREE)
    with pytest.raises(JobError, match="no chapter 9.*chapters are 1, 2, 3"):
        run(ctx, part="9")
    with pytest.raises(JobError, match="not a chapter number"):
        run(ctx, part="two")
    assert fake.made == []


def test_no_screenplay_is_said(marvin):
    fake, ctx = marvin("")
    with pytest.raises(JobError, match="no Fountain"):
        run(ctx)


def test_more_records_than_one_page_are_all_seen_so_nothing_is_made_twice(marvin):
    text = "INT. ROOM - DAY\n\nANN\nHello.\n"
    have = {}
    for n in range(1, 451):  # more than two pages of 200
        have[f"s-line-{n:02d}-1"] = {"id": f"l{n}", "slug": f"s-line-{n:02d}-1", "title": "x", "dataJson": {"story": "s"}}
    have["s-beat-01"] = {"id": "b1", "slug": "s-beat-01", "title": "x", "dataJson": {"story": "s", "number": "01"}}
    have["s-line-01-1"] = {"id": "l1", "slug": "s-line-01-1", "title": "x", "dataJson": {"story": "s", "text": "Hello.", "speaker": "ann", "beat": "s-beat-01"}}
    fake, ctx = marvin(text, have=have)
    done = run(ctx)
    assert done["result"]["beats_made"] == 0 and done["result"]["lines_made"] == 0


def test_without_a_part_the_storys_own_import_part_says_which_chapters(marvin):
    fake, ctx = marvin(THREE)
    fake.story["dataJson"]["import_part"] = "3"
    done = run(ctx)
    assert done["result"]["chapters_made"] == ["s-chapter-03"] and done["result"]["part"] == "3"
    fake2, ctx2 = marvin(THREE)
    fake2.story["dataJson"]["import_part"] = "3"
    assert run(ctx2, part="1")["result"]["chapters_made"] == ["s-chapter-01"]  # a part given in the run wins


def test_a_chapter_whose_title_changed_under_the_same_number_is_flagged_before_anything_is_made(marvin):
    have = {"s-chapter-02": {"id": "c2", "slug": "s-chapter-02", "title": "Something else", "dataJson": {"story": "s", "number": "02"}}}
    fake, ctx = marvin(THREE, have=have)
    done = run(ctx, dry_run="yes")
    assert "Check the numbering" in done["log"] and "chapter 2 is “Something else” in Marvin but “Two” in the screenplay" in done["log"]
    assert "Check the numbering" not in run(marvin(THREE)[1], dry_run="yes")["log"]  # nothing there yet: nothing to flag


NOTED = """Title: Granny Advice
Author: J

/* a boneyard
that runs over
several lines */

# Act One

EXT. PORCH - DUSK

Granny rocks. [[the dog is asleep]]

GRANNY
Never go to bed angry.

## The dog

INT. KITCHEN - NIGHT

Tea is poured.

# Act Two

EXT. PORCH - DAWN

GRANNY
Nonsense.
"""


def test_chapter_slices_are_the_writers_own_text_notes_and_all_cut_at_the_section_that_starts_each():
    plan = fountain.cut(fountain.parse(NOTED), chapter_pages=0.1)
    slices = fountain.chapter_texts(NOTED, plan)
    assert slices is not None and len(slices) == len(plan.chapters) >= 2
    joined = "".join(slices[n] for n in sorted(slices))
    assert "[[the dog is asleep]]" in joined  # a note survives
    assert "Title: Granny Advice" not in joined and "boneyard" not in joined  # the title page and the boneyard above the first section are not in a chapter
    first = slices[min(slices)]
    assert first.startswith("# Act One")  # a chapter starts at the section written above its first scene
    assert slices[max(slices)].startswith("# Act Two") and slices[max(slices)].rstrip().endswith("Nonsense.")
    assert all(s.endswith("\n") and not s.endswith("\n\n") for s in slices.values())


def test_a_screenplay_of_one_chapter_gives_one_slice_from_its_first_scene_to_the_end():
    one = "Title: T\n\nEXT. PORCH - DUSK\n\nGranny rocks.\n\nGRANNY\nHello.\n"
    plan = fountain.cut(fountain.parse(one))
    assert fountain.chapter_texts(one, plan) == {1: "EXT. PORCH - DUSK\n\nGranny rocks.\n\nGRANNY\nHello.\n"}


def test_slices_work_on_windows_line_breaks_and_a_byte_order_mark():
    text = "﻿" + NOTED.replace("\n", "\r\n")
    plan = fountain.cut(fountain.parse(text), chapter_pages=0.1)
    slices = fountain.chapter_texts(text, plan)
    assert slices is not None and "\r" not in "".join(slices.values())


def test_no_slices_when_the_text_does_not_match_the_chapters_found():
    plan = fountain.cut(fountain.parse(NOTED), chapter_pages=0.1)
    assert fountain.chapter_texts(NOTED.replace("EXT. PORCH - DAWN", "EXT. PORCH - NOON"), plan) is None


# --- the Fountain is the one source: a field, a file, an older field; each chapter holds its own part ---------------------------------------


def _chapter_texts(fake):
    return {m["slug"]: m["dataJson"].get("fountain") for m in fake.made if m["slug"].startswith("s-chapter-")}


def test_each_chapter_made_holds_its_own_part_of_the_fountain(marvin):
    fake, ctx = marvin(THREE)
    run(ctx)
    held = _chapter_texts(fake)
    assert set(held) == {"s-chapter-01", "s-chapter-02", "s-chapter-03"}
    assert held["s-chapter-01"].startswith("# 01 One") and held["s-chapter-02"].startswith("# 02 Two") and held["s-chapter-03"].startswith("# 03 Three")
    assert "".join(held[k] for k in sorted(held)).count("INT. ROOM - DAY") == THREE.count("INT. ROOM - DAY")  # nothing is lost between them


def test_one_part_gives_only_that_chapter_its_text(marvin):
    fake, ctx = marvin(THREE)
    run(ctx, part="2")
    assert list(_chapter_texts(fake)) == ["s-chapter-02"] and _chapter_texts(fake)["s-chapter-02"].startswith("# 02 Two")


def test_a_preview_makes_nothing_and_says_the_chapters_would_hold_their_text(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx, dry_run="yes")
    assert fake.made == [] and "would hold" in done["log"]


def test_the_fountain_field_is_read_in_place_of_the_older_screenplay_field(marvin):
    fake, ctx = marvin("")
    fake.story["dataJson"]["fountain"] = THREE
    run(ctx)
    assert len(_chapter_texts(fake)) == 3


def test_an_uploaded_fountain_file_is_read_whatever_its_size(marvin, monkeypatch):
    fake, ctx = marvin("")
    fake.story["dataJson"]["fountain_file"] = "asset-1"
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, asset, dest: dest.write_text(THREE, encoding="utf-8"))
    run(ctx)
    assert len(_chapter_texts(fake)) == 3
    assert jobs._fountain_text(ctx, "s", fake.story["dataJson"])[1] == "s's uploaded Fountain file"


def test_fountain_text_and_an_uploaded_file_together_are_said_not_guessed_at(marvin):
    fake, ctx = marvin("")
    fake.story["dataJson"].update(fountain=THREE, fountain_file="asset-1")
    with pytest.raises(JobError, match="Fountain text and an uploaded Fountain file"):
        run(ctx)


def test_a_chapter_made_before_chapters_held_their_text_is_given_it(marvin):
    fake, ctx = marvin(THREE, have=["s-chapter-01", "s-chapter-02"])
    run(ctx)
    filled = {p[0]: p[1]["dataJson"]["fountain"] for p in fake.patched if p[0].startswith("id-s-chapter-")}
    assert set(filled) == {"id-s-chapter-01", "id-s-chapter-02"} and filled["id-s-chapter-01"].startswith("# 01 One")
    assert set(_chapter_texts(fake)) == {"s-chapter-03"}  # the one that was missing is made with its text


# --- rules read from the Fountain spec and from screenplay-tools' parser, found with a real file ---------------------------------------------

PIRATES = '''Title: THE DEVIL'S SHOALS
Credit: Written by
Author: AI Collaborator
Source: Original Story
Draft date: November 2026
Format: Short Screenplay

TITLE CARD: "Dead men tell no tales."

EXT. THE DEVIL'S SHOALS - NIGHT

A violent thunderstorm rages.

CHET
(shouting over the storm)
The hull is groaning, Captain!

VALERIE (CONT'D)
(sneers)
Drop anchor in a graveyard, boy?
'''


def test_a_title_page_may_hold_keys_of_its_own_and_is_not_made_into_a_picture():
    els = fountain.parse(PIRATES)
    assert els[0] == {"t": "action", "text": 'TITLE CARD: "Dead men tell no tales."'}  # the title page is gone; the writer's own first line is not
    plan = fountain.cut(els)
    assert not any("Credit" in b["picture"] or "Written by" in b["picture"] for _c, _n, b in plan.rows())


def test_a_first_line_that_only_looks_like_a_key_is_action_not_a_title_page():
    els = fountain.parse('TITLE CARD: "Dead men tell no tales."\n\nEXT. SHOALS - NIGHT\n\nWaves.\n')
    assert els[0]["t"] == "action" and "TITLE CARD" in els[0]["text"]


def test_a_note_never_closed_ends_at_the_blank_line_and_cannot_swallow_the_script():
    text = "INT. PORCH - DAY\n\nGranny rocks. [[never closed\n\nGRANNY\nHello, dear.\n\nINT. KITCHEN - NIGHT\n\nTea. [[fine note]]\n"
    els = fountain.parse(text)
    assert [(e["t"], e.get("name") or e.get("text")) for e in els] == [
        ("scene", "INT. PORCH - DAY"), ("action", "Granny rocks."), ("dialogue", "GRANNY"), ("scene", "INT. KITCHEN - NIGHT"), ("action", "Tea."),
    ]


def test_a_note_over_several_lines_is_still_the_writers_and_dropped():
    els = fountain.parse("INT. PORCH - DAY\n\nGranny rocks. [[a note\nover two lines]] She hums.\n")
    assert els[1]["text"] == "Granny rocks.  She hums."


def test_contd_is_not_an_extension_and_the_name_stays_the_name():
    els = [e for e in fountain.parse(PIRATES) if e["t"] == "dialogue"]
    assert [(e["name"], e["ext"]) for e in els] == [("CHET", ""), ("VALERIE", "")]


def test_fountain_handed_over_in_a_code_fence_reads_as_if_it_were_not():
    fenced = "```fountain\n" + PIRATES + "```\n"
    assert fountain.parse(fenced) == fountain.parse(PIRATES)
    plan = fountain.cut(fountain.parse(fenced))
    assert fountain.chapter_texts(fenced, plan) == fountain.chapter_texts(PIRATES, fountain.cut(fountain.parse(PIRATES)))


def test_a_fence_in_the_middle_of_the_script_is_left_alone():
    text = "INT. PORCH - DAY\n\n```\nnot a fence round the whole\n\nGranny rocks.\n"
    assert any("```" in e.get("text", "") for e in fountain.parse(text))


DUAL = """INT. DECK - NIGHT

CHET
Captain, look down.

VALERIE
What now?

CHET^
(screaming)
They're here!
VALERIE^
(laughing)
Looks like we're joining the fleet!

CHET
BREAKER AHEAD!
"""


def test_two_speakers_run_together_with_no_blank_line_between_them_are_two_speeches():
    speeches = [(e["name"], e["text"], e["paren"]) for e in fountain.parse(DUAL) if e["t"] == "dialogue"]
    assert speeches == [
        ("CHET", "Captain, look down.", []), ("VALERIE", "What now?", []),
        ("CHET", "They're here!", ["screaming"]), ("VALERIE", "Looks like we're joining the fleet!", ["laughing"]),
        ("CHET", "BREAKER AHEAD!", []),
    ]


def test_a_shouted_line_that_is_not_a_known_speaker_stays_part_of_the_speech():
    text = "INT. DECK - NIGHT\n\nCHET\nLook!\nBREAKER AHEAD!\nHold on.\n\nVALERIE\nAye.\n"
    chet = [e for e in fountain.parse(text) if e["t"] == "dialogue" and e["name"] == "CHET"]
    assert len(chet) == 1 and chet[0]["text"] == "Look! BREAKER AHEAD! Hold on."


def test_the_marks_of_bold_italic_and_underline_do_not_reach_the_words():
    els = fountain.parse("INT. DECK - NIGHT\n\nJagged, *black* rocks and **tattered** sails, ***both***, _underlined_.\n\nCHET\nIt's *so* big, and 2 * 3 * 4 stays, snake_case too.\n")
    assert els[1]["text"] == "Jagged, black rocks and tattered sails, both, underlined."
    assert els[2]["text"] == "It's so big, and 2 * 3 * 4 stays, snake_case too."


# --- every element of the Fountain spec in one script: what the reader must make of each -----------------------------------------------------

ALL_ELEMENTS = """Title: All Elements
Credit: Written by
Author: Test
Contact:
    Agent: Someone
    123 Street

[[A note
over two lines]]

/* a boneyard
over two lines */

# ACT ONE

= A synopsis of the act.

## The porch

= Another synopsis.

EXT. PORCH - DUSK #1#

Granny rocks. *Italic*, **bold**, ***both***, _underline_. [[inline note]]

!SHOUT IN ACTION, FORCED

.A FORCED HEADING

INT. KITCHEN - NIGHT

GRANNY (V.O.)
(softly)
Never go to bed angry.

@McDUFF
A forced character cue.

BOB
I'm here.

ANN
Wait for me.

> CENTERED <

~Willy wanna go home
~Willy wanna go home

CUT TO:

> FADE OUT.

===

# ACT TWO

INT. HALL - DAY

BRICK
Screw retirement.

STEEL ^
Screw retirement.

GRANNY (CONT'D)
Done.

THE END
"""


def test_every_element_of_the_fountain_spec_is_read_as_the_spec_says():
    def show(e):
        if e["t"] == "dialogue":
            return ("dialogue", e["name"], e["ext"], e["paren"], e["text"])
        if e["t"] == "break":
            return ("break",)
        return (e["t"], e.get("title") or e["text"]) if e["t"] != "section" else ("section", e["depth"], e["title"])

    assert [show(e) for e in fountain.parse(ALL_ELEMENTS)] == [
        ("section", 1, "ACT ONE"),  # a section; the page break is the writer's, and the title page, notes and boneyard are dropped
        ("synopsis", "A synopsis of the act."),  # a synopsis is the writer's one-line summary
        ("section", 2, "The porch"),
        ("synopsis", "Another synopsis."),
        ("scene", "EXT. PORCH - DUSK"),  # its scene number (#1#) is not part of the place
        ("action", "Granny rocks. Italic, bold, both, underline."),  # emphasis marks and the inline note are gone
        ("action", "SHOUT IN ACTION, FORCED"),  # `!` forces action
        ("scene", "A FORCED HEADING"),  # `.` forces a scene heading
        ("scene", "INT. KITCHEN - NIGHT"),
        ("dialogue", "GRANNY", "V.O.", ["softly"], "Never go to bed angry."),  # an extension, a parenthetical
        ("dialogue", "McDUFF", "", [], "A forced character cue."),  # `@` forces a cue (mixed case)
        ("dialogue", "BOB", "", [], "I'm here."),
        ("dialogue", "ANN", "", [], "Wait for me."),
        ("centred", "CENTERED"),  # `> text <` alone is centred text: the words of a plain card
        ("lyrics", "Willy wanna go home Willy wanna go home"),  # lyrics (`~`) are the words, without the mark
        ("transition", "CUT TO:"),
        ("transition", "FADE OUT."),  # `>` forces a transition
        ("break",),  # `===` starts the next picture
        ("section", 1, "ACT TWO"),
        ("scene", "INT. HALL - DAY"),
        ("dialogue", "BRICK", "", [], "Screw retirement."),
        ("dialogue", "STEEL", "", [], "Screw retirement."),  # the second speaker of a dual dialogue (`^`) is a speech like any other
        ("dialogue", "GRANNY", "", [], "Done."),  # (CONT'D) is not an extension
        ("action", "THE END"),
    ]


def test_a_synopsis_right_under_a_scene_heading_is_the_writers_and_is_not_in_the_beat():
    text = "EXT. SHOALS - NIGHT\n= The brigantine fights a losing battle.\n\nA violent storm rages.\n\n.THE DECK - NIGHT\n= Introduce the environment.\n\nLightning flashes.\n"
    els = fountain.parse(text)
    assert [(e["t"], e["text"]) for e in els] == [
        ("scene", "EXT. SHOALS - NIGHT"), ("synopsis", "The brigantine fights a losing battle."), ("action", "A violent storm rages."),
        ("scene", "THE DECK - NIGHT"), ("synopsis", "Introduce the environment."), ("action", "Lightning flashes."),
    ]
    assert not any("=" in b["picture"] for _c, _n, b in fountain.cut(els).rows())


def test_centred_text_written_with_empty_markers_round_it_is_just_the_words():
    els = fountain.parse("INT. DECK - NIGHT\n\n> <\n**THE DEVIL'S SHOALS**\n> <\n\nWaves.\n")
    assert [e["text"] for e in els if e["t"] == "action"] == ["THE DEVIL'S SHOALS", "Waves."]
    assert [(e["t"], e["text"]) for e in fountain.parse("INT. DECK - NIGHT\n\n> THE END <\n")][1:] == [("centred", "THE END")]  # written as one line it is a card's words


SONG = "INT. PORCH - DUSK\n\nGranny rocks.\n\n~Row, row, row your boat\n~Gently down the stream\n\nGRANNY\nListen to this.\n~Merrily, merrily\n~Life is but a dream\n\nThe dog howls.\n"


def test_lyrics_are_not_described_in_the_picture_and_a_sung_line_of_a_speech_has_no_mark():
    els = fountain.parse(SONG)
    assert [(e["t"], e.get("text")) for e in els if e["t"] in ("lyrics", "dialogue")] == [("lyrics", "Row, row, row your boat Gently down the stream"), ("dialogue", "Listen to this. Merrily, merrily Life is but a dream")]
    plan = fountain.cut(els)
    assert not any("Row, row" in b["picture"] for _c, _n, b in plan.rows())


def test_a_sung_line_travels_with_its_beat_as_a_sound_note_and_the_cut_still_loses_nothing():
    plan = fountain.cut(fountain.parse(SONG))
    assert fountain.check(plan) == []
    kind, rows = beat_import.parse_any(plan.sheet())
    first = rows[0]
    assert "Row, row, row your boat" in beat_import.notes_of(first) and "Sound:" in beat_import.notes_of(first)
    assert [l["text"] for r in rows for l in r["lines"]] == ["Listen to this. Merrily, merrily Life is but a dream"]


def test_a_sound_note_is_read_once_from_a_cell_written_with_pilcrows():
    plan = fountain.cut(fountain.parse(SONG))
    notes = [beat_import.notes_of(r) for r in beat_import.parse_any(plan.sheet())[1]]
    assert notes[0] == "Sound: sung: Row, row, row your boat Gently down the stream"


def test_an_escaped_mark_is_the_plain_character():
    els = fountain.parse("INT. X - DAY\n\nTwo \\*stars\\* here, _under_ and snake\\_case.\n")
    assert els[1]["text"] == "Two *stars* here, under and snake_case."


# --- the metadata: title page, transitions, synopses ------------------------------------------------------------------------------------------


def test_the_title_page_is_read_with_its_own_keys_and_its_multi_line_entries():
    entries = fountain.title_page(DEVILS)
    assert entries["title"] == "THE DEVIL'S SHOALS" and entries["draft_date"] == "November 2026" and entries["format"] == "Short Screenplay"
    assert entries["contact"] == "Agent: Blackbeard Literary\n123 Tortuga Way"
    assert list(entries)[:3] == ["title", "credit", "author"]
    assert fountain.title_page("EXT. SHOALS - NIGHT\n\nWaves.\n") == {} and fountain.title_page('TITLE CARD: "Dead men."\n\nEXT. X - DAY\n') == {}


DEVILS = """Title: THE DEVIL'S SHOALS
Credit: Written by
Author: AI Collaborator
Draft date: November 2026
Format: Short Screenplay
Contact:
    Agent: Blackbeard Literary
    123 Tortuga Way

# ACT I: THE WRECK

= The wreck of a pirate ship.

EXT. SHOALS - NIGHT
= The brigantine fights a losing battle.

Waves crash.

CROSSFADE TO:

INT. CABIN - NIGHT
= The captain refuses to back down.

CHET
Look!

FADE OUT.

# ACT II: THE DAMNED

INT. HOLD - DAY
= Seawater floods the hold.

Gold spills.

CUT TO:

EXT. DECK - DAY

Fog.
"""


def test_a_transition_belongs_to_the_beat_that_comes_after_it_in_the_words_the_video_has():
    plan = fountain.cut(fountain.parse(DEVILS))
    beats = [b for _c, _n, b in plan.rows()]
    assert [(b["picture"][:12], b.get("transition"), b.get("transition_text")) for b in beats] == [
        ("Exterior: Sh", None, None),  # the heading in words, not INT./EXT.
        ("Interior: Ca", "dissolve", "CROSSFADE TO:"),
        ("Interior: Ho", "fade", "FADE OUT."),  # written at the end of the last chapter, it belongs to the first beat of the next
        ("Exterior: De", "cut", "CUT TO:"),
    ]


@pytest.mark.parametrize(
    ("line", "kind"),
    [("CUT TO:", "cut"), ("SMASH CUT TO:", "cut"), ("MATCH CUT TO:", "cut"), ("DISSOLVE TO:", "dissolve"), ("CROSSFADE TO:", "dissolve"), ("CROSS DISSOLVE TO:", "dissolve"),
     ("FADE TO:", "fade"), ("FADE OUT.", "fade"), ("FADE TO BLACK.", "fade"), ("FADE IN:", "fade"), ("WIPE TO:", None)],
)
def test_a_transition_line_is_a_cut_a_fade_or_a_dissolve(line, kind):
    assert fountain.transition_kind(line) == kind


def test_synopses_become_the_chapters_summary_those_under_the_section_first():
    plan = fountain.cut(fountain.parse(DEVILS))
    assert [c.summary for c in plan.chapters] == [
        "The wreck of a pirate ship. The brigantine fights a losing battle. The captain refuses to back down.",
        "Seawater floods the hold.",
    ]
    assert not any("=" in b["picture"] or "brigantine fights" in b["picture"] for _c, _n, b in plan.rows())


# --- nothing the writer wrote is dropped: each beat and line keeps its own piece, as written -----------------------------------------------------


def _planned(text):
    return fountain.cut(fountain.parse(text, lines=True), chapter_pages=0.1, text=text)


def test_the_pieces_of_all_the_beats_and_the_front_make_the_whole_text_again():
    plan = _planned(DEVILS)
    beats = [b for _c, _n, b in plan.rows()]
    assert plan.front.startswith("Title: THE DEVIL'S SHOALS") and "123 Tortuga Way" in plan.front
    whole = plan.front + "\n" + "\n".join(b["fountain"] for b in beats)
    assert whole.split() == DEVILS.split()  # every word, in order (the blank lines between pieces are the only difference)


def test_a_section_and_a_transition_written_before_a_beat_belong_to_it():
    beats = [b for _c, _n, b in _planned(DEVILS).rows()]
    assert beats[2]["fountain"].startswith("FADE OUT.\n\n# ACT II: THE DAMNED")  # the transition into it, then its section
    assert "= Seawater floods the hold." in beats[2]["fountain"]  # and its synopsis
    assert beats[1]["fountain"].startswith("CROSSFADE TO:")
    assert beats[3]["fountain"].startswith("CUT TO:")


def test_a_speech_keeps_its_own_text_with_the_marks_the_words_do_not_show():
    text = "INT. PORCH - DAY\n\nANN (V.O.)\n(softly)\nI said *never* [[stress it]].\n\nBOB\nWell.\n"
    plan = _planned(text)
    lines = [ln for _c, _n, b in plan.rows() for ln in b["lines"]]
    assert lines[0]["text"] == "I said never ." and lines[0]["fountain"] == "ANN (V.O.)\n(softly)\nI said *never* [[stress it]].\n"
    assert lines[1]["fountain"] == "BOB\nWell.\n"


def test_two_speakers_at_once_are_flagged_on_the_second_whichever_way_the_caret_was_written():
    spec = "INT. DECK - NIGHT\n\nBRICK\nScrew retirement.\n\nSTEEL ^\nScrew retirement.\n"
    ai = "INT. DECK - NIGHT\n\nVALERIE\nBrace.\n\nCHET^\n(screaming)\nHere!\nVALERIE^\n(laughing)\nFleet!\n"
    for text, flags in ((spec, [False, True]), (ai, [False, False, True])):
        assert [bool(e.get("dual")) for e in fountain.parse(text) if e["t"] == "dialogue"] == flags


def test_attaching_the_source_gives_new_records_their_piece_and_the_transition():
    plan = _planned(DEVILS)
    imp = beat_import.import_plan("s", beat_import.parse_any(plan.sheet())[1], {})
    fountain.attach_source(imp, plan, "s")
    beats = {d["number"]: d for _s, _t, d in imp["beats"]}
    assert any(d.get("transition") == "dissolve" and d["fountain"].startswith("CROSSFADE TO:") for d in beats.values())
    lines = [d for _s, _t, d in imp["lines"]]
    assert lines and lines[0]["fountain"] == "CHET\nLook!\n" and "simultaneous" not in lines[0]


def test_the_job_gives_each_beat_its_text_and_transition_each_chapter_its_summary_and_the_story_its_title_page(marvin):
    fake, ctx = marvin(DEVILS)
    run(ctx, chapter_pages="0.1")
    beats = {m["slug"]: m["dataJson"] for m in fake.made if "-beat-" in m["slug"]}
    assert beats and all(d.get("fountain") for d in beats.values())
    assert any(d.get("transition") == "dissolve" and d.get("transition_text") == "CROSSFADE TO:" for d in beats.values())
    chapters = {m["slug"]: m["dataJson"] for m in fake.made if "-chapter-" in m["slug"]}
    assert chapters["s-chapter-01"]["summary"].startswith("The wreck of a pirate ship.") and chapters["s-chapter-02"]["summary"] == "Seawater floods the hold."
    lines = [m["dataJson"] for m in fake.made if "-line-" in m["slug"]]
    assert lines and all(d.get("fountain") for d in lines)
    story = fake.patched[-1][1]["dataJson"]
    assert story["author"] == "AI Collaborator" and story["credit"] == "Written by" and story["draft_date"] == "November 2026"
    assert story["contact"] == "Agent: Blackbeard Literary\n123 Tortuga Way" and story["title_page_other"] == "format: Short Screenplay"
    assert story["fountain_front"].startswith("Title: THE DEVIL'S SHOALS")


def test_a_title_page_field_the_person_filled_in_is_kept_and_a_preview_writes_none(marvin):
    fake, ctx = marvin(DEVILS)
    fake.story["dataJson"]["author"] = "Jared"
    run(ctx, chapter_pages="0.1")
    assert fake.patched[-1][1]["dataJson"]["author"] == "Jared"
    fake2, ctx2 = marvin(DEVILS)
    run(ctx2, source="fountain", dry_run="yes", chapter_pages="0.1")
    assert "author" not in fake2.patched[-1][1]["dataJson"] and "fountain_front" not in fake2.patched[-1][1]["dataJson"]


# --- the characters and places a screenplay implies -------------------------------------------------------------------------------------

CAST_TEXT = """# ONE

EXT. THE REEF - NIGHT #1#
= The ship breaks up.

CAPTAIN VALERIE "THE VULTURE" VANE (40s) stands at the wheel. She wears a tricorn hat. One eye is clouded over. She jams a compass into her belt.

In the corner sits CHET (20s), a young, terrified cabin boy clutching a logbook.

VALERIE
Hold her straight!

CHET
The hull is groaning!

OLD HAND
Aye.

INT. CAPTAIN'S CABIN - NIGHT

Lamps swing.

EXT. THE REEF - DAWN

Calm.
"""


def test_a_character_is_made_for_each_speaker_with_what_the_screenplay_says_of_them():
    plan = fountain.cut(fountain.parse(CAST_TEXT))
    who = {c["handle"]: c for c in plan.characters}
    assert set(who) == {"Valerie", "Chet", "Hand"}
    v = who["Valerie"]
    assert (v["name"], v["age"], v["sex"]) == ('Captain Valerie "The Vulture" Vane', "40s", "female")
    assert "One eye is clouded over" in v["description"] and "compass" in v["description"]  # all of the paragraph about her alone
    assert (who["Chet"]["age"], who["Chet"]["sex"]) == ("20s", "male") and "cabin boy" in who["Chet"]["description"]
    assert who["Hand"] == {"cue": "OLD HAND", "handle": "Hand", "name": "Old Hand", "age": "", "sex": "", "description": ""}  # never introduced: only the name


def test_a_paragraph_that_names_two_people_gives_each_only_their_own_sentences():
    text = "INT. ROOM - DAY\n\nANN (30s) smiles. She waves. BOB (40s) frowns at her. He leaves.\n\nANN\nHi.\n\nBOB\nBye.\n"
    who = {c["handle"]: c for c in fountain.cut(fountain.parse(text)).characters}
    assert who["Ann"]["sex"] == "female" and who["Ann"]["description"] == "ANN (30s) smiles. She waves."
    assert who["Bob"]["sex"] == "male" and "frowns" in who["Bob"]["description"]


def test_a_place_is_once_whatever_the_time_of_day_and_beats_know_theirs():
    plan = fountain.cut(fountain.parse(CAST_TEXT))
    assert list(plan.places) == ["the-reef", "captains-cabin"]
    assert plan.places["the-reef"] == {"name": "The Reef", "kinds": ["exterior"], "times": ["Night", "Dawn"]}
    assert plan.places["captains-cabin"]["kinds"] == ["interior"]
    assert fountain.place_of(".THE BARNACLE'S REVENGE - DECK - NIGHT") == {"slug": "the-barnacles-revenge-deck", "name": "The Barnacle's Revenge - Deck", "kind": "", "time": "Night"}
    assert fountain.place_of("INT. HOLD - CONTINUOUS #4#")["time"] == "Continuous"
    assert {b["place"] for _c, _n, b in plan.rows()} == {"EXT. THE REEF - NIGHT", "INT. CAPTAIN'S CABIN - NIGHT", "EXT. THE REEF - DAWN"}


class CastingMarvin(FakeMarvin):
    """FakeMarvin that also knows Characters and Scenes, and keeps the ones already there apart from lines."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.on_hand = {"cast-member": {}, "scene": {}, "sound": {}}

    def query(self, creds, spec, limit=100):
        if "entries" not in spec and spec["entry_type"] in self.on_hand:
            return list(self.on_hand[spec["entry_type"]].values())
        return super().query(creds, spec, limit)

    def request(self, creds, path, **kw):
        if path == "/api/platform/entry-types":
            types = json.loads(super().request(creds, path, **kw))
            return json.dumps(types + [{"slug": "cast-member", "id": "T-cast"}, {"slug": "scene", "id": "T-scene"}, {"slug": "sound", "id": "T-sound"}]).encode()
        return super().request(creds, path, **kw)


@pytest.fixture
def casting(monkeypatch, tmp_path):
    def make(screenplay):
        fake = CastingMarvin("", {})
        fake.story["dataJson"]["fountain"] = screenplay
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")

    return make


def test_the_import_makes_the_characters_and_scenes_and_puts_each_beat_in_its_scene(casting):
    fake, ctx = casting(CAST_TEXT)
    done = run(ctx)
    by = {m["slug"]: m for m in fake.made}
    valerie = by["s-valerie"]["dataJson"]
    assert by["s-valerie"]["entryTypeId"] == "T-cast" and by["s-valerie"]["title"] == 'Captain Valerie "The Vulture" Vane'
    assert valerie["speaker"] == "valerie" and valerie["story"] == "s" and valerie["status"] == "draft" and "actor" not in valerie
    assert valerie["role"].startswith("Woman, 40s. CAPTAIN VALERIE") and by["s-chet"]["dataJson"]["role"].startswith("Man, 20s.")
    assert by["s-hand"]["dataJson"]["role"] == ""  # not introduced: nothing is made up
    assert (valerie["age"], valerie["sex"], valerie["age_state"]) == ("40s", "female", "mid")  # what the screenplay says, as fields
    assert (by["s-chet"]["dataJson"]["age"], by["s-chet"]["dataJson"]["sex"], by["s-chet"]["dataJson"]["age_state"]) == ("20s", "male", "young")
    assert not {"age", "sex", "age_state"} & set(by["s-hand"]["dataJson"])  # and nothing for someone it says nothing of
    reef, cabin = by["s-the-reef"]["dataJson"], by["s-captains-cabin"]["dataJson"]
    assert by["s-the-reef"]["entryTypeId"] == "T-scene" and reef["place"] == "The Reef" and reef["inside_outside"] == "exterior" and reef["look"] == "Night, Dawn" and "ambience_muffled" not in reef
    assert cabin["inside_outside"] == "interior" and cabin["ambience_muffled"] is True and cabin["story_ambience_muffled"] is True  # heard from inside
    assert "story_ambience_muffled" not in reef
    beats = {m["slug"]: m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-beat"}
    assert {d["scene"] for d in beats.values()} == {"s-the-reef", "s-captains-cabin"}
    assert sorted(done["result"]["characters_made"]) == ["s-chet", "s-hand", "s-valerie"] and sorted(done["result"]["scenes_made"]) == ["s-captains-cabin", "s-the-reef"]
    assert "3 characters" in done["log"] and "2 scenes" in done["log"]


def test_a_second_import_leaves_the_characters_and_scenes_that_are_there(casting):
    fake, ctx = casting(CAST_TEXT)
    fake.on_hand["cast-member"]["s-valerie"] = {"id": "c1", "slug": "s-valerie", "title": "Vale", "dataJson": {"story": "s", "speaker": "valerie", "actor": "nell"}}
    fake.on_hand["scene"]["s-the-reef"] = {"id": "sc1", "slug": "s-the-reef", "title": "Reef", "dataJson": {"story": "s"}}
    done = run(ctx)
    assert done["result"]["characters_made"] == ["s-chet", "s-hand"] and done["result"]["scenes_made"] == ["s-captains-cabin"]
    patched = {p[0]: p[1]["dataJson"] for p in fake.patched if p[0] != "e0"}
    assert set(patched) == {"c1"}  # the only change to what exists: the Character gets the age and sex the screenplay says of her
    assert patched["c1"] == {"story": "s", "speaker": "valerie", "actor": "nell", "age": "40s", "sex": "female", "age_state": "mid"}  # nothing else touched


def test_a_preview_makes_none_of_them_but_says_so(casting):
    fake, ctx = casting(CAST_TEXT)
    done = run(ctx, dry_run="yes")
    assert fake.made == [] and "3 characters" in done["log"] and len(done["result"]["scenes_to_make"]) == 2


def test_running_the_import_again_makes_the_scenes_and_puts_earlier_beats_in_them(casting):
    first, ctx = casting(CAST_TEXT)
    run(ctx)
    beats = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": {k: v for k, v in m["dataJson"].items() if k != "scene"}} for m in first.made if m["entryTypeId"] == "T-beat"}
    again, ctx2 = casting(CAST_TEXT)
    again.records = dict(beats)
    again.on_hand["scene"]["s-the-reef"] = {"id": "sc1", "slug": "s-the-reef", "title": "Reef", "dataJson": {"story": "s", "look": "mine"}}
    done = run(ctx2)
    assert done["result"]["records_filled_in"] >= len(beats) and done["result"]["scenes_made"] == ["s-captains-cabin"]
    put = {p[0]: p[1]["dataJson"]["scene"] for p in again.patched if p[0] != "e0"}
    assert set(put.values()) == {"s-the-reef", "s-captains-cabin"} and len(put) == len(beats)


SOUND_TEXT = """INT. CABIN - NIGHT

Rain lashes the window. The sound of wood splintering echoes below. A deafening CRUNCH shakes the room. She wears a rain-soaked hat.

ANN
Hold on!

EXT. DECK - DAY

From somewhere, a ghostly low melody drifts.

~ Yo ho, yo ho
~ A pirate's life

Then, a splashing sound nearby.
"""


def test_a_beats_own_words_call_for_sounds_and_a_place_for_its_bed():
    plan = fountain.cut(fountain.parse(SOUND_TEXT))
    cues = {n: [(c["kind"], c["title"]) for c in b["sounds"]] for _c, n, b in plan.rows()}
    first = next(iter(cues.values()))
    assert ("effect", "Wood splintering") in first and ("effect", "Crunch") in first
    assert not any("Cabin" in t or "Night" in t for _k, t in first)  # the scene heading is not a sound
    music = [c for _c, _n, b in plan.rows() for c in b["sounds"] if c["kind"] == "music"]
    assert len(music) == 1 and "Yo ho, yo ho A pirate's life" in music[0]["prompt"] and "ghostly low melody" in music[0]["prompt"]
    assert any(c["title"] == "Splashing sound" for _c, _n, b in plan.rows() for c in b["sounds"])
    assert list(plan.ambience) == ["cabin"] and "Rain lashes the window" in plan.ambience["cabin"]["prompt"] and "rain-soaked" not in plan.ambience["cabin"]["prompt"]


def test_the_import_makes_a_sound_to_fill_in_for_each_and_places_it_on_its_beat(casting):
    fake, ctx = casting(SOUND_TEXT)
    done = run(ctx)
    sounds = {m["slug"]: m for m in fake.made if m["entryTypeId"] == "T-sound"}
    assert "s-ambience-cabin" in sounds and sounds["s-ambience-cabin"]["dataJson"]["kind"] == "ambience" and sounds["s-ambience-cabin"]["dataJson"]["loop"] is True
    assert all(m["dataJson"]["status"] == "draft" and m["dataJson"]["story"] == "s" and m["dataJson"]["source"] == "generated" for m in sounds.values())  # nothing is queued: nothing is spent
    scenes = {m["slug"]: m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-scene"}
    assert scenes["s-cabin"]["ambience"] == "s-ambience-cabin"
    placed = [d["sounds"] for m in fake.made if m["entryTypeId"] == "T-beat" for d in [m["dataJson"]] if d.get("sounds")]
    assert placed and all(p["sound"] in sounds and p["at"] == 0 for group in placed for p in group)
    assert len(done["result"]["sounds_made"]) == len(sounds)


def test_a_score_placeholder_is_made_and_set_as_the_storys_music_unless_it_has_one(casting):
    fake, ctx = casting(SOUND_TEXT)
    done = run(ctx)
    score = next(m for m in fake.made if m["slug"] == "s-score")
    assert score["entryTypeId"] == "T-sound" and score["dataJson"]["kind"] == "music" and score["dataJson"]["status"] == "draft" and score["dataJson"]["loop"] is True
    assert "s-score" in done["result"]["sounds_made"]
    assert [p[1]["dataJson"].get("music") for p in fake.patched if p[0] == "e0"] == ["s-score"]
    own, ctx2 = casting(SOUND_TEXT)
    own.story["dataJson"]["music"] = "my-theme"
    run(ctx2)
    assert not any(m["slug"] == "s-score" for m in own.made)
    assert [p[1]["dataJson"]["music"] for p in own.patched if p[0] == "e0"] == ["my-theme"]


# --- a page break, and the complete export ----------------------------------------------------------------------------------------------


def test_a_page_break_starts_the_next_picture():
    text = ".THE GALLEY\n\nA pot on a table.\n\n===\n\nA cook enters.\n\n===\n\nA hand.\n\nCOOK\nHello.\n"
    plan = fountain.cut(fountain.parse(text))
    assert [b["picture"] for _c, _n, b in plan.rows()] == ["The Galley. A pot on a table.", "A cook enters.", "A hand."]
    merged = fountain.cut(fountain.parse(text.replace("===\n\n", "")))
    assert len(merged.rows()) == 1  # without the breaks small actions are one picture, as before


def _records():
    row = lambda slug, title, **d: {"slug": slug, "title": title, "dataJson": d}  # noqa: E731
    return {
        "story": row("s", "The Last Onion", premise="A cook has one onion.", format="short-9x16", target_seconds=30, music="theme"),
        "chapters": {},
        "scenes": {"s-galley": row("s-galley", "Galley", story="s", place="A small galley.", look="Lantern light.", set_dressing="A pot.", continuity="Onion on the table.", ambience="s-sea", ambience_volume=0.3, ambience_muffled=True)},
        "sounds": {"s-sea": row("s-sea", "Sea", prompt="Waves on a hull."), "s-clank": row("s-clank", "Clank", prompt="A pot lid clanks.")},
        "characters": [row("s-cook", "Old Cook (Bill)", cast_id="cook", speaker="cook", role="ship's cook", costume="A brown apron.", props="A wooden spoon.", rules="Peg leg on the left.", actor="bill")],
        "beats": [
            row("s-beat-01", "b1", story="s", number="01", scene="s-galley", picture="EXT. THE GALLEY, a wide shot of a pot.", hold_seconds=6, focus="the pot", sounds=[{"sound": "s-clank", "at": 1.5}]),
            row("s-beat-02", "b2", story="s", number="02", scene="s-galley", picture="A close shot of a hand.", cast="old-ship-cook"),
        ],
        "lines": {"s-beat-02": [row("s-line-02-1", "l", story="s", beat="s-beat-02", speaker="cook", text="One onion.", direction="Flat.", voice="s-voice-cook")]},
    }


def test_the_complete_export_keeps_every_detail_and_reads_back_as_the_same_beats_and_lines():
    from storyrender import script

    text = script.fountain_complete(_records())
    for said in ("Title: The Last Onion", "Premise: A cook has one onion.", "Length: about", "Music: theme", "COOK is Old Cook (Bill). Role: ship's cook. Costume: A brown apron. Props: A wooden spoon. Rules: Peg leg on the left. Played by: bill.",
                 ".GALLEY #1#", "Place: A small galley. Light: Lantern light. Set dressing: A pot. Continuity: Onion on the table.", "Ambience: Sea, level 0.3, muffled (indoors). Waves on a hull.",
                 "Hold: 6s. Focus: the pot.", "Sound: Clank. A pot lid clanks at 1.5s.", "One onion.", "(flat)", "Voice: s-voice-cook."):
        assert said in text, said
    assert "\n!EXT. THE GALLEY, a wide shot of a pot." in text  # a picture that begins like a scene heading stays a picture
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    assert [(len(c.beats), c.lines()) for c in plan.chapters] == [(2, 1)]
    assert plan.characters and plan.places and "galley" in plan.places


def test_a_hold_note_on_a_beat_sets_its_hold_and_a_hold_already_set_is_kept():
    text = ".THE GALLEY\n\nA pot.\n\n[[Beat 01. Hold: 6s. Focus: the pot.]]\n\n===\n\nA hand.\n\n[[Hold: 2.5s]]\n\n===\n\nA cook.\n"
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    imp = {"beats": [("b1", "t", {"number": "01"}), ("b2", "t", {"number": "02", "hold_seconds": 9}), ("b3", "t", {"number": "03"})], "lines": []}
    fountain.attach_source(imp, plan, "s")
    assert [d.get("hold_seconds") for _s, _t, d in imp["beats"]] == [6.0, 9, None]


def test_a_sound_note_on_a_beat_is_the_writers_own_cue_and_is_placed_where_it_says():
    text = ".THE GALLEY\n\nA pot on a table.\n\n[[Beat 01. Hold: 4s.]]\n\n[[Sound: a pot lid clanks at 1.5s.]]\n\n[[Sound: rain and wind.]]\n\n===\n\nA hand.\n"
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    first = plan.rows()[0][2]["sounds"]
    assert [(c["kind"], c["prompt"], c["at"]) for c in first] == [("effect", "a pot lid clanks", 1.5), ("effect", "rain and wind", 0.0)]
    assert plan.rows()[1][2]["sounds"] == []
    imp = {"beats": [("b1", "t", {"number": "01"})], "lines": []}
    fountain.attach_source(imp, plan, "s")
    assert imp["beats"][0][2]["sounds"] == [{"sound": "s-sound-01-1", "at": 1.5}, {"sound": "s-sound-01-2", "at": 0.0}]


def test_a_re_run_gives_records_made_earlier_their_own_piece_of_the_fountain_and_leaves_what_is_set(casting):
    first, ctx = casting(CAST_TEXT)
    run(ctx)
    recs = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": {k: v for k, v in m["dataJson"].items() if k not in ("fountain", "transition", "transition_text", "simultaneous", "scene", "sounds")}} for m in first.made if m["entryTypeId"] in ("T-beat", "T-line")}
    keep = next(s for s in recs if s.startswith("s-beat-"))
    recs[keep]["dataJson"]["fountain"] = "already mine"
    again, ctx2 = casting(CAST_TEXT)
    again.records = dict(recs)
    run(ctx2)
    patched = {p[0]: p[1]["dataJson"] for p in again.patched if p[0] != "e0"}
    assert patched.get(recs[keep]["id"], {}).get("fountain", "already mine") == "already mine"
    lines = [d for i, d in patched.items() if "-line-" in i]
    assert lines and all(d.get("fountain") for d in lines)
    beats = [d for i, d in patched.items() if "-beat-" in i and i != recs[keep]["id"]]
    assert beats and all(d.get("fountain") for d in beats)


# --- revisions: a revised Fountain is fitted to the beats already made, by what they say --------------------------------------------------


def _pieces(text):
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    return plan, {n: b["fountain"] for _c, n, b in plan.rows()}


REVISED = ".THE GALLEY\n\nA pot on a table.\n\n===\n\nA cook enters.\n\nCOOK\nHello.\n\n===\n\nA hand.\n\n===\n\nThe lid.\n"


def test_an_unchanged_fountain_keeps_every_number():
    plan, made = _pieces(REVISED)
    again, _ = _pieces(REVISED)
    found = fountain.align(again, made)
    assert found == {"same": 4, "reworded": 0, "new": [], "removed": []}
    assert [n for _c, n, _b in again.rows()] == ["01", "02", "03", "04"]


def test_a_beat_inserted_in_the_middle_is_numbered_after_the_beat_before_it_and_nothing_else_moves():
    _plan, made = _pieces(REVISED)
    revised = REVISED.replace("===\n\nA hand.", "===\n\nThe cook looks up at the sky.\n\n===\n\nA hand.")
    plan, _ = _pieces(revised)
    found = fountain.align(plan, made)
    assert found["new"] == ["02a"] and found["same"] == 4 and found["reworded"] == 0
    assert [n for _c, n, _b in plan.rows()] == ["01", "02", "02a", "03", "04"]
    two = fountain.align(_pieces(revised.replace("The cook looks up at the sky.", "The cook looks up.\n\n===\n\nThe sky darkens."))[0], made)
    assert two["new"] == ["02a", "02b"]


def test_more_than_26_beats_inserted_in_one_place_carry_on_aa_ab_and_still_play_in_order():
    _plan, made = _pieces(REVISED)
    many = "".join(f"===\n\nBeat {i} of the long insertion, with words of its own.\n\n" for i in range(30))
    plan, _ = _pieces(REVISED.replace("===\n\nA hand.", many + "===\n\nA hand."))
    found = fountain.align(plan, made)
    letters = [n[2:] for n in found["new"]]
    assert letters[:3] == ["a", "b", "c"] and letters[25:28] == ["z", "aa", "ab"] and len(found["new"]) == 30
    numbers = [n for _c, n, _b in plan.rows()]
    assert sorted(numbers, key=numbering.order_key) == numbers  # z comes before aa, and the old beats keep their places
    assert numbers[0:2] == ["01", "02"] and numbers[-2:] == ["03", "04"]


def test_beat_numbers_count_on_like_spreadsheet_columns_and_sort_by_length_first():
    assert [numbering.after(n) for n in ("02", "02a", "02y", "02z", "02az", "02zz")] == ["02a", "02b", "02z", "02aa", "02ba", "02aaa"]
    shuffled = ["3001", "3000b", "3000aa", "3000z", "3000", "3000a"]
    assert sorted(shuffled, key=numbering.order_key) == ["3000", "3000a", "3000b", "3000z", "3000aa", "3001"]


def test_a_beat_inserted_at_the_start_comes_before_the_first():
    _plan, made = _pieces(REVISED)
    plan, _ = _pieces(".THE GALLEY\n\nA wide shot of the sea.\n\n===\n\nA pot on a table.\n\n===\n\nA cook enters.\n\nCOOK\nHello.\n\n===\n\nA hand.\n\n===\n\nThe lid.\n")
    found = fountain.align(plan, made)
    assert found["new"] == ["00a"] and [n for _c, n, _b in plan.rows()][:2] == ["00a", "01"]


def test_a_reworded_beat_keeps_its_number_and_a_removed_one_is_named():
    _plan, made = _pieces(REVISED)
    plan, _ = _pieces(REVISED.replace("A pot on a table.", "A large iron pot on a scarred wooden table.").replace("===\n\nThe lid.\n", ""))
    found = fountain.align(plan, made)
    assert found["reworded"] == 1 and found["removed"] == ["04"] and found["new"] == []
    assert [n for _c, n, _b in plan.rows()] == ["01", "02", "03"]


def test_with_nothing_made_yet_or_no_positions_there_is_nothing_to_fit():
    plan, _ = _pieces(REVISED)
    assert fountain.align(plan, {}) is None
    assert fountain.align(fountain.cut(fountain.parse(REVISED)), {"01": "x"}) is None  # read without line numbers: no pieces to compare


def test_a_revised_import_adds_only_the_new_beat_and_keeps_the_numbers_of_the_rest(casting):
    first, ctx = casting(CAST_TEXT)
    run(ctx)
    made = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": dict(m["dataJson"])} for m in first.made if m["entryTypeId"] in ("T-beat", "T-line")}
    revised = CAST_TEXT.replace("INT. CAPTAIN'S CABIN - NIGHT\n\nLamps swing.", "NARRATOR\nForty days at sea.\n\n===\n\nThe lamps are all that is left of the daylight.\n\n===\n\nINT. CAPTAIN'S CABIN - NIGHT\n\nLamps swing.")
    again, ctx2 = casting(revised)
    again.records = dict(made)
    done = run(ctx2, mode="refresh")
    assert done["result"]["revision"]["new"] and done["result"]["revision"]["same"] >= 2
    new_beats = [m["slug"] for m in again.made if m["entryTypeId"] == "T-beat"]
    assert new_beats and all(re.search(r"-beat-\d+[a-z]$", s) for s in new_beats)
    assert not any(p for p in again.patched if p[0] in {r["id"] for s, r in made.items() if "-beat-" in s} and p[1]["dataJson"].get("number") != made[[k for k, v in made.items() if v["id"] == p[0]][0]]["dataJson"].get("number"))
    assert [e for e in again.deleted] == []  # nothing is trashed: the old beats are all still in the text


# --- revision drafts: check what a revision would do, then apply it ---------------------------------------------------------------------


class RevisionMarvin(CastingMarvin):
    """CastingMarvin that also serves the revision records by slug."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.entries_by_slug = {}

    def query(self, creds, spec, limit=100):
        if "entries" in spec and spec["entries"] in self.entries_by_slug:
            return [self.entries_by_slug[spec["entries"]]]
        return super().query(creds, spec, limit)

    def request(self, creds, path, **kw):
        out = super().request(creds, path, **kw)
        if kw.get("method") == "DELETE":  # a trashed record is gone from what a query returns
            gone = path.rsplit("/", 1)[-1]
            self.records = {s: r for s, r in self.records.items() if r["id"] != gone}
        if kw.get("method") == "PATCH" and path.endswith("/e0"):  # a real server keeps what it is sent: the import that follows an apply reads the new text
            self.story["dataJson"] = json.loads(kw["data"])["dataJson"]
        return out


@pytest.fixture
def revising(monkeypatch, tmp_path):
    def make(text, proposed):
        first = CastingMarvin("", {})
        first.story["dataJson"]["fountain"] = text
        monkeypatch.setattr(jobs.marvin_api, "query", first.query)
        monkeypatch.setattr(jobs.marvin_api, "request", first.request)
        ctx = Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")
        run(ctx)
        fake = RevisionMarvin("", {})
        fake.story["dataJson"].update({"fountain": text})
        fake.records = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": dict(m["dataJson"])} for m in first.made if m["entryTypeId"] in ("T-beat", "T-line")}
        fake.entries_by_slug["rev-1"] = {"id": "rev1", "slug": "rev-1", "title": "Revision A", "dataJson": {"story": "s", "proposed": proposed, "status": "draft", "note": "More narration"}}
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, ctx

    return make


NEW_TEXT = CAST_TEXT.replace("INT. CAPTAIN'S CABIN - NIGHT\n\nLamps swing.", "NARRATOR\nForty days at sea.\n\n===\n\nThe lamps are all that is left of the daylight.\n\n===\n\nINT. CAPTAIN'S CABIN - NIGHT\n\nLamps swing.")


def _job(kind_args):
    return {"job": "j", "args": kind_args}


def test_a_check_says_what_a_revision_would_do_and_writes_only_to_the_revision(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    done = jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    assert done["result"]["new_beats"] and done["result"]["same"] >= 2
    patched = {p[0]: p[1]["dataJson"] for p in fake.patched}
    assert set(patched) == {"rev1"}  # the story was not touched
    assert patched["rev1"]["base_digest"] and "Revision of what was brought in before" in patched["rev1"]["report"] and patched["rev1"]["checked"]
    assert fake.made == []  # and nothing was made


def test_applying_a_checked_revision_sets_the_text_numbers_it_and_brings_it_in(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    fake.entries_by_slug["rev-1"]["dataJson"]["base_digest"] = next(p[1]["dataJson"]["base_digest"] for p in fake.patched if p[0] == "rev1")
    done = jobs.apply_revision(_job({"revision": "rev-1"}), ctx)
    assert done["result"]["number"] == 1
    story_patches = [p[1]["dataJson"] for p in fake.patched if p[0] == "e0"]
    assert story_patches[0]["fountain"] == NEW_TEXT and story_patches[0]["revision"] == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", story_patches[0]["revision_date"])
    applied = [p[1]["dataJson"] for p in fake.patched if p[0] == "rev1"][-1]
    assert applied["status"] == "applied" and applied["number"] == 1 and applied["applied_at"]
    assert any(re.search(r"-beat-\d+[a-z]$", m["slug"]) for m in fake.made if m["entryTypeId"] == "T-beat")


def test_an_unchecked_revision_and_a_stale_one_are_refused(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    with pytest.raises(JobError, match="has not been checked"):
        jobs.apply_revision(_job({"revision": "rev-1"}), ctx)
    jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    fake.entries_by_slug["rev-1"]["dataJson"]["base_digest"] = next(p[1]["dataJson"]["base_digest"] for p in fake.patched if p[0] == "rev1")
    fake.story["dataJson"]["fountain"] = CAST_TEXT + "\nEXT. A NEW PLACE - DAY\n\nSomething else.\n"  # the story's own text moved on after the check
    with pytest.raises(JobError, match="changed after"):
        jobs.apply_revision(_job({"revision": "rev-1"}), ctx)
    assert not any(p[0] == "e0" for p in fake.patched)


def test_the_revision_is_printed_on_the_title_page_of_every_export():
    from storyrender import script

    story = {"dataJson": {"revision": 3, "revision_date": "2026-11-11"}}
    assert script.revision_text(3, "2026-11-11") == "Revision 3, 11 November 2026" and script.revision_text(None, None) == ""
    plain = script.stamp_revision("Title: X\nCredit: Written by\n\nINT. A - DAY\n", story)
    assert plain.startswith("Title: X\nCredit: Written by\nDraft date: Revision 3, 11 November 2026\n\nINT. A")
    old = script.stamp_revision("Title: X\nDraft date: November 2026\n\nINT. A - DAY\n", story)
    assert "Draft date: Revision 3, 11 November 2026 (first draft: November 2026)" in old
    assert script.stamp_revision("Title: X\n\nINT. A\n", {"dataJson": {}}) == "Title: X\n\nINT. A\n"  # no revision, no change
    assert script.stamp_revision("INT. A - DAY\n\nA man.\n", story) == "INT. A - DAY\n\nA man.\n"  # no title page to put it on
    cover = script.with_title_page("<html><title>Screenplay</title><body></body></html>", old)
    assert "Revision 3, 11 November 2026" in cover and "<title>X: script</title>" in cover


def test_the_breakdown_lists_the_applied_revisions():
    from storyrender import script

    records = {"story": {"slug": "s", "title": "S", "dataJson": {"revision": 2, "revision_date": "2026-11-12"}}, "beats": [], "lines": {}, "revisions": [
        {"slug": "r1", "title": "R1", "dataJson": {"number": 1, "applied_at": "2026-11-11", "note": "Narration in act one", "same": 14, "reworded": 1, "new_beats": "1002a", "removed": 0}},
        {"slug": "r2", "title": "R2", "dataJson": {"number": 2, "applied_at": "2026-11-12", "note": "A longer cabin scene", "same": 15, "reworded": 0, "new_beats": "1004a, 1004b", "removed": 1}}]}
    page = script.breakdown_html(script.breakdown(records))
    assert "Revisions" in page and "Narration in act one" in page and "1004a, 1004b" in page and "Revision 2, 12 November 2026" in page


# --- who is in a beat's picture ----------------------------------------------------------------------------------------------------------

def test_the_cast_of_a_beat_is_who_speaks_in_it_then_who_its_action_names_and_never_a_narrator():
    people = [{"handle": "Valerie", "cue": "VALERIE", "name": "Valerie"}, {"handle": "Chet", "cue": "CHET", "name": "Chet"}, {"handle": "Narrator", "cue": "NARRATOR (V.O.)", "name": "Narrator"}]
    beat = {"picture": "Chet looks up while the narrator speaks. Valerie waits.", "lines": [{"speaker": "Narrator"}]}
    assert fountain.cast_of(beat, people) == ["chet", "valerie"]  # named, in the order the action names them; the narrator is a voice
    assert fountain.cast_of({"picture": "Rain.", "lines": [{"speaker": "Valerie"}, {"speaker": "Chet"}, {"speaker": "Valerie"}]}, people) == ["valerie", "chet"]
    assert fountain.cast_of({"picture": "Chetwynd Hall at dusk.", "lines": []}, people) == []  # whole words only


def test_new_beats_are_cast_from_who_speaks_and_who_the_action_names(casting):
    fake, ctx = casting(CAST_TEXT)
    run(ctx)
    beats = {m["slug"]: m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-beat"}
    first = beats["s-beat-01"]
    assert first["cast"].split(",")[:2] == ["s-valerie", "s-chet"] and "s-hand" in first["cast"].split(",")
    assert "references" not in first  # nobody has a master picture yet: the cast is set and a later import adds the pictures


def test_running_the_import_again_adds_the_masters_of_the_cast_and_keeps_what_was_set(casting):
    first, ctx = casting(CAST_TEXT)
    run(ctx)
    beats = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": dict(m["dataJson"])} for m in first.made if m["entryTypeId"] == "T-beat"}
    beats["s-beat-01"]["dataJson"].pop("cast")
    mine = next(b for slug, b in beats.items() if slug != "s-beat-01")
    mine["dataJson"]["cast"] = "s-chet"  # set by hand: left as it is
    mine["dataJson"]["references"] = "a-place-picture"  # a picture of the place: kept, and the master follows it
    again, ctx2 = casting(CAST_TEXT)
    again.records = dict(beats)
    for who, master in (("valerie", "m-val"), ("chet", "m-chet")):
        again.on_hand["cast-member"][f"s-{who}"] = {"id": f"c-{who}", "slug": f"s-{who}", "title": who, "dataJson": {"story": "s", "speaker": who, "master": master}}
    run(ctx2)
    put = {p[0]: p[1]["dataJson"] for p in again.patched if p[0] != "e0"}
    one = put["id-s-beat-01"]
    assert one["cast"].split(",")[:2] == ["s-valerie", "s-chet"] and one["references"] == ["m-val", "m-chet"]  # a list: the field is an asset picker
    if mine["slug"] in {b["slug"] for b in beats.values()} and f"id-{mine['slug']}" in put:
        assert put[f"id-{mine['slug']}"]["cast"] == "s-chet" and put[f"id-{mine['slug']}"]["references"] == "a-place-picture"


def test_the_masters_follow_the_pictures_a_beat_already_lists_whether_it_holds_a_list_or_older_comma_text():
    people = {"valerie": {"slug": "s-valerie", "dataJson": {"master": "m-val"}}, "chet": {"slug": "s-chet", "dataJson": {"master": "m-chet"}}}
    beat = {"picture": "VALERIE and CHET on deck."}
    chars = [{"handle": "valerie", "name": "Valerie"}, {"handle": "chet", "name": "Chet"}]
    for held in (["place-pic"], "place-pic", "place-pic,m-val"):
        got = jobs._cast_for("s", beat, chars, people, {"references": held})  # no cast yet: it is set, and the masters follow the pictures it lists
        assert got["references"][0] == "place-pic" and set(got["references"]) == {"place-pic", "m-val", "m-chet"}, held  # kept in order, masters added once
    assert jobs._asset_refs(None) == [] and jobs._asset_refs(" a , ,b") == ["a", "b"] and jobs._asset_refs(["a", " ", "b"]) == ["a", "b"]


def test_a_beat_whose_writer_named_its_sounds_gets_only_those():
    beat = {"picture": "Lightning reveals THE BARNACLE'S REVENGE. The ship LURCHES.", "place": "EXT. SEA - NIGHT", "sung": [], "fountain": "x\n[[Sound: timber grinding against rock at 0s.]]\n"}
    assert [c["prompt"] for c in fountain.sound_cues(beat, set())] == ["timber grinding against rock"]
    unnamed = {**beat, "fountain": "x"}
    assert "Lurches" in [c["title"] for c in fountain.sound_cues(unnamed, set())]  # nobody named a sound: the words are read for one


# --- replace: start the story afresh from a revision --------------------------------------------------------------------------------------

def test_a_replace_check_says_what_goes_to_the_trash_and_what_stays(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    fake.entries_by_slug["rev-1"]["dataJson"]["how"] = "replace"
    done = jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    saved = next(p[1]["dataJson"] for p in fake.patched if p[0] == "rev1")
    assert saved["report"].startswith("REPLACE: applying this moves everything made from the current text to the Trash")
    assert done["result"]["removed"] == len([r for r in fake.records.values() if "-beat-" in r["slug"]]) and done["result"]["new_beats"] == "numbered afresh"
    assert fake.deleted == [] and fake.made == []  # a check changes nothing


def test_a_replace_apply_gives_old_records_a_new_slug_trashes_them_and_numbers_the_new_beats_afresh(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    fake.entries_by_slug["rev-1"]["dataJson"]["how"] = "replace"
    jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    fake.entries_by_slug["rev-1"]["dataJson"]["base_digest"] = next(p[1]["dataJson"]["base_digest"] for p in fake.patched if p[0] == "rev1")
    old_beats = {r["id"] for r in fake.records.values() if "-beat-" in r["slug"]}
    jobs.apply_revision(_job({"revision": "rev-1"}), ctx)
    renamed = {p[0]: p[1]["slug"] for p in fake.patched if p[1].get("slug", "").endswith("-before-rev1")}
    assert old_beats <= set(renamed) and old_beats <= set(fake.deleted)  # renamed first, then moved to the Trash
    made = {m["slug"] for m in fake.made if m["entryTypeId"] == "T-beat"}
    assert made and all(re.fullmatch(r"s-beat-\d+", s) for s in made)  # no `a` suffixes: the numbers start again
    applied = [p[1]["dataJson"] for p in fake.patched if p[0] == "rev1"][-1]
    assert applied["status"] == "applied" and applied["before"] == CAST_TEXT  # and the text it replaced is kept, to go back to


def test_an_edit_apply_keeps_the_text_it_replaced_and_trashes_nothing(revising):
    fake, ctx = revising(CAST_TEXT, NEW_TEXT)
    jobs.check_revision(_job({"revision": "rev-1"}), ctx)
    fake.entries_by_slug["rev-1"]["dataJson"]["base_digest"] = next(p[1]["dataJson"]["base_digest"] for p in fake.patched if p[0] == "rev1")
    jobs.apply_revision(_job({"revision": "rev-1"}), ctx)
    assert fake.deleted == [] and [p[1]["dataJson"] for p in fake.patched if p[0] == "rev1"][-1]["before"] == CAST_TEXT


# --- the story's setting and premise --------------------------------------------------------------------------------------------------

def test_setting_and_premise_come_from_the_title_page_and_a_filled_in_one_is_kept(marvin):
    said = DEVILS.replace("Title: THE DEVIL'S SHOALS\n", "Title: THE DEVIL'S SHOALS\nSetting: A brigantine in a night storm.\nPremise: A captain and her cabin boy are wrecked.\n", 1)
    assert said != DEVILS
    fake, ctx = marvin(said)
    run(ctx, chapter_pages="0.1")
    story = fake.patched[-1][1]["dataJson"]
    assert story["setting"] == "A brigantine in a night storm." and story["premise"] == "A captain and her cabin boy are wrecked."
    assert "setting" not in story.get("title_page_other", "") and "premise" not in story.get("title_page_other", "")
    fake2, ctx2 = marvin(said)
    fake2.story["dataJson"]["setting"] = "Mine."
    run(ctx2, chapter_pages="0.1")
    assert fake2.patched[-1][1]["dataJson"]["setting"] == "Mine."


def test_with_no_setting_line_the_first_synopsis_stands_in_and_what_is_still_missing_is_named(marvin):
    fake, ctx = marvin(DEVILS)
    done = run(ctx, chapter_pages="0.1")
    story = fake.patched[-1][1]["dataJson"]
    assert story["setting"] == "The wreck of a pirate ship." and not story.get("premise")  # a premise is never made up
    assert any(g.startswith("no Premise") for g in done["result"]["story_gaps"]) and any(g.startswith("no World") for g in done["result"]["story_gaps"])
    assert not any(g.startswith("no Setting") for g in done["result"]["story_gaps"])
    assert "The story still lacks:" in done["log"] and "Setting taken from the screenplay" in done["log"]


def test_a_preview_names_the_gaps_and_writes_no_setting(marvin):
    fake, ctx = marvin(DEVILS)
    done = run(ctx, chapter_pages="0.1", dry_run="yes")
    assert "The story still lacks:" in done["log"]
    assert not any("setting" in (p[1].get("dataJson") or {}) for p in fake.patched)


def test_a_screenplay_with_no_synopsis_is_set_where_its_first_place_is():
    plan = fountain.cut(fountain.parse(CAST_TEXT.replace("= The ship breaks up.\n", "")))
    assert jobs._setting_from(plan) == "The Reef (exterior), Night, Dawn"


def test_a_character_is_introduced_by_a_comma_age_as_well_as_a_bracketed_one():
    text = "INT. CABIN - NIGHT\n\nCAPTAIN VALERIE \"THE VULTURE\" VANE, 40s, braces herself over a chart. A clouded eye beneath a soaked tricorn.\n\nCHET, 20s, clutches a waterlogged logbook.\n\nCHET\nWe have to drop anchor!\n\nVALERIE\nWe push through.\n"
    who = {c["handle"]: c for c in fountain.cut(fountain.parse(text)).characters}
    assert (who["Valerie"]["age"], who["Valerie"]["sex"]) == ("40s", "female") and "clouded eye" in who["Valerie"]["description"]
    assert who["Chet"]["age"] == "20s" and "logbook" in who["Chet"]["description"]


@pytest.mark.parametrize("age, state", [("20s", "young"), ("29", "young"), ("30s", "mid"), ("40", "mid"), ("mid-50s", "mid"), ("60s", "old"), ("70", "old"), ("", ""), (None, ""), ("elderly", "")])
def test_an_age_the_screenplay_gives_says_which_of_the_actors_ages_the_master_is_made_from(age, state):
    assert fountain.age_state(age) == state


def test_a_character_keeps_an_age_state_or_sex_a_person_set_and_only_empty_fields_are_filled(casting):
    fake, ctx = casting(CAST_TEXT)
    fake.on_hand["cast-member"]["s-valerie"] = {"id": "c1", "slug": "s-valerie", "title": "Vale", "dataJson": {"story": "s", "speaker": "valerie", "age_state": "old", "sex": "female"}}
    run(ctx)
    patched = {p[0]: p[1]["dataJson"] for p in fake.patched if p[0] != "e0"}
    assert patched["c1"]["age_state"] == "old" and patched["c1"]["age"] == "40s"  # the person's Age state stays; the empty Age is filled


def test_a_replace_makes_its_characters_new_so_it_fills_none_of_the_old_ones(casting):
    fake, ctx = casting(CAST_TEXT)
    fake.on_hand["cast-member"]["s-valerie"] = {"id": "c1", "slug": "s-valerie", "title": "Vale", "dataJson": {"story": "s", "speaker": "valerie"}}
    run(ctx, fresh="yes")
    assert not [p for p in fake.patched if p[0] == "c1"]


LINTED = """Title: Test
Author: Me

# ACT I

EXT. REEF - NIGHT

CHET (O.S.)
The hull is groaning!

NARRATOR (V.O.)
(softly)
It was a long night.

MRS. HUDSON
Well?

CRUNCH.

The bow is buried against the reef.

THE PLAGUE OF THE SEA RISES AGAIN.
The sailors hold their breath.

UNDERWATER - CONTINUOUS

A pale skull faces upward.

SUPER: THE DEVIL'S SHOALS

CUT TO:

THE END
"""


def test_lint_names_a_capitals_line_that_would_be_read_as_a_speaker_and_the_line_it_is_on():
    said = fountain.lint(LINTED)
    crunch = next(w for w in said if "`CRUNCH.`" in w)
    assert crunch.startswith("line 18:") and "!CRUNCH." in crunch and "nothing to say" in crunch  # alone in capitals
    plague = next(w for w in said if "PLAGUE" in w)
    assert plague.startswith("line 22:") and "read as a speaker" in plague and "!THE PLAGUE" in plague  # capitals above text


def test_lint_says_a_place_and_a_time_in_capitals_without_int_or_ext_is_not_a_scene():
    heading = next(w for w in fountain.lint(LINTED) if "UNDERWATER" in w)
    assert heading.startswith("line 25:") and "EXT. UNDERWATER - CONTINUOUS" in heading and ".UNDERWATER - CONTINUOUS" in heading
    assert not fountain.lint("INT. CABIN - NIGHT\n\nA lamp.\n\n.UNDERWATER - CONTINUOUS\n\nA skull.\n")  # a heading, or a forced one, is fine


def test_lint_leaves_real_cues_titles_transitions_the_title_page_and_forced_action_alone():
    said = " ".join(fountain.lint(LINTED))
    for fine in ("CHET (O.S.)", "NARRATOR (V.O.)", "MRS. HUDSON", "SUPER:", "CUT TO:", "THE END", "Title: Test", "Author: Me"):
        assert fine not in said
    assert not fountain.lint("EXT. REEF - NIGHT\n\n!CRUNCH.\n\nThe bow is buried.\n\n!THE PLAGUE OF THE SEA RISES.\n")


def test_lint_keeps_line_numbers_through_notes_and_boneyards_and_stops_at_a_dozen():
    text = "EXT. REEF - NIGHT\n\n[[a note\nover two lines]]\n\n/* cut\nthis */\n\nCRUNCH.\n"
    assert fountain.lint(text)[0].startswith("line 9:")
    many = "EXT. REEF - NIGHT\n\n" + "\n\n".join(f"BANG{n}." for n in range(20)) + "\n"
    said = fountain.lint(many)
    assert len(said) == 13 and said[-1] == "and 8 more like these"


def test_the_import_report_carries_the_checks_under_check(casting):
    fake, ctx = casting(LINTED)
    done = run(ctx, dry_run="yes")
    assert "Check:" in done["log"] and "line 18: `CRUNCH.`" in done["log"] and "UNDERWATER - CONTINUOUS" in done["log"]


def test_every_spoken_line_names_its_character_so_a_setup_can_offer_just_one_characters_lines(casting):
    fake, ctx = casting(CAST_TEXT)
    run(ctx)
    lines = [m for m in fake.made if m["entryTypeId"] == "T-line"]
    assert lines and all(m["dataJson"]["character"] == f"s-{m['dataJson']['speaker']}" for m in lines)  # the slug the import gives the Character it makes


def test_a_line_names_the_characters_real_slug_when_the_character_was_made_another_way(casting):
    fake, ctx = casting(CAST_TEXT)
    fake.on_hand["cast-member"]["s-the-captain"] = {"id": "c1", "slug": "s-the-captain", "title": "Captain", "dataJson": {"story": "s", "speaker": "valerie"}}
    run(ctx)
    said = {m["dataJson"]["speaker"]: m["dataJson"]["character"] for m in fake.made if m["entryTypeId"] == "T-line"}
    assert said["valerie"] == "s-the-captain" and said["chet"] == "s-chet"


def test_a_line_made_before_lines_named_their_character_gets_it_without_losing_its_own_piece_of_the_text(revising):
    fake, ctx = revising(CAST_TEXT, CAST_TEXT)
    for record in fake.records.values():
        record["dataJson"].pop("character", None)  # lines as an older import made them
        if record["slug"].startswith("s-line-"):
            record["dataJson"].pop("fountain", None)  # and one that also lacks its own piece of the text
    run(ctx)
    patched = {p[0]: p[1]["dataJson"] for p in fake.patched if p[0] != "e0"}
    changed = {fake.records[slug]["id"]: slug for slug in fake.records if slug.startswith("s-line-")}
    assert changed and all(patched[i]["character"].startswith("s-") and patched[i].get("fountain") for i in changed), patched  # both at once: one change to each record


@pytest.mark.parametrize(
    ("heading", "words"),
    [
        ("INT. CAPTAIN'S CABIN - NIGHT #2#", "Interior: Captain's Cabin, night"),
        ("EXT. THE DEVIL'S SHOALS - NIGHT", "Exterior: The Devil's Shoals, night"),
        ("INT. CAPTAIN'S CABIN - CONTINUOUS #2#", "Interior: Captain's Cabin"),  # when in the story is not what the light is
        ("EXT. THE WRECK - LATER", "Exterior: The Wreck"),
        ("INT./EXT. DOORWAY - DAY", "Interior and exterior: Doorway, day"),
        (".UNDERWATER - CONTINUOUS", "Underwater"),  # a forced heading says no inside or outside
    ],
)
def test_a_scene_heading_becomes_words_for_the_picture_text(heading, words):
    assert fountain.heading_words(heading) == words


@pytest.mark.parametrize("kind", ["interior", "exterior", "both"])
def test_inside_or_outside_goes_both_ways_between_the_heading_and_the_field(kind):
    heading = f"{fountain.kind_prefix(kind)} THE REEF - NIGHT"
    assert fountain.place_of(heading)["kind"] == kind  # what the script writes, the import reads back as the same
    assert fountain.kind_of_places([kind]) == kind
    assert fountain.kind_prefix("") == "" and fountain.kind_prefix(None) == "" and fountain.kind_prefix("sideways") == ""
    assert fountain.kind_of_places(["interior", "exterior"]) == "both" and fountain.kind_of_places([]) == ""


def test_a_scenes_first_picture_says_where_in_words_and_the_sounds_and_beds_do_not_read_the_heading_as_story():
    text = "INT. HOLD - NIGHT\n\nWater rushes in. A hush follows.\n\nEXT. DECK - DAY\n\nRain falls on the planks.\n"
    plan = fountain.cut(fountain.parse(text))
    pictures = [b["picture"] for _c, _n, b in plan.rows()]
    assert pictures[0].startswith("Interior: Hold, night. Water rushes in.") and pictures[1].startswith("Exterior: Deck, day. Rain falls")
    assert "INT." not in " ".join(pictures) and "EXT." not in " ".join(pictures)
    assert fountain._without_heading(pictures[0], "INT. HOLD - NIGHT").lstrip(". ").startswith("Water rushes in")  # stripped, whichever way it was written


def test_the_import_gives_a_beat_the_time_of_day_its_heading_had_and_none_when_it_had_none():
    text = "INT. HOLD - NIGHT\n\nWater rushes in.\n\n===\n\nA hand.\n\nEXT. DECK - CONTINUOUS\n\nRain falls.\n\nEXT. QUAY\n\nGulls.\n"
    plan = fountain.cut(fountain.parse(text))
    imp = {"beats": [(f"b{n}", "t", {"number": n}) for _c, n, _b in plan.rows()], "lines": []}
    fountain.attach_source(imp, plan, "s")
    times = [d.get("time_of_day") for _s, _t, d in imp["beats"]]
    assert times == ["Night", "Night", "Continuous", None]  # every beat of a heading has its time; a heading with none sets none
