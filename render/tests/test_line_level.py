"""A speech line's own level and muffling: set once on the line, they apply to whichever take plays."""

import json
import subprocess
from pathlib import Path

import pytest

from storyrender import audio_measure, build, ffmpeg, manifest
from storyrender.manifest import Line, Manifest, ManifestError, Shot
from tests.test_overlay_music import needs_ffmpeg


def _load(tmp_path: Path, line: dict):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "v.mp3").write_bytes(b"x")
    body = {"shots": [{"id": "b01", "still": "a.png", "lines": [{"audio": "v.mp3", "text": "Hi.", **line}]}]}
    (tmp_path / "m.json").write_text(json.dumps(body))
    return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_the_manifest_keeps_a_lines_level_and_muffling_and_a_plain_line_is_as_recorded(tmp_path):
    line = _load(tmp_path, {"volume": 0.4, "muffled": True}).shots[0].lines[0]
    assert (line.volume, line.muffled) == (0.4, True)
    plain = _load(tmp_path, {}).shots[0].lines[0]
    assert (plain.volume, plain.muffled) == (1.0, False)
    assert _load(tmp_path, {"volume": ""}).shots[0].lines[0].volume == 1.0 and _load(tmp_path, {"volume": 0}).shots[0].lines[0].volume == 0  # 0 is silence


@pytest.mark.parametrize(("volume", "words"), [(1.5, "volume is 0–1"), (-0.1, "volume is 0–1"), ("loud", "volume is a number")])
def test_a_bad_line_level_is_refused_with_the_manifest_error(tmp_path, volume, words):
    with pytest.raises(ManifestError, match=words):
        _load(tmp_path, {"volume": volume})


def _two_tones(path: Path) -> Path:
    """300 Hz (what a wall lets through) and 5 kHz (what it stops), a second."""
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:d=1", "-f", "lavfi", "-i", "sine=f=5000:d=1", "-filter_complex", "amix=inputs=2:normalize=0", str(path)])
    return path


def _band_db(path: Path, hz: int) -> float:
    done = subprocess.run(["ffmpeg", "-i", str(path), "-af", f"bandpass=f={hz}:width_type=h:w=200,volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(next(ln for ln in done.stderr.splitlines() if "mean_volume" in ln).split("mean_volume:")[1].split()[0].replace("-inf", "-91"))


def _mix(tmp_path: Path, take: Path, **line) -> Path:
    planned = manifest.plan(Manifest("t", (1080, 1920), 30, [Shot("s", tmp_path / "a.png", lines=[Line("x", take, 1.0, **line)], lead=0.0, tail=0.0)]))
    out = tmp_path / f"n-{len(list(tmp_path.glob('n-*.wav')))}.wav"
    build._narration(planned.shots[0], out)
    return out


@needs_ffmpeg
def test_a_lines_level_lowers_it_in_the_mix_and_muffling_removes_the_highs_and_keeps_the_lows(tmp_path):
    take = _two_tones(tmp_path / "take.wav")
    plain, half, muffled = _mix(tmp_path, take), _mix(tmp_path, take, volume=0.5), _mix(tmp_path, take, muffled=True)
    assert audio_measure.levels(half)[1] - audio_measure.levels(plain)[1] == pytest.approx(-6.0, abs=0.7)  # half the level is 6 dB down
    assert _band_db(muffled, 5000) < _band_db(plain, 5000) - 25  # the highs are gone
    assert _band_db(muffled, 300) > _band_db(plain, 300) - 2  # the lows stay
    assert _band_db(half, 300) == pytest.approx(_band_db(plain, 300) - 6.0, abs=0.7)  # a level alone changes no tone
