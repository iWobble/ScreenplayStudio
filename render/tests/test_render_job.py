"""The `render` kind: a story's approved stills and recorded lines made into a video, kept on the story as `video` (real ffmpeg, a placeholder project)."""

import json
import shutil
from pathlib import Path

import pytest

from marvin_worker.jobs import Context, JobError
from storyrender import demo, jobs

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


class Marvin:
    """Stands in for Marvin: pull makes the demo project, uploads and writes are recorded."""

    def __init__(self, tmp_path, monkeypatch, beats=(), old_video=None, refuse_upload=False):
        self.beats = {slug: {"id": f"id-{slug}", "slug": slug, "dataJson": {"story": "s", "status": status}} for slug, status in beats}
        self.story = {"id": "e0", "slug": "s", "dataJson": {"video": old_video}}
        self.uploads, self.updated, self.deleted = [], [], []
        self.refuse = refuse_upload
        project = demo.make(tmp_path / "demo", size=(360, 640))

        def pull(story, out, creds=None):
            return {"manifest": str(project), "shots": 3, "lines": 3, "not_recorded": []}

        monkeypatch.setattr(jobs.marvin_pull, "pull", pull)
        monkeypatch.setattr(jobs.marvin_api, "query", self.query)
        monkeypatch.setattr(jobs.marvin_api, "upload_asset", self.upload)
        monkeypatch.setattr(jobs.marvin_api, "update_entry", self.update)
        monkeypatch.setattr(jobs.marvin_api, "request", self.request)

    def query(self, creds, spec, limit=100):
        if "entries" in spec:
            return [self.story]
        return list(self.beats.values())

    def upload(self, creds, file, **kw):
        if self.refuse:
            raise jobs.marvin_api.MarvinError("413 too large")
        self.uploads.append((Path(file).name, Path(file).stat().st_size, kw))
        return {"id": "asset-new", "publicUrl": "https://assets.example/v.mp4"}

    def update(self, creds, slug, changes):
        self.updated.append((slug, changes))
        if slug in self.beats:
            self.beats[slug]["dataJson"].update(changes)
        return {}

    def request(self, creds, path, **kw):
        self.deleted.append((path, kw.get("method")))
        return b"{}"


def _ctx(tmp_path):
    return Context(creds=("http://m", "tok"), work=tmp_path / "work", name="render-1")


@needs_ffmpeg
def test_it_renders_uploads_a_preview_copy_and_puts_it_on_the_story(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch, old_video="asset-old")
    (tmp_path / "work").mkdir()
    done = jobs.render_video({"job": "render-1", "args": {"story": "s"}}, _ctx(tmp_path))
    (name, size, meta), = marvin.uploads
    assert name == "render-1-preview.mp4" and meta["mime"] == "video/mp4" and meta["slug"] == "render-1-video" and meta["metadata"]["quality"] == "preview"
    assert ("s", {"video": "asset-new"}) in marvin.updated and ("/api/platform/assets/asset-old", "DELETE") in marvin.deleted  # the old copy goes to the Trash
    assert done["result"]["video"] == "asset-new" and done["result"]["quality"] == "preview" and done["result"]["seconds"] > 3


@needs_ffmpeg
def test_the_full_quality_file_is_kept_in_the_output_folder_when_one_is_set(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("STUDIO_OUT_DIR", str(out))
    Marvin(tmp_path, monkeypatch)
    (tmp_path / "work").mkdir()
    done = jobs.render_video({"job": "render-1", "args": {"story": "s"}}, _ctx(tmp_path))
    kept = Path(done["result"]["kept"])
    assert kept == out / "s-render-1.mp4" and kept.is_file() and kept.stat().st_size > 0
    assert "Full-quality file" in done["log"]


@needs_ffmpeg
def test_a_full_quality_copy_that_cannot_be_kept_does_not_fail_the_render(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the output folder should be")
    monkeypatch.setenv("STUDIO_OUT_DIR", str(blocker / "out"))
    marvin = Marvin(tmp_path, monkeypatch)
    (tmp_path / "work").mkdir()
    ctx = _ctx(tmp_path)
    done = jobs.render_video({"job": "render-1", "args": {"story": "s"}}, ctx)
    assert done["result"]["video"] == "asset-new" and done["result"]["kept"] == "" and marvin.uploads
    assert any("could not keep the full-quality file" in n for n in ctx.notes)


@needs_ffmpeg
def test_quality_full_uploads_the_full_file_and_says_so(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch)
    (tmp_path / "work").mkdir()
    done = jobs.render_video({"job": "render-1", "args": {"story": "s", "quality": "full"}}, _ctx(tmp_path))
    assert marvin.uploads[0][0] == "render-1.mp4" and done["result"]["quality"] == "full"


@needs_ffmpeg
def test_approve_beats_marks_every_unapproved_beat_first(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch, beats=[("s-beat-01", "made"), ("s-beat-02", "approved"), ("s-beat-03", "draft")])
    (tmp_path / "work").mkdir()
    ctx = _ctx(tmp_path)
    jobs.render_video({"job": "render-1", "args": {"story": "s", "approve_beats": "yes"}}, ctx)
    assert {s for s, c in marvin.updated if c == {"status": "approved"}} == {"s-beat-01", "s-beat-03"}  # the approved one is left alone
    assert all(b["dataJson"]["status"] == "approved" for b in marvin.beats.values()) and any("marked 2 beats approved" in n for n in ctx.notes)


@needs_ffmpeg
def test_beats_are_left_as_they_are_unless_asked(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch, beats=[("s-beat-01", "made")])
    (tmp_path / "work").mkdir()
    jobs.render_video({"job": "render-1", "args": {"story": "s"}}, _ctx(tmp_path))
    assert marvin.beats["s-beat-01"]["dataJson"]["status"] == "made"


@needs_ffmpeg
def test_an_upload_marvin_refuses_says_where_the_full_file_is(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_OUT_DIR", str(tmp_path / "out"))
    Marvin(tmp_path, monkeypatch, refuse_upload=True)
    (tmp_path / "work").mkdir()
    with pytest.raises(JobError, match=r"would not take the upload.*s-render-1\.mp4"):
        jobs.render_video({"job": "render-1", "args": {"story": "s", "quality": "full"}}, _ctx(tmp_path))


def test_it_declares_its_contract():
    from marvin_worker.jobs import META

    meta = META["render"]
    assert meta["inputs"]["story"]["required"] and not meta["inputs"]["quality"]["required"] and "video/mp4" in meta["produces"] and "ffmpeg" in meta["needs"]
