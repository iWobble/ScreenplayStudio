"""A person's actor sheet (v203): four full-length views in one landscape row, as the house sheets are; no empty field printed as an empty slot;
the style actor's sheet for the finish only, never the person; an optional picture of the person; the sheet attached only when it is kept; and
Open call says what a person actor lacks before a sheet is paid for."""

import json
import re
import subprocess

import pytest

from tests.test_package_prompts import BASE_SHEET, PERSON_SHEET_PROMPT, sent_text
from tests.test_world_context import BLUEPRINTS, PACKAGE, render

SLUG = "screenplay-make-actor-sheet"
FLOW = BLUEPRINTS[SLUG]["payload"]["definition"]
STEPS = {a.get("id") or f"{a['kind']}{i}": a for i, a in enumerate(FLOW["actions"])}
PERSON = sent_text(FLOW["actions"], "sheet")
FIELDS = ("age", "hair", "skin_tone", "look", "distinguishing_features", "baseline_wardrobe")

ANIMAL_SHEET_PROMPT_V202 = (
    "A character sheet of one animal actor on a landscape canvas: three full-body views of the same animal in one row that fills the whole "
    "picture, front, right-side profile, back. The same neutral standing quadruped pose in all three (four legs planted, head level, weight even,"
    " tail natural), the same scale and light, each animal whole in frame with margin, paws complete, the three views clearly separated, soft "
    "ground shadows on a plain warm cream studio background. No collar, no clothes, no props, no scenery, no labels, no text. The first attached "
    "picture is this world's ${entry.data.base} base sheet: keep its construction, proportions and scale exactly and add only what is written "
    "here. Any further attached picture is an existing animal actor of this world: copy only its finish, never its markings. The finish: softly "
    "dimensional and hand-painted, matte, subtly handmade, fine grain, gentle diffuse light, understated shadow, toy-like simplicity: rounded "
    "simplified shapes, an oversized rounded head, rounded simplified paws, small dark oval eyes, a simple dark nose, little facial detail. "
    "Animal anatomy, not a person's: no hands or fingers, never standing upright, no human proportions, face or smile; the legs bend where this "
    "animal's legs bend. Not photorealistic, not glossy plastic, not polished 3D-film realism. The actor: ${entry.title}, a ${entry.data.base}, "
    "age ${entry.data.age}. Build: ${entry.data.build} Look and coat: ${entry.data.look} Markings, the actor's permanent identity, identical in "
    "every view: ${entry.data.distinguishing_features} The world's own rules follow; apply them to the style and finish only, and leave out any "
    "that are about people (hands, clothes, height in heads): ${steps.world.output.rows.0.data.rules}"
)


def _actor(**data) -> dict:
    return {"entry": {"title": "Mara", "data": {"base": "woman", "build": "Small and sturdy.", "world": "storyworld", **data}},
            "input": {"style_actor": "arthur", "size": "1536x1024"}, "steps": {"world": {"output": {"rows": [{"data": {"rules": "Rounded painted miniatures."}}]}}}}  # fmt: skip


def test_a_persons_sheet_is_four_views_in_one_landscape_row_at_a_landscape_size():
    assert PERSON == PERSON_SHEET_PROMPT
    assert "landscape canvas, four full-length views side by side in one row filling the picture: front, three-quarter, right-side profile and back" in PERSON
    assert "soft ground shadows on a plain warm cream background" in PERSON and "No labels, no text" in PERSON
    assert "portrait" not in PERSON.lower() and "2 by 2" not in PERSON and "grid" not in PERSON and "top row" not in PERSON
    size = next(i for i in FLOW["trigger"]["inputs"] if i["name"] == "size")
    assert size["default"] == "1536x1024" and STEPS["sheet"]["args"]["size"] == '${input.size|default:"1536x1024"}'


def test_an_empty_field_never_prints_an_empty_slot():
    said = render(PERSON, _actor())  # Mara as she was: only a base and a build
    for label in ("Age", "Hair", "Skin tone", "Look", "Distinguishing features, the same in every view", "Wearing, in every view"):
        assert re.search(re.escape(label) + r": \S", said), label  # always words after the label
    assert not re.search(r":\s*[.:]|:\s*$|age \.|\s\.\s", said)  # no "age ." and no label with only a full stop after it
    assert "Hair: not specified: choose a simple hair that does not copy the second picture's person." in said
    assert "Wearing, in every view: not specified: a plain neutral outfit that differs from the second picture's clothes." in said
    full = render(PERSON, _actor(age="50s", hair="Grey bun.", skin_tone="Fair.", look="Kind.", distinguishing_features="A scar.", baseline_wardrobe="A blue oilskin"))
    assert "Age: 50s. Build: Small and sturdy. Hair: Grey bun. Skin tone: Fair. Look: Kind." in full and "not specified" not in full


def test_the_style_actor_gives_the_finish_only_and_never_its_person():
    assert "The second attached picture is an existing actor sheet of this world, for the FINISH ONLY: flat soft matte shapes" in PERSON
    assert "two small dark dot eyes" in PERSON and "a tiny smile" in PERSON and "no skin pores" in PERSON and "no fine fabric weave" in PERSON
    assert "Do NOT copy that picture's person, face, hair, skin tone, clothes or colours: this actor's own description below governs" in PERSON
    assert "clearly different from the second picture" in PERSON
    assert "draw the faces, hands, hair, skin and cloth exactly in its way" not in PERSON  # the v181 words that made Mara a copy of Arthur
    assert "for the finish only" in STEPS["spend"]["message"]


PICTURE_ID = "0b9e6c1e-1111-2222-3333-444455556666"
OWN_ID = "7f3a0000-aaaa-bbbb-cccc-ddddeeeeffff"
AGED_ID = "5c1d0000-1234-5678-9abc-def012345678"
SOURCE = ("The third attached picture shows this person: take her or his face, hair and build from it, not the finish, and draw the clothes "
          "written below, not the clothes in it.")  # fmt: skip
OWN = "It is this actor's own existing sheet: the new sheet keeps THIS person exactly and may only fix the layout and the finish."


def _holds(when, context: dict) -> bool:
    """A stand-in for Marvin's conditions (matcher.matches) with the operators these steps use."""
    if isinstance(when, list):
        return all(_holds(w, context) for w in when)
    if "not" in when:
        return not _holds(when["not"], context)
    value, op, want = render("${" + when["field"] + "}", context), when["op"], when["value"]
    if op == "in":
        return value in [x.strip() for x in render(want, context).split(",")]
    return len(value) > want if op == "longer_than" else len(value) < want


def _person(context: dict) -> dict:
    """What the parallel step finds, as Marvin runs it: each branch's collect when its conditions hold (an asset found by its id)."""
    found = {}
    for branch in next(a for a in FLOW["actions"] if a.get("id") == "person")["branches"]:
        (step,) = branch["steps"]
        ids = [x for x in render(step["query"]["ids"], context).split(",") if x.strip()] if _holds(step["when"], context) else []
        found[branch["name"]] = {"output": {"rows": [{"id": ids[0]}]} if ids else {}}
    context["steps"]["person"] = {"output": {"branches": found}}
    return context


def _sent(context: dict) -> list[str]:
    return [r for r in render(STEPS["sheet"]["references"], context).split(",") if r.strip()]  # Marvin drops a blank reference


def _with(*, given: str = "", sheet: str = "", aged: "list | None" = None) -> dict:
    context = _actor(general_view=sheet, age_views=aged or [])
    context["input"].update(source_picture=given, animal_bases="dog,cat,horse,bird")
    context["entry"]["data"]["age_views"] = ",".join(aged or [])  # a list reads as its ids, comma separated
    return _person(context)


def test_the_third_reference_is_the_picture_given_else_the_actors_own_sheet_else_its_first_view_at_an_age_else_none():
    source = next(i for i in FLOW["trigger"]["inputs"] if i["name"] == "source_picture")
    assert source["type"] == "asset" and source["required"] is False
    assert _sent(_with()) == ["storyworld-base-woman", "arthur"]  # nothing of the person: no third picture, no sentence
    assert "third attached picture" not in render(PERSON, _with()) and "third reference" not in render(STEPS["spend"]["message"], _with())
    assert _sent(_with(sheet=OWN_ID)) == ["storyworld-base-woman", "arthur", OWN_ID]  # Mara's own uploaded picture
    assert _sent(_with(given=PICTURE_ID, sheet=OWN_ID, aged=[AGED_ID])) == ["storyworld-base-woman", "arthur", PICTURE_ID]  # the picture given wins
    assert _sent(_with(aged=[AGED_ID, OWN_ID])) == ["storyworld-base-woman", "arthur", AGED_ID]  # no sheet: the first view at an age
    assert _sent(_with(sheet=OWN_ID, aged=[AGED_ID])) == ["storyworld-base-woman", "arthur", OWN_ID]


def test_the_prompt_and_the_question_say_which_picture_of_the_person_is_attached():
    own = render(PERSON, _with(sheet=OWN_ID))
    assert own.count(SOURCE) == 1 and OWN in own  # its own sheet: keep this person, fix only the layout and the finish
    given = render(PERSON, _with(given=PICTURE_ID, sheet=OWN_ID))
    assert given.count(SOURCE) == 1 and OWN not in given
    assert render(PERSON, _with(aged=[AGED_ID])).count(SOURCE) == 1
    asked = render(STEPS["spend"]["message"], _with(sheet=OWN_ID))
    assert "The actor's own picture (its sheet now) is attached as the third reference: the person to keep." in asked
    assert "The picture of the person you gave is attached as the third reference." in render(STEPS["spend"]["message"], _with(given=PICTURE_ID))


def test_an_animal_is_never_sent_a_picture_of_a_person():
    dog = _with(sheet=OWN_ID)
    dog["entry"]["data"]["base"] = "dog"
    assert not any(b["output"] for b in _person(dog)["steps"]["person"]["output"]["branches"].values())
    assert STEPS["sheet_animal"]["references"] == BASE_SHEET + ",${input.style_animal}"


def test_the_animal_sheet_is_sent_as_in_v202():
    assert sent_text(FLOW["actions"], "sheet_animal") == ANIMAL_SHEET_PROMPT_V202
    assert STEPS["sheet_animal"]["args"]["size"] == '${input.size|default:"1536x1024"}'


def test_the_sheet_is_attached_to_the_actor_only_when_it_is_kept():
    acts = FLOW["actions"]
    at_keep = next(n for n, a in enumerate(acts) if a.get("id") == "keep")
    for a in acts[:at_keep]:  # nothing before the question writes the picture (or anything) onto the actor
        assert not (a.get("kind") == "entry" and a.get("op") == "set_data"), a
        assert "general_view" not in json.dumps(a.get("data") or {}), a
    keep = acts[at_keep]
    assert keep["image"] == "${steps.sheet.output.asset.url}${steps.sheet_animal.output.asset.url}" and keep["choices"] == ["Keep", "Redo"] and keep["redo"] == "Redo"
    (attach,) = [a for a in acts if "general_view" in json.dumps(a.get("data") or {})]
    assert {"field": "steps.keep.output.choice", "op": "eq", "value": "Keep"} in attach["when"]  # a Redo, a skip or a "no" leaves the actor as it was
    assert attach["data"] == {"general_view": "${steps.sheet.output.asset.id}${steps.sheet_animal.output.asset.id}", "status": "approved"}


def test_open_call_says_what_a_person_actor_lacks_before_a_sheet_is_paid_for():
    ready = next(s for s in BLUEPRINTS["open-call"]["payload"]["steps"] if s["id"] == "ready")
    fixes = [c for c in ready["checks"] if c["label"].startswith("Fix before making the sheet")]
    assert [c["label"].split("missing ")[1] for c in fixes] == ["Age", "Hair", "Skin tone", "Baseline wardrobe"]
    for check, key in zip(fixes, ("age", "hair", "skin_tone", "baseline_wardrobe"), strict=True):
        assert check["query"]["entry_type"] == "actor" and check["query"]["fields"] == {"world": "${world}"} and (check["op"], check["value"]) == ("eq", 0)
        assert check["query"]["where"][0] == {"field": key, "op": "missing"} and check["step"] == "sheet"
        bases = {w["value"] for w in check["query"]["where"][1:] if w["op"] == "neq" and w["field"] == "base"}
        assert bases == set(next(i for i in FLOW["trigger"]["inputs"] if i["name"] == "animal_bases")["default"].split(","))  # an animal needs none of them


def test_every_other_workflow_and_setup_is_as_it_was():
    try:
        before = json.loads(subprocess.run(["git", "show", "origin/main:docs/screenplay-studio.marvin-package.json"], cwd=PACKAGE.parents[1], capture_output=True, check=True).stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("no git history to compare with")
    if "source_picture" in json.dumps(next(b for b in before["blueprints"] if b["slug"] == SLUG)):
        pytest.skip("main already has it: this compares the release that changes it with the one before")
    changed = {SLUG, "open-call", "screenplay-studio"}  # the Playbook is the skill, checked by its own test
    old = {b["slug"]: b for b in before["blueprints"] if b["slug"] not in changed}
    now = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["slug"] not in changed}
    assert now == old
    was = next(b for b in before["blueprints"] if b["slug"] == "open-call")["payload"]["steps"]
    is_ = BLUEPRINTS["open-call"]["payload"]["steps"]
    assert [s for s in is_ if s["id"] not in ("ready", "make_sheet", "sheet")] == [s for s in was if s["id"] not in ("ready", "make_sheet", "sheet")]
    old_ready, new_ready = (next(s for s in x if s["id"] == "ready") for x in (was, is_))
    assert new_ready["checks"][: len(old_ready["checks"])] == old_ready["checks"]  # the old checks first, as they were


def test_open_calls_make_step_says_the_actors_picture_is_the_reference_nothing_is_replaced_before_keep_and_what_to_fix():
    steps = {s["id"]: s for s in BLUEPRINTS["open-call"]["payload"]["steps"]}
    make, sheet = steps["make_sheet"], steps["sheet"]
    assert make["when"] == sheet["when"] == {"ctx": "actor", "op": "set"} and make["requires"] == {"entry": "actor", "field": "build"}
    said = make["help"]
    assert "When the actor already has a picture (its General view, else its first view at an age), that picture is attached as the reference" in said
    assert "nothing is replaced until you choose Keep" in said and "when it has none, the sheet is drawn from the written fields alone" in said
    assert "Fix before making the sheet: a person needs Age, Hair, Skin tone and Baseline wardrobe" in said
    assert "from the sheet on the step before" not in said and "2 by 2" not in said and "Skip this step when you uploaded the picture" not in said
    assert "a skipped or denied one leaves the actor as it was" in said
    paid = make["paid"]
    assert set(paid["needs"]) == {"age", "hair", "skin_tone", "baseline_wardrobe"} <= set(paid["sends"])  # the notice names any of them that is empty
    assert len(paid["sends"]) <= 6 and "replaces it only when you keep the new one" in sheet["help"]

