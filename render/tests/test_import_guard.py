"""One Fountain job per story at a time, a preview that says it made nothing, and an import that keeps what a person changed while it ran."""

import json

import pytest
from marvin_worker.jobs import Context

from storyrender import jobs
from tests.test_fountain import THREE, CastingMarvin

ASKED = "2026-11-13T18:39:14Z"  # when the job being run was asked for


class JobsMarvin(CastingMarvin):
    """CastingMarvin that also holds `job` records (with the times Marvin stamps on every entry), found by slug or by kind."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.jobs: dict[str, dict] = {}

    def job(self, slug, kind, story, status, created, updated=None, **data):
        self.jobs[slug] = {
            "id": f"id-{slug}", "slug": slug, "title": f"Job {slug}", "createdAt": created, "updateAt": updated or created,
            "dataJson": {"kind": kind, "status": status, "args": {"story": story}, **data},
        }  # fmt: skip

    def request(self, creds, path, *, method="GET", data=None, **kw):
        out = super().request(creds, path, method=method, data=data, **kw)
        if method == "POST" and path == "/api/platform/entries":  # a real server keeps what it is sent: a second run finds it there
            m = json.loads(data)
            kind = {"T-cast": "cast-member", "T-scene": "scene", "T-sound": "sound"}.get(m["entryTypeId"])
            (self.on_hand[kind] if kind else self.records)[m["slug"]] = {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]}
        return out

    def query(self, creds, spec, limit=100):
        if "entries" in spec and spec["entries"] in self.jobs:
            return [self.jobs[spec["entries"]]]
        if spec.get("entry_type") == "job":
            rows = [r for r in self.jobs.values() if r["dataJson"]["kind"] == spec["data"]["kind"]]
            return sorted(rows, key=lambda r: r["createdAt"], reverse=True)[:limit]
        return super().query(creds, spec, limit)


@pytest.fixture
def jobs_marvin(monkeypatch, tmp_path):
    def make(screenplay=THREE):
        fake = JobsMarvin("", {})
        fake.story["dataJson"]["fountain"] = screenplay
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        return fake, Context(creds=("http://m", "tok"), work=tmp_path, name="import-2")

    return make


def _import(ctx, **args):
    return jobs.import_beats({"job": "import-2", "args": {"story": "s", **args}}, ctx)


def _check(ctx):
    return jobs.check_fountain({"job": "check-2", "args": {"story": "s"}}, ctx)


# --- the guard -------------------------------------------------------------------------------------------------------------------------


def test_an_import_asked_for_while_another_was_working_on_the_story_is_skipped_once_its_turn_comes(jobs_marvin):
    """The runner takes one job at a time, so the second press waits behind the first and runs after it is done: it must still do nothing."""
    fake, ctx = jobs_marvin()
    fake.job("import-1", "import-beats", "s", "done", "2026-11-13T18:39:10Z", "2026-11-13T18:52:42Z", claimed_at="2026-11-13T18:39:11+00:00", result={"beats_made": 597})
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    done = _import(ctx)
    assert fake.made == [] and fake.patched == []  # nothing made and the story is not touched
    said = done["log"]
    first = said.splitlines()[0]
    assert first == "Skipped: import-1 already had s (started 2026-11-13 18:39 UTC, done 18:52 UTC); nothing was done." and "Traceback" not in said
    assert done["result"]["skipped"] is True and done["result"]["already"] == "import-1" and done["result"]["summary"] == said.splitlines()[0]


def test_an_import_is_skipped_while_another_for_the_story_is_still_running_or_waiting(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("import-1", "import-beats", "s", "running", "2026-11-13T18:39:10Z", "2026-11-13T18:39:11Z", claimed_at="2026-11-13T18:39:11+00:00")
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    assert _import(ctx)["result"]["skipped"] is True and fake.made == []
    fake.job("import-1", "import-beats", "s", "queued", "2026-11-13T18:39:10Z")  # two workers: the older one has not started yet
    done = _import(ctx, dry_run="yes")  # a preview is skipped the same way
    assert done["result"]["skipped"] is True and "waiting" in done["log"] and fake.patched == []


def test_an_import_for_another_story_is_not_blocked(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("import-1", "import-beats", "other-story", "running", "2026-11-13T18:39:10Z", claimed_at="2026-11-13T18:39:11+00:00")
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    done = _import(ctx)
    assert not done["result"].get("skipped") and len(done["result"]["chapters_made"]) == 3 and fake.made


def test_a_job_that_ended_before_this_one_was_asked_for_or_failed_or_was_left_behind_blocks_nothing(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("import-0", "import-beats", "s", "done", "2026-11-13T18:30:00Z", "2026-11-13T18:31:00Z")  # finished before: an ordinary second run
    fake.job("import-1", "import-beats", "s", "failed", "2026-11-13T18:39:00Z", "2026-11-13T18:40:00Z")  # failed: running again is the point
    fake.job("import-x", "import-beats", "s", "running", "2026-11-12T09:00:00Z", "2026-11-12T09:00:05Z")  # a worker that stopped a day ago
    fake.job("import-3", "import-beats", "s", "queued", "2026-11-13T18:40:00Z")  # asked for after this one: it waits for this one, not the other way round
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    assert not _import(ctx)["result"].get("skipped") and fake.made


def test_a_skipped_job_is_not_the_one_named_as_working(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("import-1", "import-beats", "s", "done", "2026-11-13T18:39:10Z", "2026-11-13T18:52:42Z", claimed_at="2026-11-13T18:39:11+00:00")
    fake.job("import-15", "import-beats", "s", "done", "2026-11-13T18:39:12Z", "2026-11-13T18:52:50Z", result={"skipped": True})
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    assert _import(ctx)["result"]["already"] == "import-1"


def test_a_check_of_the_fountain_is_skipped_while_another_check_of_the_story_works_and_a_check_of_another_story_is_not(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("check-1", "check-fountain", "s", "running", "2026-11-13T18:39:10Z", claimed_at="2026-11-13T18:39:11+00:00")
    fake.job("check-2", "check-fountain", "s", "running", ASKED)
    done = _check(ctx)
    assert done["result"]["skipped"] is True and "check-1" in done["log"] and fake.patched == []
    fake.jobs["check-1"]["dataJson"]["args"]["story"] = "other-story"
    done = _check(ctx)
    assert not done["result"].get("skipped") and done["result"]["report"] and [p[0] for p in fake.patched] == ["e0"]


def test_an_import_running_does_not_stop_a_check_and_a_job_with_no_record_is_not_guarded(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.job("import-1", "import-beats", "s", "running", "2026-11-13T18:39:10Z", claimed_at="2026-11-13T18:39:11+00:00")
    fake.job("check-2", "check-fountain", "s", "running", ASKED)
    assert not _check(ctx)["result"].get("skipped")
    assert not jobs.import_beats({"job": "run-by-hand", "args": {"story": "s"}}, ctx)["result"].get("skipped")  # no record to compare with: it runs


# --- the preview -----------------------------------------------------------------------------------------------------------------------


def test_a_preview_says_it_made_nothing_and_names_what_it_would_make_not_what_it_made(jobs_marvin):
    fake, ctx = jobs_marvin()
    done = _import(ctx, dry_run="yes")
    r = done["result"]
    assert fake.made == [] and r["dry_run"] is True
    assert r["summary"].startswith("Preview only: nothing was made.") and "would make" in r["summary"] and "3 chapters" in r["summary"]
    assert not [k for k in r if k.endswith("_made")] and r["beats_to_make"] > 0 and len(r["chapters_to_make"]) == 3
    assert ctx.notes[0].endswith("Preview only: nothing was made.")  # the first line of the job's log, which the Workers page shows
    plan = [p for p in fake.patched if p[0] == "e0"][0][1]["dataJson"]["split_plan"]
    assert "Preview only: nothing was made" in plan.splitlines()[0]


def test_an_import_says_what_it_made_in_one_line(jobs_marvin):
    fake, ctx = jobs_marvin()
    r = _import(ctx)["result"]
    assert r["summary"].startswith("Made ") and "3 chapters" in r["summary"] and r["beats_made"] > 0 and "Preview" not in r["summary"]
    again = _import(ctx)["result"]  # nothing new: the second run says so instead of reading like an import
    assert again["summary"].startswith("Nothing new")


# --- the story is read again before it is written --------------------------------------------------------------------------------------


def test_an_edit_made_to_the_story_while_the_import_ran_is_kept(jobs_marvin):
    fake, ctx = jobs_marvin()
    fake.story["dataJson"]["sheet_log"] = "2026-11-01 · add · earlier"
    sent = fake.request

    def request(creds, path, *, method="GET", data=None, **kw):
        if method == "POST" and path == "/api/platform/entries" and "premise" not in fake.story["dataJson"]:  # a person saves the story mid-import
            fake.story = {**fake.story, "title": "Renamed", "dataJson": {**fake.story["dataJson"], "premise": "Written while it ran.", "setting": "Mine.", "sheet_log": "2026-11-01 · add · earlier\n2026-11-13 · by hand"}}
        return sent(creds, path, method=method, data=data, **kw)

    jobs.marvin_api.request = request  # monkeypatched already by the fixture, so it is put back after the test
    _import(ctx)
    story = [p[1] for p in fake.patched if p[0] == "e0"]
    assert len(story) == 1
    kept = story[0]["dataJson"]
    assert kept["premise"] == "Written while it ran." and kept["setting"] == "Mine." and story[0]["title"] == "Renamed"
    assert kept["sheet_log"].startswith("2026-11-01 · add · earlier\n2026-11-13 · by hand\n") and "from the Fountain" in kept["sheet_log"]
    assert "3 chapters" in kept["split_plan"]
