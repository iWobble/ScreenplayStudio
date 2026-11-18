"""`transcribe-clip`: what is said in a beat's clip, written to the beat as `clip_text` and `clip_words` (queued by the runner's describe-video)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from marvin_worker.jobs import META, Context
from storytranscribe import jobs
from tests.test_time_words import _Model


def _ctx(tmp_path):
    return Context(creds=("http://m", "tok"), work=tmp_path, name="clip-words-1")


def _wire(monkeypatch, beats: list[dict], *, sound=True, model=None):
    """The beat as each read finds it in turn (the last one stays), and what the job writes to it."""
    written, reads = [], iter(beats)
    seen = {"now": beats[0]}

    def query(creds, spec, limit=100):
        seen["now"] = next(reads, seen["now"])
        return [seen["now"]] if spec.get("entries") == seen["now"]["slug"] else []

    monkeypatch.setattr(jobs.marvin_api, "query", query)
    monkeypatch.setattr(jobs.marvin_api, "asset", lambda creds, a: {"id": a, "name": "me on camera", "originalFilename": "clip.webm"})
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, a, dest: dest.write_bytes(b"x"))
    monkeypatch.setattr(jobs.marvin_api, "update_entry", lambda creds, slug, data: written.append((slug, data)))
    monkeypatch.setattr(jobs, "has_sound", lambda path: sound)
    monkeypatch.setattr(jobs, "load_model", lambda name: model or _Model([]))
    return written


def _beat(clip="vid-1"):
    return {"slug": "b04", "dataJson": {"clip": clip, "clip_start": 1.5}}


def test_the_words_heard_in_the_clip_are_written_to_the_beat_on_the_recordings_own_clock(tmp_path, monkeypatch):
    model = _Model([("Hello,", 0.52, 0.9), ("I'm", 1.0, 1.2), ("Jared.", 1.2, 1.71)])
    written = _wire(monkeypatch, [_beat()], model=model)
    done = jobs.transcribe_clip({"job": "j", "args": {"entry": "b04", "clip": "vid-1"}}, _ctx(tmp_path))
    ((slug, data),) = written
    assert slug == "b04" and data["clip_text"] == "Hello, I'm Jared."
    assert data["clip_words"] == [{"word": "Hello,", "start": 0.52, "end": 0.9}, {"word": "I'm", "start": 1.0, "end": 1.2}, {"word": "Jared.", "start": 1.2, "end": 1.71}]
    assert set(data) == {"clip_text", "clip_words"}  # never the clip itself, so the beat's clip workflow is not set off again
    assert model.kw["word_timestamps"] is True and model.kw["vad_filter"] is True
    assert done["result"]["words"] == 3 and "3 words heard" in done["log"]


def test_a_clip_with_no_speech_or_no_sound_leaves_what_you_said_empty_and_says_so_without_failing(tmp_path, monkeypatch):
    written = _wire(monkeypatch, [_beat()], model=_Model([]))  # what faster-whisper gives a tone or a hush: no segments, no words
    done = jobs.transcribe_clip({"job": "j", "args": {"entry": "b04", "clip": "vid-1"}}, _ctx(tmp_path))
    assert written == [("b04", {"clip_text": "", "clip_words": []})] and "no speech heard" in done["log"]

    class _Deaf:
        def transcribe(self, *a, **kw):
            raise AssertionError("a file with no sound is never handed to the model (it fails inside the decoder)")

    written = _wire(monkeypatch, [_beat()], sound=False, model=_Deaf())
    done = jobs.transcribe_clip({"job": "j", "args": {"entry": "b04", "clip": "vid-1"}}, _ctx(tmp_path))
    assert written == [("b04", {"clip_text": "", "clip_words": []})] and "has no sound" in done["log"]


def test_a_clip_replaced_before_or_while_it_is_heard_writes_nothing(tmp_path, monkeypatch):
    written = _wire(monkeypatch, [_beat("vid-2")])
    done = jobs.transcribe_clip({"job": "j", "args": {"entry": "b04", "clip": "vid-1"}}, _ctx(tmp_path))
    assert written == [] and done["result"]["skipped"] is True
    written = _wire(monkeypatch, [_beat("vid-1"), _beat("vid-2")], model=_Model([("Hi", 0.1, 0.4)]))
    done = jobs.transcribe_clip({"job": "j", "args": {"entry": "b04", "clip": "vid-1"}}, _ctx(tmp_path))
    assert written == [] and done["result"]["skipped"] is True and "changed while" in done["log"]
    written = _wire(monkeypatch, [_beat("")])
    assert jobs.transcribe_clip({"job": "j", "args": {"entry": "b04"}}, _ctx(tmp_path))["result"]["skipped"] is True and written == []


def test_it_declares_what_it_takes_and_the_transcriber_offers_it():
    meta = META["transcribe-clip"]
    assert meta["inputs"]["entry"]["type"] == "string" and meta["inputs"]["clip"]["required"] is False and "faster-whisper" in meta["needs"]
    compose = (Path(__file__).resolve().parents[2] / "docker" / "compose.yml").read_text(encoding="utf-8")
    transcriber = re.search(r"desktop-transcriber.*?WORKER_KINDS:\s*(\S+)", compose, re.S).group(1).split(",")
    assert "transcribe-clip" in transcriber


def test_a_video_files_sound_track_is_found_and_one_without_is_not(tmp_path):
    """With the decoder faster-whisper uses (`av`), where it is installed (the transcriber image; the tests run without it)."""
    pytest.importorskip("av")
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    picture = ["-f", "lavfi", "-i", "color=c=red:s=160x120:r=30:d=1"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *picture, *tone, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / "a.mp4")], check=True)
    (tmp_path / "b.webm").write_bytes(subprocess.run(["ffmpeg", "-loglevel", "error", *picture, *tone, "-c:v", "libvpx", "-c:a", "libopus", "-f", "webm", "pipe:1"], capture_output=True, check=True).stdout)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *picture, "-pix_fmt", "yuv420p", str(tmp_path / "c.mp4")], check=True)
    assert jobs.has_sound(tmp_path / "a.mp4") and jobs.has_sound(tmp_path / "b.webm") and not jobs.has_sound(tmp_path / "c.mp4")
