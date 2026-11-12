"""The story's own ambience bed (the waves that run under the whole film): a scene or a beat turns it down and muffles it without the bed ever
stopping (no fade out and in per scene), and the beds can go down under speech."""

import json
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest, marvin_pull
from storyrender.manifest import Line, Manifest, ManifestError, Shot
from tests.test_overlay_music import _at, _bed_db, _shot, _timeline, _tone, needs_ffmpeg


# ── what the beat and its scene say ─────────────────────────────────────────
def test_a_beats_own_level_wins_over_its_scenes_and_only_the_scene_says_indoors():
    scene = {"dataJson": {"story_ambience_volume": 0.1, "story_ambience_muffled": True}}
    assert marvin_pull.story_bed_in({}, scene) == {"bed_volume": 0.1, "bed_muffled": True}
    assert marvin_pull.story_bed_in({"story_ambience_volume": 0.02}, scene) == {"bed_volume": 0.02, "bed_muffled": True}  # the beat's, else the scene's
    assert marvin_pull.story_bed_in({"story_ambience_volume": 0}, scene)["bed_volume"] == 0  # 0 is silence, not "not set"
    assert marvin_pull.story_bed_in({"story_ambience_volume": 2}, None) == {}  # out of range: ignored
    assert marvin_pull.story_bed_in({}, {"dataJson": {"story_ambience_muffled": False}}) == {} and marvin_pull.story_bed_in({}, None) == {}


def _load(tmp_path: Path, shot: dict | None = None, **raw):
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "hum.mp3").write_bytes(b"x")
    body = {"shots": [{"id": "b01", "still": "b.png", "hold": 2, "lines": [], **(shot or {})}], "ambience": {"audio": "hum.mp3", "volume": 0.4}, **raw}
    (tmp_path / "m.json").write_text(json.dumps(body))
    return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_the_manifest_keeps_a_shots_bed_level_and_muffling_and_the_stories_ambience_ducking(tmp_path):
    m = _load(tmp_path, {"bed_volume": 0.1, "bed_muffled": True}, ambience_duck="light")
    assert (m.shots[0].bed_volume, m.shots[0].bed_muffled, m.ambience_duck) == (0.1, True, "light")
    plain = _load(tmp_path)
    assert (plain.shots[0].bed_volume, plain.shots[0].bed_muffled, plain.ambience_duck) == (None, False, "")


@pytest.mark.parametrize(("shot", "raw", "words"), [({"bed_volume": 1.5}, {}, "bed_volume is 0–1"), ({}, {"ambience_duck": "crushing"}, "ambience_duck is light or strong")])
def test_a_bad_bed_level_or_ducking_is_refused_with_the_manifest_error(tmp_path, shot, raw, words):
    with pytest.raises(ManifestError, match=words):
        _load(tmp_path, shot, **raw)


def test_the_story_asks_for_ambience_ducking_only_with_a_known_strength():
    assert [d for d in ("light", "strong", "none", "crushing", "") if d in ("light", "strong")] == ["light", "strong"]  # the puller's test of the same words


# ── the level and the muffling over the film ───────────────────────────────────
def test_nothing_set_leaves_the_bed_exactly_as_it_was():
    plain = _timeline(_shot("a", 4), _shot("b", 4))
    assert build.story_bed_level(plain, 0.4) is None and build.story_bed_muffle(plain) is None
    same = _timeline(_shot("a", 4, bed_volume=0.4), _shot("b", 4))  # a level equal to the story's is no change
    assert build.story_bed_level(same, 0.4) is None


def test_a_scene_turns_the_bed_down_and_it_eases_there_and_back_in_a_second_without_stopping():
    shots = _timeline(_shot("sea", 6), _shot("cabin", 6, bed_volume=0.1), _shot("hold", 6, bed_volume=0.03), _shot("sea2", 6))
    expr = build.story_bed_level(shots, 0.5)
    assert _at(expr, 2.0) == pytest.approx(0.5) and _at(expr, 9.0) == pytest.approx(0.1) and _at(expr, 15.0) == pytest.approx(0.03) and _at(expr, 21.0) == pytest.approx(0.5)
    assert _at(expr, 6.0) == pytest.approx(0.3)  # half way down on the cut itself: eased over a second, centred on it
    assert min(_at(expr, t / 10) for t in range(0, 240)) == pytest.approx(0.03)  # it only ever goes between the levels: never to silence and back
    assert "if(" not in expr  # smooth ramps, not steps


def test_muffling_eases_in_and_out_the_same_way_and_is_none_when_no_shot_is_indoors():
    indoors = _timeline(_shot("sea", 6), _shot("cabin", 6, bed_muffled=True), _shot("sea2", 6))
    expr = build.story_bed_muffle(indoors)
    assert _at(expr, 1.0) == pytest.approx(0.0) and _at(expr, 9.0) == pytest.approx(1.0) and _at(expr, 15.0) == pytest.approx(0.0)
    assert _at(expr, 6.0) == pytest.approx(0.5)
    assert build.story_bed_muffle(_timeline(_shot("a", 4))) is None


# ── the filter graph ───────────────────────────────────────────────────────────
def _graph(monkeypatch, tmp_path, timeline, *, duck: str = "", muffled_bed: bool = False) -> str:
    ran = []
    monkeypatch.setattr(build.ffmpeg, "run", lambda cmd, *a, **k: ran.append(cmd))
    bed = build.Ambience(tmp_path / "waves.mp3", 0.5)
    build._with_ambience(timeline, tmp_path / "narration.wav", story_bed=bed, ambience_duck=duck)
    return ran[0][ran[0].index("-filter_complex") + 1]


def test_a_bed_heard_from_inside_in_some_scenes_is_the_same_sound_twice_crossfaded_and_a_plain_bed_is_unchanged(monkeypatch, tmp_path):
    outdoors = _graph(monkeypatch, tmp_path, _timeline(_shot("a", 4), _shot("b", 4)))
    assert "asplit" not in outdoors and "lowpass" not in outdoors and "amix=inputs=2" in outdoors  # as before: one chain, no filter it did not have
    mixed = _graph(monkeypatch, tmp_path, _timeline(_shot("a", 4), _shot("b", 4, bed_muffled=True)))
    assert "asplit=2" in mixed and mixed.count("lowpass=f=700") == 1 and "amix=inputs=3" in mixed  # as it is, and low-passed: one input, two chains


def test_ambience_ducking_multiplies_the_beds_gain_by_the_dip_under_speech_and_is_absent_without_it(monkeypatch, tmp_path):
    timeline = _timeline(Shot("a", Path("a.png"), hold=0.0, lines=[Line("x", None, 2.0)]), _shot("b", 4))
    assert "*(1-" not in _graph(monkeypatch, tmp_path, timeline)
    ducked = _graph(monkeypatch, tmp_path, timeline, duck="strong")
    assert "*(1-0.880*" in ducked  # strong: the bed's gain falls to 0.12 inside a line


# ── real renders ───────────────────────────────────────────────────────────────
def _film(tmp_path: Path, hz: int, per_shot: list[dict], **top) -> tuple[Manifest, Path]:
    project = demo.make(tmp_path / "demo", size=(360, 640))
    _tone(project.parent / "waves.mp3", 40.0, hz)
    for voice in (project.parent / "audio").glob("*.wav"):  # the demo's stand-in voices are very quiet: bring them up to a speaking level, or the final loudness normalising lifts a ducked bed back
        louder = voice.with_name("louder.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-af", "volume=6", str(louder)], check=True)
        louder.replace(voice)
    raw = json.loads(project.read_text())
    raw["ambience"] = {"audio": "waves.mp3", "volume": 0.8, "fade_in": 0, "fade_out": 0}
    raw.update(top)
    for shot, extra in zip(raw["shots"], per_shot, strict=False):
        shot.update(extra)
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    out = tmp_path / "out.mp4"
    build.render(m, out, draft=True)
    return m, out


def _window(plan, i):
    shot = plan.shots[i]
    return shot.start + 1.3, max(0.2, min(shot.duration - 2.6, 1.0))  # clear of the one-second ramps at the cuts


@needs_ffmpeg
def test_a_scene_turns_the_story_bed_down_and_it_comes_back_with_the_bed_running_throughout(tmp_path):
    m, out = _film(tmp_path / "turned", 1500, [{}, {"bed_volume": 0.1}, {}])
    _, plain = _film(tmp_path / "plain", 1500, [{}, {}, {}])
    plan = manifest.plan(m)
    before, quiet, after = (_bed_db(out, *_window(plan, i)) for i in range(3))
    assert quiet == pytest.approx(before - 18.1, abs=3.0)  # 0.8 to 0.1: about 18 dB down
    assert after == pytest.approx(before, abs=1.5)  # and back, at the story's level
    assert before == pytest.approx(_bed_db(plain, *_window(plan, 0)), abs=1.0)  # the other scenes are exactly as without it


@needs_ffmpeg
def test_a_scene_heard_from_inside_muffles_the_story_bed_without_changing_its_level_and_it_comes_back(tmp_path):
    m, out = _film(tmp_path / "inside", 5000, [{}, {"bed_muffled": True}, {}])  # a 5 kHz bed: the low-pass at 700 Hz removes it
    plan = manifest.plan(m)
    before, inside, after = (_bed_db(out, *_window(plan, i), hz=5000) for i in range(3))
    assert inside < before - 25 and after > inside + 25  # through the wall, then out again
    # and a low bed (300 Hz) is not lost when it is muffled: the same window, with and without the muffling, is the same level (the low wash of the sea stays)
    m_low, low = _film(tmp_path / "low", 300, [{}, {"bed_muffled": True}, {}])
    _, open_air = _film(tmp_path / "open", 300, [{}, {}, {}])
    window = _window(manifest.plan(m_low), 1)
    assert _bed_db(low, *window, hz=300) == pytest.approx(_bed_db(open_air, *window, hz=300), abs=2.5)


@needs_ffmpeg
def test_ambience_ducking_dips_the_story_bed_under_a_spoken_line_by_a_set_amount(tmp_path):
    m, plain = _film(tmp_path / "plain", 1500, [{}, {}, {}])
    _, strong = _film(tmp_path / "strong", 1500, [{}, {}, {}], ambience_duck="strong")
    line = manifest.plan(m).shots[0].lines[0]
    window = (line.start + 0.5, min(1.0, line.line.duration - 0.8))
    assert _bed_db(strong, *window) == pytest.approx(_bed_db(plain, *window) - 18.4, abs=3.5)
    assert _bed_db(strong, *window) < _bed_db(plain, *window) - 12


def test_the_helpers_used_above_are_the_ones_the_music_tests_use():
    assert callable(subprocess.run) and callable(_tone)
