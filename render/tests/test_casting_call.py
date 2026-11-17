"""Casting call's master steps (v205): the prompt the AI writes is shown when it is written and has a step of its own, apart from the picture; the
picture is made only once the role has an Age, whose step the page names."""

from tests.test_world_context import BLUEPRINTS

STEPS = BLUEPRINTS["casting-call"]["payload"]["steps"]
BY = {s["id"]: s for s in STEPS}


def test_the_prompt_and_the_picture_are_two_steps_in_order():
    order = [s["id"] for s in STEPS]
    assert order[order.index("master_prompt_write") :] == ["master_prompt_write", "master_prompt_edit", "master_picture", "master", "approve", "ready"]
    prompt, picture = BY["master_prompt_edit"], BY["master_picture"]
    assert (prompt["kind"], prompt["title"], prompt["entry"], prompt["fields"]) == ("form", "The master prompt", "role", ["master_prompt"])
    assert (picture["kind"], picture["title"], picture["entry"], picture["fields"]) == ("form", "The master picture", "role", ["master"])
    assert prompt["help"].startswith("Written by the AI from the actor's sheet, the costume, the story and the world's style; edit it, then make the picture on the next step.")
    assert picture["help"].startswith("Leave this empty to make the picture on the next step from the prompt above; upload a picture here only if you already have a master")
    assert not [s for s in STEPS if s["kind"] == "form" and {"master", "master_prompt"} <= set(s.get("fields") or [])]  # never one folded step again


def test_the_written_prompt_shows_on_the_run_step_and_its_sent_box_says_where_to_change_the_costume():
    write = BY["master_prompt_write"]
    assert write["report"] == {"entry": "role", "field": "master_prompt", "label": "The prompt the AI wrote"}
    assert "to read only: to change the costume or props, go back to “Give the role to the actor”." in write["help"]


def test_the_requires_chain_names_the_step_that_fills_each_field():
    fills = {f: s["id"] for s in STEPS if s["kind"] == "form" for f in s["fields"]}
    assert BY["voice_lines"]["requires"] == {"entry": "role", "field": "voice"} and fills["voice"] == "assign"
    assert BY["master_prompt_write"]["requires"] == {"entry": "role", "field": "actor"} and fills["actor"] == "assign"
    assert BY["master"]["requires"] == {"entry": "role", "field": "age_state"} and fills["age_state"] == "assign"  # no Age: no "no such tag(s): age-"
    assert fills["master_prompt"] == "master_prompt_edit" and fills["master"] in ("master_picture", "approve")
    assert set(BY["master"]["paid"]["needs"]) == {"master_prompt", "age_state"}  # an empty prompt is named above the button too
    assert "Set the Age on “Give the role to the actor” first" in BY["master"]["help"]
    checks = {c["label"]: c.get("step") for c in BY["ready"]["checks"]}
    assert checks["Every role we see has a master picture"] == "master_picture" and all(step in BY for step in checks.values() if step)


def test_a_fresh_workspace_shows_the_master_prompt_outside_the_folded_master_picture_section():
    fields = {f["key"]: f for f in BLUEPRINTS["cast-member"]["payload"]["schema_json"]["fields"]}
    assert "group" not in fields["master_prompt"] and fields["master"]["group"] == "Master picture"
