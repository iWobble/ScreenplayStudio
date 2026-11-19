"""v237: a new install lists only the Stories and the Sound library of Screenplay Studio in the sidebar (the rest stay reachable from a story, the
guided setups and search), and the Timeline asks for its own sidebar link (Marvin #310: view spec `sidebar`)."""

import json

from tests.test_world_context import PACKAGE


def _blueprints():
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]


def test_only_stories_and_the_sound_library_are_in_the_sidebar():
    shown = {b["slug"] for b in _blueprints() if b["kind"] == "collection" and b["payload"]["in_sidebar"]}
    assert shown == {"screenplay-stories", "screenplay-sounds"}


def test_the_timeline_view_asks_for_a_sidebar_link():
    view = next(b for b in _blueprints() if b["kind"] == "view" and b["slug"] == "story-timeline")
    assert view["payload"]["sidebar"] is True
