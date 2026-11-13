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
    assert plan["lines"][0][2] == {"story": "s", "beat": "s-beat-02", "speaker": "narrator", "text": "Tonight, she said.", "status": "draft", "order": 1}


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
        if path == "/api/platform/entries/query":  # the job pages through the records itself: a page at a time, until one is empty
            body = json.loads(data)
            rows = self.query(creds, body["spec"], body["limit"])[body.get("offset", 0) : body.get("offset", 0) + body["limit"]]
            return json.dumps({"entries": rows}).encode()
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


def test_a_table_beat_can_be_an_insertion():
    _, rows = beat_import.parse_any("| 04a | 24–26s | Sound: a pot lid rattles | Same picture as 04. |\n")
    assert rows[0]["beat"] == "04a"


def _rec(slug, **data):
    return {"id": f"id-{slug}", "slug": slug, "title": "Old title", "dataJson": {"story": "s", **data}}


REFRESHED = "**01** — Narrator: The first line, rewritten.\n**02** — Narrator: Second stays the same.\n"


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


def test_a_beat_title_skips_the_scene_heading_its_first_picture_begins_with():
    assert beat_import._action_of("Interior: Captain's Cabin. A lantern hangs at an angle.") == "A lantern hangs at an angle."
    assert beat_import._action_of("Exterior: The Devil's Shoals, night. Black rocks break the surface.") == "Black rocks break the surface."
    assert beat_import._action_of("Interior and exterior: Doorway. A cat waits.") == "A cat waits."
    assert beat_import._action_of("Interior: Hold.") == "Interior: Hold."  # nothing follows it: the whole picture is the title
    assert beat_import._action_of("A cook enters.") == "A cook enters." and beat_import._action_of("") == ""
