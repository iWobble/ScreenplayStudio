"""A sound placed in a beat (its `sounds`, `at` seconds from the beat's start) may start before the beat (v222): a negative `at` reaches back into the
beat before, as a sound on a word already could (a strike of lightning that lands just before the picture). Never before the film starts."""

import json
from pathlib import Path

import pytest

from storyrender import build, manifest, marvin_pull
from storyrender.manifest import Line, Manifest, Sfx, Shot
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone


def _start(*shots: Shot) -> list[float]:
    t = manifest.plan(Manifest("t", (180, 320), 24, list(shots)))
    return [p.audio_start + at for p in t.shots for at in p.sfx_at]


def test_a_placed_sound_with_a_negative_at_starts_before_its_beat_but_never_before_the_film():
    before = Shot("a", Path(), hold=2.0)
    assert _start(before, Shot("b", Path(), hold=2.0, sfx=[Sfx(Path("x.wav"), at=-0.5, duration=0.3)])) == [pytest.approx(1.5)]
    assert _start(before, Shot("b", Path(), hold=2.0, sfx=[Sfx(Path("x.wav"), at=-999, duration=0.3)])) == [0.0]
    assert _start(Shot("a", Path(), hold=2.0, sfx=[Sfx(Path("x.wav"), at=-0.5, duration=0.3)])) == [0.0]  # the first beat: the film's start
    assert _start(before, Shot("b", Path(), hold=2.0, sfx=[Sfx(Path("x.wav"), at=0.4, duration=0.3)])) == [pytest.approx(2.4)]  # as it always was


def test_the_manifest_and_the_pull_keep_a_negative_at(tmp_path, monkeypatch):
    (tmp_path / "x.wav").write_bytes(b"")
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "a", "hold": 1}, {"id": "b", "hold": 1, "sfx": [{"audio": "x.wav", "at": -0.5}]}]}))
    assert manifest.load(tmp_path / "m.json", probe=lambda _p: 0.3, need_stills=False).shots[1].sfx[0].at == -0.5
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda *_a: tmp_path / "audio" / "sounds" / "s-sound-1.mp3")
    library = {"s-sound-1": {"slug": "s-sound-1", "dataJson": {"audio": "asset-1"}}}
    assert marvin_pull._sound_effects(None, tmp_path, [{"sound": "s-sound-1", "at": -0.5}], library, lambda e: e["dataJson"], [])[0]["at"] == -0.5


def _film(tmp_path: Path, at: float, mix: list[dict] = ()) -> list:
    grey = _colour(tmp_path / "grey.png", "gray")
    strike, voice = _tone(tmp_path / "s.wav", 2.0, 3300), _tone(tmp_path / "v.wav", 2.0, 440)
    first = Shot("a", grey, hold=2.0, move_to=manifest.Move())
    second = Shot("b", grey, lead=0.3, lines=[Line("w", voice, 2.0, ref="l1")], sfx=[Sfx(strike, at=at, duration=2.0)], mix_cues=list(mix), move_to=manifest.Move())
    out = tmp_path / f"film{at}.mp4"
    build.render(Manifest("t", (180, 320), 24, [first, second], loudnorm=False), out, draft=True)
    return _samples(out)


@needs_ffmpeg
def test_the_render_plays_a_negative_at_that_long_before_the_beat_and_its_dead_air_still_silences_it(tmp_path):
    sound = _film(tmp_path, -0.5)
    assert _strength(sound, 1.35, 3300) < 0.01 < _strength(sound, 1.65, 3300)  # from 1.5 s: half a second before beat b at 2.0
    hushed = _film(tmp_path, -0.5, [{"kind": "dead-air", "seconds": 0.6, "line": "l1", "at": 0.2}])  # from 2.5 s
    assert _strength(hushed, 1.8, 3300) > 0.04 and _strength(hushed, 2.9, 3300) < 0.01 and _strength(hushed, 2.9, 440) > 0.04
