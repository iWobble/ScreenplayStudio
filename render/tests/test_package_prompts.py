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


def test_an_actors_new_voice_reaches_the_characters_who_play_them_unless_given_another_on_purpose():
    flow = json.loads(workflow("screenplay-actor-voice-reaches-characters"))
    assert flow["trigger"]["event"] == "entry_updated"
    assert {"field": "entry.data.voice", "op": "changed"} in flow["conditions"]
    people = next(a for a in flow["actions"] if a.get("id") == "people")
    assert people["query"] == {"entry_type": "cast-member", "data": {"actor": "${entry.slug}"}}
    give = json.dumps(next(a for a in flow["actions"] if a.get("id") == "follow")["steps"])
    assert "${event.before.data.voice}" in give and "shorter_than" in give  # only a voice that was empty or the actor's old one is replaced


def _flow(slug: str) -> dict:
    return json.loads(workflow(slug))


def test_a_batch_approval_covers_every_still_and_sound_so_the_single_workflow_asks_nothing_more_and_uses_the_flag_up():
    for single in ("screenplay-take-still", "screenplay-take-sound"):
        acts = _flow(single)["actions"]
        assert acts[0]["data"] == {"spend_approved": "used"} and acts[0]["when"]["value"] == "yes"  # used up first: a later redo asks again
        asked = [a for a in acts if a.get("kind") == "approval"]
        assert {a["id"] for a in asked} == {"spend", "keep"}
        assert all(a["when"] == {"field": "entry.data.spend_approved", "op": "neq", "value": "yes"} for a in asked)
    for batch, noun in (("screenplay-make-stills", "beat"), ("screenplay-make-sounds", "sound")):
        acts = _flow(batch)["actions"]
        assert len([a for a in acts if a.get("kind") == "approval" and a["id"] == "spend"]) == 1
        queue = next(a for a in acts if a.get("kind") == "repeat")
        assert queue["steps"][0]["data"] == {"status": "queued", "spend_approved": "yes"}
        assert next(a for a in acts if a.get("kind") == "collect")["query"]["entry_type"] == noun


def test_keeping_what_was_made_is_one_approval_that_only_touches_the_made_ones():
    for keep, status in (("screenplay-keep-stills", "made"), ("screenplay-keep-sounds", "recorded")):
        acts = _flow(keep)["actions"]
        assert {"field": "status", "op": "eq", "value": status} in next(a for a in acts if a.get("kind") == "collect")["query"]["where"]
        assert next(a for a in acts if a.get("id") == "keep")["choices"] == ["Keep all", "Leave them"]
        assert next(a for a in acts if a.get("kind") == "repeat")["when"]["value"] == "Keep all"
