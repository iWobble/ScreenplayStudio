"""Screenplay: write the cover subject (v202): the workspace AI writes a world's, series', story's or chapter's What the cover shows from what its
records say, and it is saved on the entry, never over one already there unless asked. No image is made: no image credit is spent."""

import json
import subprocess

import pytest

from tests.test_world_context import BLUEPRINTS, LEVELS, PACKAGE, _fields, render

SLUG = "screenplay-write-cover-subject"
FLOW = BLUEPRINTS[SLUG]["payload"]["definition"]
STEPS = {a.get("id") or a["kind"]: a for a in FLOW["actions"]}
BRANCHES = {b["name"]: b["steps"][0] for b in STEPS["shows"]["branches"]}
WHAT_IT_SHOWS = {"story": "story_beats", "chapter": "chapter_beats", "series": "series_stories", "world": "world_stories"}


def _holds(when, context: dict) -> bool:
    """A stand-in for Marvin's conditions (matcher.matches) with the operators these steps use."""
    if isinstance(when, list):
        return all(_holds(w, context) for w in when)
    if "any" in when:
        return any(_holds(w, context) for w in when["any"])
    value, op, want = render("${" + when["field"] + "}", context), when["op"], when["value"]
    if op in ("eq", "neq"):
        return (value == want) is (op == "eq")
    return len(value) > want if op == "longer_than" else len(value) < want


def _context(level: str, *, has: str = "", replace: str = "no") -> dict:
    return {"entry": {"entry_type": level, "slug": "it", "title": "It", "data": {"cover_subject": has, "summary": "The bet is made." if level == "chapter" else ""}},
            "input": {"replace": replace}, "steps": {}}  # fmt: skip


def test_it_is_a_manual_workflow_on_an_entry_with_a_replace_choice_that_defaults_to_no():
    assert BLUEPRINTS[SLUG]["name"] == BLUEPRINTS[SLUG]["payload"]["name"] == "Screenplay: write the cover subject"
    inputs = {i["name"]: i for i in FLOW["trigger"]["inputs"]}
    assert FLOW["trigger"]["type"] == "manual" and list(inputs) == ["entry", "replace"]
    assert inputs["entry"]["type"] == "entry" and inputs["entry"]["required"] is True and all(level in inputs["entry"]["label"] for level in LEVELS)
    assert (inputs["replace"]["type"], inputs["replace"]["options"], inputs["replace"]["default"]) == ("choice", ["no", "yes"], "no")
    assert len(FLOW["actions"]) <= 10  # Marvin's ten steps


def test_it_finds_each_level_as_the_cover_does():
    cover = {a["id"]: a for a in BLUEPRINTS["screenplay-make-cover"]["payload"]["definition"]["actions"] if a.get("kind") == "collect"}
    for level in ("story", "series", "world"):
        assert STEPS[level]["query"] == cover[level]["query"] and STEPS[level]["query"]["entry_type"] == level
    assert {"data.premise", "data.setting", "data.world", "data.series"} <= set(STEPS["story"]["fields"])
    assert set(STEPS["series"]["fields"]) == {"data.premise"} and {"data.premise", "data.rules"} <= set(STEPS["world"]["fields"])


@pytest.mark.parametrize("level", LEVELS)
def test_what_its_pictures_show_is_read_for_its_own_level_only(level):
    ran = [name for name, step in BRANCHES.items() if _holds(step["when"], _context(level))]
    assert ran == [WHAT_IT_SHOWS[level]]
    step = BRANCHES[WHAT_IT_SHOWS[level]]
    assert step["limit"] == 12 and step["query"]["data"] == {level: "${entry.slug}"}
    if level in ("story", "chapter"):  # the first twelve beats in order, each with its shot direction and its picture to fall back on
        assert step["query"]["entry_type"] == "beat" and step["query"]["sort"]["by"] == "number" and step["fields"] == ["data.direction", "data.picture"]
    else:  # a series' or a world's stories with their premises
        assert step["query"]["entry_type"] == "story" and step["fields"] == ["data.premise"]


def test_the_ai_reads_the_world_down_to_the_entry_and_what_its_pictures_show_cut_short():
    message = STEPS["write"]["message"]
    for path in ("steps.world.output.rows.0.data.premise|truncate:800", "steps.world.output.rows.0.data.rules|truncate:1500",
                 "steps.series.output.rows.0.data.premise|truncate:800", "steps.story.output.rows.0.data.premise|truncate:800",
                 "steps.story.output.rows.0.data.setting|truncate:800", "entry.data.summary|truncate:800"):  # fmt: skip
        assert "${" + path in message, path
    for name in BRANCHES:
        assert "${steps.shows.output.branches.%s.output.text|truncate:6000}" % name in message
    context = _context("chapter")
    context["steps"] = {"world": {"output": {"rows": [{"data": {"premise": "A storybook realm.", "rules": "Rounded painted miniatures."}}]}},
                        "shows": {"output": {"branches": {"chapter_beats": {"output": {"text": "- Beat 01\n  data.direction: Wide on three ships"}}}}}}  # fmt: skip
    said = render(message, context)
    assert "WORLD: A storybook realm." in said and "STYLE RULES OF THE WORLD: Rounded painted miniatures." in said and "THIS CHAPTER: The bet is made." in said
    assert "SERIES: none" in said and "Wide on three ships" in said


def test_the_ai_is_told_one_short_paragraph_from_the_material_only_no_text_and_no_invented_people():
    message = STEPS["write"]["message"]
    for rule in ("ONE short paragraph, at most 60 words", "single most striking, drawable moment", "who or what is in frame, where, and the light",
                 "never invent people", "If the material shows no people", "put no people on the cover", "No lettering", "style rules",
                 "Answer with the paragraph and NOTHING else"):  # fmt: skip
        assert rule in message, rule
    master = next(a for a in BLUEPRINTS["screenplay-write-master-prompt"]["payload"]["definition"]["actions"] if a["kind"] == "agent")
    assert STEPS["write"]["kind"] == "agent" and (STEPS["write"]["agent"], STEPS["write"]["playbooks"]) == (master["agent"], master["playbooks"])


def test_it_saves_the_paragraph_as_what_the_cover_shows_and_never_over_one_already_there_unless_asked():
    save = STEPS["entry"]
    assert save["op"] == "set_data" and save["data"] == {"cover_subject": "${steps.write.output.answer}"} and "entity_slug" not in save
    assert "cover_subject" in _fields("story") and all("cover_subject" in _fields(level) for level in LEVELS)
    for has, replace, saved in (("", "no", True), ("", "yes", True), ("Three ships.", "yes", True), ("Three ships.", "no", False)):
        context = _context("story", has=has, replace=replace)
        assert _holds(save["when"], context) is saved and _holds(STEPS["kept"]["when"], context) is not saved, (has, replace)
    kept = STEPS["kept"]["message"]
    assert "${entry.data.cover_subject}" in kept and "${steps.write.output.answer}" in kept and "replace: yes" in kept  # says so, with the proposal


def test_it_makes_no_image_and_calls_no_integration_anywhere():
    def steps(actions):
        for a in actions:
            yield a
            for b in a.get("branches") or []:
                yield from steps(b["steps"])

    kinds = {a["kind"] for a in steps(FLOW["actions"])}
    assert "integration" not in kinds and "media" not in kinds and "openai_images" not in json.dumps(FLOW)
    assert "no image credit is spent" in BLUEPRINTS[SLUG]["description"]


def test_every_other_workflow_is_as_it_was():
    try:
        before = json.loads(subprocess.run(["git", "show", "origin/main:docs/screenplay-studio.marvin-package.json"], cwd=PACKAGE.parents[1], capture_output=True, check=True).stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("no git history to compare with")
    if any(b["slug"] == SLUG for b in before["blueprints"]):
        pytest.skip("main already has it: this compares the release that adds it with the one before")
    old = {b["slug"]: b for b in before["blueprints"] if b.get("kind") == "workflow" and b["slug"] != SLUG}
    now = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b.get("kind") == "workflow" and b["slug"] != SLUG}
    assert now == old
