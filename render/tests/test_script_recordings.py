"""The script's breakdown reads a line's length from its Recording (Media package, design P13) only when the Recording is of the very file in the
line's `audio`; otherwise, and in a workspace without Recordings, from the line's own `duration_seconds` as before."""

import pytest

from storyrender import script

S = "the-last-onion"


def _row(slug, title="", **data):
    return {"slug": slug, "title": title or slug, "dataJson": data}


def _rec(slug, asset, **data):
    return {"id": f"id-{slug}", **_row(slug, asset=asset, kind="audio", **data)}


REC = _rec("rec-a1", "a1", duration_seconds=3.0)
OTHER = _rec("rec-a9", "a9", duration_seconds=99.0)


def _records(line, recordings=None):
    out = {
        "story": _row(S, "The Last Onion"),
        "beats": [_row(f"{S}-beat-04", story=S, number="04", picture="Wide.")],
        "lines": {f"{S}-beat-04": [line]},
    }
    if recordings is not None:
        out["recordings"] = recordings
    return out


def _spoken(records) -> float:
    return script.breakdown(records)["seconds_spoken"]


def _line(**data):
    return _row("l1", story=S, beat=f"{S}-beat-04", speaker="narrator", text="The captain ordered a feast.", duration_seconds=2.5, **data)


def test_a_line_whose_recording_is_of_its_file_takes_the_recordings_length():
    assert _spoken(_records(_line(audio="a1", recording="rec-a1"), {"rec-a1": REC})) == 3.0


def test_ids_are_compared_without_case_or_spaces_and_a_field_holding_an_id_object_counts():
    assert _spoken(_records(_line(audio=" A1 ", recording="rec-a1"), {"rec-a1": REC})) == 3.0
    assert _spoken(_records(_line(audio={"id": "a1"}, recording="rec-a1"), {"rec-a1": REC})) == 3.0


@pytest.mark.parametrize(
    "line, recordings",
    [
        (_line(audio="a1", recording="rec-a9"), {"rec-a9": OTHER}),  # a pointer left on another file's Recording
        (_line(audio="a2", recording="rec-a1"), {"rec-a1": REC}),  # the file changed and the pointer has not caught up
        (_line(recording="rec-a1"), {"rec-a1": REC}),  # no file in the line any more
        (_line(audio="a1", recording="rec-a1"), {}),  # no Recording found: the workspace has no Recording type
        (_line(audio="a1", recording="rec-a1"), None),  # records made before Recordings (no `recordings` at all)
        (_line(audio="a1"), {"rec-a1": REC}),  # the line names no Recording
        (_line(audio="a1", recording="rec-a1"), {"rec-a1": _rec("rec-a1", "a1", status="failed")}),  # a Recording that does not know its length
    ],
)
def test_otherwise_the_line_keeps_its_own_length(line, recordings):
    assert _spoken(_records(line, recordings)) == 2.5


def test_a_line_with_no_length_anywhere_counts_nothing_as_before():
    line = _line(audio="a1", recording="rec-a9")
    line["dataJson"]["duration_seconds"] = "not a number"
    assert _spoken(_records(line, {"rec-a9": OTHER})) == 0.0


@pytest.fixture
def marvin(monkeypatch):
    """`entries` gives the rows; each `query` is recorded and answered from the Recordings, as Marvin filters them (type and slugs or ids)."""
    import marvin_worker.marvin_api as api

    seen = {"rows": [], "recordings": [], "queries": [], "fail": False}

    def query(creds, spec, *, limit=100):
        seen["queries"].append(spec)
        if seen["fail"]:
            raise api.MarvinUnreachable("can't reach Marvin")
        wanted = set(spec["entries"])
        return [r for r in seen["recordings"] if spec["entry_type"] == "recording" and (r["slug"] in wanted or r["id"] in wanted)][:limit]

    monkeypatch.setattr(api, "entries", lambda creds: seen["rows"])
    monkeypatch.setattr(api, "query", query)
    return seen


def _story_rows(*lines):
    return [_row(S, "The Last Onion"), _row(f"{S}-beat-04", story=S, number="04", picture="Wide."), *lines]


def _pulled_line(slug, audio, recording=None, seconds=2.5):
    return _row(slug, story=S, beat=f"{S}-beat-04", speaker="narrator", text="Words.", audio=audio, duration_seconds=seconds, **({"recording": recording} if recording else {}))


def test_pulling_asks_once_for_every_recording_the_lines_name_and_the_breakdown_trusts_only_matching_ones(marvin):
    marvin["rows"] = _story_rows(_pulled_line("l1", "a1", "rec-a1"), _pulled_line("l2", "a2", "rec-a9"), _pulled_line("l3", "a3", "id-rec-a3"), _pulled_line("l4", "a4"))
    marvin["recordings"] = [REC, OTHER, _rec("rec-a3", "a3", duration_seconds=1.25)]
    records = script.pull_records(S, ("u", "t"))
    assert marvin["queries"] == [{"entry_type": "recording", "entries": ["id-rec-a3", "rec-a1", "rec-a9"]}]  # one query, by the slugs (or ids) named
    assert set(records["recordings"]) == {"rec-a1", "id-rec-a1", "rec-a9", "id-rec-a9", "rec-a3", "id-rec-a3"}
    assert _spoken(records) == 3.0 + 2.5 + 1.25 + 2.5  # l1 its Recording's; l2's points at another file's: its own; l3 named by id; l4 none


def test_pulling_a_story_whose_lines_name_no_recording_asks_nothing(marvin):
    marvin["rows"] = _story_rows(_pulled_line("l1", "a1"))
    records = script.pull_records(S, ("u", "t"))
    assert marvin["queries"] == [] and records["recordings"] == {} and _spoken(records) == 2.5


def test_a_workspace_without_recordings_or_a_marvin_that_does_not_answer_leaves_each_line_its_own_length(marvin):
    marvin["rows"] = _story_rows(_pulled_line("l1", "a1", "rec-a1"))
    assert _spoken(script.pull_records(S, ("u", "t"))) == 2.5  # no Recording type: the query finds nothing
    marvin["recordings"], marvin["fail"] = [REC], True
    assert _spoken(script.pull_records(S, ("u", "t"))) == 2.5 and len(marvin["queries"]) == 2


def test_many_named_recordings_are_asked_for_500_at_a_time(marvin):
    marvin["rows"] = _story_rows(*(_pulled_line(f"l{n:04}", f"a{n}", f"rec-a{n:04}") for n in range(1001)))
    script.pull_records(S, ("u", "t"))
    assert [len(q["entries"]) for q in marvin["queries"]] == [500, 500, 1]
