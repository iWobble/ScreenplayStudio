"""The filmstrip page (storyrender.filmstrip): what it holds, and that the render's plan and moves are what it plays."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import ffmpeg, filmstrip, manifest

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")

SHOTS = [
    {"id": "b01", "label": "Beat 01", "start": 0.0, "duration": 4.0, "image": "data:image/jpeg;base64,AAAA", "from": {"x": 0.5, "y": 0.5, "zoom": 1.0}, "to": {"x": 0.5, "y": 0.5, "zoom": 1.08}, "lines": [{"speaker": "narrator", "text": "One.", "start": 0.4, "end": 1.4}]},
    {"id": "b02", "label": "Beat 02", "start": 4.0, "duration": 3.0, "image": "data:image/jpeg;base64,BBBB", "from": {"x": 0.8, "y": 0.36, "zoom": 1.35}, "to": {"x": 0.8, "y": 0.36, "zoom": 1.8}, "lines": []},
]


def test_the_page_holds_every_shot_its_timing_and_its_sound_and_names_the_story():
    page = filmstrip.player("The Last Onion", SHOTS, "data:audio/mpeg;base64,CCCC")
    assert page.startswith("<!DOCTYPE html>") and "<title>The Last Onion: filmstrip</title>" in page
    assert '"start": 4.0' in page and "data:image/jpeg;base64,BBBB" in page and "data:audio/mpeg;base64,CCCC" in page
    assert "Next shot" in page and "Previous shot" in page and "keydown" in page  # next and previous, by button and by arrow key


def test_a_title_or_caption_with_markup_cannot_break_out_of_the_page():
    shots = [{**SHOTS[0], "lines": [{"speaker": "x", "text": "</script><b>hi</b>", "start": 0, "end": 1}]}]
    page = filmstrip.player("<img src=x onerror=alert(1)>", shots, "a.mp3")
    assert "<img src=x" not in page and "&lt;img src=x" in page
    assert "</script><b>hi" not in page  # a closing tag inside the data is escaped, so the data stays data


def test_the_camera_stays_inside_the_picture():
    assert filmstrip._clamp(0.99, 2.0) == pytest.approx(0.75) and filmstrip._clamp(0.0, 2.0) == pytest.approx(0.25) and filmstrip._clamp(0.3, 1.0) == pytest.approx(0.5)


def _tone(path: Path, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame", str(path)], check=True)
    return path


def _still(path: Path, colour: str) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=360x640", "-frames:v", "1", str(path)], check=True)
    return path


@needs_ffmpeg
def test_making_a_filmstrip_follows_the_renders_plan_and_moves_and_keeps_a_silent_held_shot(tmp_path):
    _tone(tmp_path / "a.mp3", 1.0)
    _still(tmp_path / "one.png", "red")
    _still(tmp_path / "two.png", "blue")
    (tmp_path / "m.json").write_text(
        json.dumps(
            {
                "title": "Onion",
                "shots": [
                    {"id": "b01", "still": "one.png", "lines": [{"id": "l1", "audio": "a.mp3", "text": "One.", "speaker": "narrator"}]},
                    {"id": "b02", "still": "two.png", "hold": 3, "lines": [], "move": {"from": {"x": 0.8, "y": 0.4, "zoom": 1.3}, "to": {"x": 0.8, "y": 0.36, "zoom": 1.8}}},
                ],
            }
        )
    )
    m = manifest.load(tmp_path / "m.json", probe=ffmpeg.duration)

    made = filmstrip.make(m, tmp_path / "out")

    page = made["html"].read_text()
    planned = manifest.plan(m)
    assert made["shots"] == 2 and made["seconds"] == pytest.approx(planned.duration, abs=0.01)
    assert '"label": "Beat 02"' in page and '"zoom": 1.8' in page and '"text": "One."' in page  # the move and the caption are the render's
    assert page.count("data:image/jpeg;base64,") >= 2 and "data:audio/mpeg;base64," in page and len(page) < 2_000_000
    assert planned.shots[1].duration == pytest.approx(3.0, abs=0.01)  # the silent shot keeps its asked-for time
