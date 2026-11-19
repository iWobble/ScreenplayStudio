"""v234: a story's scenes are listed in the order of their numbers, and those with no number as they were made, in the story's own list and in
the two guided steps that list a story's scenes (the import already numbers the scenes it makes: storyrender/jobs.py `scene_number`)."""

from tests.test_world_context import BLUEPRINTS

ORDER = {"by": "number", "then": "created_at"}


def test_the_story_lists_its_scenes_by_number_then_as_made():
    lists = {c["title"]: c for c in BLUEPRINTS["story"]["payload"]["schema_json"]["children"]}
    assert lists["Scenes"]["sort"] == ORDER


def test_the_guided_steps_over_scenes_sort_the_same_way():
    seen = []
    for slug in ("narrate-a-story", "sounds-for-a-story"):
        for step in BLUEPRINTS[slug]["payload"]["steps"]:
            if step.get("entry_type") == "scene" and step.get("kind") == "list":
                assert step["sort"] == ORDER, (slug, step["id"])
                seen.append((slug, step["id"]))
    assert seen == [("narrate-a-story", "scenes"), ("sounds-for-a-story", "beds")]
