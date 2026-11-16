"""A story brought in a few chapters at a time makes the Characters of those chapters only: whoever speaks in them. Handles are the whole
script's, so a chapter brought in later makes the rest under the names a whole import gives, and a beat is cast only with Characters there."""

from marvin_worker.jobs import Context

from storyrender import jobs
from tests.test_import_guard import ASKED, _clock  # noqa: F401  (_clock: the guard reads the time)
from tests.test_import_resume import Shaky, _story_now

STORY = """# 01 The reef

EXT. THE REEF - NIGHT

ANN (30s) holds the wheel. MRS HALE (60s), a stern woman, bails water. DEE watches from the cliff.

ANN
Hold her straight!

MRS HALE
The hull is groaning!

NARRATOR
They were far from home.

# 02 The shore

EXT. BEACH - DAWN

DR HALE (50s) waits on the sand.

DR HALE
Land.

DEE
Told you.

ANN
Home.
"""

CH1 = {"s-ann", "s-mrs-hale", "s-narrator"}
EVERYONE = CH1 | {"s-dr-hale", "s-dee"}


def _fake(monkeypatch) -> Shaky:
    fake = Shaky("", {})
    fake.story["dataJson"]["fountain"] = STORY
    fake.job("import-2", "import-beats", "s", "running", ASKED)
    monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
    monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
    return fake


def _run(tmp_path, **args) -> dict:
    ctx = Context(creds=("http://m", "tok"), work=tmp_path, name="import-2")
    return jobs.import_beats({"job": "import-2", "args": {"story": "s", **args}}, ctx)


def _cast(fake) -> dict:
    return {s: r["dataJson"] for s, r in fake.on_hand["cast-member"].items()}


def test_a_part_makes_only_the_characters_who_speak_in_it(monkeypatch, tmp_path):
    fake = _fake(monkeypatch)
    done = _run(tmp_path, part="1")
    assert set(_cast(fake)) == CH1  # not Dee or Dr Hale, who speak only in chapter 2
    assert set(done["result"]["characters_made"]) == CH1
    assert _cast(fake)["s-mrs-hale"]["speaker"] == "mrs-hale"  # Dr Hale (chapter 2) still sets the handle apart, as a whole import does
    summary = done["result"]["summary"]
    assert "3 characters (the speakers of chapter 1)" in summary and summary.startswith("Done: made ")
    assert "+3 characters (the speakers of chapter 1)" in _story_now(fake)["sheet_log"]
    beats = {s: r["dataJson"] for s, r in fake.records.items() if "-beat-" in s}
    assert beats and all(s.startswith("s-beat-1") for s in beats)
    reef = next(d for d in beats.values() if "DEE watches" in d.get("fountain", ""))
    assert reef["cast"].split(",") == ["s-ann", "s-mrs-hale"]  # Dee is named, but has no Character yet: the cast names only Characters there
    every_cast = {c for d in beats.values() for c in str(d.get("cast") or "").split(",") if c}
    lines = [r["dataJson"] for s, r in fake.records.items() if "-line-" in s]
    assert every_cast <= set(_cast(fake)) and {ln["character"] for ln in lines} <= set(_cast(fake))
    assert set(fake.on_hand["scene"]) == {"s-the-reef"}  # scenes and sounds were already the chapter's own
    assert not any(s.startswith("s-sound-2") for s in fake.on_hand["sound"])


def test_the_next_part_adds_the_rest_as_a_whole_import_would_and_a_rerun_makes_nothing(monkeypatch, tmp_path):
    whole = _fake(monkeypatch)
    _run(tmp_path)
    fake = _fake(monkeypatch)
    _run(tmp_path, part="1")
    before = _cast(fake)
    done = _run(tmp_path, part="2")
    assert set(done["result"]["characters_made"]) == {"s-dr-hale", "s-dee"}  # Ann speaks in chapter 2 too, and is already there
    assert "2 characters (the speakers of chapter 2)" in done["result"]["summary"]
    assert _cast(fake) == _cast(whole)  # the same slugs, handles and descriptions as bringing it all in at once
    assert all(_cast(fake)[s] == d for s, d in before.items())  # chapter 1's are left as they were
    creates = fake.creates
    again = _run(tmp_path, part="2")
    assert fake.creates == creates and again["result"]["characters_made"] == []
    assert again["result"]["summary"].startswith("Nothing new")


def test_a_whole_import_makes_every_speaker_as_before(monkeypatch, tmp_path):
    fake = _fake(monkeypatch)
    done = _run(tmp_path)
    assert set(_cast(fake)) == EVERYONE and set(done["result"]["characters_made"]) == EVERYONE
    assert "5 characters, " in done["result"]["summary"]
    assert "the speakers of" not in done["log"]
    reef = next(r["dataJson"] for s, r in fake.records.items() if "-beat-" in s and "DEE watches" in r["dataJson"].get("fountain", ""))
    assert reef["cast"].split(",") == ["s-ann", "s-mrs-hale", "s-dee"]


def test_a_part_casts_a_character_the_story_already_has(monkeypatch, tmp_path):
    fake = _fake(monkeypatch)
    _run(tmp_path, part="2")  # Dee is made with chapter 2
    _run(tmp_path, part="1")
    reef = next(r["dataJson"] for s, r in fake.records.items() if "-beat-" in s and "DEE watches" in r["dataJson"].get("fountain", ""))
    assert reef["cast"].split(",") == ["s-ann", "s-mrs-hale", "s-dee"]
    assert set(_cast(fake)) == EVERYONE


def test_a_preview_of_a_part_says_which_characters_it_would_make(monkeypatch, tmp_path):
    fake = _fake(monkeypatch)
    done = _run(tmp_path, part="1", dry_run="yes")
    assert set(done["result"]["characters_to_make"]) == CH1 and fake.on_hand["cast-member"] == {}
    assert "It would make " in done["result"]["summary"] and "3 characters (the speakers of chapter 1)" in done["result"]["summary"]
