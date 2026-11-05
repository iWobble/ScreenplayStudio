"""Fades on effects, beds and music, and the story's music bed: the filter text, what a render really does, and what the pull passes on."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest, marvin_pull

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _tone(path: Path, seconds: float, hz: int = 440) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", "-c:a", "libmp3lame", str(path)], check=True)
    return path


def _mean_db(path: Path, start: float, length: float) -> float:
    done = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", done.stderr).group(1).replace("-inf", "-91"))


def test_fades_are_filters_held_to_half_the_sound():
    assert build.fades(4.0) == ""
    assert build.fades(4.0, 1.0, 0.5) == "afade=t=in:st=0:d=1.000,afade=t=out:st=3.500:d=0.500,"
    assert build.fades(1.0, 5.0, 5.0) == "afade=t=in:st=0:d=0.500,afade=t=out:st=0.500:d=0.500,"  # never more than half each, so they cannot overlap
    assert build.fades(4.0, 0.0, 2.0) == "afade=t=out:st=2.000:d=2.000,"


@needs_ffmpeg
def test_an_effect_with_a_fade_in_rises_from_silence_instead_of_starting_at_full_level(tmp_path):
    _tone(tmp_path / "fx.mp3", 3.0)
    for name, fade in (("plain", 0), ("faded", 1.5)):
        (tmp_path / f"{name}.json").write_text(json.dumps({"shots": [{"id": "b01", "hold": 3.0, "lines": [], "sfx": [{"audio": "fx.mp3", "at": 0, "volume": 1.0, "fade_in": fade}]}]}))
        m = manifest.load(tmp_path / f"{name}.json", probe=ffmpeg.duration, need_stills=False)
        build.listen(m, tmp_path / f"{name}.mp3")
    plain_start, faded_start = _mean_db(tmp_path / "plain.mp3", 0.0, 0.3), _mean_db(tmp_path / "faded.mp3", 0.0, 0.3)
    faded_later = _mean_db(tmp_path / "faded.mp3", 2.0, 0.5)
    assert faded_start < plain_start - 6  # the first moments are much quieter
    assert faded_later > faded_start + 6  # and it has come up by the end of the fade


def test_the_manifest_keeps_a_sounds_fades_and_a_music_beds(tmp_path):
    (tmp_path / "fx.mp3").write_bytes(b"x")
    (tmp_path / "m.json").write_text(
        json.dumps(
            {
                "shots": [{"id": "b01", "hold": 2, "lines": [], "sfx": [{"audio": "fx.mp3", "fade_in": 0.5, "fade_out": 1}], "ambience": {"audio": "fx.mp3", "fade_in": 2}}],
                "music": {"audio": "fx.mp3", "volume": 0.2, "fade_in": 3, "fade_out": 4},
            }
        )
    )
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)
    fx, amb = m.shots[0].sfx[0], m.shots[0].ambience
    assert (fx.fade_in, fx.fade_out, amb.fade_in, amb.fade_out) == (0.5, 1.0, 2.0, 0.0)
    assert m.music["fade_in"] == 3 and m.music["fade_out"] == 4 and m.music["volume"] == 0.2


@needs_ffmpeg
def test_a_video_renders_with_a_music_bed_that_fades_in_and_out(tmp_path):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    _tone(project.parent / "bed.mp3", 5.0, 220)
    raw = json.loads(project.read_text())
    raw["music"] = {"audio": "bed.mp3", "volume": 1.0, "fade_in": 1.5, "fade_out": 1.5}
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    made = build.render(m, tmp_path / "out.mp4", draft=True)
    assert made["measured_seconds"] > 3 and (tmp_path / "out.mp4").stat().st_size > 0


def test_fades_are_passed_on_only_when_the_sound_sets_them():
    assert marvin_pull.fades_of({"fade_in": 1.5, "fade_out": None}) == {"fade_in": 1.5}
    assert marvin_pull.fades_of({"fade_in": 0, "fade_out": ""}) == {}
    assert marvin_pull.fades_of({"fade_out": "2"}) == {"fade_out": 2.0}


def test_the_story_names_a_music_bed_and_it_is_pulled_with_its_level_and_fades(tmp_path, monkeypatch):
    data = lambda e: e["dataJson"]  # noqa: E731
    row = {"slug": "theme", "dataJson": {"kind": "music", "audio": "asset-1", "volume": None, "fade_in": 2, "fade_out": 3}}
    monkeypatch.setattr(marvin_pull.marvin_api, "query", lambda creds, spec, limit=100: [row] if spec["entries"] == "theme" else [])
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: (tmp_path / "audio" / "sounds" / "theme.mp3"))
    got = marvin_pull.music_of(("u", "t"), tmp_path, {"music": "theme"}, data)
    assert got == {"audio": "audio/sounds/theme.mp3", "volume": 0.12, "id": "theme", "fade_in": 2.0, "fade_out": 3.0}  # no volume on the sound: the default bed level
    assert marvin_pull.music_of(("u", "t"), tmp_path, {}, data) is None  # the story names none
    assert marvin_pull.music_of(("u", "t"), tmp_path, {"music": "missing"}, data) is None  # no such sound
    row["dataJson"]["audio"] = None
    assert marvin_pull.music_of(("u", "t"), tmp_path, {"music": "theme"}, data) is None  # its take is not made yet
