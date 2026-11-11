"""A Fountain screenplay cut into chapters and beats (no AI), read back by the importer, and brought in a piece at a time by the job."""

import json

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import beat_import, beats, fountain, jobs
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
    assert ("action", "INT. NOT A HEADING") in got and ("action", "THE END") in got
    assert not any("synopsis" in str(v) for _, v in got)


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
        fake.story["dataJson"]["screenplay"] = screenplay
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")

    return make


def run(ctx, **args):
    return jobs.import_beats({"job": "import-beats-1", "args": {"story": "s", "source": "screenplay", **args}}, ctx)


THREE = "# 01 One\n\n" + scenes(2) + "\n# 02 Two\n\n" + scenes(2) + "\n# 03 Three\n\n" + scenes(2)


def test_the_job_cuts_the_screenplay_and_leaves_the_script_alone(marvin):
    fake, ctx = marvin(THREE, script="hand edited script")
    done = run(ctx)
    assert done["result"]["source"] == "fountain" and len(done["result"]["chapters_made"]) == 3
    assert "3 chapters" in done["log"]
    assert fake.story["dataJson"]["script"] == "hand edited script"
    slugs = {m["slug"] for m in fake.made}
    assert "s-chapter-01" in slugs and "s-beat-1001" in slugs and "s-beat-3001" in slugs and "s-line-1001-1" in slugs or "s-line-1002-1" in slugs
    story_patch = [p for p in fake.patched if p[0] == "e0"]
    assert all("sheet_base" not in p[1]["dataJson"] for p in story_patch)
    assert story_patch and "from the screenplay" in story_patch[0][1]["dataJson"]["sheet_log"]


def test_a_preview_reports_the_split_and_writes_nothing(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx, dry_run="yes")
    assert fake.made == [] and "3 chapters" in done["log"] and done["result"]["dry_run"] is True
    story = [p for p in fake.patched if p[0] == "e0"]  # only the report is written, to the story's split_plan: no records, and no entry in its log
    assert len(fake.patched) == 1 and "preview" in story[0][1]["dataJson"]["split_plan"] and "3 chapters" in story[0][1]["dataJson"]["split_plan"]
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
    run(ctx, source="fountain")
    held = _chapter_texts(fake)
    assert set(held) == {"s-chapter-01", "s-chapter-02", "s-chapter-03"}
    assert held["s-chapter-01"].startswith("# 01 One") and held["s-chapter-02"].startswith("# 02 Two") and held["s-chapter-03"].startswith("# 03 Three")
    assert "".join(held[k] for k in sorted(held)).count("INT. ROOM - DAY") == THREE.count("INT. ROOM - DAY")  # nothing is lost between them


def test_one_part_gives_only_that_chapter_its_text(marvin):
    fake, ctx = marvin(THREE)
    run(ctx, source="fountain", part="2")
    assert list(_chapter_texts(fake)) == ["s-chapter-02"] and _chapter_texts(fake)["s-chapter-02"].startswith("# 02 Two")


def test_a_preview_makes_nothing_and_says_the_chapters_would_hold_their_text(marvin):
    fake, ctx = marvin(THREE)
    done = run(ctx, source="fountain", dry_run="yes")
    assert fake.made == [] and "would hold" in done["log"]


def test_the_fountain_field_is_read_in_place_of_the_older_screenplay_field(marvin):
    fake, ctx = marvin("")
    fake.story["dataJson"]["fountain"] = THREE
    run(ctx, source="fountain")
    assert len(_chapter_texts(fake)) == 3


def test_an_uploaded_fountain_file_is_read_whatever_its_size(marvin, monkeypatch):
    fake, ctx = marvin("")
    fake.story["dataJson"]["fountain_file"] = "asset-1"
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, asset, dest: dest.write_text(THREE, encoding="utf-8"))
    run(ctx, source="fountain")
    assert len(_chapter_texts(fake)) == 3
    assert jobs._fountain_text(ctx, "s", fake.story["dataJson"])[1] == "s's uploaded Fountain file"


def test_fountain_text_and_an_uploaded_file_together_are_said_not_guessed_at(marvin):
    fake, ctx = marvin("")
    fake.story["dataJson"].update(fountain=THREE, fountain_file="asset-1")
    with pytest.raises(JobError, match="Fountain text and an uploaded Fountain file"):
        run(ctx, source="fountain")


def test_a_chapter_made_before_chapters_held_their_text_is_given_it(marvin):
    fake, ctx = marvin(THREE, have=["s-chapter-01", "s-chapter-02"])
    run(ctx, source="fountain")
    filled = {p[0]: p[1]["dataJson"]["fountain"] for p in fake.patched if p[0].startswith("id-s-chapter-")}
    assert set(filled) == {"id-s-chapter-01", "id-s-chapter-02"} and filled["id-s-chapter-01"].startswith("# 01 One")
    assert set(_chapter_texts(fake)) == {"s-chapter-03"}  # the one that was missing is made with its text
