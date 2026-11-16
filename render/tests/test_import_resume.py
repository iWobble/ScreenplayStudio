"""An import that loses the line to Marvin partway (a 13-minute feature, one dropped connection) is run again and carries on: it makes only
what is missing, under the numbers a run that never stopped would have used, and the failure says so in one line."""

import pytest
from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError

from storyrender import jobs
from tests.test_import_guard import ASKED, JobsMarvin, _clock  # noqa: F401  (_clock: the guard reads the time)

STORY = """# 01 The reef

EXT. THE REEF - NIGHT

ANN (30s) holds the wheel. BOB (40s) bails water.

ANN
Hold her straight!

BOB
The hull is groaning!

===

The mast cracks.

ANN
Down!

INT. CABIN - NIGHT

Lamps swing.

BOB
We're through.

# 02 The shore

EXT. BEACH - DAWN

Calm water.

ANN
Land.

===

BOB
Told you.
"""


class Shaky(JobsMarvin):
    """JobsMarvin that finds any record it holds by slug, and drops the line for good after `fail_after` creates, as the runner's did."""

    fail_after: "int | None" = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.creates = 0

    def every(self) -> dict:
        return {**self.records, **{s: r for kind in self.on_hand.values() for s, r in kind.items()}}

    def query(self, creds, spec, limit=100):
        if "entries" in spec and spec["entries"] in self.every():
            return [self.every()[spec["entries"]]]
        return super().query(creds, spec, limit)

    def request(self, creds, path, *, method="GET", data=None, **kw):
        if method == "POST" and path == "/api/platform/entries":
            if self.fail_after is not None and self.creates >= self.fail_after:
                raise marvin_api.MarvinUnreachable("can't reach Marvin ([SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol) after 6 attempts")
            self.creates += 1
        return super().request(creds, path, method=method, data=data, **kw)


@pytest.fixture
def shaky(monkeypatch, tmp_path):
    fake = Shaky("", {})
    fake.story["dataJson"]["fountain"] = STORY
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
    monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
    return fake


def _run(fake, tmp_path, **args):
    ctx = Context(creds=("http://m", "tok"), work=tmp_path, name="import-2")
    return jobs.import_beats({"job": "import-2", "args": {"story": "s", **args}}, ctx), ctx


def _story_now(fake) -> dict:
    """The story as the import last wrote it."""
    return next((p[1]["dataJson"] for p in reversed(fake.patched) if p[0] == "e0"), fake.story["dataJson"])


def _clean(tmp_path, monkeypatch) -> tuple[dict, dict]:
    fake = Shaky("", {})
    fake.story["dataJson"]["fountain"] = STORY
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    with monkeypatch.context() as m:
        m.setattr(jobs.marvin_api, "query", fake.query)
        m.setattr(jobs.marvin_api, "request", fake.request)
        _run(fake, tmp_path)
    return {s: r["dataJson"] for s, r in fake.every().items()}, _story_now(fake)


def test_an_import_that_lost_the_line_partway_is_finished_by_running_it_again(shaky, tmp_path, monkeypatch):
    want, story_after = _clean(tmp_path, monkeypatch)
    total = len(want)
    assert any("-line-" in s for s in want) and "s-score" in want and story_after["music"] == "s-score"
    for stop in (1, 4, total // 2, total - 1):  # in the characters and scenes, among the beats, among the lines, at the last record
        fake = Shaky("", {})
        fake.story["dataJson"]["fountain"] = STORY
        fake.job("import-2", "import-beats", "s", "running", ASKED)
        monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
        monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
        fake.fail_after = stop
        with pytest.raises(JobError) as failed:
            _run(fake, tmp_path)
        first = str(failed.value).splitlines()[0]
        assert first == f"lost the connection to Marvin after {stop} records. Run Bring these chapters in again: it carries on from where it stopped."
        summary = [p[1]["dataJson"]["result"]["summary"] for p in fake.patched if p[0] == "id-import-2"]
        assert summary == ["Failed: " + first]  # where the Workers page shows it
        assert "UNEXPECTED_EOF" in str(failed.value)  # the reason is still in the log
        fake.fail_after = None
        done, ctx = _run(fake, tmp_path)
        now = {s: r["dataJson"] for s, r in fake.every().items()}
        assert set(now) == set(want), stop  # the rest made, nothing twice, and no beat numbered after the last made (1002a)
        assert all(now[s] == want[s] for s in now if "-beat-" in s or "-line-" in s)
        assert _story_now(fake)["music"] == "s-score"  # the score made before the stop is the story's music
        assert done["result"]["summary"].startswith("Done: made ")
        if stop > 4:  # the beats made before the stop were there
            assert any(n.endswith(" records already there") and "Carrying on: " in n for n in ctx.notes)


def test_a_chapter_brought_in_after_another_takes_its_own_numbers(shaky, tmp_path):
    _run(shaky, tmp_path, part="1")
    _run(shaky, tmp_path, part="2")
    beats = sorted(s for s in shaky.records if "-beat-" in s)
    assert beats == ["s-beat-1001", "s-beat-1002", "s-beat-1003", "s-beat-2001", "s-beat-2002"]


def test_a_revised_fountain_is_still_fitted_to_what_was_made(shaky, tmp_path):
    _run(shaky, tmp_path)
    shaky.story["dataJson"]["fountain"] = STORY.replace("The mast cracks.", "A wave hits.\n\n===\n\nThe mast cracks.")
    done, _ctx = _run(shaky, tmp_path)
    assert "s-beat-1001a" in shaky.records and done["result"]["revision"]["new"] == ["1001a"]


def test_a_failure_before_anything_was_written_says_so(shaky, tmp_path):
    shaky.fail_after = 0
    with pytest.raises(JobError, match=r"^lost the connection to Marvin before it wrote anything\. Run Bring these chapters in again"):
        _run(shaky, tmp_path)
    with pytest.raises(JobError, match=r"^lost the connection to Marvin before it wrote anything\. Run it again\.\n"):
        _lost_reading(shaky, tmp_path)


def _lost_reading(fake, tmp_path):
    """A preview writes no records: the line lost while it reads is said with a plain "run it again"."""
    def gone(creds, spec, limit=100):
        raise marvin_api.MarvinUnreachable("can't reach Marvin (timed out) after 6 attempts")

    jobs.marvin_api.query = gone
    _run(fake, tmp_path, dry_run="yes")


def test_a_request_marvin_refused_is_not_called_a_lost_connection(shaky, tmp_path):
    def refuse(creds, path, *, method="GET", data=None, **kw):
        if method == "POST" and path == "/api/platform/entries":
            raise marvin_api.MarvinError("Marvin answered 422 for /api/platform/entries: bad data")
        return JobsMarvin.request(shaky, creds, path, method=method, data=data, **kw)

    jobs.marvin_api.request = refuse  # monkeypatched already by the fixture, so it is put back after the test
    with pytest.raises(marvin_api.MarvinError, match="422") as failed:
        _run(shaky, tmp_path)
    assert "lost the connection" not in str(failed.value)
    summary = [p[1]["dataJson"]["result"]["summary"] for p in shaky.patched if p[0] == "id-import-2"]
    assert summary and summary[0].startswith("Failed: MarvinError: Marvin answered 422")
