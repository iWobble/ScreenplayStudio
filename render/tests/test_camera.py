"""Camera presets: names a beat, scene or story picks, turned into the still's move."""

import json
import subprocess
from pathlib import Path

import pytest

from storyrender import build, camera, manifest
from storyrender.manifest import Manifest, Shot
from tests.test_overlay_music import needs_ffmpeg


@pytest.mark.parametrize("name", sorted(camera.PRESETS))
def test_every_preset_is_a_move_the_manifest_accepts(name):
    move = camera.move_of(name)
    for end in ("from", "to"):
        got = manifest._move(move[end], manifest.Move(), name)  # x and y within the picture, zoom 1 or more
        assert 0 <= got.x <= 1 and 0 <= got.y <= 1 and got.zoom >= 1


def test_a_preset_that_moves_is_not_a_still_and_a_still_stays_put():
    for name, preset in camera.PRESETS.items():
        assert (preset.start == preset.end) is (name == "still")


def test_opposite_presets_swap_their_ends():
    pairs = [("push-in", "pull-out"), ("zoom-in", "zoom-out"), ("pan-left", "pan-right"), ("tilt-up", "tilt-down"), ("pedestal-up", "pedestal-down"), ("truck-left", "truck-right")]
    for a, b in pairs:
        assert camera.PRESETS[a].start == camera.PRESETS[b].end and camera.PRESETS[a].end == camera.PRESETS[b].start


def test_a_pan_left_moves_the_frame_left_and_a_tilt_up_moves_it_up():
    pan, tilt = camera.PRESETS["pan-left"], camera.PRESETS["tilt-up"]
    assert pan.end[0] < pan.start[0] and pan.start[2] > 1  # room to move: closer than the whole picture
    assert tilt.end[1] < tilt.start[1] and tilt.start[2] > 1


def test_a_name_is_read_without_regard_to_case_or_spaces_and_a_wrong_one_is_nothing():
    assert camera.move_of(" Push-In ") == camera.move_of("push-in") == camera.move_of("Push in") == camera.move_of("push_in")
    assert all(camera.move_of(preset.label) == camera.move_of(key) for key, preset in camera.PRESETS.items())  # the form's choices are read as the table's keys
    assert camera.move_of("dolly-zoom") is None and camera.move_of("") is None and camera.move_of(None) is None


def test_the_beats_preset_wins_then_the_scenes_then_the_storys_and_a_typo_falls_through():
    assert camera.pick({"camera": "pan-left"}, {"camera": "tilt-up"}, {"camera": "drift"}) == "pan-left"
    assert camera.pick({}, {"camera": "tilt-up"}, {"camera": "drift"}) == "tilt-up"
    assert camera.pick({}, {}, {"camera": "drift"}) == "drift"
    assert camera.pick({"camera": "wobble"}, {"camera": "tilt-up"}, {}) == "tilt-up"
    assert camera.pick({}, None, {}) is None


def _frames(tmp_path: Path, name: str) -> int:
    still = tmp_path / "still.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=160x280:d=1", "-frames:v", "1", str(still)], check=True)
    move = camera.move_of(name)
    shot = Shot("a", still, hold=0.5, move_from=manifest.Move(**{k: v for k, v in move["from"].items()}), move_to=manifest.Move(**{k: v for k, v in move["to"].items()}))
    planned = manifest.plan(Manifest("t", (80, 140), 12, [shot])).shots[0]
    out = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(still), "-vf", build.zoompan_filter(planned, (80, 140), 12), "-frames:v", "6", str(out)], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "json", str(out)], capture_output=True, text=True, check=True)
    return int(json.loads(probe.stdout)["streams"][0]["nb_read_frames"])


@needs_ffmpeg
def test_every_preset_renders_through_the_real_filter(tmp_path):
    assert {name: _frames(tmp_path, name) for name in camera.PRESETS} == {name: 6 for name in camera.PRESETS}
