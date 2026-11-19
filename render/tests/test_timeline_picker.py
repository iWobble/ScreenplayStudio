"""v238: the Timeline's story picker draws cards (Marvin #313: view spec `picker`), and the types nobody makes by hand are not offered in the
New menu of a new install (Marvin #312: capabilities `offer_in_new`)."""

import json

from tests.test_world_context import PACKAGE

MACHINE_MADE = {"band", "beat", "cast-member", "casting", "render-job", "revision", "scene", "shot", "speech-line", "still", "take"}
MADE_BY_HAND = {"actor", "chapter", "pronunciation", "series", "sound", "story", "voice", "world"}


def _blueprints():
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]


def _types():
    return {b["slug"]: b["payload"] for b in _blueprints() if b["kind"] == "entry_type"}


def test_the_timeline_picker_asks_for_cards():
    view = next(b for b in _blueprints() if b["kind"] == "view" and b["slug"] == "story-timeline")["payload"]
    picker = view["picker"]
    assert set(picker) <= {"picture", "subtitle", "badges", "strip", "play"}
    story = {f["key"]: f for f in _types()["story"]["schema_json"]["fields"]}
    for key in (picker["picture"], picker["play"]):
        assert story[key]["type"] == "asset"
    assert story["series"] and story["episode"] and story["status"]
    assert picker["strip"] == {"limit": 16}
    assert view["spine"]["picture"] == "still"  # the strip needs spine.picture


def test_machine_made_types_are_not_offered_in_the_new_menu():
    types = _types()
    for slug in MACHINE_MADE:
        assert types[slug]["capabilities_json"]["offer_in_new"] is False, slug
    for slug in MADE_BY_HAND:
        assert (types[slug].get("capabilities_json") or {}).get("offer_in_new", True) is True, slug
