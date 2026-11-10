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
