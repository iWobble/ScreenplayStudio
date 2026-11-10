"""The plain card a draft shows for a beat that has no still yet."""

import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import marvin_pull

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")
    return int(w), int(h)


def test_the_placeholder_is_a_vertical_picture_the_size_of_a_short(tmp_path):
    card = marvin_pull._placeholder(tmp_path / "stills" / "b02-placeholder.png", "02")
    assert card.is_file() and _size(card) == (1080, 1920)


def test_a_beat_number_with_odd_characters_cannot_break_the_picture(tmp_path):
    card = marvin_pull._placeholder(tmp_path / "x.png", "04a:'\\")
    assert card.is_file() and card.stat().st_size > 0
