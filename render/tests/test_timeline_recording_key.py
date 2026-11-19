"""v236: the Timeline view reads a clip's and a line's facts from the Recording the entry names (Marvin #307): `recording` on the beat's clip
and on the Lines lane, each naming the field the Media worker keeps. The Sounds lane (and the bed lanes) are left as they were: a generated
sound's own length is the one asked of ElevenLabs, and a bed reads neither length nor waveform."""

from tests.test_world_context import BLUEPRINTS


def _view() -> dict:
    return BLUEPRINTS["story-timeline"]["payload"]


def test_the_clip_and_the_lines_lane_name_the_recording_field_and_the_other_lanes_do_not():
    view = _view()
    assert view["spine"]["clip"]["recording"] == "recording"
    lanes = {lane["id"]: lane for lane in view["lanes"]}
    assert lanes["lines"]["recording"] == "recording" and lanes["lines"]["audio"] == "audio"  # a lane that names a recording names its audio
    assert [i for i, lane in lanes.items() if "recording" in lane] == ["lines"]


def test_the_field_it_names_is_a_field_of_the_beat_and_the_speech_line():
    for slug in ("beat", "speech-line"):
        keys = {f["key"] for f in BLUEPRINTS[slug]["payload"]["schema_json"]["fields"]}
        assert "recording" in keys, slug
