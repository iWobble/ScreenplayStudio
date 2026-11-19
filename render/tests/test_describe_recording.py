"""A recording that is not a beat's clip is described on its own: `describe-video` with `{asset}` and no entry writes the facts to the asset's
own metadata (`video` for a file with a picture, `audio` for a sound) and nothing else. Started by hand (`screenplay-describe-recording`); a new
upload is the Media package's to describe, so Studio has no upload workflow. And a Transcript points at its recording by id."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from marvin_worker.jobs import META, Context, JobError, check_args

from storyrender import audio_measure, jobs
from tests.test_clip import _clip_file
from tests.test_world_context import BLUEPRINTS

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
ID = "a6e76f6c-1362-43f3-8bfa-c11642c974d2"


def _sound(path: Path, seconds: float = 1.5, *, rate: int = 22050, layout: str = "stereo") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate={rate}", "-ac", "2" if layout == "stereo" else "1", str(path)], check=True)
    return path


class _Library:
    """The one asset, as Marvin's API gives it by slug or id, and what the job does to it. Any entry read or write fails the test."""

    def __init__(self, file: Path | None, mime: str, name: str = "Recording Nov 18", meta: dict | None = None):
        self.file, self.patched, self.fetched = file, {}, []
        self.record = {"id": ID, "slug": "recording-nov-18", "name": name, "mimeType": mime, "originalFilename": file.name if file else "x.bin", "metadataJson": meta or {}}

    def wire(self, monkeypatch):
        api = jobs.marvin_api
        monkeypatch.setattr(api, "asset", lambda creds, ref: self.record if ref in (ID, "recording-nov-18") else pytest.fail(f"no asset {ref}"))
        monkeypatch.setattr(api, "download_asset", lambda creds, ref, dest: self.fetched.append(ref) or shutil.copy(self.file, dest))
        monkeypatch.setattr(api, "request", self.request)
        for name in ("query", "update_entry", "create_entry", "upload_asset"):
            monkeypatch.setattr(api, name, lambda *a, _n=name, **k: pytest.fail(f"a loose recording's description calls no {_n}"))
        return self

    def request(self, creds, path, method="GET", data=None, content_type=None):
        assert method == "PATCH" and path.startswith("/api/platform/assets/"), (method, path)
        self.patched[path.rsplit("/", 1)[1]] = json.loads(data)["metadata"]
        return b"{}"


def _run(args: dict, tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return jobs.describe_video({"job": "describe-1", "args": args}, Context(creds=("http://m", "t"), work=tmp_path, name="describe-1"))


# ── a sound's facts ──────────────────────────────────────────────────────────
@needs_ffmpeg
def test_a_sound_is_described_by_its_length_codec_rate_and_channels(tmp_path):
    facts = audio_measure.describe(_sound(tmp_path / "s.wav", 1.5, rate=22050, layout="mono"))
    assert facts == {"duration_seconds": pytest.approx(1.5, abs=0.02), "codec": "pcm_s16le", "sample_rate": 22050, "channels": 1, "format": facts["format"]}
    assert facts["format"].startswith("pcm_s16le · 22.05 kHz · mono")


@needs_ffmpeg
def test_a_picture_has_no_sound_to_describe(tmp_path):
    still = tmp_path / "p.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=8x8", "-frames:v", "1", str(still)], check=True)
    with pytest.raises(Exception, match="no sound"):
        audio_measure.describe(still)


# ── the job, on a recording alone ────────────────────────────────────────────
@needs_ffmpeg
@pytest.mark.parametrize("asked", ["recording-nov-18", ID])
def test_a_video_alone_gets_its_facts_on_its_own_metadata_and_nothing_else_is_written(tmp_path, monkeypatch, asked):
    lib = _Library(_clip_file(tmp_path / "src.webm", 2.0, piped=True), "video/webm", meta={"recording": {"source": "browser"}}).wire(monkeypatch)
    done = _run({"asset": asked}, tmp_path / "w")
    meta = lib.patched[ID]  # by its id, whichever it was asked with
    assert meta["recording"] == {"source": "browser"} and set(meta) == {"recording", "video"}
    assert meta["video"] == {"duration_seconds": pytest.approx(2.0, abs=0.1), "width": 160, "height": 120, "fps": pytest.approx(30, abs=0.5), "has_audio": True}
    assert lib.fetched == [ID] and done["result"]["asset"] == ID and done["result"]["kind"] == "video" and "poster" not in done["result"]
    assert "160x120" in done["log"] and "with sound" in done["log"]


@needs_ffmpeg
def test_a_browsers_webm_that_holds_only_sound_is_described_as_a_sound(tmp_path, monkeypatch):
    webm = tmp_path / "voice.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1.2", "-c:a", "libopus", "-f", "webm", str(webm)], check=True)
    lib = _Library(webm, "video/webm").wire(monkeypatch)
    done = _run({"asset": ID}, tmp_path / "w")
    audio = lib.patched[ID]["audio"]
    assert "video" not in lib.patched[ID] and audio["codec"] == "opus" and audio["sample_rate"] == 48000 and audio["channels"] == 1
    assert audio["duration_seconds"] == pytest.approx(1.2, abs=0.05) and done["result"]["kind"] == "audio"


@needs_ffmpeg
def test_a_sound_keeps_its_other_metadata_and_its_old_facts_are_replaced(tmp_path, monkeypatch):
    lib = _Library(_sound(tmp_path / "s.mp3", 1.0), "audio/mpeg", meta={"words": [{"text": "hi"}], "audio": {"duration_seconds": 99}}).wire(monkeypatch)
    _run({"asset": ID}, tmp_path / "w")
    meta = lib.patched[ID]
    assert meta["words"] == [{"text": "hi"}] and meta["audio"]["duration_seconds"] == pytest.approx(1.0, abs=0.1) and meta["audio"]["channels"] == 2


def test_a_file_that_is_not_a_recording_fails_and_writes_nothing(tmp_path, monkeypatch):
    lib = _Library(None, "image/png", name="still.png").wire(monkeypatch)
    with pytest.raises(JobError, match="is not a recording"):
        _run({"asset": ID}, tmp_path)
    assert lib.patched == {} and lib.fetched == []


def test_an_entry_and_an_asset_together_or_neither_are_refused(tmp_path):
    with pytest.raises(JobError, match="not both"):
        _run({"entry": "b04", "asset": ID}, tmp_path)
    with pytest.raises(JobError, match="args.asset"):
        _run({}, tmp_path)


def test_the_kind_takes_an_asset_alone_or_an_entry_alone():
    check_args("describe-video", {"asset": "recording-nov-18"})  # no entry needed any more
    check_args("describe-video", {"entry": "b04", "field": "clip", "clip": ID})
    meta = META["describe-video"]
    assert meta["inputs"]["asset"]["type"] == "asset" and meta["inputs"]["asset"]["required"] is False and meta["inputs"]["entry"]["required"] is False


# ── what starts it ───────────────────────────────────────────────────────────
def _flow(slug):
    return BLUEPRINTS[slug]["payload"]["definition"]


def test_the_manual_workflow_is_made_as_transcribe_a_recording_is():
    flow, model = _flow("screenplay-describe-recording"), _flow("screenplay-transcribe")
    assert BLUEPRINTS["screenplay-describe-recording"]["name"] == "Screenplay: describe a recording"
    (given,) = flow["trigger"]["inputs"]
    assert flow["trigger"]["type"] == model["trigger"]["type"] == "manual"
    assert given == {"name": "asset", "label": "Recording (the audio or video asset's slug or id)", "type": "text", "required": True}
    (act,) = flow["actions"]
    assert {k: v for k, v in act.items() if k not in ("title", "data")} == {k: v for k, v in model["actions"][0].items() if k not in ("title", "data")}
    assert act["data"] == {"kind": "describe-video", "args": {"asset": "${input.asset}"}, "status": "queued"}


def test_studio_describes_no_upload_by_itself():
    """v229's `screenplay-describe-recording-uploaded` is dropped (Media package design, Decision 4): the Media
    package's upload workflow describes a person's new recording, and two owners would look at each file twice. No Studio workflow listens for an
    upload; a workspace that had v229 keeps the workflow (a package update deletes nothing), switched off as it arrived."""
    assert "screenplay-describe-recording-uploaded" not in BLUEPRINTS
    on_upload = [slug for slug, b in BLUEPRINTS.items() if b["kind"] == "workflow" and (b["payload"]["definition"].get("trigger") or {}).get("event") == "asset_uploaded"]
    assert on_upload == []


def test_the_new_workflows_pass_marvins_own_check():
    validation = pytest.importorskip("marvin.services.automation.validation")
    for slug in ("screenplay-describe-recording", "screenplay-make-transcript"):
        assert validation.structural_issues(_flow(slug)) == [], slug


# ── a Transcript's recording ─────────────────────────────────────────────────
def test_a_transcript_points_at_its_recording_by_the_id_the_job_reports():
    """The Recording is an asset field, which keeps only an id: Marvin drops a slug there and the field comes out empty. The transcribe job
    reports the id (`source_id`) and the name whichever it was started with, and the workflow writes those."""
    (make, _mark) = _flow("screenplay-make-transcript")["actions"]
    assert make["data"]["source"] == "${entry.data.result.source_id}" and "args.audio" not in json.dumps(make)
    assert "result.source_name" in make["title"]
    source = next(f for f in BLUEPRINTS["transcript"]["payload"]["schema_json"]["fields"] if f["key"] == "source")
    assert source["type"] == "asset"
