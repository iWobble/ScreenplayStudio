"""A story's `end_fade`: every bed (the ambience that runs to the end of the film, and the music) fades out over that long at the end."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest, marvin_pull
from storyrender.manifest import ManifestError

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
DATA = lambda e: e["dataJson"]  # noqa: E731


def _tone(path: Path, seconds: float, hz: int) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", "-c:a", "libmp3lame", str(path)], check=True)
    return path


def _band_db(path: Path, start: float, length: float, hz: int) -> float:
    done = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", f"bandpass=f={hz}:width_type=h:w=300,volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", done.stderr).group(1).replace("-inf", "-91"))


def _load(tmp_path: Path, **top):
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "b01", "still": "b.png", "hold": 2, "lines": []}], **top}))
    return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_the_manifest_keeps_an_end_fade_and_leaves_it_out_when_none_is_set(tmp_path):
    assert _load(tmp_path, end_fade=3).end_fade == 3.0
    assert _load(tmp_path).end_fade is None and _load(tmp_path, end_fade="").end_fade is None


@pytest.mark.parametrize("bad", [0, -1, 31])
def test_an_end_fade_must_be_above_zero_and_at_most_thirty_seconds(tmp_path, bad):
    with pytest.raises(ManifestError, match="end_fade"):
        _load(tmp_path, end_fade=bad)


@pytest.mark.parametrize(("given", "want"), [(3, 3.0), ("2.5", 2.5), (0, None), ("", None), (None, None), ("long", None), (-2, None)])
def test_the_story_field_is_a_positive_number_of_seconds_or_nothing(given, want):
    assert marvin_pull._positive(given) == want


def _project(tmp_path: Path, end_fade, *, with_music: bool):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    folder = project.parent
    _tone(folder / "bed.mp3", 30.0, 1500)
    raw = json.loads(project.read_text())
    for shot in raw["shots"]:  # one ambience under the whole film
        shot["ambience"] = {"audio": "bed.mp3", "volume": 0.8}
    if with_music:
        _tone(folder / "tune.mp3", 30.0, 2500)
        raw["music"] = {"audio": "tune.mp3", "volume": 0.8, "fade_in": 0, "fade_out": 0.4}
    if end_fade:
        raw["end_fade"] = end_fade
    project.write_text(json.dumps(raw))
    return manifest.load(project, probe=ffmpeg.duration)


@needs_ffmpeg
def test_the_ambience_that_runs_to_the_end_fades_out_over_the_stories_setting(tmp_path):
    plain, faded = _project(tmp_path / "a", None, with_music=False), _project(tmp_path / "b", 4.0, with_music=False)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    build.render(faded, tmp_path / "faded.mp4", draft=True)
    total = manifest.plan(plain).duration
    assert total > 6
    window = (total - 1.5, 0.5)  # a stretch the default 0.6 s fade has long finished with, and a 4 s fade is well into
    assert _band_db(tmp_path / "faded.mp4", *window, 1500) < _band_db(tmp_path / "plain.mp4", *window, 1500) - 3


@needs_ffmpeg
def test_the_music_fades_out_over_the_stories_setting_instead_of_its_own_short_fade(tmp_path):
    plain, faded = _project(tmp_path / "a", None, with_music=True), _project(tmp_path / "b", 4.0, with_music=True)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    build.render(faded, tmp_path / "faded.mp4", draft=True)
    total = manifest.plan(plain).duration
    window = (total - 1.5, 0.5)
    assert _band_db(tmp_path / "faded.mp4", *window, 2500) < _band_db(tmp_path / "plain.mp4", *window, 2500) - 3


# ── start_fade: the same for the start of the film ───────────────────────────────────────────────────────────────────────────────────────
def test_the_manifest_keeps_a_start_fade_and_leaves_it_out_when_none_is_set(tmp_path):
    assert _load(tmp_path, start_fade=3).start_fade == 3.0
    assert _load(tmp_path).start_fade is None and _load(tmp_path, start_fade="").start_fade is None


@pytest.mark.parametrize("bad", [0, -1, 31])
def test_a_start_fade_must_be_above_zero_and_at_most_thirty_seconds(tmp_path, bad):
    with pytest.raises(ManifestError, match="start_fade"):
        _load(tmp_path, start_fade=bad)


def _start_project(tmp_path: Path, start_fade, *, with_music: bool, music_fade_in: float = 0.0):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    folder = project.parent
    _tone(folder / "bed.mp3", 30.0, 1500)
    raw = json.loads(project.read_text())
    raw["ambience"] = {"audio": "bed.mp3", "volume": 0.8}
    if with_music:
        _tone(folder / "tune.mp3", 30.0, 2500)
        raw["music"] = {"audio": "tune.mp3", "volume": 0.8, "fade_in": music_fade_in, "fade_out": 0.4}
    if start_fade:
        raw["start_fade"] = start_fade
    project.write_text(json.dumps(raw))
    return manifest.load(project, probe=ffmpeg.duration)


@needs_ffmpeg
def test_the_story_wide_ambience_fades_in_over_the_stories_setting(tmp_path):
    plain, faded = _start_project(tmp_path / "a", None, with_music=False), _start_project(tmp_path / "b", 4.0, with_music=False)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    build.render(faded, tmp_path / "faded.mp4", draft=True)
    window = (0.9, 0.5)  # past the default 0.6 s fade, well inside a 4 s one
    assert _band_db(tmp_path / "faded.mp4", *window, 1500) < _band_db(tmp_path / "plain.mp4", *window, 1500) - 3


@needs_ffmpeg
def test_the_music_fades_in_over_the_stories_setting_in_place_of_its_own(tmp_path):
    plain, faded = _start_project(tmp_path / "a", None, with_music=True, music_fade_in=0.2), _start_project(tmp_path / "b", 4.0, with_music=True, music_fade_in=0.2)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    build.render(faded, tmp_path / "faded.mp4", draft=True)
    window = (0.9, 0.5)
    assert _band_db(tmp_path / "faded.mp4", *window, 2500) < _band_db(tmp_path / "plain.mp4", *window, 2500) - 3  # the story's 4 s wins over the sound's 0.2 s


# ── the cascade: the sound's own fades, then the story's, then the beat's ────────────────────────────────────────────────────────────────
def test_fades_cascade_sound_then_story_then_beat_each_overriding_the_one_before():
    sound = {"fade_in": 1.0, "fade_out": 2.0}
    assert marvin_pull.cascaded_fades(sound) == {"fade_in": 1.0, "fade_out": 2.0}  # the sound alone: nothing marked as set
    story = {"ambience_fade_in": 3, "ambience_fade_out": ""}
    assert marvin_pull.cascaded_fades(sound, story) == {"fade_in": 3.0, "fade_out": 2.0, "fade_in_set": True}  # the story replaces what it sets
    beat = {"ambience_fade_out": "4"}
    assert marvin_pull.cascaded_fades(sound, story, beat) == {"fade_in": 3.0, "fade_out": 4.0, "fade_in_set": True, "fade_out_set": True}
    assert marvin_pull.cascaded_fades({}, {"ambience_fade_in": 0, "ambience_fade_out": "x"}) == {}  # zero, empty or not a number sets nothing


def test_a_beats_bed_and_the_stories_bed_carry_the_cascaded_fades(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / f"{asset}.mp3")
    sounds = {"hum": {"dataJson": {"audio": "a-hum", "fade_in": 1.0}}, "rain": {"dataJson": {"audio": "a-rain"}}}
    story = {"ambience": "hum", "ambience_fade_out": 5}
    bed = marvin_pull.story_ambience(("u", "t"), tmp_path, story, sounds, DATA, {}, [])
    assert (bed["fade_in"], bed["fade_out"], bed.get("fade_in_set"), bed.get("fade_out_set")) == (1.0, 5.0, None, True)  # fade-in from the sound, fade-out from the story
    local = marvin_pull._ambience(("u", "t"), tmp_path, {"ambience": "rain", "ambience_fade_in": 0.4}, {}, sounds, DATA, {}, [], story)
    assert (local["fade_in"], local["fade_out"], local.get("fade_in_set"), local.get("fade_out_set")) == (0.4, 5.0, True, True)  # the beat's fade-in, the story's fade-out


def test_the_manifest_keeps_which_fades_were_set_above_the_sound(tmp_path):
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "a.mp3").write_bytes(b"x")
    shot = {"id": "b01", "still": "b.png", "hold": 2, "lines": [], "ambience": {"audio": "a.mp3", "fade_in": 0.4, "fade_in_set": True}}
    (tmp_path / "m.json").write_text(json.dumps({"shots": [shot], "ambience": {"audio": "a.mp3", "fade_out": 5, "fade_out_set": True}}))
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)
    assert (m.shots[0].ambience.fade_in_set, m.shots[0].ambience.fade_out_set) == (True, False)
    assert (m.ambience.fade_in_set, m.ambience.fade_out_set) == (False, True)


@needs_ffmpeg
def test_a_fade_the_story_sets_for_its_ambience_is_not_replaced_by_the_films_start_fade(tmp_path):
    # the story's ambience asks for a 0.2 s fade-in itself: that is more specific than the film's 4 s, so it wins
    plain = _start_project(tmp_path / "a", None, with_music=False)
    general = _start_project(tmp_path / "b", 4.0, with_music=False)
    specific_path = _start_project(tmp_path / "c", 4.0, with_music=False)
    raw_file = next((tmp_path / "c" / "demo").glob("*.json"))
    raw = json.loads(raw_file.read_text())
    raw["ambience"] = {**raw["ambience"], "fade_in": 0.2, "fade_in_set": True}
    raw_file.write_text(json.dumps(raw))
    specific = manifest.load(raw_file, probe=ffmpeg.duration)
    for name, m in (("plain", plain), ("general", general), ("specific", specific)):
        build.render(m, tmp_path / f"{name}.mp4", draft=True)
    window = (0.9, 0.5)
    at = lambda name: _band_db(tmp_path / f"{name}.mp4", *window, 1500)  # noqa: E731
    assert at("general") < at("plain") - 3  # the film's 4 s fade holds the bed down here
    assert at("specific") == pytest.approx(at("plain"), abs=2.5)  # the story's own short fade has it up by now
