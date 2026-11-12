"""The music's level and fades, set like the ambience's: the beat's own, else its scene's, else the story's, else the sound's."""

import json
from pathlib import Path

import pytest

from storyrender import build, manifest, marvin_pull
from storyrender.manifest import Manifest, ManifestError
from tests.test_overlay_music import DATA, _at, _shot, _timeline


def test_a_beats_music_level_is_its_own_else_its_scenes_and_nothing_when_neither_says():
    assert marvin_pull.music_in({"music_volume": 0.3}, {"music_volume": 0.6}) == {"music_volume": 0.3}  # the beat wins
    assert marvin_pull.music_in({}, {"music_volume": 0.6}) == {"music_volume": 0.6}  # else the scene's
    assert marvin_pull.music_in({"music_volume": 0}, {"music_volume": 0.6}) == {"music_volume": 0}  # 0 is silence, not "unset"
    assert marvin_pull.music_in({"music_volume": ""}, {}) == {} and marvin_pull.music_in({}, {}) == {}  # the story's level is the bed's
    assert marvin_pull.music_in({"music_volume": 1.5}, {"music_volume": 0.6}) == {"music_volume": 0.6}  # out of range is as empty


def test_a_beats_music_fades_are_passed_only_when_set_above_zero():
    assert marvin_pull.music_in({"music_fade_in": 3, "music_fade_out": 1.5}, {}) == {"music_fade_in": 3.0, "music_fade_out": 1.5}
    assert marvin_pull.music_in({"music_fade_in": 0, "music_fade_out": ""}, {}) == {}


def _music(tmp_path, monkeypatch, sound: dict, **story):
    row = {"slug": "theme", "dataJson": {"kind": "music", "audio": "asset-1", **sound}}
    monkeypatch.setattr(marvin_pull.marvin_api, "query", lambda creds, spec, limit=100: [row])
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / "theme.mp3")
    return marvin_pull.music_of(("u", "t"), tmp_path, {"music": "theme", **story}, DATA)


def test_the_stories_music_level_is_its_own_else_the_sounds_else_a_tenth(tmp_path, monkeypatch):
    assert _music(tmp_path, monkeypatch, {"volume": 0.4}, music_volume=0.2)["volume"] == 0.2
    assert _music(tmp_path, monkeypatch, {"volume": 0.4})["volume"] == 0.4
    assert _music(tmp_path, monkeypatch, {})["volume"] == 0.12
    assert _music(tmp_path, monkeypatch, {"volume": 0.4}, music_volume=0)["volume"] == 0  # the story can silence it
    assert _music(tmp_path, monkeypatch, {"volume": 0.4}, music_volume=7)["volume"] == 0.4  # out of range: the sound's


def test_the_stories_music_fades_are_kept_apart_from_the_sounds_own(tmp_path, monkeypatch):
    got = _music(tmp_path, monkeypatch, {"fade_in": 1, "fade_out": 2}, music_fade_in=4, music_fade_out=6)
    assert (got["fade_in"], got["fade_out"], got["story_fade_in"], got["story_fade_out"]) == (1.0, 2.0, 4.0, 6.0)
    plain = _music(tmp_path, monkeypatch, {"fade_out": 2})
    assert "story_fade_in" not in plain and "story_fade_out" not in plain


def _load(tmp_path: Path, shot: dict | None = None, music: dict | None = None) -> Manifest:
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "bed.mp3").write_bytes(b"x")
    body = {"shots": [{"id": "b01", "still": "a.png", "hold": 2, **(shot or {})}], **({"music": {"audio": "bed.mp3", **music}} if music else {})}
    (tmp_path / "m.json").write_text(json.dumps(body))
    return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_the_manifest_keeps_a_shots_music_fades_and_the_musics_story_fades(tmp_path):
    m = _load(tmp_path, {"music_fade_in": 2.5, "music_fade_out": 1}, {"story_fade_in": 3, "story_fade_out": 5})
    assert (m.shots[0].music_fade_in, m.shots[0].music_fade_out) == (2.5, 1.0)
    assert (m.music["story_fade_in"], m.music["story_fade_out"]) == (3, 5)
    plain = _load(tmp_path)
    assert (plain.shots[0].music_fade_in, plain.shots[0].music_fade_out) == (None, None)


@pytest.mark.parametrize(("shot", "music"), [({"music_fade_in": -1}, None), ({"music_fade_out": 99}, None), (None, {"story_fade_out": 99})])
def test_a_bad_music_fade_is_refused_with_the_manifest_error(tmp_path, shot, music):
    with pytest.raises(ManifestError, match="seconds"):
        _load(tmp_path, shot, music)


def test_a_beats_own_fade_sets_how_long_the_music_takes_to_reach_its_level():
    # a (4 s, story level), b (6 s, level 0.0, takes 3 s to fade in), c (4 s, story level, takes the default back)
    expr = build.music_level(_timeline(_shot("a", 4), _shot("b", 6, music_volume=0.0, music_fade_in=3.0), _shot("c", 4)), 0.2)
    assert _at(expr, 4 - 1.5) == pytest.approx(0.2) and _at(expr, 4.0) == pytest.approx(0.1) and _at(expr, 4 + 1.5) == pytest.approx(0.0)  # 3 s ramp centred on the cut
    assert _at(expr, 10.0) == pytest.approx(0.1) and _at(expr, 10.25) == pytest.approx(0.2)  # back up over the default half second


def test_a_beats_fade_out_is_used_when_the_next_beat_asks_for_none():
    expr = build.music_level(_timeline(_shot("a", 6, music_volume=0.0, music_fade_out=4.0), _shot("b", 6)), 0.2)
    assert _at(expr, 6.0) == pytest.approx(0.1) and _at(expr, 4.0) == pytest.approx(0.0) and _at(expr, 8.0) == pytest.approx(0.2)  # 4 s ramp out of a


def test_the_next_beats_fade_in_beats_the_previous_beats_fade_out():
    expr = build.music_level(_timeline(_shot("a", 8, music_volume=0.0, music_fade_out=6.0), _shot("b", 8, music_fade_in=2.0)), 0.2)
    assert _at(expr, 7.0) == pytest.approx(0.0) and _at(expr, 9.0) == pytest.approx(0.2)  # 2 s, not 6


def test_no_fade_asked_for_leaves_the_default_half_second_ramp():
    expr = build.music_level(_timeline(_shot("a", 4), _shot("b", 4, music_volume=0.0)), 0.2)
    assert _at(expr, 3.75) == pytest.approx(0.2) and _at(expr, 4.25) == pytest.approx(0.0)
