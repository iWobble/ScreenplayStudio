"""`time-words`: the times of a recording's words fitted onto the line's own written words, and the job that writes them to the recording."""

import json
from types import SimpleNamespace

import pytest

from marvin_worker.jobs import META, Context, JobError
from storytranscribe import align, jobs


def _heard(*pairs):
    return [{"text": t, "start": s, "end": e} for t, s, e in pairs]


def test_written_words_take_the_times_of_the_heard_words_they_match_and_keep_the_authors_spelling():
    heard = _heard(("Your", 0.0, 0.3), ("feast", 0.4, 0.9), ("make", 1.2, 1.5), ("do", 1.5, 1.9))
    got = align.script_times("Your feast. Make do.", heard)
    assert [(w["text"], w["start"], w["end"]) for w in got] == [("Your", 0.0, 0.3), ("feast.", 0.4, 0.9), ("Make", 1.2, 1.5), ("do.", 1.5, 1.9)]  # punctuation and case are the author's


def test_a_misheard_word_is_still_given_a_place_between_its_neighbours_by_its_length():
    heard = _heard(("The", 0.0, 0.2), ("capting", 0.3, 0.9), ("ordered", 1.0, 1.4), ("a", 1.4, 1.5), ("feast", 1.5, 2.0))  # "captain" heard as "capting": no match
    got = align.script_times("The captain ordered a feast.", heard)
    assert [w["text"] for w in got] == ["The", "captain", "ordered", "a", "feast."]
    captain = got[1]
    assert captain["start"] == pytest.approx(0.2) and captain["end"] == pytest.approx(1.0)  # the gap between "The" and "ordered"
    assert all(a["end"] <= b["start"] + 1e-9 for a, b in zip(got, got[1:], strict=False))  # in order, never overlapping


def test_a_word_heard_but_not_written_is_left_out_and_one_written_but_not_heard_is_placed():
    heard = _heard(("well", 0.0, 0.3), ("make", 0.5, 0.8), ("do", 0.8, 1.1))
    got = align.script_times("Make do.", heard)
    assert [(w["text"], w["start"]) for w in got] == [("Make", 0.5), ("do.", 0.8)]  # the "well" that was said is not shown
    tail = align.script_times("Make do now.", heard)
    assert tail[2]["text"] == "now." and tail[2]["start"] == pytest.approx(1.1) and tail[2]["end"] >= tail[2]["start"]  # after the last heard word


def test_nothing_heard_gives_nothing_and_no_script_gives_the_heard_words():
    assert align.script_times("Make do.", []) == [] and align.script_times("Make do.", _heard(("", 0, 1))) == []
    assert [w["text"] for w in align.script_times("", _heard(("Hello", 0.0, 0.5), ("there", 0.6, 1.0)))] == ["Hello", "there"]


def test_nothing_matching_at_all_spreads_the_written_words_over_what_was_heard():
    got = align.script_times("alpha beta", _heard(("xx", 1.0, 1.5), ("yy", 1.5, 2.0)))
    assert got[0]["start"] == pytest.approx(1.0) and got[-1]["end"] == pytest.approx(2.0) and got[0]["end"] <= got[1]["start"] + 1e-9


class _Model:
    def __init__(self, words):
        self.words = words
        self.kw = {}

    def transcribe(self, path, **kw):
        self.kw = kw
        seg = SimpleNamespace(words=[SimpleNamespace(word=f" {t}", start=s, end=e) for t, s, e in self.words])
        return iter([seg]), SimpleNamespace(language="en", language_probability=0.99, duration=2.0)


def _ctx(tmp_path):
    return Context(creds=("http://m", "tok"), work=tmp_path, name="time-words-1")


def _wire(monkeypatch, entry, line=None, patched=None):
    def query(creds, spec, limit=100):
        slug = spec.get("entries")
        return [entry] if slug == entry["slug"] else ([line] if line and slug == line["slug"] else [])

    monkeypatch.setattr(jobs.marvin_api, "query", query)
    monkeypatch.setattr(jobs.marvin_api, "asset", lambda creds, a: {"id": "asset-1", "name": "my take", "originalFilename": "take.webm", "metadataJson": {"keep": "me"}})
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, a, dest: dest.write_bytes(b"x"))
    monkeypatch.setattr(jobs.marvin_api, "request", lambda creds, path, **kw: (patched.append((path, kw["method"], json.loads(kw["data"]))) if patched is not None else None) or b"{}")


def test_the_job_times_the_takes_words_against_its_lines_text_and_writes_them_to_the_recording(tmp_path, monkeypatch):
    patched = []
    entry = {"slug": "take-1", "dataJson": {"audio": "asset-1", "line": "story-line-01", "spoken": ""}}
    line = {"slug": "story-line-01", "dataJson": {"text": "Your feast. Make do."}}
    _wire(monkeypatch, entry, line, patched)
    model = _Model([("Your", 0.0, 0.3), ("feast", 0.4, 0.9), ("Make", 1.2, 1.5), ("do", 1.5, 1.9)])
    monkeypatch.setattr(jobs, "load_model", lambda name: model)
    done = jobs.time_words({"job": "time-words-1", "args": {"entry": "take-1"}}, _ctx(tmp_path))
    (path, method, body), = patched
    assert (path, method) == ("/api/platform/assets/asset-1", "PATCH")
    assert body["metadata"]["keep"] == "me" and body["metadata"]["words_from"] == "faster-whisper"  # the rest of the metadata is kept
    assert [(w["text"], w["start"]) for w in body["metadata"]["words"]] == [("Your", 0.0), ("feast.", 0.4), ("Make", 1.2), ("do.", 1.5)]
    assert model.kw["word_timestamps"] is True and model.kw["hotwords"] == "Your feast. Make do."  # the written words nudge the model towards the right spelling
    assert done["result"]["words"] == 4 and done["result"]["from_text"] is True


def test_a_take_with_its_own_spoken_text_uses_that_and_one_with_none_uses_what_is_heard(tmp_path, monkeypatch):
    patched = []
    _wire(monkeypatch, {"slug": "take-2", "dataJson": {"audio": "asset-1", "spoken": "Hello there"}}, patched=patched)
    monkeypatch.setattr(jobs, "load_model", lambda name: _Model([("Hello", 0.0, 0.5), ("there", 0.6, 1.0)]))
    jobs.time_words({"job": "j", "args": {"entry": "take-2"}}, _ctx(tmp_path))
    assert [w["text"] for w in patched[0][2]["metadata"]["words"]] == ["Hello", "there"]
    patched.clear()
    _wire(monkeypatch, {"slug": "take-3", "dataJson": {"audio": "asset-1"}}, patched=patched)
    done = jobs.time_words({"job": "j", "args": {"entry": "take-3"}}, _ctx(tmp_path))
    assert done["result"]["from_text"] is False and "no written text" in done["log"]


def test_a_silent_recording_a_missing_take_and_a_take_with_no_recording_each_say_so(tmp_path, monkeypatch):
    _wire(monkeypatch, {"slug": "take-1", "dataJson": {"audio": "asset-1", "spoken": "x"}})
    monkeypatch.setattr(jobs, "load_model", lambda name: _Model([]))
    with pytest.raises(JobError, match="no speech was heard"):
        jobs.time_words({"job": "j", "args": {"entry": "take-1"}}, _ctx(tmp_path))
    with pytest.raises(JobError, match="no entry"):
        jobs.time_words({"job": "j", "args": {"entry": "nothing"}}, _ctx(tmp_path))
    _wire(monkeypatch, {"slug": "take-4", "dataJson": {}})
    with pytest.raises(JobError, match="has nothing in"):
        jobs.time_words({"job": "j", "args": {"entry": "take-4"}}, _ctx(tmp_path))
    with pytest.raises(JobError, match="needs args.entry"):
        jobs.time_words({"job": "j", "args": {}}, _ctx(tmp_path))


def test_it_declares_what_it_takes():
    meta = META["time-words"]
    assert meta["inputs"]["entry"]["type"] == "string" and meta["inputs"]["language"]["required"] is False and "faster-whisper" in meta["needs"]
