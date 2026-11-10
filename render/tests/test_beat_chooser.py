"""Which beats a quick look is for: `3`, `2-4`, `1,3,5`, `4a`, said the way a person would."""

import pytest

from storyrender import marvin_pull
from storyrender.marvin_pull import PullError, beat_chooser


def _chosen(spec: str, numbers: list[str]) -> list[str]:
    wants = beat_chooser(spec)
    return [n for n in numbers if wants(n)]


BEATS = ["01", "02", "03", "04", "04a", "05", "06", "10"]


def test_no_choice_means_every_beat():
    assert beat_chooser(None) is None and beat_chooser("") is None and beat_chooser("  ") is None


def test_one_number_takes_that_beat_and_the_ones_inserted_after_it():
    assert _chosen("4", BEATS) == ["04", "04a"]
    assert _chosen("04", BEATS) == ["04", "04a"]  # with or without its zero
    assert _chosen("1", BEATS) == ["01"]  # not 10


def test_a_letter_takes_only_the_inserted_beat():
    assert _chosen("4a", BEATS) == ["04a"]


def test_a_range_is_by_number_and_a_list_is_each():
    assert _chosen("2-4", BEATS) == ["02", "03", "04", "04a"]
    assert _chosen("1, 3 ,5", BEATS) == ["01", "03", "05"]
    assert _chosen("1,5-6", BEATS) == ["01", "05", "06"]


def test_a_beat_with_no_number_is_never_chosen():
    wants = beat_chooser("1")
    assert not wants(None) and not wants("") and not wants("intro")


@pytest.mark.parametrize("bad", ["x", "1;2", "two", "3-", "-3"])
def test_something_that_is_not_a_beat_says_how_to_ask(bad):
    with pytest.raises(PullError, match="not a beat"):
        beat_chooser(bad)


def test_the_pull_takes_the_choice_through(monkeypatch):
    seen = []
    monkeypatch.setattr(marvin_pull, "credentials", lambda: ("u", "t"))
    monkeypatch.setattr(marvin_pull, "_pull", lambda story, out, creds, chosen=None, placeholders=False: seen.append(chosen) or {})
    marvin_pull.pull("s", None, beats="2-3")
    marvin_pull.pull("s", None)
    assert seen[0]("02") and not seen[0]("04") and seen[1] is None
