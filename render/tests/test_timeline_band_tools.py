"""v239: on the Timeline a band drafts its beats (Marvin view spec `spine.bands[].run`) and the chosen beats can be put in a band (`assign`)."""

import json

from tests.test_world_context import PACKAGE


def _blueprints():
    return json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]


def _spine():
    return next(b for b in _blueprints() if b["kind"] == "view" and b["slug"] == "story-timeline")["payload"]["spine"]


def test_the_band_row_drafts_its_beats_and_takes_the_chosen_ones():
    bands = {b["field"]: b for b in _spine()["bands"]}
    assert bands["band"]["run"] is True and bands["band"]["assign"] is True
    # a beat's scene is set on its page: the Scene row drafts, but takes nothing
    assert bands["scene"]["run"] is True and "assign" not in bands["scene"]


def test_a_band_draft_is_the_beats_draft_the_render_reads():
    run = _spine()["run"]  # Marvin refuses a band's `run` without it
    assert (run["workflow"], run["item"], run["field"]) == ("screenplay-render", "beats", "number")
    render = next(b for b in _blueprints() if b["kind"] == "workflow" and b["slug"] == "screenplay-render")["payload"]["definition"]
    assert "beats" in {i["name"] for i in render["trigger"]["inputs"]}  # "1,3": the beats of a band with a gap


def test_add_to_band_offers_the_story_own_bands():
    beat = next(b for b in _blueprints() if b["kind"] == "entry_type" and b["slug"] == "beat")["payload"]
    band = next(f for f in beat["schema_json"]["fields"] if f["key"] == "band")
    # Marvin offers what the beat's form offers: its ref, narrowed by ref_match to the beat's own story
    assert band["ref"] == "band" and band["ref_match"] == {"story": "story"}
    assert _spine()["of"] != "band"  # assign never writes the field that puts a beat in the view
