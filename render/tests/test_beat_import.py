"""Beats and spoken lines read out of numbered lines or a beat-sheet table, planned as records, and made by the `import-beats` job."""

import json
from types import SimpleNamespace

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import beat_import, jobs

NUMBERED = """# One Small Boat

**01** — Narrator: The captain ordered a feast. At dawn, they would attack a merchant ship.
**02** — Narrator: Tonight, she said, they would eat like kings.
**03** — Narrator: The old cook checked his stores. Cook: Your feast. Captain: Make do.
**03a** — Sound: a pot lid rattles
- **04** — He drew breath to explain.
Cook: I have one onion.
"""

TABLE = """# Beat sheet

| Beat | Provisional time | Audio | Single still / composition |
|---|---|---|---|
| 01 | 0–8s | Narrator: The captain ordered a feast. | Low-angle medium: captain on the raised deck. |
| 02 | 8–12s | Narrator: Tonight, she said. Sound: wind in the rigging | Exterior establishing shot of the hull. |
| 3 | 12–15s | | A held picture of the sea. |
"""


def test_numbered_lines_become_beats_with_their_speakers():
    kind, rows = beat_import.parse_any(NUMBERED)
    assert kind == "numbered" and [r["beat"] for r in rows] == ["01", "02", "03", "03a", "04"]
    three = rows[2]["lines"]
    assert [(ln["speaker"], ln["text"]) for ln in three] == [("Narrator", "The old cook checked his stores."), ("Cook", "Your feast."), ("Captain", "Make do.")]


def test_words_with_no_speaker_are_the_narrators_and_a_following_speaker_line_continues_the_beat():
    _, rows = beat_import.parse_any(NUMBERED)
    four = rows[4]["lines"]
    assert [(ln["speaker"], ln["text"]) for ln in four] == [("Narrator", "He drew breath to explain."), ("Cook", "I have one onion.")]


def test_a_direction_for_a_held_beat_is_not_a_line_to_speak():
    text = "**23** — Captain: What is that for?\n**24** — Narrator: No speech. Hold on the captain's small smile. Cut to black.\n**25** — Silence.\n**26** — Silence fell over the deck.\n"
    _, rows = beat_import.parse_any(text)
    assert [len(r["lines"]) for r in rows] == [1, 0, 0, 1]  # 24 and 25 are held pictures; 26 is narration that starts with the word


def test_a_sound_cue_is_kept_apart_from_speech():
    _, rows = beat_import.parse_any(NUMBERED)
    assert rows[3]["lines"] == [] and rows[3]["sounds"][0]["text"] == "a pot lid rattles"


def test_a_beat_sheet_table_is_read_with_its_pictures_and_times():
    kind, rows = beat_import.parse_any(TABLE)
    assert kind == "table" and [r["beat"] for r in rows] == ["01", "02", "03"]
    assert rows[0]["picture"].startswith("Low-angle") and rows[0]["hold"] == 8.0
    assert rows[1]["sounds"][0]["text"] == "wind in the rigging" and rows[2]["lines"] == []


def test_text_with_neither_format_has_no_beats():
    assert beat_import.parse_any("Just a paragraph of prose.\n\nAnother one.") == ("", [])


def test_beat_numbers_are_normalised():
    assert [beat_import.beat_number(n) for n in ("4", "04", "12", "04A", "7b")] == ["04", "04", "12", "04a", "07b"]


def test_the_plan_makes_what_is_missing_and_leaves_what_is_there():
    _, rows = beat_import.parse_any(TABLE)
    plan = beat_import.import_plan("s", rows, existing={"s-beat-01", "s-line-01-1"})
    assert [b[0] for b in plan["beats"]] == ["s-beat-02", "s-beat-03"] and [ln[0] for ln in plan["lines"]] == ["s-line-02-1"]
    assert plan["have"] == {"beats": 1, "lines": 1, "chapters": 0} and plan["sounds"] == ["beat 02: wind in the rigging"]
    slug, title, data = plan["beats"][0]
    assert title.startswith("Beat 02: Narrator: Tonight") and data == {"story": "s", "number": "02", "status": "draft", "picture": "Exterior establishing shot of the hull.", "audio_notes": "Sound: wind in the rigging"}  # a spoken beat has no hold; the sound cue is kept as a note
    assert plan["lines"][0][2] == {"story": "s", "beat": "s-beat-02", "speaker": "narrator", "text": "Tonight, she said.", "status": "draft"}


def test_a_repeated_beat_number_is_reported_and_only_the_first_is_used():
    rows = beat_import.parse_numbered("**01** — Narrator: One.\n**01** — Narrator: Again.\n")
    plan = beat_import.import_plan("s", rows, set())
    assert len(plan["beats"]) == 1 and "beat 01 appears more than once" in plan["problems"][0]


class FakeMarvin:
    """Stands in for Marvin's API: a story, the entry types, the records already there (slug -> record), what gets made and what gets rewritten."""

    def __init__(self, script, have=()):
        self.story = {"id": "e0", "slug": "s", "dataJson": {"script": script}}
        self.records = {slug: {"id": f"id-{slug}", "slug": slug, "title": "old", "dataJson": {"story": "s"}} for slug in have} if not isinstance(have, dict) else have
        self.made, self.patched, self.deleted = [], [], []

    def query(self, creds, spec, limit=100):
        if "entries" in spec:
            return [self.story] if spec["entries"] == self.story["slug"] else []
        kind = spec["entry_type"]
        want = {"beat": "-beat-", "chapter": "-chapter-"}.get(kind, "-line-")
        assert spec["data"] == {"story": "s"}
        return [r for slug, r in self.records.items() if want in slug]

    def request(self, creds, path, *, method="GET", data=None, content_type=None, pause=1.0):
        if path == "/api/platform/entry-types":
            return json.dumps([{"slug": "beat", "id": "T-beat"}, {"slug": "speech-line", "id": "T-line"}, {"slug": "chapter", "id": "T-chapter"}]).encode()
        if method == "DELETE":
            self.deleted.append(path.rsplit("/", 1)[-1])
            return b"{}"
        if method == "PATCH":
            self.patched.append((path.rsplit("/", 1)[-1], json.loads(data)))
            return b"{}"
        assert path == "/api/platform/entries" and method == "POST"
        self.made.append(json.loads(data))
        return b"{}"


@pytest.fixture
def marvin(monkeypatch, tmp_path):
    def make(script=NUMBERED, have=(), sheet=None):
        fake = FakeMarvin(script, have)
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        if sheet is not None:
            monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, ref, dest: dest.write_text(sheet))
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-beats-1")

    return make


def test_the_job_reads_the_storys_script_field_and_makes_its_beats_and_lines(marvin):
    fake, ctx = marvin()
    done = jobs.import_beats({"job": "import-beats-1", "args": {"story": "s"}}, ctx)
    assert (done["result"]["format"], done["result"]["beats_made"], done["result"]["lines_made"]) == ("numbered", 5, 7)
    by_slug = {m["slug"]: m for m in fake.made}
    assert by_slug["s-beat-03"]["entryTypeId"] == "T-beat" and by_slug["s-line-03-2"]["entryTypeId"] == "T-line"
    assert by_slug["s-line-03-2"]["dataJson"]["speaker"] == "cook" and by_slug["s-line-03-2"]["dataJson"]["beat"] == "s-beat-03"
    assert "made 5 beats and 7 spoken lines" in done["log"] and "1 sound cues were not imported" in done["log"]


def test_a_second_run_changes_nothing_that_is_there(marvin):
    have = ["s-beat-01", "s-line-01-1", "s-beat-02", "s-line-02-1"]
    fake, ctx = marvin(have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)
    assert done["result"]["beats_existing"] == 2 and done["result"]["lines_existing"] == 2
    assert not {m["slug"] for m in fake.made} & set(have) and len(fake.made) == 3 + 5  # three beats (03, 03a, 04) and five lines (03 has three, 04 two)


def test_a_dry_run_says_what_it_would_make_and_makes_nothing(marvin):
    fake, ctx = marvin()
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "dry_run": "yes"}}, ctx)
    assert fake.made == [] and done["result"]["dry_run"] is True and done["log"].startswith("would make 5 beats")


def test_a_beat_sheet_asset_is_read_instead_of_the_script_field(marvin):
    fake, ctx = marvin(script="", sheet=TABLE)
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "sheet": "my-beat-sheet"}}, ctx)
    assert done["result"]["format"] == "table" and done["result"]["beats_made"] == 3
    made = {m["slug"]: m["dataJson"] for m in fake.made}
    assert "hold_seconds" not in made["s-beat-01"] and made["s-beat-03"]["hold_seconds"] == 3.0  # only the silent beat keeps its time


def test_nothing_to_read_or_no_beats_in_it_says_what_is_expected(marvin):
    _, ctx = marvin(script="")
    with pytest.raises(JobError, match="script field is empty"):
        jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)
    _, ctx = marvin(script="Just prose, no numbers.")
    with pytest.raises(JobError, match=r"\*\*01\*\* — Narrator"):
        jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)


def test_it_declares_its_inputs_and_a_story_that_is_not_there_is_refused(marvin):
    from marvin_worker.jobs import META

    assert META["import-beats"]["inputs"]["sheet"]["required"] is False and META["import-beats"]["inputs"]["sheet"]["type"] == "asset"
    fake, ctx = marvin()
    fake.story["slug"] = "other"
    with pytest.raises(JobError, match="no story “s”"):
        jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)


def _example():
    import pathlib

    doc = pathlib.Path(__file__).resolve().parents[2] / "skills" / "storyworld-stories" / "references" / "beat-sheet-format.md"
    text = doc.read_text()
    return text.split("<!-- example:start -->")[1].split("<!-- example:end -->")[0]


def test_the_worked_example_in_the_skill_reads_as_the_skill_says():
    kind, rows = beat_import.parse_any(_example())
    assert kind == "table" and [r["beat"] for r in rows] == ["01", "02", "03", "04", "04a", "05", "06", "07"]  # two scenes, two tables, one numbering
    assert [[ln["speaker"] for ln in r["lines"]] for r in rows] == [["Narrator"], ["Narrator"], ["Narrator"], ["Cook", "Captain"], [], [], [], []]
    assert rows[4]["sounds"][0]["text"] == "a pot lid rattles" and rows[5]["sounds"][0]["text"].startswith("wind")
    assert rows[6]["lines"] == [] and rows[6]["sounds"] == []  # a note that narration is wanted is neither a line nor a sound cue
    assert rows[7]["hold"] == 4.0 and rows[7]["lines"] == [] and rows[-1]["end"] == 44.0
    plan = beat_import.import_plan("s", rows, set())
    assert len(plan["beats"]) == 8 and len(plan["lines"]) == 5 and plan["problems"] == [] and plan["sounds"] == ["beat 04a: a pot lid rattles", "beat 05: wind, creaking timber"]
    assert [(c[0], c[1]) for c in plan["chapters"]] == [("s-chapter-01", "The Feast"), ("s-chapter-02", "The Table")]  # each scene heading is a chapter
    assert [b[2]["chapter"] for b in plan["beats"]] == ["s-chapter-01"] * 3 + ["s-chapter-02"] * 5


def test_a_table_beat_can_be_an_insertion():
    _, rows = beat_import.parse_any("| 04a | 24–26s | Sound: a pot lid rattles | Same picture as 04. |\n")
    assert rows[0]["beat"] == "04a"


def _rec(slug, **data):
    return {"id": f"id-{slug}", "slug": slug, "title": "Old title", "dataJson": {"story": "s", **data}}


REFRESHED = "**01** — Narrator: The first line, rewritten.\n**02** — Narrator: Second stays the same.\n"


def test_refresh_rewrites_what_nothing_has_been_made_from_and_keeps_what_has(marvin):
    have = {
        "s-beat-01": _rec("s-beat-01", number="01", status="draft"),
        "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="The first line.", status="draft"),
        "s-beat-02": _rec("s-beat-02", number="02", status="approved", still="asset-9"),  # a picture was made
        "s-line-02-1": _rec("s-line-02-1", beat="s-beat-02", speaker="narrator", text="An older second line.", status="recorded", audio="take-1"),  # recorded
        "s-beat-09": _rec("s-beat-09", number="09", status="draft"),  # not in the sheet any more
    }
    fake, ctx = marvin(script=REFRESHED, have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx)
    r = done["result"]
    assert r["updated"] == ["s-line-01-1", "s-beat-01"] or sorted(r["updated"]) == ["s-beat-01", "s-line-01-1"]
    patched = {pid: body for pid, body in fake.patched}
    assert patched["id-s-line-01-1"]["dataJson"]["text"] == "The first line, rewritten." and patched["id-s-line-01-1"]["slug"] == "s-line-01-1"
    assert patched["id-s-line-01-1"]["dataJson"]["status"] == "draft" and "id-s-beat-02" not in patched and "id-s-line-02-1" not in patched
    assert [k["slug"] for k in r["kept_because_worked_on"]] == ["s-line-02-1"] and "text" in r["kept_because_worked_on"][0]["why"]
    assert r["not_in_the_sheet"] == ["s-beat-09"] and r["trashed"] == ["s-beat-09"] and fake.deleted == ["id-s-beat-09"] and fake.made == []  # gone and untouched: Trash
    assert "Kept as they are" in done["log"] and "beat 09" in done["log"] and "Moved to the Trash" in done["log"]


def test_refresh_keeps_the_fields_the_sheet_does_not_carry(marvin):
    have = {"s-beat-01": _rec("s-beat-01", number="01", status="draft", scene="s-deck", cast="captain", picture="old picture"), "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="x", status="draft", voice="s-voice")}
    fake, ctx = marvin(script="**01** — Narrator: New words.\n", have=have)
    jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx)
    line = next(b for pid, b in fake.patched if pid == "id-s-line-01-1")["dataJson"]
    assert line["voice"] == "s-voice" and line["text"] == "New words."
    assert all(pid != "id-s-beat-01" or b["dataJson"]["scene"] == "s-deck" for pid, b in fake.patched)  # an untouched beat keeps its scene and cast


def test_add_mode_never_rewrites_a_record_that_exists(marvin):
    have = {"s-beat-01": _rec("s-beat-01", number="01", status="draft"), "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="old", status="draft")}
    fake, ctx = marvin(script=REFRESHED, have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)
    assert [p for p in fake.patched if p[0] != "e0"] == [] and done["result"]["mode"] == "add" and done["result"]["updated"] == []  # only the story's own log is written


def test_a_refresh_preview_writes_nothing(marvin):
    have = {"s-beat-01": _rec("s-beat-01", number="01", status="draft"), "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="old", status="draft")}
    fake, ctx = marvin(script=REFRESHED, have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh", "dry_run": "yes"}}, ctx)
    assert fake.patched == [] and fake.made == [] and done["log"].startswith("would make") and "would update" in done["log"]


def test_a_silent_beat_may_carry_a_sound_and_a_note_with_a_lowercase_colon_is_not_a_speaker():
    _, rows = beat_import.parse_any("| 01 | 0–6s | No speech. Sound: gulls, wind | A wide shot. |\n| 02 | 6–12s | No speech. (narration wanted: what the old man admits) | A close shot. |\n")
    assert [len(r["lines"]) for r in rows] == [0, 0] and rows[0]["sounds"][0]["text"] == "gulls, wind" and rows[1]["sounds"] == []


SCENES = """## Scene 1 - The Feast

| 01 | 0–8s | Narrator: One. | A wide shot. |
| 02 | 8–12s | No speech. | A close shot. |

## Chapter 2 - The Table

| 03 | 12–20s | Cook: Two. | A two-shot. |
"""


def test_headings_make_chapters_and_put_their_beats_in_them():
    kind, rows = beat_import.parse_any(SCENES)
    assert kind == "table" and [(r["beat"], r["chapter"]["number"], r["chapter"]["title"]) for r in rows] == [("01", "01", "The Feast"), ("02", "01", "The Feast"), ("03", "02", "The Table")]
    plan = beat_import.import_plan("s", rows, set())
    assert [c[0] for c in plan["chapters"]] == ["s-chapter-01", "s-chapter-02"] and plan["chapters"][1][2] == {"story": "s", "number": "02"}


def test_numbered_lines_under_headings_are_chaptered_too_and_a_beat_with_no_heading_has_none():
    _, rows = beat_import.parse_any("**01** — Narrator: Before any heading.\n\n## Scene 3 - Later\n**02** — Narrator: Under one.\n")
    assert [r["chapter"] and r["chapter"]["number"] for r in rows] == [None, "03"]


def test_an_existing_beat_with_no_chapter_is_given_one_but_nothing_else_changes(marvin):
    have = {"s-beat-01": _rec("s-beat-01", number="01", status="approved", still="asset-1", picture="kept"), "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="One.", status="recorded", audio="t")}
    fake, ctx = marvin(script="## Scene 1 - The Feast\n**01** — Narrator: One.\n", have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)  # add mode
    patched = {pid: body for pid, body in fake.patched}
    assert patched["id-s-beat-01"]["dataJson"]["chapter"] == "s-chapter-01" and patched["id-s-beat-01"]["dataJson"]["picture"] == "kept" and patched["id-s-beat-01"]["dataJson"]["still"] == "asset-1"
    assert [m["slug"] for m in fake.made] == ["s-chapter-01"] and "id-s-line-01-1" not in patched and done["result"]["chapters_made"] == ["s-chapter-01"]


def test_refresh_renames_an_existing_chapter_and_can_move_a_worked_on_beat_between_chapters_but_not_change_its_words():
    have = {"s-beat-01": _rec("s-beat-01", number="01", status="approved", still="a", chapter="s-chapter-01")}
    _, rows = beat_import.parse_any("## Scene 2 - New place\n| 01 | 0–8s | No speech. | A different picture. |\n")
    plan = beat_import.import_plan("s", rows, have, refresh=True, chapters={"s-chapter-02": {"id": "c2", "title": "Old title", "dataJson": {}}})
    assert [k[0] for k in plan["kept"]] == ["s-beat-01"] and "picture" in plan["kept"][0][1]  # its picture was made: kept, not rewritten
    assert any(u[0] == "s-chapter-02" and u[2] == "New place" for u in plan["updates"])


def _story_log(fake):
    body = next(b for pid, b in fake.patched if pid == "e0")  # the story's own record
    return body["dataJson"]


ORPHANS = {
    "s-beat-01": _rec("s-beat-01", number="01", status="draft", chapter="s-chapter-01"),
    "s-line-01-1": _rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="One.", status="draft"),
    "s-beat-02": _rec("s-beat-02", number="02", status="draft"),  # gone from the script, nothing made from it
    "s-line-02-1": _rec("s-line-02-1", beat="s-beat-02", speaker="narrator", text="Two.", status="draft"),
    "s-beat-03": _rec("s-beat-03", number="03", status="approved", still="asset-1"),  # gone, but a picture was made
    "s-beat-04": _rec("s-beat-04", number="04", status="draft"),  # gone, nothing made from it, but a line of it was recorded
    "s-line-04-1": _rec("s-line-04-1", beat="s-beat-04", speaker="narrator", text="Four.", status="recorded", audio="take-1"),
    "s-chapter-01": _rec("s-chapter-01", number="01"),
    "s-chapter-09": _rec("s-chapter-09", number="09"),  # no beat is in it any more
}


def test_refresh_trashes_what_is_gone_and_untouched_and_flags_what_was_made_from(marvin):
    fake, ctx = marvin(script="## Scene 1 - The Feast\n**01** — Narrator: One.\n", have=dict(ORPHANS))
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx)
    assert sorted(fake.deleted) == sorted(f"id-{slug}" for slug in ("s-beat-02", "s-line-02-1", "s-chapter-09"))  # a beat goes with its lines
    kept = {k["slug"]: k["why"] for k in done["result"]["kept_though_gone"]}
    assert kept == {"s-beat-03": "a picture was made", "s-beat-04": "a line of it was recorded"}
    assert set(done["result"]["trashed"]) == {"s-beat-02", "s-line-02-1", "s-chapter-09"} and fake.made == []
    log = _story_log(fake)["sheet_log"]
    assert "refresh" in log and "trashed: beat 02, line 02 1, chapter 09" in log and "kept though gone" in log and "beat 03" in log


def test_add_mode_only_reports_what_is_gone_and_never_trashes(marvin):
    fake, ctx = marvin(script="**01** — Narrator: One.\n", have=dict(ORPHANS))
    done = jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)
    assert fake.deleted == [] and done["result"]["trashed"] == [] and "not touched in Add mode" in done["log"]


def test_a_chapter_a_kept_beat_is_still_in_is_not_trashed(marvin):
    have = dict(ORPHANS)
    have["s-beat-03"] = _rec("s-beat-03", number="03", status="approved", still="asset-1", chapter="s-chapter-09")
    fake, ctx = marvin(script="**01** — Narrator: One.\n", have=have)
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx)
    assert "id-s-chapter-09" not in fake.deleted
    assert {"slug": "s-chapter-09", "why": "a beat that is kept is still in it"} in done["result"]["kept_though_gone"]


def test_a_preview_trashes_nothing_but_says_it_would(marvin):
    fake, ctx = marvin(script="**01** — Narrator: One.\n", have=dict(ORPHANS))
    done = jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh", "dry_run": "yes"}}, ctx)
    assert fake.deleted == [] and fake.patched == [] and "Would move to the Trash" in done["log"]


def test_the_script_is_the_one_place_a_sheet_file_only_loads_into_an_empty_one(marvin):
    _, ctx = marvin(script="**01** — Narrator: Already here.\n", sheet=TABLE)
    with pytest.raises(JobError, match="the one place to edit"):
        jobs.import_beats({"job": "j", "args": {"story": "s", "sheet": "my-sheet"}}, ctx)
    fake, ctx = marvin(script="", sheet=TABLE)
    jobs.import_beats({"job": "j", "args": {"story": "s", "sheet": "my-sheet"}}, ctx)
    saved = _story_log(fake)
    assert saved["script"] == TABLE and "loaded from my-sheet" in saved["sheet_log"]  # the file became the story's script


def test_the_log_gains_a_line_each_time_something_changes_and_none_when_nothing_does(marvin):
    fake, ctx = marvin(script="**01** — Narrator: One.\n")
    jobs.import_beats({"job": "j", "args": {"story": "s"}}, ctx)
    first = _story_log(fake)["sheet_log"]
    assert first.count("\n") == 0 and "+1 beats, +1 lines" in first and "UTC" in first
    same = {"s-beat-01": {**_rec("s-beat-01", number="01", status="draft"), "title": "Beat 01: Narrator: One."}, "s-line-01-1": {**_rec("s-line-01-1", beat="s-beat-01", speaker="narrator", text="One.", status="draft"), "title": "01 Narrator: One."}}
    fake2, ctx2 = marvin(script="**01** — Narrator: One.\n", have=same)
    jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx2)
    assert all("sheet_log" not in b["dataJson"] for pid, b in fake2.patched if pid == "e0")  # nothing changed: no log line (only the agreement is remembered)


# ---- writing the sheet back out (beat_export) and the sync-sheet job --------------------------------------------------------------------------

from storyrender import beat_export  # noqa: E402

SHEET = """# One Small Boat - Beat Sheet

## Speakers

- Narrator: the old man telling it

## Scene 1 - The Tavern

| Beat | Time | Audio | Single still / composition |
|---|---|---|---|
| 01 | 0–6s | Sound: rain and wind, a sign creaking | High wide shot of the tavern sign. |
| 02 | 6–12s | Narrator: Tell me about your first ship. Cook: The first I commanded, or the first I couldn't get off? | Two-shot across a table. |
| 02a | 12–16s | No speech. Hold on the empty cup. | Close on a bottle and two cups. |

## Scene 2 - The Deck

| Beat | Time | Audio | Single still / composition |
|---|---|---|---|
| 03 | 16–22s | No speech. (narration wanted: the old man admits how far his thoughts went) Sound: gulls | Wide shot of the deck, a boy scrubbing. |
| 04 | 22–28s | Captain: Make do. | Captain at the rail. |
"""


def _records_from_sheet(story="s"):
    """The records the importer would make from SHEET, as Marvin would hand them back."""
    _, rows = beat_import.parse_any(SHEET)
    plan = beat_import.import_plan(story, rows, set())
    recs = {}
    for slug, title, data in plan["chapters"] + plan["beats"] + plan["lines"]:
        recs[slug] = {"id": f"id-{slug}", "slug": slug, "title": title, "dataJson": data}
    return recs, rows


def _split(recs, story="s"):
    pick = lambda marker: [r for slug, r in recs.items() if marker in slug]  # noqa: E731
    return pick("-chapter-"), pick("-beat-"), pick("-line-")


def test_a_sheet_survives_the_round_trip_through_the_records_losing_nothing():
    recs, rows = _records_from_sheet()
    chapters, beat_records, line_records = _split(recs)
    text = beat_export.render_sheet("s", chapters, beat_records, line_records, beat_export.preamble_of(SHEET))
    _, again = beat_import.parse_any(text)
    assert beat_export.signature_of_rows(again) == beat_export.signature_of_rows(rows) == beat_export.signature_of_records("s", beat_records, line_records)
    assert text.startswith("# One Small Boat - Beat Sheet") and "- Narrator: the old man telling it" in text  # the preamble is kept as it was
    assert "Hold on the empty cup" in text and "Sound: gulls" in text and "narration wanted" in text  # notes and sound cues are kept
    assert "| 02a |" in text and "## Scene 2 - The Deck" in text
    plan = beat_import.import_plan("s", again, recs, refresh=True, chapters={c["slug"]: c for c in chapters})
    assert plan["updates"] == [] and plan["kept"] == [] and plan["trash"] == [] and plan["beats"] == [] and plan["lines"] == []  # reading it back changes nothing


def test_times_are_worked_out_from_the_recordings_and_do_not_count_as_an_edit():
    recs, rows = _records_from_sheet()
    chapters, beat_records, line_records = _split(recs)
    before = beat_export.digest(beat_export.signature_of_records("s", beat_records, line_records))
    for rec in line_records:
        rec["dataJson"]["duration_seconds"] = 9.5  # recordings arrived
    after = beat_export.digest(beat_export.signature_of_records("s", beat_records, line_records))
    assert before == after
    text = beat_export.render_sheet("s", chapters, beat_records, line_records)
    assert "| 01 | 0–6s |" in text  # a silent beat lasts its own hold
    assert "| 02 | 6–26s |" in text  # two recorded lines of 9.5 s plus a second at the ends: the time follows the recording


def _ready(marvin, recs, script, base="UNSET"):
    fake, ctx = marvin(script=script, have=recs)
    if base != "UNSET":
        fake.story["dataJson"]["sheet_base"] = base
    return fake, ctx


def _agreed():
    recs, _ = _records_from_sheet()
    chapters, beat_records, line_records = _split(recs)
    return recs, beat_export.digest(beat_export.signature_of_records("s", beat_records, line_records))


def test_sync_writes_the_script_back_when_only_a_beat_was_edited(marvin):
    recs, base = _agreed()
    recs["s-beat-04"]["dataJson"]["picture"] = "Captain at the rail, wind in her coat."  # edited by hand in Marvin
    fake, ctx = _ready(marvin, recs, SHEET, base)
    done = jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)
    saved = _story_log(fake)
    assert done["result"]["decision"] == "rewrote" and done["result"]["beats_edited"] == ["04"]
    assert "wind in her coat" in saved["script"] and saved["script"].startswith("# One Small Boat - Beat Sheet") and "Sound: gulls" in saved["script"]
    assert saved["sheet_base"] != base and "beats edited by hand: 04" in saved["sheet_log"]


def test_sync_says_there_is_nothing_to_do_when_the_two_agree(marvin):
    recs, base = _agreed()
    fake, ctx = _ready(marvin, recs, SHEET, base)
    assert jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)["result"]["decision"] == "in sync" and fake.patched == []


def test_sync_refuses_when_only_the_script_was_edited_and_points_to_updating_the_beats(marvin):
    recs, base = _agreed()
    fake, ctx = _ready(marvin, recs, SHEET.replace("Captain at the rail.", "Captain at the wheel."), base)
    with pytest.raises(JobError, match="update the beats from the script"):
        jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)
    assert fake.patched == []


def test_sync_stops_and_names_the_beats_when_both_were_edited(marvin):
    recs, base = _agreed()
    recs["s-beat-01"]["dataJson"]["picture"] = "A different tavern sign."  # a beat edited by hand
    fake, ctx = _ready(marvin, recs, SHEET.replace("Captain at the rail.", "Captain at the wheel."), base)  # and the script edited too
    with pytest.raises(JobError, match=r"both changed.*01, 04"):
        jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)
    assert fake.patched == []


def test_sync_will_not_guess_which_is_newer_when_they_never_agreed(marvin):
    recs, _ = _agreed()
    fake, ctx = _ready(marvin, recs, SHEET.replace("Captain at the rail.", "Captain at the wheel."))
    with pytest.raises(JobError, match="never been brought into agreement"):
        jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)


def test_sync_writes_an_empty_script_from_the_beats(marvin):
    recs, _ = _agreed()
    fake, ctx = _ready(marvin, recs, "")
    done = jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)
    assert done["result"]["decision"] == "rewrote" and "## Scene 1 - The Tavern" in _story_log(fake)["script"] and "script was empty" in _story_log(fake)["sheet_log"]


def test_a_dry_sync_writes_nothing(marvin):
    recs, base = _agreed()
    recs["s-beat-04"]["dataJson"]["picture"] = "Changed."
    fake, ctx = _ready(marvin, recs, SHEET, base)
    done = jobs.sync_sheet({"job": "j", "args": {"story": "s", "dry_run": "yes"}}, ctx)
    assert fake.patched == [] and done["result"]["decision"] == "would rewrite"


def test_sync_will_not_write_a_sheet_that_would_not_read_back_the_same(marvin):
    recs, base = _agreed()
    recs["s-line-04-1"]["dataJson"]["text"] = "Make do."
    recs["s-line-02-1"]["dataJson"]["text"] = "Tell me. Captain: it reads as another speaker."  # a line that looks like a second voice
    fake, ctx = _ready(marvin, recs, SHEET, base)
    with pytest.raises(JobError, match="cannot be written back without losing something"):
        jobs.sync_sheet({"job": "j", "args": {"story": "s"}}, ctx)
    assert fake.patched == []


def test_an_import_that_leaves_the_script_and_beats_in_agreement_records_the_agreement(marvin):
    recs, base = _agreed()
    fake, ctx = _ready(marvin, recs, SHEET)
    jobs.import_beats({"job": "j", "args": {"story": "s", "mode": "refresh"}}, ctx)
    assert _story_log(fake)["sheet_base"] == base
