"""Covers and stills are made from the world down (v200): the world (premise, rules, style picture), the series, the story, the chapter and,
for a still, the scene. A cover can be made for any of those levels, with or without characters leading it, in the story's shape."""

import json
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"
BLUEPRINTS = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
LEVELS = ("world", "series", "story", "chapter")


def _fields(slug: str) -> dict:
    return {f["key"]: f for f in BLUEPRINTS[slug]["payload"]["schema_json"]["fields"]}


def _actions(slug: str) -> list:
    return BLUEPRINTS[slug]["payload"]["definition"]["actions"]


def _step(slug: str, step_id: str) -> dict:
    return next(a for a in _actions(slug) if a.get("id") == step_id)


def _prompt(slug: str) -> str:
    (box,) = _step(slug, "spend")["fields"]
    return box["value"]


# A small stand-in for Marvin's templates (services/automation/matcher.py and filters.py): ${path|filter:"arg",...}, with the three filters
# these prompts use. Enough to read what a prompt says for a given story; Marvin's own resolution is what runs.
def _lookup(path: str, context: dict):
    node = context
    for key in path.split("."):
        if isinstance(node, list) and key.isdigit():
            node = node[int(key)] if int(key) < len(node) else None
        elif isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    return node


def _apply(value, name: str, args: list[str]):
    text = "" if value is None else str(value)
    if name == "default":
        return args[0] if value in (None, "", [], {}) else value
    if name == "replace":
        return text.replace(args[0], args[1] if len(args) > 1 else "")
    if name == "split":
        return value if isinstance(value, list) else [x.strip() for x in text.split(args[0] if args else ",")] if text else []
    if name == "first":
        return value[0] if isinstance(value, list | str) and value else None
    if name == "truncate":  # as Marvin's: at most N characters, ending on a whole word with … (or the second argument)
        size, end = max(int(args[0]), 1), args[1] if len(args) > 1 else "…"
        if len(text) <= size:
            return text
        cut = text[: max(size - len(end), 0)]
        words = cut.rsplit(" ", 1)[0] if " " in cut else cut
        return (words if len(words) >= size // 2 else cut).rstrip(" ,.;:") + end
    raise AssertionError(f"filter {name} is not in the stand-in")


def _resolve(expr: str, context: dict):
    path, *chain = re.findall(r'(?:[^|"]|"[^"]*")+', expr)
    value = _lookup(path.strip(), context)
    for part in chain:
        name, _, rest = part.partition(":")
        value = _apply(value, name, [quoted or bare for quoted, bare in re.findall(r'"([^"]*)"|([^,"]+)', rest)])
    return value


def render(template: str, context: dict) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: "" if (v := _resolve(m.group(1), context)) is None else str(v), template)


# ── the fields ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_world_series_story_and_chapter_each_have_a_cover_as_the_story_has_and_what_it_shows():
    story_cover = _fields("story")["cover"]
    for slug in LEVELS:
        fields = _fields(slug)
        cover = fields["cover"]
        assert {k: cover[k] for k in ("type", "role", "accept")} == {k: story_cover[k] for k in ("type", "role", "accept")}, slug
        assert cover["helpText"].strip() and "make a cover" in cover["helpText"], slug
        subject = fields["cover_subject"]
        assert subject["type"] == "text" and not subject.get("required") and "three generation ships" in subject["helpText"], slug


def test_a_world_has_a_style_reference_picture_and_says_what_its_premise_and_rules_are_for():
    world = _fields("world")
    style = world["style_reference"]
    assert (style["type"], style["accept"]) == ("asset", "image/*")
    assert style["helpText"].startswith("A picture whose painted style, palette and finish every cover and picture of this world follows, e.g. the world's logo")
    assert "WORLD line" in world["premise"]["helpText"] and "STYLE RULES" in world["rules"]["helpText"]  # read by every still and cover
    assert list(world).index("style_reference") == list(world).index("rules") + 1


# ── the still ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# The still's prompt as it was before v200, line by line. Two words changed on purpose: the world is read through the context step
# (STYLE RULES), and the shape follows the story's format (the last line); every other line is still there as it was.
OLD_STILL_LINES = [
    "Reference pictures, in this order: ${entry.data.cast}.",
    "Keep each character's face, hair, build, clothes and the illustration style exactly as in their reference.",
    "Reference pictures other than a character's own are for the place, light and style only: match their room, layout, light and furnishings, and never draw anyone who is in them.",
    "The people in this picture are the characters listed below and any figure THIS MOMENT names (a crowd, a skeleton, a stranger); nobody who appears only in a reference picture.",
    "STORY SETTING: ${steps.story.output.rows.0.data.setting}\n",
    "SCENE: ${steps.scene.output.rows.0.data.place}\n",
    "Light: ${steps.scene.output.rows.0.data.look}\n",
    "Always on the set: ${steps.scene.output.rows.0.data.set_dressing}\n",
    'Shot direction (where the camera looks): ${entry.data.direction|default:"none"}\n',
    "What they are doing and how they look: ${entry.data.expression}\n",
    "The one prop the frame is about: ${entry.data.focus}\n",
    "STYLE RULES: ${steps.context.output.branches.world.output.rows.0.data.rules}\n",
    ", in the same palette and style as the references. No readable text or writing anywhere: no alphabet characters, signs or captions.",
]

WORLD = "steps.context.output.branches.world.output.rows.0.data"


def _beat_context(*, format="", world=None, series=None, chapter=None, story_premise="Two old sailors bet on an onion.", cast=None, picture="The cook lifts the onion."):
    branch = lambda data: {"output": {"rows": [{"data": data}]} if data is not None else {}}  # noqa: E731 (a skipped collect has no rows)
    return {
        "entry": {"data": {"cast": "cook", "picture": picture, "expression": "proud", "focus": "the onion", "chapter": "ch-1" if chapter else ""}},
        "steps": {
            "story": {"output": {"rows": [{"data": {"setting": "A ship's galley.", "premise": story_premise, "format": format, "series": "s" if series else ""}}]}},
            "scene": {"output": {"rows": [{"data": {"place": "The galley", "look": "Lamplight", "set_dressing": "Pots"}}]}},
            "context": {"output": {"branches": {**({"world": branch({"rules": "Painted miniatures.", **(world or {})}), "series": branch(series), "chapter": branch(chapter)}), "cast": cast if cast is not None else {"steps": {"people": {"text": "- the cook\n  data.role: Cook\n  data.age_state: old", "count": 1}, "things": {"text": "", "count": 0}, "someone": {"entity": "entry"}}}}}},
        },
    }


def test_the_still_keeps_every_line_it_had():
    prompt = _prompt("screenplay-take-still")
    for line in OLD_STILL_LINES:
        assert prompt.count(line) == 1, line


def test_the_still_reads_the_world_series_story_and_chapter_before_the_scene_widest_first():
    prompt = _prompt("screenplay-take-still")
    labels = ["WORLD: ", "SERIES: ", "STORY PREMISE (for mood only): ", "STORY SETTING: ", "THIS CHAPTER: ", "CHARACTERS (", "SCENE: "]
    at = [prompt.index("\n" + label) for label in labels]
    assert at == sorted(at)
    said = render(prompt, _beat_context(world={"premise": "A storybook realm."}, series={"premise": "Voyages of the cook."}, chapter={"summary": "The bet is made."}))
    for line in ("WORLD: A storybook realm.", "SERIES: Voyages of the cook.", "STORY PREMISE (for mood only): Two old sailors bet on an onion.",
                 "STORY SETTING: A ship's galley.", "THIS CHAPTER: The bet is made.", "STYLE RULES: Painted miniatures."):  # fmt: skip
        assert "\n" + line + "\n" in said, line


def test_a_story_with_no_series_chapter_or_world_premise_says_none_and_never_leaves_a_label_empty():
    said = render(_prompt("screenplay-take-still"), _beat_context(story_premise=""))
    for label in ("WORLD", "SERIES", "STORY PREMISE (for mood only)", "THIS CHAPTER"):
        assert f"\n{label}: none\n" in said, label
    assert not re.search(r": *\n", said)  # no label is left with nothing after it


def test_the_series_and_chapter_are_looked_up_only_when_the_story_and_beat_name_them_and_the_world_as_before():
    # Marvin runs a workflow's first ten steps unless the workspace raises it: take-still was already at twelve, so the three lookups are
    # one parallel step in the place of the world's, and a story with no world still fails the run (the world branch is unguarded).
    acts = _actions("screenplay-take-still")
    assert len(acts) == 11 and [a.get("id") for a in acts].index("context") == 2  # (v213: the cast lookups moved into it, as a branch)
    context = _step("screenplay-take-still", "context")
    assert context["kind"] == "parallel" and context.get("join", "all") == "all" and "on_branch_failure" not in context
    branches = {b["name"]: b["steps"] for b in context["branches"]}
    ((world,), (series,), (chapter,)) = branches["world"], branches["series"], branches["chapter"]
    assert world["query"] == {"entries": "${steps.story.output.rows.0.data.world}"} and "when" not in world
    assert {"data.rules", "data.premise", "data.style_reference"} <= set(world["fields"])
    assert series["query"] == {"entries": "${steps.story.output.rows.0.data.series}"} and series["fields"] == ["data.premise"]
    assert series["when"] == {"field": "steps.story.output.rows.0.data.series", "op": "longer_than", "value": 0}  # an empty lookup fails a run
    assert chapter["query"] == {"entries": "${entry.data.chapter}"} and chapter["fields"] == ["data.summary"]
    assert chapter["when"] == {"field": "entry.data.chapter", "op": "longer_than", "value": 0}
    assert {"data.premise", "data.series", "data.format"} <= set(_step("screenplay-take-still", "story")["fields"])


def test_the_worlds_style_picture_is_sent_last_and_only_when_the_world_has_one():
    refs = _step("screenplay-take-still", "still")["references"]
    assert refs == ["${entry.data.references}", "${steps.scene.output.rows.0.data.anchor}", "${" + WORLD + ".style_reference}"]
    with_one = [render(r, _beat_context(world={"style_reference": "storyworld-logo"})) for r in refs]
    without = [render(r, _beat_context()) for r in refs]
    assert with_one[-1] == "storyworld-logo" and without[-1] == ""  # Marvin drops a blank reference
    assert "for the place, light and style only" in _prompt("screenplay-take-still")


SHAPES = {"short-9x16": ("Vertical portrait composition", "1024x1536"), "portrait-4x5": ("Vertical portrait composition", "1024x1536"),
          "square-1x1": ("Square composition", "1024x1024"), "wide-16x9": ("Landscape widescreen composition", "1536x1024")}  # fmt: skip


def test_every_picture_shape_the_story_offers_has_its_words_and_its_size():
    assert sorted(SHAPES) == sorted(_fields("story")["format"]["options"])  # a new shape needs its words and size here and in the prompts


@pytest.mark.parametrize("fmt", [*SHAPES, ""])
def test_the_still_is_tall_square_or_wide_as_the_story_and_tall_when_it_says_nothing(fmt):
    words, size = SHAPES.get(fmt, ("Vertical portrait composition", ""))  # no format: tall as before, at the connection's own size
    context = _beat_context(format=fmt)
    said = render(_prompt("screenplay-take-still"), context)
    assert said.rstrip().endswith(words + ", in the same palette and style as the references. No readable text or writing anywhere: no alphabet characters, signs or captions.")
    assert render(_step("screenplay-take-still", "still")["args"]["size"], context) == size


# ── the cover ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _cover_context(level: str, *, leads: str = "", style_reference: str = "", fmt: str = "wide-16x9", subject: str = "") -> dict:
    """What the cover's lookups find for an entry of this level, resolved as Marvin's collect does: the refs in `entries` (blanks dropped),
    kept when of the step's type."""
    records = {
        "storyworld": {"entry_type": "world", "data": {"premise": "A storybook realm.", "rules": "Rounded painted miniatures.", "style_reference": style_reference}},
        "voyages": {"entry_type": "series", "data": {"premise": "Voyages of the cook.", "world": "storyworld"}},
        "onion": {"entry_type": "story", "data": {"premise": "A bet on an onion.", "setting": "A ship at sea.", "world": "storyworld", "series": "voyages", "format": fmt}},
        "onion-chapter-01": {"entry_type": "chapter", "data": {"story": "onion", "summary": "The bet is made."}},
    }
    slug = next(s for s, r in records.items() if r["entry_type"] == level)
    entry = {"slug": slug, "title": slug.title(), "entry_type": level, "data": {**records[slug]["data"], "cover_subject": subject}}
    context = {"entry": entry, "input": {"leads": leads, "style_cover": "the-last-onion-at-sea"}, "steps": {}}
    for step in _actions("screenplay-make-cover"):
        if step.get("kind") != "collect" or step["entity"] != "entry":
            continue
        if step.get("when") and not render("${" + step["when"]["field"] + "}", context):
            continue  # skipped: nothing joins steps
        query = step["query"]
        refs = [r.strip() for r in render(query["entries"], context).split(",") if r.strip()]
        assert refs, (level, step["id"])  # an empty lookup would fail the run
        if "entry_type" in query:
            rows = [{"slug": r, **records[r]} for r in refs if r in records and records[r]["entry_type"] == query["entry_type"]][: step.get("limit", 25)]
        else:
            rows = [{"data": {"master": f"{r}-master"}} for r in refs]
        context["steps"][step["id"]] = {"output": {"rows": rows}}
    if not style_reference:  # the house cover, looked up only when the world has no style picture of its own
        context["steps"]["house"] = {"output": {"rows": [{"id": "house-cover-id"}]}}
    return context


def test_the_cover_takes_a_world_series_story_or_chapter_and_sets_that_entrys_cover():
    flow = BLUEPRINTS["screenplay-make-cover"]["payload"]["definition"]
    (entry,) = [i for i in flow["trigger"]["inputs"] if i["type"] == "entry"]
    assert entry["name"] == "entry" and entry["required"] is True
    for level in LEVELS:
        assert level in entry["label"]
    (made,) = [a for a in flow["actions"] if a.get("kind") == "entry"]
    assert made == {"kind": "entry", "op": "set_data", "data": {"cover": "${steps.cover.output.asset.id}"}}  # the run's own entry
    assert len(flow["actions"]) <= 10  # Marvin's ten steps


@pytest.mark.parametrize("level", LEVELS)
def test_each_level_reads_the_world_and_every_level_between_down_to_itself(level):
    context = _cover_context(level)
    found = {k: [r["slug"] for r in context["steps"][k]["output"]["rows"]] for k in ("world", "series", "story")}
    assert found["world"] == ["storyworld"]
    assert found["series"] == ([] if level == "world" else ["voyages"])
    assert found["story"] == (["onion"] if level in ("story", "chapter") else [])
    said = render(_prompt("screenplay-make-cover"), context)
    assert f"for the {level} “{context['entry']['title']}”" in said and "WORLD: A storybook realm." in said
    assert ("SERIES: Voyages of the cook." in said) == (level != "world")
    assert ("STORY PREMISE (for mood only): A bet on an onion." in said) == (level in ("story", "chapter"))
    assert ("THIS CHAPTER: The bet is made." in said) == (level == "chapter")
    assert "The look: Rounded painted miniatures." in said and "rounded miniature illustration, warm painted palette" not in said


def test_the_cover_has_the_old_words_only_when_the_world_has_no_rules():
    prompt = _prompt("screenplay-make-cover")
    assert '|default:"rounded miniature illustration, warm painted palette, matte surfaces"}' in prompt
    context = _cover_context("world")
    context["steps"]["world"]["output"]["rows"][0]["data"]["rules"] = ""
    assert "The look: rounded miniature illustration, warm painted palette, matte surfaces" in render(prompt, context)


def test_leads_are_optional_and_a_cover_with_none_sends_no_character_pictures_and_says_what_it_shows():
    flow = BLUEPRINTS["screenplay-make-cover"]["payload"]["definition"]
    leads = next(i for i in flow["trigger"]["inputs"] if i["name"] == "leads")
    assert leads["required"] is False and "default" not in leads
    assert _step("screenplay-make-cover", "cast")["when"] == {"field": "input.leads", "op": "longer_than", "value": 0}
    references = _step("screenplay-make-cover", "cover")["references"]
    sent = lambda context: [r for r in render(references, context).split(",") if r.strip()]  # noqa: E731 (blanks dropped, as Marvin does)
    assert sent(_cover_context("story")) == ["house-cover-id"]  # no leads: the style picture only
    assert sent(_cover_context("story", leads="cook,captain")) == ["cook-master", "captain-master", "house-cover-id"]
    said = render(_prompt("screenplay-make-cover"), _cover_context("story", subject="three generation ships"))
    assert "WHAT THE COVER SHOWS: three generation ships" in said and "none: no character leads this cover" in said
    assert "sums up the premise below" in render(_prompt("screenplay-make-cover"), _cover_context("story"))


def test_the_worlds_style_picture_is_the_covers_style_and_the_house_cover_only_stands_in_for_it():
    house = _step("screenplay-make-cover", "house")
    assert house["entity"] == "asset" and house["query"]["ids"] == "${input.style_cover}"
    assert {"field": "steps.world.output.rows.0.data.style_reference", "op": "shorter_than", "value": 1} in house["when"]
    references = _step("screenplay-make-cover", "cover")["references"]
    sent = lambda context: [r for r in render(references, context).split(",") if r.strip()]  # noqa: E731
    assert sent(_cover_context("chapter", style_reference="storyworld-logo", leads="cook")) == ["cook-master", "storyworld-logo"]
    prompt = _prompt("screenplay-make-cover")
    assert "last attached picture" in prompt and "second attached picture" not in prompt  # the style picture is last, however many leads


@pytest.mark.parametrize("fmt", [*SHAPES, ""])
def test_the_cover_is_tall_square_or_wide_as_the_story_and_tall_for_a_world_or_series(fmt):
    words, size = SHAPES.get(fmt, ("Vertical portrait composition", ""))
    context = _cover_context("chapter", fmt=fmt)
    assert "\n\n" + words + ". Use the last attached picture ONLY" in render(_prompt("screenplay-make-cover"), context)
    assert render(_step("screenplay-make-cover", "cover")["args"]["size"], context) == size
    above = _cover_context("series", fmt=fmt)  # no story above a series: tall, at the connection's size
    assert "\n\nVertical portrait composition. Use" in render(_prompt("screenplay-make-cover"), above)
    assert render(_step("screenplay-make-cover", "cover")["args"]["size"], above) == ""


def test_the_cover_asks_before_spending_shows_the_prompt_and_offers_keep_or_redo_and_writes_only_the_title():
    spend, keep = _step("screenplay-make-cover", "spend"), _step("screenplay-make-cover", "keep")
    assert "OpenAI image credit" in spend["message"] and spend["fields"][0]["name"] == "prompt"
    assert keep["choices"] == ["Keep", "Redo"] and keep["redo"] == "Redo"
    prompt = _prompt("screenplay-make-cover")
    assert "gold lettering on a dark painted brush-stroke block, exactly this text and nothing else: ${entry.title}." in prompt
    assert "No other text anywhere" in prompt


# ── who is in a still (v213) ───────────────────────────────────────────────────────────────────────────────────────────────────────────
NOBODY = "NOBODY appears in this picture: no people, children or figures of any kind (the style picture's characters are not in it), unless THIS MOMENT names a figure."
SHIPS = {"steps": {"people": {"text": "", "count": 0}, "things": {"text": "- The Flash ships\n  data.role: three generation ships\n  data.rules: hulls as in the reference", "count": 1}, "someone": {"skipped": True}}}


def test_the_cast_is_read_as_people_and_things_and_someone_is_looked_for_only_among_the_people():
    branches = {b["name"]: b["steps"] for b in _step("screenplay-take-still", "context")["branches"]}
    people, things, someone = branches["cast"]
    on = {"field": "entry.data.cast", "op": "longer_than", "value": 0}
    assert people["query"]["where"] == [{"field": "actor", "op": "exists"}, {"field": "presence", "op": "neq", "value": "voice only"}, {"field": "presence", "op": "neq", "value": "object"}]
    assert things["query"]["where"] == [{"field": "actor", "op": "missing"}, {"field": "presence", "op": "neq", "value": "voice only"}]
    assert people["when"] == things["when"] == on and "data.age_state" in people["fields"] and "data.age_state" not in things["fields"]
    assert someone["when"] == {"field": "steps.people.output.count", "op": "gt", "value": 0}


def test_a_still_with_people_names_them_with_readable_labels_and_never_says_nobody():
    said = render(_prompt("screenplay-take-still"), _beat_context())
    assert "CHARACTERS (each exactly as in their reference, with these rules): - the cook\n  Role: Cook\n  Age: old\n" in said
    assert "IN THE PICTURE BUT NOT A PERSON (an object such as a ship, exactly as in its reference): none\n" in said
    assert NOBODY not in said and "data." not in said


def test_a_still_of_ships_or_of_no_cast_says_nobody_is_in_it_and_gives_the_ships_no_age():
    for cast in (SHIPS, {"steps": {"people": {"skipped": True}, "things": {"skipped": True}, "someone": {"skipped": True}}}):
        said = render(_prompt("screenplay-take-still"), _beat_context(cast=cast))
        assert NOBODY in said and "Age:" not in said and "data." not in said
        assert said.index(NOBODY) > said.index("THIS MOMENT:")  # near the end, after the moment it may name a figure in
    assert "  Role: three generation ships\n  Rules: hulls as in the reference\n" in render(_prompt("screenplay-take-still"), _beat_context(cast=SHIPS))


def test_this_moment_is_the_picture_without_its_delivery_note_and_the_changes_read_as_words():
    said = render(_prompt("screenplay-take-still"), _beat_context(picture="Interior: Shuttle Hangar - 2302 Delivery: Narrator (V.O.)."))
    assert "THIS MOMENT: Interior: Shuttle Hangar - 2302\n" in said and "Narrator" not in said
    context = _beat_context()
    context["steps"]["changes"] = {"output": {"text": "- Beat 03\n  data.number: 03\n  data.changes: the mast is broken"}}
    assert "  Beat number: 03\n  Changes: the mast is broken" in render(_prompt("screenplay-take-still"), context)


def test_the_import_no_longer_writes_the_delivery_note_into_a_beats_picture_and_a_refresh_leaves_an_old_one():
    from storyrender import beat_import

    rows = [{"beat": "01", "picture": "The hangar. Delivery: Narrator (V.O.).", "lines": [{"speaker": "Narrator", "text": "They waited."}], "sounds": [], "hold": None, "chapter": None}]
    plan = beat_import.import_plan("s", rows, {})
    (_slug, _title, beat), (_ls, _lt, line) = plan["beats"][0], plan["lines"][0]
    assert beat["picture"] == "The hangar." and line.get("extension") == "V.O."  # the line still gets how it is said
    old = {"s-beat-01": {"id": "b1", "title": beat_import.import_plan("s", rows, {})["beats"][0][1], "dataJson": {**beat, "picture": "The hangar. Delivery: Narrator (V.O.)."}}}
    assert beat_import.import_plan("s", rows, old, refresh=True)["updates"] == []  # a picture made before keeps its note: not a difference
