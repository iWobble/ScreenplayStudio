"""The info card: a beat's label, title and sentence (and an icon) drawn over a dimmed backdrop and handed to the renderer as the beat's overlay."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from storyrender import build, cards, demo, ffmpeg, manifest, marvin_pull

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
CARD = {"label": "Real fact", "title": "Water heaters", "text": "Most of them are set hotter than they need to be.", "icon": None, "dim": 0.45}


def test_a_beat_has_a_card_when_it_has_a_title_or_a_sentence_and_the_dim_is_kept_between_0_and_1():
    assert cards.info_of({}) is None and cards.info_of({"info_label": "Fact", "info_icon": "abc"}) is None  # a label or an icon alone is no card
    one = cards.info_of({"info_title": " Water heaters ", "info_label": " Real fact ", "info_icon": " abc "})
    assert one == {"label": "Real fact", "title": "Water heaters", "text": "", "icon": "abc", "dim": cards.INFO_DIM}
    assert cards.info_of({"info_text": "A sentence."})["title"] == ""
    for given, want in ((0.8, 0.8), ("0.2", 0.2), (3, 1.0), (-1, 0.0), ("dark", cards.INFO_DIM), (None, cards.INFO_DIM)):
        assert cards.info_of({"info_title": "x", "info_dim": given})["dim"] == want


def test_the_card_is_a_transparent_picture_the_size_of_the_frame_dimmed_with_text_in_the_middle(tmp_path):
    path = cards.make_info(CARD, tmp_path / "info" / "b1.png", (1080, 1920))
    image = Image.open(path).convert("RGBA")
    assert image.size == (1080, 1920)
    assert image.getpixel((5, 5)) == (0, 0, 0, round(0.45 * 255))  # the backdrop: black at the dim level
    assert image.getpixel((1075, 1915))[3] == round(0.45 * 255)
    inked = image.crop((0, 0, 1080, 1920)).getchannel("A").point(lambda a: 255 if a > 250 else 0).getbbox()
    assert inked is not None  # solid text is there
    left, top, right, bottom = inked
    assert left > 1080 * 0.06 and right < 1080 * 0.94  # inside the margins
    assert 1920 * 0.2 < top and bottom < 1920 * 0.65  # in the middle of the picture: the captions' band, low down, stays clear


def test_no_dim_leaves_the_rest_of_the_picture_clear_and_a_card_without_a_label_is_still_drawn(tmp_path):
    image = Image.open(cards.make_info({**CARD, "label": "", "dim": 0.0}, tmp_path / "x.png", (360, 640))).convert("RGBA")
    assert image.getpixel((3, 3))[3] == 0 and image.getchannel("A").getbbox() is not None


def test_a_long_sentence_is_wrapped_inside_the_margins(tmp_path):
    long = {**CARD, "text": "word " * 80}
    image = Image.open(cards.make_info(long, tmp_path / "long.png", (1080, 1920), None)).convert("RGBA")
    solid = image.getchannel("A").point(lambda a: 255 if a > 250 else 0).getbbox()
    assert solid and solid[0] > 1080 * 0.06 and solid[2] < 1080 * 0.94


def test_an_icon_is_drawn_above_the_label_centred_and_one_that_cannot_be_read_is_left_out(tmp_path):
    icon = tmp_path / "icon.png"
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(icon)
    with_icon = Image.open(cards.make_info(CARD, tmp_path / "a.png", (1080, 1920), icon)).convert("RGBA")
    red = [(x, y) for y in range(0, 1920, 6) for x in range(0, 1080, 6) if with_icon.getpixel((x, y))[:3] == (255, 0, 0) and with_icon.getpixel((x, y))[3] == 255]
    assert red and abs((min(x for x, _ in red) + max(x for x, _ in red)) / 2 - 540) < 20  # centred
    text = [(x, y) for y in range(0, 1920, 3) for x in range(0, 1080, 3) if with_icon.getpixel((x, y))[3] == 255 and with_icon.getpixel((x, y))[:3] != (255, 0, 0)]
    assert text and max(y for _, y in red) < min(y for _, y in text)  # the icon sits above the label, title and sentence
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a picture")
    assert Image.open(cards.make_info(CARD, tmp_path / "c.png", (360, 640), bad)).size == (360, 640)


def test_the_pull_hands_the_card_on_as_the_beats_overlay_with_its_defaults_and_the_beats_own_fade_and_delay(tmp_path, monkeypatch):
    assert marvin_pull._info_overlay(("u", "t"), tmp_path, {"overlay": "mine"}, "03", (360, 640)) is None  # no card: nothing, and the cascade goes on
    fetched = []

    def fetch(creds, asset, dest, ext):
        fetched.append(asset)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (50, 50), (0, 255, 0, 255)).save(dest.with_suffix(".png"))
        return dest.with_suffix(".png")

    monkeypatch.setattr(marvin_pull, "_fetch_asset", fetch)
    plain = marvin_pull._info_overlay(("u", "t"), tmp_path, {"info_title": "Fact", "info_icon": "icon-1"}, "03", (360, 640))
    assert plain == {"video": "video/info/b03.png", "blend": "normal", "opacity": 1.0, "id": "info-b03", "fade": cards.INFO_FADE, "delay": cards.INFO_DELAY}
    assert fetched == ["icon-1"] and (tmp_path / "video" / "info" / "b03.png").is_file()
    own = marvin_pull._info_overlay(("u", "t"), tmp_path, {"info_text": "Hi", "overlay_fade": 1.5, "overlay_delay": 0}, "04", (360, 640))
    assert (own["fade"], own["delay"]) == (1.5, cards.INFO_DELAY)  # a delay of 0 is "not set" everywhere else too


@needs_ffmpeg
def test_the_card_comes_in_after_its_delay_dims_the_still_and_fades_out_with_the_shot(tmp_path):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    cards.make_info(CARD, project.parent / "info.png", (360, 640))
    raw = json.loads(project.read_text())
    raw["shots"][0]["overlay"] = {"video": "info.png", "fade": 0.4, "delay": 1.0}
    project.write_text(json.dumps(raw))
    with_card = manifest.load(project, probe=ffmpeg.duration)
    plain = manifest.load(demo.make(tmp_path / "plain", size=(360, 640)), probe=ffmpeg.duration)
    build.render(with_card, tmp_path / "card.mp4", draft=True)
    build.render(plain, tmp_path / "plain.mp4", draft=True)

    def corner(video: Path, t: float) -> int:
        raw_px = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-vf", "crop=8:8:0:0,scale=1:1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        return raw_px[0]

    assert abs(corner(tmp_path / "card.mp4", 0.4) - corner(tmp_path / "plain.mp4", 0.4)) < 6  # before its delay: the still only
    assert corner(tmp_path / "card.mp4", 1.8) < corner(tmp_path / "plain.mp4", 1.8) * 0.75  # then the backdrop is dimmed
