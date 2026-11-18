"""A picture lead and a line's nudge: the sound is laid out first and the pictures are cut from it, so a picture can come before its words while the
line before is still spoken, and a line can be moved earlier or later (two voices overlapping). Nothing changes when neither is set."""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from storyrender import build, captions, ffmpeg, jobs, manifest, marvin_pull
from storyrender.manifest import Line, Manifest, Shot
from tests.test_listen_pull import marvin  # noqa: F401  (the fake Marvin the pull reads)
from tests.test_overlay_music import needs_ffmpeg
from tests.test_transitions import _pulled, _rgb


def _spoken(sid: str, *seconds: float, lead: float | None = None, nudges: tuple[float, ...] = (), **kw) -> Shot:
    lines = [Line(f"{sid} line {i}", duration=s, nudge=(nudges[i] if i < len(nudges) else 0.0), ref=f"{sid}-{i}") for i, s in enumerate(seconds)]
    return Shot(sid, Path(), lines=lines, lead=0.3, gap=0.25, tail=0.35, picture_lead=lead, **kw)


def _plan(*shots: Shot) -> manifest.Timeline:
    return manifest.plan(Manifest("t", (360, 640), 24, list(shots)))


def test_with_no_picture_lead_the_pictures_are_the_sounds_windows_as_before():
    t = _plan(_spoken("a", 2.0, 1.0), Shot("b", Path(), hold=3.0), _spoken("c", 1.5))
    assert [(s.start, s.duration) for s in t.shots] == [(s.audio_start, s.audio_duration) for s in t.shots]
    assert [s.start for s in t.shots] == [0.0, 0.3 + 2.0 + 0.25 + 1.0 + 0.35, 0.3 + 2.0 + 0.25 + 1.0 + 0.35 + 3.0]


def test_a_picture_lead_brings_the_picture_that_long_before_its_first_word_and_the_sound_and_the_length_stay():
    plain = _plan(_spoken("a", 2.0), _spoken("b", 1.0))
    led = _plan(_spoken("a", 2.0), _spoken("b", 1.0, lead=0.8))
    first_word = led.shots[1].lines[0].start
    assert first_word == plain.shots[1].lines[0].start == 2.65 + 0.3  # the sound did not move
    assert led.shots[1].start == pytest.approx(first_word - 0.8)  # 0.5 s into the tail and lead-in before it: the voice of a runs on under b's picture
    assert led.shots[1].audio_start == plain.shots[1].start
    assert led.shots[0].duration == pytest.approx(2.65 - 0.5) and led.shots[0].start == 0.0
    assert led.duration == pytest.approx(plain.duration)  # the film is as long either way
    assert sum(s.duration for s in led.shots) == pytest.approx(led.duration)


def test_a_lead_shorter_than_the_lead_in_brings_the_picture_later_and_0_is_at_the_first_word():
    t = _plan(_spoken("a", 2.0), _spoken("b", 1.0, lead=0.0))
    assert t.shots[1].start == pytest.approx(t.shots[1].lines[0].start)


def test_a_silent_beat_with_a_lead_comes_that_long_before_it_starts_and_keeps_its_hold_on_screen():
    t = _plan(_spoken("a", 2.0), Shot("b", Path(), hold=3.0, picture_lead=0.8), _spoken("c", 1.0, lead=0.8))
    assert t.shots[1].start == pytest.approx(t.shots[1].audio_start - 0.8)
    assert t.shots[1].duration == pytest.approx(3.0 + 0.3)  # its hold, and the lead-in before c's first word
    assert t.shots[1].duration >= 3.0


def test_a_picture_is_never_brought_before_the_film_starts_or_closer_than_the_least_after_the_one_before():
    t = _plan(_spoken("a", 0.2), _spoken("b", 0.2, lead=3.0), _spoken("c", 0.2, lead=3.0))
    assert t.shots[0].start == 0.0
    assert t.shots[1].start == pytest.approx(manifest.MIN_PICTURE)
    assert t.shots[2].start == pytest.approx(2 * manifest.MIN_PICTURE)
    assert all(s.duration > 0 for s in t.shots)


def test_a_dissolve_with_a_lead_is_centred_on_the_new_boundary():
    t = _plan(_spoken("a", 3.0), _spoken("b", 2.0, lead=0.8, transition="dissolve", transition_seconds=0.8))
    fps = 24
    edges = build.edges_of(t, fps)
    assert edges[0].blend_out == edges[1].blend_in == round(0.8 * fps / 2)
    assert build.clip_frames(t.shots[0], fps) == round(t.shots[1].start * fps)  # the first clip ends at the new boundary, so the dissolve is centred on it


def test_a_nudge_moves_a_line_and_the_lines_after_it_follow_where_it_now_ends():
    t = _plan(_spoken("a", 2.0, 1.0, 1.0, nudges=(0.0, 0.5, -0.1)))
    starts = [p.start for p in t.shots[0].lines]
    assert starts == pytest.approx([0.3, 0.3 + 2.0 + 0.25 + 0.5, 0.3 + 2.0 + 0.25 + 0.5 + 1.0 + 0.25 - 0.1])
    assert t.duration == pytest.approx(starts[-1] + 1.0 + 0.35)


def test_a_negative_nudge_overlaps_the_line_before_and_the_shot_lasts_until_its_last_line_ends():
    t = _plan(_spoken("a", 2.0, 0.5, nudges=(0.0, -2.0)))  # the second line starts 1.75 s into the first: it is wholly under it
    first, second = t.shots[0].lines
    assert second.start == pytest.approx(first.start + 2.0 + 0.25 - 2.0)
    assert t.duration == pytest.approx(first.start + 2.0 + 0.35)  # the first line ends last
    assert manifest.overlaps(t) == [("a-0", "a-1", 0.5)]
    assert manifest.overlaps(_plan(_spoken("a", 2.0, 0.5, nudges=(0.0, -0.5)))) == []  # an interruption that runs on past the line before is not reported


def test_a_nudge_into_the_beat_before_brings_its_picture_with_its_voice_and_never_before_0():
    t = _plan(_spoken("a", 2.0), _spoken("b", 1.0, nudges=(-1.0,)))
    assert t.shots[1].lines[0].start == pytest.approx(2.65 + 0.3 - 1.0)
    assert t.shots[1].start == pytest.approx(t.shots[1].lines[0].start)  # no lead set: the picture comes with the first word, never after it
    early = _plan(_spoken("a", 1.0, nudges=(-5.0,)))
    assert early.shots[0].lines[0].start == 0.0


def test_captions_follow_the_nudged_lines():
    t = _plan(_spoken("a", 2.0, 1.0, nudges=(0.0, -0.6)))
    cues = captions.cues(t)
    assert [round(c[1], 3) for c in cues] == [0.3, round(0.3 + 2.0 + 0.25 - 0.6, 3)]


def test_the_manifest_reads_a_picture_lead_and_a_nudge_and_refuses_ones_out_of_range(tmp_path):
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], check=True)

    def load(shot: dict) -> manifest.Manifest:
        (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "a", "lines": [{"audio": "a.wav", "text": "x", **shot.pop("line", {})}], **shot}]}))
        return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)

    m = load({"picture_lead": 0.8, "line": {"nudge": -0.4}})
    assert m.shots[0].picture_lead == 0.8 and m.shots[0].lines[0].nudge == -0.4
    plain = load({})
    assert plain.shots[0].picture_lead is None and plain.shots[0].lines[0].nudge == 0.0
    for bad in ({"picture_lead": 9}, {"picture_lead": -1}, {"line": {"nudge": 20}}, {"line": {"nudge": "soon"}}):
        with pytest.raises(manifest.ManifestError):
            load(bad)


def test_the_pull_takes_the_beats_timing_else_the_storys_and_the_lines_nudge(marvin, tmp_path):  # noqa: F811
    story = {"line_lead": 0.05, "line_gap": 0.12, "line_tail": 0.1, "picture_lead": 0.8}
    shots = _pulled(marvin, tmp_path, story, lead_seconds=0.5, picture_lead=0)["shots"]
    assert (shots[0]["lead"], shots[0]["gap"], shots[0]["tail"], shots[0]["picture_lead"]) == (0.5, 0.12, 0.5, 0.0)  # the beat's own wins; 0 is a value
    assert all(s.get("picture_lead") == 0.8 and s.get("lead") == 0.05 for s in shots[1:] if s.get("lines"))
    plain = _pulled(marvin, tmp_path / "plain", {})["shots"]
    assert (plain[0]["lead"], plain[0]["tail"]) == (2.5, 0.5) and "gap" not in plain[0]  # the fake's first beat sets its own
    assert not any(k in s for s in plain[1:] for k in ("lead", "gap", "tail")) and not any("picture_lead" in s for s in plain)  # nothing set: as before
    assert marvin_pull.timing_of({}, {"picture_lead": "", "line_gap": "x"}) == {}


def test_the_encodes_follow_a_slow_move_over_a_textured_still_and_the_marvin_copy_stays_under_its_limit():
    assert build.final_video_args(True)[:6] == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]  # a draft is no longer ultrafast at 28
    assert build.final_video_args(False)[:6] == ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    flags = dict(zip(jobs.PREVIEW_ENCODE[::2], jobs.PREVIEW_ENCODE[1::2], strict=True))
    assert flags["-crf"] == "22" and flags["-preset"] == "medium" and flags["-maxrate"] == "2.2M"
    video, sound = float(flags["-maxrate"][:-1]), float(flags["-b:a"][:-1]) / 1000
    assert (video + sound) * 300 / 8 < 100  # MB for a 5-minute film at the most: under Marvin's 100 MB upload


def _tone(path: Path, seconds: float, hz: int) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}:sample_rate=48000", "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def _colour(path: Path, rgb: str) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={rgb}:s=90x160", "-frames:v", "1", str(path)], check=True)
    return path


def _samples(film: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(film), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def _strength(samples: np.ndarray, at: float, hz: int, span: float = 0.08) -> float:
    """How much of `hz` is in the sound around `at` seconds."""
    piece = samples[int((at - span / 2) * 48000) : int((at + span / 2) * 48000)]
    t = np.arange(len(piece)) / 48000
    return float(abs(np.dot(piece, np.exp(-2j * np.pi * hz * t))) / max(len(piece), 1))


@needs_ffmpeg
@pytest.mark.parametrize("group", [32, 1])  # every sound in one mix, and in groups mixed together (a long film)
def test_the_voice_runs_on_across_a_picture_that_comes_before_its_words(tmp_path, monkeypatch, group):
    monkeypatch.setattr(build, "MIX_INPUTS", group)
    a, b = _tone(tmp_path / "a.wav", 2.0, 440), _tone(tmp_path / "b.wav", 1.0, 880)
    red, blue = _colour(tmp_path / "red.png", "red"), _colour(tmp_path / "blue.png", "blue")
    shots = [
        Shot("a", red, lines=[Line("a", a, 2.0)], lead=0.05, gap=0.12, tail=0.1, move_to=manifest.Move()),
        Shot("b", blue, lines=[Line("b", b, 1.0)], lead=0.05, gap=0.12, tail=0.1, move_to=manifest.Move(), picture_lead=0.8),
    ]
    m = Manifest("t", (180, 320), 24, shots, loudnorm=False)
    t = manifest.plan(m)
    boundary, words = t.shots[1].start, t.shots[1].lines[0].start
    assert words - boundary == pytest.approx(0.8) and boundary < 2.05  # the picture changes while a is still speaking (it ends at 2.05)
    assert not build.stays_in_its_shot(t)
    film = tmp_path / "film.mp4"
    build.render(m, film, draft=True, keep=tmp_path / "work")
    assert _rgb(film, boundary - 0.15)[0] > 150 and _rgb(film, boundary + 0.15)[2] > 150  # red, then blue at the boundary
    sound = _samples(film)
    for at in (boundary - 0.2, boundary, boundary + 0.2, 2.0):
        assert _strength(sound, at, 440) > 0.03, at  # a's voice goes on through the picture change, to its end
    assert _strength(sound, words - 0.1, 880) < 0.01 < _strength(sound, words + 0.1, 880)  # b's voice starts at its own place, not with its picture
    assert float(ffmpeg.probe(film)["format"]["duration"]) == pytest.approx(t.duration, abs=0.1)


@needs_ffmpeg
def test_two_nudged_voices_overlap_in_the_sound(tmp_path):
    a, b = _tone(tmp_path / "a.wav", 1.5, 440), _tone(tmp_path / "b.wav", 1.0, 880)
    still = _colour(tmp_path / "grey.png", "gray")
    shot = Shot("a", still, lines=[Line("a", a, 1.5), Line("b", b, 1.0, nudge=-0.85)], lead=0.3, gap=0.25, tail=0.35, move_to=manifest.Move())
    m = Manifest("t", (180, 320), 24, [shot], loudnorm=False)
    t = manifest.plan(m)
    second = t.shots[0].lines[1].start
    assert second == pytest.approx(0.3 + 1.5 + 0.25 - 0.85)  # 0.6 s before the first line ends
    film = tmp_path / "film.mp4"
    build.render(m, film, draft=True)
    sound = _samples(film)
    both = second + 0.3
    assert _strength(sound, both, 440) > 0.03 and _strength(sound, both, 880) > 0.03  # both voices at once
    assert _strength(sound, second - 0.2, 880) < 0.01
