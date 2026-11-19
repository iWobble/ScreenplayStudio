"""A scene's number: where its place first plays in the script, so the story lists its scenes in that order (a scene put in later takes letters, 1a)."""

import json
from pathlib import Path

from storyrender import script
from tests.test_fountain import CAST_TEXT, casting, run  # noqa: F401  (the fake workspace and the import runner)

PACKAGE = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"


def _scenes(fake) -> dict:
    return {m["slug"]: m["dataJson"].get("number") for m in fake.made if m["entryTypeId"] == "T-scene"}


def test_the_import_numbers_each_new_scene_by_where_its_place_first_appears_and_a_place_seen_again_keeps_it(casting):  # noqa: F811
    fake, ctx = casting(CAST_TEXT)  # the reef, the cabin, the reef again
    run(ctx)
    assert _scenes(fake) == {"s-the-reef": "1", "s-captains-cabin": "2"}


def test_a_refresh_numbers_a_scene_that_has_none_and_never_changes_one_that_is_set(casting):  # noqa: F811
    fake, ctx = casting(CAST_TEXT)
    fake.on_hand["scene"]["s-the-reef"] = {"id": "sc1", "slug": "s-the-reef", "title": "Reef", "dataJson": {"story": "s"}}
    fake.on_hand["scene"]["s-captains-cabin"] = {"id": "sc2", "slug": "s-captains-cabin", "title": "Cabin", "dataJson": {"story": "s", "number": "1a"}}
    run(ctx)
    patched = {p[0]: p[1]["dataJson"] for p in fake.patched if p[0] in ("sc1", "sc2")}
    assert patched == {"sc1": {"story": "s", "number": "1"}}  # the cabin's 1a is the person's


def test_the_complete_script_writes_each_scenes_own_number_and_counts_the_rest():
    beats = [{"slug": f"s-beat-0{i}", "dataJson": {"number": f"0{i}", "scene": scene, "picture": f"Picture {i}."}} for i, scene in enumerate(["s-a", "s-b", "s-c", "s-a"], 1)]
    scenes = {"s-a": {"slug": "s-a", "title": "Deck", "dataJson": {"number": "1"}}, "s-b": {"slug": "s-b", "title": "Hold", "dataJson": {"number": "1a"}}, "s-c": {"slug": "s-c", "title": "Galley", "dataJson": {}}}
    text = script.fountain_complete({"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": beats, "lines": {}, "scenes": scenes, "sounds": {}, "chapters": {}, "characters": [], "revisions": []})
    headings = [ln for ln in text.splitlines() if ln.endswith("#")]
    assert [h.rsplit(" ", 1)[-1] for h in headings] == ["#1#", "#1a#", "#3#", "#1#"]  # the galley has none: the third place


def test_a_scene_has_a_number_and_the_story_lists_its_scenes_by_it():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == "entry_type"}
    number = next(f for f in blueprints["scene"]["payload"]["schema_json"]["fields"] if f["key"] == "number")
    assert number["type"] == "text" and number["label"] == "Scene number"
    listed = next(c for c in blueprints["story"]["payload"]["schema_json"]["children"] if c["entry_type"] == "scene")
    assert listed["sort"] == {"by": "number", "then": "created_at"}  # v234: those with no number, as made


def test_a_scene_with_a_number_is_still_read_as_a_scene_and_exports_with_its_note_and_its_own_number(monkeypatch):
    from marvin_worker import marvin_api

    rows = [
        {"slug": "s", "title": "T", "dataJson": {}},
        {"slug": "s-beat-01", "title": "Beat 01", "dataJson": {"story": "s", "number": "01", "scene": "s-hangar", "picture": "The hangar doors open.", "ambience": "s-wind"}},
        {"slug": "s-chapter-1", "title": "One", "dataJson": {"story": "s", "number": "1", "ambience": "s-wind"}},
        {"slug": "s-hangar", "title": "Hangar", "dataJson": {"story": "s", "number": "1a", "place": "A hangar at night", "inside_outside": "interior"}},
        {"slug": "s-line-01-1", "title": "Line", "dataJson": {"story": "s", "beat": "s-beat-01", "speaker": "narrator", "text": "It opened.", "order": 1}},
    ]
    monkeypatch.setattr(marvin_api, "entries", lambda _creds: rows)
    records = script.pull_records("s", ("http://m", "tok"))
    assert set(records["scenes"]) == {"s-hangar"}  # not the beat or the chapter, which also have a number and an ambience
    text = script.fountain_complete(records)
    assert "INT. HANGAR #1a#" in text and "[[Scene Hangar. Place: A hangar at night.]]" in text
