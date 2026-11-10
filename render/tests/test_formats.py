"""Where a film is going: its shape, loudness and the length its platform takes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, cards, demo, ffmpeg, formats, manifest, marvin_pull
from storyrender.manifest import ManifestError

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def test_the_story_names_a_shape_and_loudness_from_a_known_list_or_gets_the_default():
    assert formats.size_of({"format": "wide-16x9"}) == (1920, 1080) and formats.size_of({"format": "Square-1x1 "}) == (1080, 1080)
    assert formats.size_of({}) is None and formats.size_of({"format": "short-9x16"}) == (1080, 1920) and formats.size_of({"format": "cinema"}) is None
    assert formats.loudness_of({"loudness": "-14"}) == -14.0 and formats.loudness_of({"loudness": "loud"}) is None and formats.loudness_of({}) is None


def test_a_film_over_its_platforms_limit_gets_words_and_one_that_fits_or_names_none_does_not():
    over = formats.length_warning(185, {"platform": "youtube-short"})
    assert over and "3:05" in over and "3:00" in over and "YouTube Short" in over and "current limit" in over
    assert formats.length_warning(180, {"platform": "youtube-short"}) is None  # exactly at the limit is fine
    assert formats.length_warning(9999, {"platform": "youtube"}) is None  # a platform with no limit worth warning about
    assert formats.length_warning(9999, {}) is None and formats.length_warning(9999, {"platform": "myspace"}) is None
    assert "10:00" in (formats.length_warning(700, {"platform": "tiktok"}) or "")


def test_the_manifest_takes_the_four_shapes_and_refuses_others(tmp_path):
    (tmp_path / "s.png").write_bytes(b"x")
    for size in ([1080, 1920], [1080, 1080], [1080, 1350], [1920, 1080], [540, 960]):
        (tmp_path / "m.json").write_text(json.dumps({"size": size, "shots": [{"id": "a", "still": "s.png", "hold": 2, "lines": []}]}))
        assert manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False).size == tuple(size)
    for bad in ([1000, 1000 * 3], [1080, 1200], [100]):
        (tmp_path / "m.json").write_text(json.dumps({"size": bad, "shots": [{"id": "a", "still": "s.png", "hold": 2, "lines": []}]}))
        with pytest.raises(ManifestError, match="size must be"):
            manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


@pytest.mark.parametrize(("raw", "ok"), [(-14, True), ("-16", True), (None, True), (-3, False), (-40, False)])
def test_the_loudness_target_is_a_sensible_lufs_value(tmp_path, raw, ok):
    (tmp_path / "s.png").write_bytes(b"x")
    (tmp_path / "m.json").write_text(json.dumps({"loudness": raw, "shots": [{"id": "a", "still": "s.png", "hold": 2, "lines": []}]}))
    if ok:
        assert manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False).loudness == (float(raw) if raw is not None else -16.0)
    else:
        with pytest.raises(ManifestError, match="loudness"):
            manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def _dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


@needs_ffmpeg
@pytest.mark.parametrize(("shape", "draft_size"), [("square-1x1", (540, 540)), ("portrait-4x5", (540, 674)), ("wide-16x9", (960, 540))])
def test_a_film_renders_in_each_shape_from_the_vertical_pictures(tmp_path, shape, draft_size):
    project = demo.make(tmp_path / "demo", size=(1080, 1920))  # the pictures are tall, as a story's are
    raw = json.loads(project.read_text())
    raw["size"] = list(formats.SHAPES[shape])
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True)
    assert _dims(tmp_path / "out.mp4") == draft_size


@needs_ffmpeg
def test_cards_and_placeholder_pictures_are_made_in_the_shape_asked_for(tmp_path):
    intro, _ = cards.shots({"intro_title": "Hello"}, tmp_path, formats.SHAPES["wide-16x9"])
    assert _dims(tmp_path / intro["still"]) == (1920, 1080)
    assert _dims(marvin_pull._placeholder(tmp_path / "p.png", "02", formats.SHAPES["square-1x1"])) == (1080, 1080)


def test_captions_sit_lower_on_a_picture_that_is_not_a_tall_short():
    from storyrender import captions
    from storyrender.manifest import Line, Manifest, Shot

    plan = manifest.plan(Manifest("t", (1920, 1080), 30, [Shot("a", Path("a.png"), hold=0.0, lines=[Line("Hi there", None, 1.0)])]))
    tall = captions.ass(manifest.plan(Manifest("t", (1080, 1920), 30, [Shot("a", Path("a.png"), hold=0.0, lines=[Line("Hi there", None, 1.0)])])), (1080, 1920))
    wide = captions.ass(plan, (1920, 1080))

    def margin(text: str) -> int:
        return int(next(line for line in text.splitlines() if line.startswith("Style:")).split(",")[21])

    assert margin(tall) == 384 and margin(wide) == 108  # 20% of the Short's height; 10% of the wide picture's
