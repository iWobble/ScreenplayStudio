"""Caption styles: classic outline, box, word-by-word highlight, none; position, size, colours, a colour per speaker; and the subtitle file."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, captions, demo, ffmpeg, manifest
from storyrender.manifest import Line, Manifest, Shot

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _timeline(speaker="Cook"):
    words = [{"text": "Your", "start": 0.0, "end": 0.3}, {"text": "feast.", "start": 0.4, "end": 0.9}, {"text": "Make", "start": 1.2, "end": 1.5}, {"text": "do.", "start": 1.5, "end": 1.9}]
    shots = [Shot("a", Path("a.png"), hold=0.0, lines=[Line("Your feast. Make do.", None, 2.0, speaker=speaker, words=words)])]
    return manifest.plan(Manifest("t", (1080, 1920), 30, shots))


def _style_line(text: str) -> list[str]:
    return next(line for line in text.splitlines() if line.startswith("Style:")).removeprefix("Style: ").split(",")


# Style: Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic, Underline, Strike, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, ML, MR, MV
def test_the_colour_as_ass_writes_it_and_a_bad_one_falls_back():
    assert captions.ass_colour("#ff8800", "#ffffff") == "&H000088FF"  # BGR
    assert captions.ass_colour("00ff00", "#ffffff") == "&H0000FF00"
    assert captions.ass_colour("red", "#ffffff") == "&H00FFFFFF" and captions.ass_colour(None, "#ffd400") == "&H0000D4FF"


def test_classic_is_the_old_look_and_nothing_is_set_by_default():
    out = captions.ass(_timeline(), (1080, 1920))
    f = _style_line(out)
    assert (f[2], f[3], f[15], f[18], f[21]) == ("77", "&H00FFFFFF", "1", "2", "384")  # 4% of the height, white, an outline, bottom centre, 20% up
    assert "{\\kf" not in out and "Dialogue: 0,0:00:00.30" in out  # the first caption starts after the shot's 0.3 s lead-in


def test_box_is_an_opaque_box_behind_the_words():
    f = _style_line(captions.ass(_timeline(), (1080, 1920), {"style": "box"}))
    assert f[15] == "3" and f[5] == "&H99000000" and f[6] == "&H99000000"  # BorderStyle 3 with a dark translucent box


def test_position_and_size_move_and_scale_the_text():
    middle = _style_line(captions.ass(_timeline(), (1080, 1920), {"position": "middle", "size": "large"}))
    assert (middle[18], middle[21], middle[2]) == ("5", "0", "96")  # centred on the picture, 5% of the height
    top = _style_line(captions.ass(_timeline(), (1080, 1920), {"position": "top", "size": "small"}))
    assert (top[18], top[2]) == ("8", "61") and int(top[21]) > 0
    odd = _style_line(captions.ass(_timeline(), (1080, 1920), {"position": "sideways", "size": "huge"}))
    assert (odd[18], odd[2]) == ("2", "77")  # what it does not know is the default


def test_the_text_colour_is_the_one_asked_for_and_the_older_ass_key_still_wins():
    assert _style_line(captions.ass(_timeline(), (1080, 1920), {"color": "#00ff00"}))[3] == "&H0000FF00"
    assert _style_line(captions.ass(_timeline(), (1080, 1920), {"color": "#00ff00", "colour": "&H0000FFFF"}))[3] == "&H0000FFFF"


def test_highlight_sweeps_each_word_as_it_is_spoken_and_lasts_to_the_next_word():
    out = captions.ass(_timeline(), (1080, 1920), {"style": "highlight", "highlight": "#00ff00", "color": "#ffffff"})
    f = _style_line(out)
    assert (f[3], f[4]) == ("&H0000FF00", "&H00FFFFFF")  # spoken words in the highlight, the rest in the text colour
    first = next(line for line in out.splitlines() if line.startswith("Dialogue"))
    assert re.findall(r"\{\\kf(\d+)\}(\w+\.?)", first) == [("40", "Your"), ("50", "feast.")]  # "Your" lasts until "feast." begins (0.4 s), the last until its own end (0.5 s)


def test_a_caption_without_word_times_still_sweeps_by_the_length_of_its_words():
    line = Line("Make do.", None, 1.0, speaker="Cook")
    plan = manifest.plan(Manifest("t", (1080, 1920), 30, [Shot("a", Path("a.png"), hold=0.0, lines=[line])]))
    out = captions.ass(plan, (1080, 1920), {"style": "highlight"})
    sweeps = re.findall(r"\{\\kf(\d+)\}", out)
    assert len(sweeps) == 2 and abs(sum(map(int, sweeps)) - 100) <= 2  # the caption's whole second, shared by the two words


def test_a_speaker_with_a_colour_is_shown_in_it_and_the_others_are_not():
    colours = {"cook": "#ff0000"}
    assert "{\\1c&H000000FF}Your feast." in captions.ass(_timeline("Cook"), (1080, 1920), {"speakers": colours})
    assert "\\1c" not in captions.ass(_timeline("Captain"), (1080, 1920), {"speakers": colours})
    assert "{\\2c&H000000FF}" in captions.ass(_timeline("COOK"), (1080, 1920), {"style": "highlight", "speakers": colours})  # not case-sensitive; in the highlight style it is the unsung colour
    assert "\\1c" not in captions.ass(_timeline("Cook"), (1080, 1920), {"speakers": {"cook": "red"}})  # not a colour: ignored


def test_none_burns_no_captions_at_all():
    assert "Dialogue" not in captions.ass(_timeline(), (1080, 1920), {"style": "none"})
    assert "Dialogue" in captions.ass(_timeline(), (1080, 1920), {"style": "sparkle"})  # not a style: classic


def test_the_subtitle_file_has_every_caption_with_its_times():
    text = captions.srt(_timeline())
    assert text.startswith("1\n00:00:00,300 --> 00:00:01,200\nYour feast.\n\n2\n00:00:01,500 --> 00:00:02,200\nMake do.\n\n")
    assert captions.srt(manifest.plan(Manifest("t", (1080, 1920), 30, []))) == ""


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["box", "highlight", "none"])
def test_every_style_renders(tmp_path, kind):
    import json

    project = demo.make(tmp_path / "demo", size=(360, 640))
    raw = json.loads(project.read_text())
    raw["caption"] = {"style": kind, "position": "middle", "size": "large", "color": "#ffee99", "highlight": "#ff3366", "speakers": {"narrator": "#99ccff"}}
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True)
    assert ffmpeg.duration(tmp_path / "out.mp4") == pytest.approx(manifest.plan(m).duration, abs=0.25)


# ── what the pull hands on ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_story_and_the_cast_make_the_manifests_caption_look():
    from storyrender import marvin_pull

    data = lambda e: e["dataJson"]  # noqa: E731
    rows = [
        {"dataJson": {"story": "s", "speaker": "Cook", "caption_color": "#FF0000"}},
        {"dataJson": {"story": "s", "speaker": "Captain", "caption_color": "00ff00"}},
        {"dataJson": {"story": "s", "speaker": "Mate", "caption_color": "red"}},  # not a colour
        {"dataJson": {"story": "other", "speaker": "Cook", "caption_color": "#0000ff"}},  # another story's cast
        {"dataJson": {"story": "s", "speaker": "", "caption_color": "#ffffff"}},
    ]
    assert marvin_pull.speaker_colours(rows, "s", data) == {"cook": "#ff0000", "captain": "#00ff00"}
    story = {"caption_style": "Highlight", "caption_position": "middle", "caption_size": "huge", "caption_color": "#FFEE99", "caption_highlight_color": "nope"}
    assert marvin_pull.caption_of(story, {"cook": "#ff0000"}) == {"style": "highlight", "position": "middle", "color": "#ffee99", "speakers": {"cook": "#ff0000"}}  # what is unknown or not a colour is left out
    assert marvin_pull.caption_of({}, {}) == {}  # nothing asked for: the manifest says nothing and the old look stays
