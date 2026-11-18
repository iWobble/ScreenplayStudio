"""Looks at some beats (a render with `beats`) pile up as their own video files: after a new one is uploaded, the story's older looks beyond the
newest three go to the Trash. Never the story's video, a whole-story render or another story's look, and a failed trash never fails the job."""

import json

import pytest

from marvin_worker.jobs import Context
from storyrender import jobs, looks
from tests.test_render_job import Marvin, _ctx, needs_ffmpeg


def _look(asset_id, story="s", beats="3", kind="video"):
    meta = {"kind": kind, "story": story, "quality": "draft", **({"beats": beats} if beats else {})}
    return {"id": asset_id, "name": f"{story}: video (draft of beat {beats})", "metadataJson": meta}


class Library:
    """Only what the tidy-up asks of Marvin: the story's record, the library listing (newest first) and DELETE."""

    def __init__(self, monkeypatch, assets, story_data=None, refuse=(), list_fails=False):
        self.assets, self.story_data, self.refuse, self.list_fails = assets, story_data or {}, set(refuse), list_fails
        self.trashed, self.listed = [], []
        monkeypatch.setattr(looks.marvin_api, "query", lambda creds, spec, limit=100: [{"slug": "s", "dataJson": self.story_data}])
        monkeypatch.setattr(looks.marvin_api, "request", self.request)

    def request(self, creds, path, **kw):
        if kw.get("method") != "DELETE":
            self.listed.append(path)
            if self.list_fails:
                raise looks.marvin_api.MarvinError("502 bad gateway")
            return json.dumps(self.assets).encode()
        asset_id = path.rsplit("/", 1)[-1]
        if asset_id in self.refuse:
            raise looks.marvin_api.MarvinError("503 busy")
        self.trashed.append(asset_id)
        return b"{}"


def _context(tmp_path):
    return Context(creds=("http://m", "tok"), work=tmp_path, name="render-9")


def test_five_old_looks_and_a_new_one_keep_the_newest_three_and_trash_the_oldest_three(tmp_path, monkeypatch):
    lib = Library(monkeypatch, [_look("new"), *(_look(f"old-{n}") for n in range(1, 6))])  # newest first: old-1 is the newest old one
    ctx = _context(tmp_path)
    assert looks.trash_old_looks(ctx, "s", "new") == 3
    assert lib.trashed == ["old-3", "old-4", "old-5"]
    assert "asset_type=video" in lib.listed[0] and "sort=newest" in lib.listed[0]
    assert any("put 3 older looks at some beats in the Trash" in n for n in ctx.notes)


def test_another_storys_looks_a_whole_story_video_and_the_storys_current_video_are_never_trashed(tmp_path, monkeypatch):
    others = [_look(f"t-{n}", story="t") for n in range(5)]
    full = [{"id": f"full-{n}", "metadataJson": {"kind": "video", "story": "s", "quality": "preview"}} for n in range(5)]  # no `beats`
    lib = Library(monkeypatch, [_look("new"), *others, *full, _look("current"), _look("old-1"), _look("old-2"), _look("old-3")], story_data={"video": "current"})
    assert looks.trash_old_looks(_context(tmp_path), "s", "new") == 1
    assert lib.trashed == ["old-3"]


def test_a_trash_that_fails_is_noted_and_the_rest_still_go(tmp_path, monkeypatch):
    lib = Library(monkeypatch, [_look("new"), *(_look(f"old-{n}") for n in range(1, 6))], refuse={"old-4"})
    ctx = _context(tmp_path)
    assert looks.trash_old_looks(ctx, "s", "new") == 2
    assert lib.trashed == ["old-3", "old-5"]
    assert any("could not put 1 older look in the Trash: old-4" in n for n in ctx.notes)


def test_a_listing_that_fails_is_noted_and_nothing_is_trashed(tmp_path, monkeypatch):
    lib = Library(monkeypatch, [_look("new"), _look("old-1")], list_fails=True)
    ctx = _context(tmp_path)
    assert looks.trash_old_looks(ctx, "s", "new") == 0 and lib.trashed == []
    assert any("could not look for older looks" in n for n in ctx.notes)


@pytest.mark.parametrize(("field", "kept"), [(None, 3), ("5", 5), (1, 1), ("0", 1), ("lots", 3)])
def test_the_story_may_keep_more_or_fewer_but_always_the_new_one(field, kept):
    assert looks.keep_count({} if field is None else {"keep_partial_drafts": field}) == kept


@needs_ffmpeg
def test_a_look_at_some_beats_trashes_the_older_looks_and_a_trash_failure_does_not_fail_the_render(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch, old_video="asset-old")
    marvin.assets = [_look("asset-new"), *(_look(f"old-{n}") for n in range(1, 6)), _look("asset-old"), _look("t-1", story="t")]
    marvin.refuse_trash = {"old-5"}
    (tmp_path / "work").mkdir()
    ctx = _ctx(tmp_path)
    done = jobs.render_video({"job": "render-1", "args": {"story": "s", "beats": "3"}}, ctx)
    assert marvin.deleted == [("/api/platform/assets/old-3", "DELETE"), ("/api/platform/assets/old-4", "DELETE")]  # never the story's video
    assert done["result"]["beats"] == "3" and done["result"]["video"] == "asset-new"
    assert any("put 2 older looks" in n for n in ctx.notes) and any("could not put 1 older look in the Trash: old-5" in n for n in ctx.notes)


@needs_ffmpeg
def test_a_whole_story_render_never_looks_for_looks(tmp_path, monkeypatch):
    marvin = Marvin(tmp_path, monkeypatch)
    marvin.assets = [_look(f"old-{n}") for n in range(1, 6)]
    (tmp_path / "work").mkdir()
    jobs.render_video({"job": "render-1", "args": {"story": "s"}}, _ctx(tmp_path))
    assert not any("old-" in path for path, _ in marvin.deleted)
