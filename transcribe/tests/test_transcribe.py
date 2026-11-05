"""The `transcribe` kind: the three text forms, the transcript written as the model speaks, and the job that downloads, transcribes and uploads."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from marvin_worker.jobs import Context, JobError
from storytranscribe import jobs, text

SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "Thieving, lying, swearing."},
    {"start": 2.2, "end": 4.0, "text": "Joined to the most abominable lewdness."},
    {"start": 6.5, "end": 8.0, "text": "They were cowards."},
]


class FakeModel:
    """Yields the segments like faster-whisper does: lazily, so a failure part-way leaves the earlier ones."""

    def __init__(self, fail_after=None):
        self.fail_after = fail_after

    def transcribe(self, path, **kw):
        self.args = (path, kw)

        def run():
            for i, s in enumerate(SEGMENTS):
                if self.fail_after is not None and i == self.fail_after:
                    raise RuntimeError("decoder died")
                yield SimpleNamespace(**s)

        return run(), SimpleNamespace(language="en", language_probability=0.99, duration=8.0)


def test_the_three_forms():
    assert text.plain(SEGMENTS).splitlines()[0] == "Thieving, lying, swearing."
    assert text.timestamped(SEGMENTS).splitlines()[2] == "[0:00:06] They were cowards."
    assert text.paragraphs(SEGMENTS) == "Thieving, lying, swearing. Joined to the most abominable lewdness.\n\nThey were cowards.\n"
    assert text.stamp(3725) == "1:02:05"


def test_the_transcript_is_written_as_the_model_speaks_so_a_failure_keeps_what_was_heard(tmp_path):
    with pytest.raises(RuntimeError):
        jobs.transcribe_file(FakeModel(fail_after=2), tmp_path / "a.wav", tmp_path / "job-1")
    assert (tmp_path / "job-1.txt").read_text() == "Thieving, lying, swearing.\nJoined to the most abominable lewdness.\n"


def test_a_finished_run_writes_every_form_and_reports_what_it_heard(tmp_path):
    notes = []
    made = jobs.transcribe_file(FakeModel(), tmp_path / "a.wav", tmp_path / "job-1", language="", note=notes.append, every=2)
    assert (made["language"], made["seconds"], made["segments"]) == ("en", 8.0, 3)
    assert set(made["files"]) == {"text", "timestamped", "paragraphs", "json"} and all(p.is_file() for p in made["files"].values())
    assert json.loads(made["files"]["json"].read_text())["segments"][2]["start"] == 6.5
    assert any("en (99%)" in n for n in notes) and any("heard" in n for n in notes)


def _context(tmp_path):
    return Context(creds=("http://m", "tok"), work=tmp_path, name="transcribe-1")


def test_the_job_downloads_the_recording_transcribes_it_and_keeps_each_form_as_an_asset(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(jobs.marvin_api, "asset", lambda creds, a: {"name": "Devil with devil", "originalFilename": "Devil with devil.wav"})
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, a, dest: dest.write_bytes(b"RIFF"))
    monkeypatch.setattr(jobs.marvin_api, "upload_asset", lambda creds, file, **kw: seen.setdefault(kw["slug"], kw) and {"id": kw["slug"] + "-id", "publicUrl": f"https://a/{kw['slug']}"})
    monkeypatch.setattr(jobs, "load_model", lambda name: FakeModel())

    done = jobs.transcribe({"job": "transcribe-1", "args": {"audio": "devil"}}, _context(tmp_path))

    assert set(seen) == {"transcribe-1-text", "transcribe-1-timestamped", "transcribe-1-paragraphs", "transcribe-1-json"}
    assert seen["transcribe-1-json"]["mime"] == "application/json" and seen["transcribe-1-text"]["metadata"]["source"] == "devil"
    assert done["result"]["url"] == "https://a/transcribe-1-paragraphs" and done["result"]["files"]["json"]["id"] == "transcribe-1-json-id"
    assert done["result"]["segments"] == 3 and "3 segments" in done["log"]


def test_hotwords_reach_the_model_and_empty_ones_do_not(tmp_path):
    model = FakeModel()
    jobs.transcribe_file(model, tmp_path / "a.wav", tmp_path / "j1", hotwords="Callum Marguerite")
    assert model.args[1]["hotwords"] == "Callum Marguerite"
    jobs.transcribe_file(model, tmp_path / "a.wav", tmp_path / "j2", hotwords="")
    assert model.args[1]["hotwords"] is None


def test_a_job_with_no_recording_says_so(tmp_path):
    with pytest.raises(JobError, match="needs an audio asset"):
        jobs.transcribe({"job": "transcribe-1", "args": {}}, _context(tmp_path))


def test_it_declares_what_it_takes_so_a_worker_can_tell_marvin():
    meta = jobs.META["transcribe"] if hasattr(jobs, "META") else None
    from marvin_worker.jobs import META

    meta = META["transcribe"]
    assert meta["inputs"]["audio"]["type"] == "asset" and "audio/*" in meta["inputs"]["audio"]["accepts"]
    assert meta["inputs"]["language"]["required"] is False and "faster-whisper" in meta["needs"]
