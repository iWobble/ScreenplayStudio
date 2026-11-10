"""Title and end cards: which story fields make one, how long it lasts (the same rules as the timeline view's spine.cards), and the picture."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, cards, demo, ffmpeg, manifest

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def test_a_card_exists_when_its_title_has_text_and_lasts_its_seconds_else_the_default():
    assert cards.card_of({}, "intro") is None and cards.card_of({"intro_title": "   "}, "intro") is None
    intro = cards.card_of({"intro_title": " Granny's Advice ", "intro_subtitle": "A short", "intro_seconds": "3.5"}, "intro")
    assert (intro["title"], intro["subtitle"], intro["seconds"]) == ("Granny's Advice", "A short", 3.5)
    assert cards.card_of({"intro_title": "x"}, "intro")["seconds"] == 2.5 and cards.card_of({"outro_title": "x"}, "outro")["seconds"] == 3.0  # the defaults
    for nothing in (0, -2, "", None, "long"):
        assert cards.card_of({"outro_title": "x", "outro_seconds": nothing}, "outro")["seconds"] == 3.0  # not a length above 0: the default


@pytest.mark.parametrize(("given", "want"), [("#FF8800", "0xff8800"), ("ff8800", "0xff8800"), ("  #123abc ", "0x123abc"), ("red", "0x111111"), ("#12345", "0x111111"), (None, "0x111111"), ("", "0x111111")])
def test_a_colour_is_six_hex_digits_or_the_fallback(given, want):
    assert cards.colour(given, cards.DEFAULT_COLOUR) == want


def test_text_is_broken_into_lines_that_fit_and_keeps_the_writers_own_breaks():
    wrapped = cards._lines("A very long title that cannot possibly fit on one line of a vertical picture", 92, 1080)
    assert len(wrapped) > 1 and all(len(line) <= 11 + 5 for line in wrapped)
    assert cards._lines("One\nTwo", 92, 1080) == ["One", "Two"]


def _mean(path: Path, region: str) -> tuple[int, int, int]:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"{region},scale=1:1", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


@needs_ffmpeg
def test_the_card_picture_is_a_vertical_still_with_the_text_on_the_colour(tmp_path):
    card = cards.card_of({"intro_title": "Granny's Advice: 100% true", "intro_subtitle": "A story", "card_color": "#102030", "card_text_color": "#ffffff"}, "intro")
    still = cards.make_still(card, tmp_path / "stills" / "intro-card.png")
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(still)], capture_output=True, text=True, check=True).stdout.strip()
    assert size == "1080,1920"
    corner = _mean(still, "crop=100:100:0:0")
    assert max(abs(a - b) for a, b in zip(corner, (0x10, 0x20, 0x30), strict=True)) < 6  # the colour asked for
    middle = _mean(still, "crop=1000:700:40:610")
    assert sum(middle) > sum(corner) + 20  # and light text over the middle of it (an apostrophe, a colon and a percent sign did not stop it)


@needs_ffmpeg
def test_a_story_with_a_title_and_an_end_card_gets_real_shots_that_last_their_seconds(tmp_path):
    intro, outro = cards.shots({"intro_title": "Hello", "intro_seconds": 2, "outro_title": "Bye"}, tmp_path)
    assert (intro["id"], intro["hold"], intro["lines"]) == ("intro", 2.0, []) and (outro["id"], outro["hold"]) == ("outro", 3.0)
    assert (tmp_path / intro["still"]).is_file() and (tmp_path / outro["still"]).is_file()
    assert cards.shots({}, tmp_path) == (None, None) and cards.shots({"outro_title": "x"}, tmp_path)[0] is None  # no title, no card


@needs_ffmpeg
def test_cards_are_part_of_the_film_and_move_everything_after_them(tmp_path):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    raw = json.loads(project.read_text())
    intro, outro = cards.shots({"intro_title": "Hello", "intro_seconds": 2, "outro_title": "Bye", "outro_seconds": 1.5}, project.parent, size=(360, 640))
    plain = manifest.plan(manifest.load(project, probe=ffmpeg.duration))
    raw["shots"] = [intro, *raw["shots"], outro]
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    plan = manifest.plan(m)
    assert [s.shot.id for s in plan.shots][0::len(plan.shots) - 1] == ["intro", "outro"]
    assert plan.shots[1].start == pytest.approx(2.0) and plan.duration == pytest.approx(plain.duration + 2.0 + 1.5)  # every beat after the title starts 2 s later
    build.render(m, tmp_path / "out.mp4", draft=True)
    assert ffmpeg.duration(tmp_path / "out.mp4") == pytest.approx(plan.duration, abs=0.2)


# ── the pause where a scene ends ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_pause_follows_a_shot_whose_next_shot_is_in_another_scene_and_nothing_else_does():
    from storyrender import marvin_pull

    scenes = ["deck", "deck", "cabin", "", "cabin", "cabin", "deck"]
    assert marvin_pull.scene_breaks(scenes, 1.5) == [0.0, 1.5, 0.0, 0.0, 0.0, 1.5, 0.0]  # deck→cabin, then cabin→deck; a shot with no scene breaks nothing
    assert marvin_pull.scene_breaks(scenes, 0) == marvin_pull.scene_breaks(scenes, None) == marvin_pull.scene_breaks(scenes, "") == [0.0] * 7  # none set: nothing, whatever the old default was
    assert marvin_pull.scene_breaks([], 1) == [] and marvin_pull.scene_breaks(["a"], 1) == [0.0]


def test_a_shots_pause_is_part_of_its_length_and_moves_the_next_shot():
    from pathlib import Path

    from storyrender.manifest import Line, Manifest, Shot

    a, b = Shot("a", Path("a.png"), hold=2.0), Shot("b", Path("b.png"), hold=2.0, lines=[Line("x", None, 1.0)])
    a.after = 1.5
    plan = manifest.plan(Manifest("t", (360, 640), 30, [a, b]))
    assert plan.shots[0].duration == pytest.approx(3.5) and plan.shots[1].start == pytest.approx(3.5)  # the hold plus the pause
    assert plan.shots[1].lines[0].start == pytest.approx(3.5 + 0.3)  # a line after it keeps its lead-in from the new start


@needs_ffmpeg
def test_the_pause_is_quiet_picture_held_and_the_film_is_that_much_longer(tmp_path):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    plain = manifest.plan(manifest.load(project, probe=ffmpeg.duration))
    raw = json.loads(project.read_text())
    raw["shots"][0]["after"] = 2.0
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True)
    assert manifest.plan(m).duration == pytest.approx(plain.duration + 2.0)
    assert ffmpeg.duration(tmp_path / "out.mp4") == pytest.approx(plain.duration + 2.0, abs=0.2)
