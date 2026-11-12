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


def test_the_story_timeline_lets_a_made_still_be_kept_or_redone_in_place():
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "story-timeline":
            assert b["payload"]["spine"]["review"] == {"ready": ["made"], "keep": "approved", "redo": "redo"}
            break
    else:
        raise AssertionError("story-timeline")
    requeue = json.dumps(_flow("screenplay-requeue-redo"))
    assert '"redo"' in requeue  # the status the Redo button writes is the one the requeue workflow acts on


def test_writing_the_beat_details_asks_once_then_queues_the_job_and_the_cast_has_age_and_sex_fields():
    flow = _flow("screenplay-write-beat-details")["actions"]
    assert [a.get("id") for a in flow if a.get("kind") == "approval"] == ["none", "spend"]
    job = next(a for a in flow if a.get("kind") == "entry")
    assert job["data"]["kind"] == "write-beat-details" and job["when"]["op"] == "gte"
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "cast-member":
            keys = [f["key"] for f in b["payload"]["schema_json"]["fields"]]
            assert {"age", "sex", "age_state"} <= set(keys) and keys.index("age") < keys.index("speaker")


def test_a_still_is_told_the_changes_from_earlier_beats_and_the_beat_has_the_field_for_them():
    acts = _flow("screenplay-take-still")["actions"]
    changes = next(a for a in acts if a.get("id") == "changes")
    assert {"field": "number", "op": "lte", "value": "${entry.data.number}"} in changes["query"]["where"]  # this beat's own note counts too
    prompt = next(a for a in acts if a.get("kind") == "integration")["args"]["prompt"]
    assert prompt.index("CHANGES THAT HOLD") < prompt.index("THIS MOMENT: ") and "steps.changes.output.text" in prompt
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "beat":
            assert "changes" in [f["key"] for f in b["payload"]["schema_json"]["fields"]]


def test_the_plan_check_looks_at_elevenlabs_for_free_then_queues_the_readiness_job_with_what_it_found():
    flow = _flow("screenplay-check-ready-plan")["actions"]
    look = flow[0]
    assert (look["kind"], look["integration"], look["action"]) == ("integration", "elevenlabs", "get_usage")  # the free usage lookup, nothing that records
    args = next(a for a in flow if a.get("kind") == "entry")["data"]["args"]
    assert args["plan_tier"] == "${steps.plan.output.tier}" and args["plan_characters_left"] == "${steps.plan.output.characters_left}"
    assert not [a for a in flow if a.get("kind") == "approval"]  # free: nothing to approve


def test_an_actor_sheet_may_ask_for_its_own_picture_size_and_says_so_in_the_approval():
    flow = _flow("screenplay-make-actor-sheet")
    assert any(i["name"] == "size" and i["required"] is False for i in flow["trigger"]["inputs"])
    assert next(a for a in flow["actions"] if a.get("kind") == "integration")["args"]["size"] == '${input.size|default:""}'  # empty: the connection's, as before
    assert "Picture size:" in next(a for a in flow["actions"] if a.get("id") == "spend")["message"]
