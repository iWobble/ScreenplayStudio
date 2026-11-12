"""waveform: a recording as the peaks the Timeline draws, and the job that writes them to an entry."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from marvin_worker.jobs import Context, JobError

from storyrender import ffmpeg, jobs, waveform

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed")


def _loud_then_quiet(path: Path) -> Path:
    """A second of a loud tone (about -2.5 dBFS) and then a second of a quiet one (-18 dBFS)."""
    graph = "sine=frequency=440:duration=1,volume=6.0[a];sine=frequency=440:duration=1,volume=1.0[b];[a][b]concat=n=2:v=0:a=1"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-filter_complex", graph, str(path)], check=True)
    return path


def test_the_peaks_follow_the_loudness_of_the_recording_in_the_audiowaveform_format(tmp_path):
    wave = waveform.peaks(_loud_then_quiet(tmp_path / "a.wav"), points=100)
    assert (wave["version"], wave["bits"], wave["channels"], wave["length"]) == (2, 8, 1, 100) and len(wave["data"]) == 200
    first = max(abs(v) for v in wave["data"][:100])  # the first half, the loud second
    second = max(abs(v) for v in wave["data"][100:])
    assert first > 80 and 8 < second < first / 3  # the loud second reaches near the top of the 8 bits; the quiet one is much lower but there
    assert all(-128 <= v <= 127 for v in wave["data"]) and all(lo <= hi for lo, hi in zip(wave["data"][::2], wave["data"][1::2]))


def test_silence_is_a_flat_line_and_what_is_not_sound_is_refused(tmp_path):
    silent = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "1", str(silent)], check=True)
    assert set(waveform.peaks(silent, points=20)["data"]) <= {0, -1}  # 0 or the lowest bit: no sound
    (tmp_path / "x.txt").write_text("not sound")
    with pytest.raises(ffmpeg.FfmpegError):
        waveform.peaks(tmp_path / "x.txt")


def test_the_job_writes_the_peaks_to_the_entry(tmp_path, monkeypatch):
    audio = _loud_then_quiet(tmp_path / "take.wav")
    written = {}
    monkeypatch.setattr(jobs.marvin_api, "query", lambda creds, spec, limit=1: [{"slug": "s-1", "dataJson": {"audio": "asset-1"}}])
    monkeypatch.setattr(jobs.marvin_api, "asset", lambda creds, ref: {"id": "asset-1", "name": "take.wav", "mimeType": "audio/wav"})
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, ref, dest: shutil.copy(audio, dest))
    monkeypatch.setattr(jobs.marvin_api, "update_entry", lambda creds, slug, data: written.update({"slug": slug, **data}))
    ctx = Context(creds=("http://m", "t"), work=tmp_path, name="wave-1")
    out = jobs.make_waveform({"job": "j", "args": {"entry": "s-1"}}, ctx)
    assert out["result"] == {"entry": "s-1", "field": "audio", "wave_field": "waveform", "points": 240}
    assert written["slug"] == "s-1" and written["waveform"]["length"] == 240 and len(json.dumps(written["waveform"])) < 3000  # small enough to keep on the entry
    with pytest.raises(JobError, match="needs args.entry"):
        jobs.make_waveform({"job": "j", "args": {}}, ctx)
    monkeypatch.setattr(jobs.marvin_api, "query", lambda creds, spec, limit=1: [{"slug": "s-2", "dataJson": {}}])
    with pytest.raises(JobError, match="has nothing in “audio”"):
        jobs.make_waveform({"job": "j", "args": {"entry": "s-2"}}, ctx)
