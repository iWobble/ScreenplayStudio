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
        assert (preset.start == preset.end) is (name == "still" or preset.rock is not None)  # only a still and a rocking keep to one place


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


# ── rocking ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_rocking_preset_carries_its_roll_period_and_heave_and_the_manifest_reads_them():
    move = camera.move_of("Rocking")
    assert move["rock"] == {"degrees": 2.5, "seconds": 6.0, "heave": 0.012}
    assert manifest._rock(move["rock"], "t") == manifest.Rock(2.5, 6.0, 0.012)
    assert "rock" not in camera.move_of("push-in")
    assert manifest._rock({"degrees": 0, "heave": 0}, "t") is None and manifest._rock(None, "t") is None  # nothing to rock


def test_a_storm_rocks_further_faster_and_heaves_more_than_a_calm_sea():
    calm, storm = camera.PRESETS["rocking"].rock, camera.PRESETS["heavy-rocking"].rock
    assert storm[0] > calm[0] and storm[1] < calm[1] and storm[2] > calm[2]


@pytest.mark.parametrize("raw", [{"degrees": 40}, {"degrees": 2, "seconds": 0.2}, {"degrees": 2, "seconds": 90}, {"degrees": 2, "heave": 0.5}, {"degrees": -1}])
def test_a_rocking_beyond_what_a_picture_can_take_is_refused(raw):
    with pytest.raises(manifest.ManifestError, match="rock is degrees"):
        manifest._rock(raw, "shot")


def test_the_roll_scales_the_frame_up_enough_to_cover_its_corners_and_runs_on_the_films_clock():
    filtered = build.rock_filter(manifest.Rock(6, 4, 0), 12.5, (360, 640))
    assert "sin(2*PI*(12.5000+t)/4)" in filtered  # a beat that starts 12.5 s in picks the rocking up where the last left it
    wide = int(filtered.split("scale=")[1].split(":")[0])
    assert wide > 360  # bigger than the frame by what a 6 degree turn needs


def _clip(tmp_path: Path, still: Path, rock: manifest.Rock, start: float = 0.0, name: str = "rock") -> Path:
    shot = Shot("a", still, hold=2.0, move_from=manifest.Move(zoom=1.0), move_to=manifest.Move(zoom=1.0), rock=rock)
    planned = manifest.plan(Manifest("t", (80, 140), 12, [shot])).shots[0]
    planned = manifest.PlannedShot(planned.shot, start, planned.duration, planned.lines)
    out = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "12", "-i", str(still), "-vf", build.zoompan_filter(planned, (80, 140), 12), "-t", "2", "-r", "12", str(out)], check=True)
    return out


def _frame(clip: Path, at: float, tmp_path: Path):
    from PIL import Image

    png = tmp_path / f"f{at}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-i", str(clip), "-frames:v", "1", str(png)], check=True)
    return Image.open(png).convert("RGB")


@needs_ffmpeg
def test_a_rocking_frame_at_its_furthest_roll_has_no_black_corners(tmp_path):
    red = tmp_path / "red.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=160x280", "-frames:v", "1", str(red)], check=True)
    clip = _clip(tmp_path, red, manifest.Rock(6, 4, 0))  # the furthest roll is a quarter of the way through a sway: 1 s
    frame = _frame(clip, 1.0, tmp_path)
    for corner in ((0, 0), (79, 0), (0, 139), (79, 139)):
        r, g, b = frame.getpixel(corner)
        assert r > 150 and g < 90 and b < 90, f"corner {corner} is {(r, g, b)}: the turned picture does not cover the frame"


@needs_ffmpeg
def test_a_rocking_frame_is_level_at_the_start_and_halfway_and_tilted_a_quarter_of_the_way_between(tmp_path):
    still = tmp_path / "bars.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=160x280", "-frames:v", "1", str(still)], check=True)
    clip = _clip(tmp_path, still, manifest.Rock(6, 2, 0))  # one sway in 2 s: level at 0 s and 1 s, furthest over at 0.5 s
    from PIL import ImageChops

    def apart(a: float, b: float) -> int:
        return sum(sum(px) for px in ImageChops.difference(_frame(clip, a, tmp_path), _frame(clip, b, tmp_path)).getdata())

    assert apart(0.0, 0.5) > 5 * max(apart(0.0, 1.0), 1)  # level to tilted is a big change; level to level (a whole half sway on) is hardly any
