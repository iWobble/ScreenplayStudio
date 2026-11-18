"""Camera cues on a word (v212): `[[Camera: punch]]`, `[[Camera: shake 2]]`, `[[Camera: nudge 0.7,0.4]]` among a line's words move the camera at the end
of the word before the note, on top of the beat's own move, inside the zoompan the still is moved by; the frame never leaves the picture."""

import json
import subprocess
from array import array
from pathlib import Path

import pytest

from storyrender import build, camera, fountain, manifest, script
from storyrender.manifest import Line, Manifest, Shot
from tests.test_overlay_music import needs_ffmpeg

W, H, FPS = 160, 284, 24


def test_a_cue_is_one_of_three_kinds_with_its_numbers_held_in_range():
    assert camera.cue_of({"kind": "punch"}) == {"kind": "punch"} and camera.cue_of({"kind": "Punch", "amount": 3}) == {"kind": "punch", "amount": 1.5}
    assert camera.cue_of({"kind": "shake", "amount": 2}) == {"kind": "shake", "amount": 2.0}
    assert camera.cue_of({"kind": "nudge", "x": 0.7, "y": 1.4}) == {"kind": "nudge", "x": 0.7, "y": 1.0}
    assert camera.cue_of({"kind": "dolly"}) is None and camera.cue_of("punch") is None and camera.cue_of({"kind": "shake", "amount": "x"}) is None


@pytest.mark.parametrize("words", ["punch", "punch 1.1", "shake", "shake 2", "nudge 0.7,0.4"])
def test_a_camera_note_reads_back_as_it_was_written(words):
    assert fountain.camera_words(fountain.camera_cue(words)) == words


def test_the_cue_terms_are_nothing_outside_their_window_and_leave_a_shot_without_cues_as_it_was():
    zoom, cx, cy = build.camera_cues([(1.0, {"kind": "punch"})], FPS, "1.0", "0.5", "0.5")
    assert zoom.startswith("(1.0)*(1+0.0600*if(lt((on/24-1.0000),0),0,") and (cx, cy) == ("0.5", "0.5")
    still = Shot("a", Path("x.png"), hold=2.0)
    planned = manifest.plan(Manifest("t", (W, H), FPS, [still])).shots[0]
    assert planned.camera == [] and "on/24-" not in build.zoompan_filter(planned, (W, H), FPS)


def test_the_plan_puts_a_cue_on_its_word_and_on_the_picture_that_is_up_then():
    host = Shot("a", Path(), lines=[Line("w", duration=4.0, ref="l1")], camera_cues=[{"kind": "punch", "line": "l1", "at": 0.5}, {"kind": "shake", "line": "l1", "at": 3.0}])
    overlay = Shot("b", Path(), starts_during={"line": "l1", "at": 2.0})
    t = manifest.plan(Manifest("t", (W, H), FPS, [host, overlay]))
    assert t.shots[0].camera == [(pytest.approx(0.3 + 0.5), {"kind": "punch"})]
    assert t.shots[1].camera == [(pytest.approx(3.0 - 2.0), {"kind": "shake"})]  # after the overlay came in: it shakes the overlay's picture


def _square(path: Path, background: str = "black") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={background}:s=320x568", "-vf", "drawbox=x=130:y=254:w=60:h=60:color=white:t=fill", "-frames:v", "1", str(path)], check=True)
    return path


def _frames(still: Path, cues: list[dict], seconds: float, tmp_path: Path, move: tuple = (manifest.Move(), manifest.Move())) -> list[array]:
    shot = Shot("a", still, hold=seconds, move_from=move[0], move_to=move[1], camera_cues=cues)
    planned = manifest.plan(Manifest("t", (W, H), FPS, [shot])).shots[0]
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds}", "-i", str(still), "-vf", build.zoompan_filter(planned, (W, H), FPS),
         "-frames:v", str(round(seconds * FPS)), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    size = W * H
    return [array("B", raw[i : i + size]) for i in range(0, len(raw), size)]


def _area(frame: array) -> int:
    return sum(1 for v in frame if v > 128)


def _centre_x(frame: array) -> float:
    xs = [i % W for i, v in enumerate(frame) if v > 128]
    return sum(xs) / max(len(xs), 1)


@needs_ffmpeg
def test_a_punch_goes_in_at_its_word_and_settles_back(tmp_path):
    frames = _frames(_square(tmp_path / "sq.png"), [{"kind": "punch", "at": 1.0}], 2.5, tmp_path)
    areas = [_area(f) for f in frames]
    rest, peak = areas[round(0.5 * FPS)], max(areas)
    assert areas.index(peak) in range(round(1.15 * FPS), round(1.3 * FPS))  # at its fullest 0.2 s after the word
    assert peak == pytest.approx(rest * 1.06**2, rel=0.08)  # 6% closer: the square's area grows by 1.06 squared
    assert areas[round(1.6 * FPS)] == pytest.approx(rest, rel=0.02) and areas[round(0.9 * FPS)] == rest  # back after 0.5 s; nothing before the word


@needs_ffmpeg
def test_a_shake_moves_the_picture_for_a_moment_and_dies_away(tmp_path):
    frames = _frames(_square(tmp_path / "sq.png"), [{"kind": "shake", "amount": 2, "at": 1.0}], 2.0, tmp_path, (manifest.Move(zoom=1.1), manifest.Move(zoom=1.1)))
    xs = [_centre_x(f) for f in frames]
    still = xs[round(0.5 * FPS)]
    moved = max(abs(x - still) for x in xs[round(1.0 * FPS) : round(1.3 * FPS)])
    assert moved > 1.8  # pixels: up to 2% of a 160-wide frame (3.2), dying away
    assert all(abs(x - still) < 0.5 for x in xs[: round(1.0 * FPS)] + xs[round(1.35 * FPS) :])


@needs_ffmpeg
def test_a_nudge_drifts_toward_its_point_and_stays(tmp_path):
    frames = _frames(_square(tmp_path / "sq.png"), [{"kind": "nudge", "x": 0.9, "y": 0.5, "at": 0.5}], 1.5, tmp_path, (manifest.Move(zoom=1.2), manifest.Move(zoom=1.2)))
    xs = [_centre_x(f) for f in frames]
    assert xs[round(1.2 * FPS)] < xs[round(0.3 * FPS)] - 2  # the camera looks right, so the square goes left
    assert xs[round(1.2 * FPS)] == pytest.approx(xs[-1], abs=0.5)  # and stays there


@needs_ffmpeg
def test_cues_at_the_edge_of_the_picture_and_the_clip_never_show_past_the_picture(tmp_path):
    white = _square(tmp_path / "white.png", "white")
    frames = _frames(white, [{"kind": "nudge", "x": 1.0, "y": 1.0, "at": 0.0}, {"kind": "shake", "amount": 10, "at": 0.3}, {"kind": "punch", "amount": 1.5, "at": 0.9}], 1.0, tmp_path)
    assert min(min(f) for f in frames) > 200  # never a black edge, at zoom 1 and at the clip's last frames


def test_a_camera_note_reaches_the_beats_cues_and_is_written_back(tmp_path):
    text = "INT. FORGE - DAY\n\nSparks.\n\nSMITH\nThe hammer strikes [[Sound: clang | Camera: punch]] the wheel [[Camera: shake 2]] and [[Camera: nudge 0.7,0.4]] rests.\n"
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    (_c, number, beat), = plan.rows()
    cues = fountain.beat_cues(beat, "s", number, {})
    assert [c.get("camera") for c in cues] == [{"kind": "punch"}, {"kind": "shake", "amount": 2.0}, {"kind": "nudge", "x": 0.7, "y": 0.4}]
    line = {"slug": "s-line-01-1", "dataJson": {"speaker": "smith", "text": beat["lines"][0]["text"]}}
    records = {"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Sparks.", "cues": cues}}],
               "lines": {"s-beat-01": [line]}, "scenes": {}, "sounds": {"s-sound-01-1": {"slug": "s-sound-01-1", "title": "Clang", "dataJson": {"prompt": "clang"}}}, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip
    assert "The hammer strikes [[Sound: clang | Camera: punch]] the wheel [[Camera: shake 2]] and [[Camera: nudge 0.7,0.4]] rests." in script.fountain_complete(records)


def test_the_pull_times_a_camera_cue_as_the_sound_beside_it_and_leaves_out_an_unknown_kind():
    from storyrender import marvin_pull

    heard = {"s-line-01-1": {"text": "The hammer strikes the wheel.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("The hammer strikes the wheel.".split())]}}
    beat = {"cues": [{"line": "s-line-01-1", "word": 3, "camera": {"kind": "punch", "amount": 1.08}}, {"line": "s-line-01-1", "word": 4, "camera": {"kind": "dolly"}}, {"line": "s-line-09-1", "word": 1, "camera": {"kind": "shake"}}]}
    assert marvin_pull._camera_cues(beat, heard, []) == [{"kind": "punch", "amount": 1.08, "line": "s-line-01-1", "line_at": 1.4}]


@pytest.mark.parametrize("shape", [(1080, 1920), (1080, 1080), (1080, 1350), (1920, 1080)])
def test_a_camera_cue_leaves_the_films_own_settings_alone(tmp_path, shape):
    """A loop over a shot's camera cues once reused the name of the whole manifest, so the size, loudness, captions and the rest were read from the last cue."""
    still = _square(tmp_path / "sq.png")
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], check=True)
    (tmp_path / "m.json").write_text(json.dumps({
        "title": "Wide", "size": list(shape), "loudness": -14,
        "shots": [{"id": "a", "still": str(still), "lines": [{"audio": str(audio), "text": "x", "id": "l1"}], "camera_cues": [{"kind": "shake", "amount": 3, "line": "l1", "line_at": 0.5}]}],
    }))  # fmt: skip
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0)
    assert m.size == shape and m.title == "Wide" and m.loudness == -14
