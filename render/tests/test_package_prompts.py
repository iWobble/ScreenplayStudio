"""The prompts the package sends to the image model keep their guardrails (a master is a portrait, not a scene; sides are anatomical; a style
reference never brings its people), so an edit to a workflow cannot quietly drop them."""

import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"


def workflow(slug: str) -> str:
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == slug:
            return json.dumps(b["payload"]["definition"])
    raise AssertionError(slug)


def test_a_master_is_sent_with_the_portrait_guard_and_the_approval_shows_the_same_words():
    made = json.loads(PACKAGE.read_text(encoding="utf-8"))
    flow = next(b for b in made["blueprints"] if b.get("slug") == "screenplay-make-master")["payload"]["definition"]["actions"]
    spend = next(a for a in flow if a.get("id") == "spend")["message"]
    sent = next(a for a in flow if a.get("id") == "master")["args"]["prompt"]
    guard = sent.split("${entry.data.master_prompt}", 1)[1].strip()
    assert "MASTER, NOT A SCENE" in guard and "anatomical left and right" in guard and "never mirror" in guard
    assert guard in spend  # what is approved is what is sent


def test_the_master_prompt_writer_ignores_scene_words_in_the_notes_and_writes_anatomical_sides():
    text = workflow("screenplay-write-master-prompt")
    assert "never a scene" in text and "names a place, weather, scene, other people or an action" in text and "anatomical left or right" in text


def test_a_still_never_draws_people_who_are_only_in_a_reference_picture():
    text = workflow("screenplay-take-still")
    assert "nobody who appears only in a reference picture" in text


def test_a_cover_and_an_actor_sheet_copy_the_style_only():
    assert "do NOT copy its characters, objects or setting" in workflow("screenplay-make-cover")
    assert "Never realistic" in workflow("screenplay-make-actor-sheet")
