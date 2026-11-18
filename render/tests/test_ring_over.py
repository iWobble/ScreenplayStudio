"""A sound that rings over (v225): `ring: true` on a cue row or a placed sound plays it in full without lengthening its beat; it sounds on over the
beats after it. The last beat waits for every sound still ringing, so the film never cuts one off. A beat with no ringing sound is as it was."""

import json
from pathlib import Path

import pytest

from storyrender import build, ffmpeg, fountain, manifest, marvin_pull, script
from storyrender.manifest import Line, Manifest, Sfx, Shot
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone


def _plan(*shots: Shot, end_hold: float = 0.0) -> manifest.Timeline:
    return manifest.plan(Manifest("t", (180, 320), 24, list(shots), end_hold=end_hold))


def _strike(ring: bool, at: float = 0.5, seconds: float = 13.0) -> Sfx:
    return Sfx(Path("x.wav"), at=at, duration=seconds, ring=ring)


def test_a_ringing_sound_does_not_lengthen_its_beat_and_one_that_does_not_ring_still_does():
    after = (Shot("b", Path(), hold=2.0), Shot("c", Path(), hold=20.0))
    rung = _plan(Shot("a", Path(), hold=2.0, sfx=[_strike(True)]), *after)
    assert [p.duration for p in rung.shots] == [2.0, 2.0, 20.0]
    assert rung.shots[0].audio_start + rung.shots[0].sfx_at[0] == 0.5  # placed where it always was
    held = _plan(Shot("a", Path(), hold=2.0, sfx=[_strike(False)]), *after)
    assert [p.duration for p in held.shots] == [13.5, 2.0, 20.0]  # as before v225


def test_a_ringing_cue_on_a_word_is_placed_as_before_with_its_nudge_and_leaves_its_beat_its_own_length():
    def beat(ring: bool) -> Shot:
        return Shot("a", Path(), lines=[Line("w", duration=2.0, ref="l1")], sfx=[Sfx(Path("x.wav"), duration=13.0, line="l1", line_at=1.0, line_nudge=0.2, ring=ring)])

    rung, held = _plan(beat(True), Shot("b", Path(), hold=20.0)), _plan(beat(False), Shot("b", Path(), hold=20.0))
    assert rung.shots[0].sfx_at == held.shots[0].sfx_at == [pytest.approx(manifest.LEAD + 1.2)]
    assert rung.shots[0].duration == pytest.approx(manifest.LEAD + 2.0 + manifest.TAIL)
    assert held.shots[0].duration == pytest.approx(manifest.LEAD + 1.2 + 13.0)


def test_the_last_beat_waits_for_every_sound_still_ringing():
    # Rung on the beat before the last: the last one is held until it ends (13.5 s into the film), then the film's end hold.
    t = _plan(Shot("a", Path(), hold=2.0, sfx=[_strike(True)]), Shot("b", Path(), hold=2.0), end_hold=1.0)
    assert [p.duration for p in t.shots] == [2.0, 12.5] and t.duration == 14.5
    # Rung on the last beat itself: it lasts as a sound that does not ring would make it.
    rung = _plan(Shot("a", Path(), hold=2.0), Shot("b", Path(), hold=2.0, sfx=[_strike(True)]), end_hold=1.0)
    held = _plan(Shot("a", Path(), hold=2.0), Shot("b", Path(), hold=2.0, sfx=[_strike(False)]), end_hold=1.0)
    assert [p.duration for p in rung.shots] == [p.duration for p in held.shots] == [2.0, 14.5]
    # One that ends before the last beat does changes nothing.
    t = _plan(Shot("a", Path(), hold=2.0, sfx=[_strike(True, seconds=3.0)]), Shot("b", Path(), hold=4.0))
    assert [p.duration for p in t.shots] == [2.0, 4.0]


def test_a_look_of_the_ringing_beat_alone_plays_it_to_its_end():
    # A render of some beats lays its last beat as the film's last: a ringing sound on it is heard in full (it is not cut at the end of the range).
    assert _plan(Shot("a", Path(), hold=2.0, sfx=[_strike(True)])).duration == 13.5


def test_with_nothing_ringing_the_plan_is_what_it_was(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"")
    shots = [{"id": "a", "hold": 1, "sfx": [{"audio": "x.wav", "at": 0.5}]}, {"id": "b", "hold": 1, "sfx": [{"audio": "x.wav", "at": -0.2}]}]
    plans = []
    for flag in ({}, {"ring": False}, {"ring": "true"}):  # absent, false, or anything but true: no ring
        (tmp_path / "m.json").write_text(json.dumps({"shots": [{**s, "sfx": [{**fx, **flag} for fx in s["sfx"]]} for s in shots]}))
        m = manifest.load(tmp_path / "m.json", probe=lambda _p: 3.0, need_stills=False)
        assert not any(fx.ring for s in m.shots for fx in s.sfx)
        plans.append([(p.start, p.duration, p.sfx_at) for p in manifest.plan(m).shots])
    assert plans[0] == plans[1] == plans[2] == [(0.0, 3.5, [0.5]), (3.5, 2.8, [-0.2])]
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{**shots[0], "sfx": [{"audio": "x.wav", "at": 0.5, "ring": True}]}]}))
    assert manifest.load(tmp_path / "m.json", probe=lambda _p: 3.0, need_stills=False).shots[0].sfx[0].ring is True


def _three(tmp_path: Path, ring: bool, mix: list[dict] = ()) -> tuple[Manifest, list]:
    grey = _colour(tmp_path / "grey.png", "gray")
    strike = _tone(tmp_path / "s.wav", 3.5, 3300)
    shots = [
        Shot("a", grey, hold=1.0, sfx=[Sfx(strike, at=0.0, duration=3.5, ring=ring)], move_to=manifest.Move()),
        Shot("b", grey, hold=1.0, move_to=manifest.Move()),
        Shot("c", grey, hold=2.5, mix_cues=list(mix), move_to=manifest.Move()),
    ]
    m = Manifest("t", (180, 320), 24, shots, loudnorm=False)
    out = tmp_path / f"film-{ring}-{len(mix)}.mp4"
    build.render(m, out, draft=True)
    return m, _samples(out)


@needs_ffmpeg
def test_the_render_plays_a_ringing_sound_over_the_beats_after_it_and_dead_air_on_a_later_beat_silences_it(tmp_path):
    m, sound = _three(tmp_path, True)
    t = manifest.plan(m)
    assert [p.duration for p in t.shots] == [1.0, 1.0, 2.5] and not build.stays_in_its_shot(t)
    assert _strength(sound, 0.5, 3300) > 0.04 and _strength(sound, 1.5, 3300) > 0.04 and _strength(sound, 3.0, 3300) > 0.04  # over b and c
    assert _strength(sound, 4.0, 3300) < 0.01  # it ended at 3.5 s
    _m, hushed = _three(tmp_path, True, [{"kind": "dead-air", "seconds": 0.5, "at": 0.3}])  # from 2.3 s, on beat c
    assert _strength(hushed, 1.5, 3300) > 0.04 and _strength(hushed, 2.6, 3300) < 0.01 and _strength(hushed, 3.3, 3300) > 0.04


@needs_ffmpeg
def test_the_render_holds_the_last_beat_until_a_ringing_sound_ends(tmp_path):
    grey = _colour(tmp_path / "grey.png", "gray")
    strike = _tone(tmp_path / "s.wav", 3.0, 3300)
    shots = [Shot("a", grey, hold=1.0, sfx=[Sfx(strike, duration=3.0, ring=True)], move_to=manifest.Move()), Shot("b", grey, hold=1.0, move_to=manifest.Move())]
    out = tmp_path / "film.mp4"
    build.render(Manifest("t", (180, 320), 24, shots, loudnorm=False), out, draft=True)
    assert float(ffmpeg.probe(out)["format"]["duration"]) == pytest.approx(3.0, abs=0.1)
    assert _strength(_samples(out), 2.7, 3300) > 0.04


@needs_ffmpeg
def test_the_rough_cuts_timeline_says_which_sounds_ring(tmp_path):
    bang, tick = _tone(tmp_path / "bang.wav", 3.0, 3300), _tone(tmp_path / "tick.wav", 0.5, 880)
    shots = [Shot("a", Path(), hold=2.0, sfx=[Sfx(bang, duration=3.0, ref="bang", ring=True), Sfx(tick, duration=0.5, ref="tick")]), Shot("b", Path(), hold=2.0)]
    result = build.listen(Manifest("t", (180, 320), 24, shots, loudnorm=False), tmp_path / "cut.mp3")
    assert [(s["id"], s["end"], s.get("ring")) for s in result["timeline"][0]["sounds"]] == [("bang", 3.0, True), ("tick", 0.5, None)]


def test_the_pull_keeps_ring_on_a_placed_sound_and_on_a_cue_sound(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda *_a: tmp_path / "audio" / "sounds" / "s-sound-1.mp3")
    library = {"s-sound-1": {"slug": "s-sound-1", "dataJson": {"audio": "asset-1"}}}
    data = lambda e: e["dataJson"]  # noqa: E731
    placed = [{"sound": "s-sound-1", "at": 0.5, "ring": True}, {"sound": "s-sound-1", "at": 1}, {"sound": "s-sound-1", "ring": "yes"}]
    assert [fx.get("ring") for fx in marvin_pull._sound_effects(None, tmp_path, placed, library, data, [])] == [True, None, None]
    heard = {"l": {"text": "Lightning strikes the mast.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("Lightning strikes the mast.".split())]}}
    beat = {"cues": [{"line": "l", "word": 2, "sound": "s-sound-1", "ring": True, "nudge": 0.1}, {"line": "l", "word": 4, "sound": "s-sound-1"}]}
    effects = marvin_pull._cue_sounds(None, tmp_path, beat, library, data, [], heard, [])
    assert [(fx["line_at"], fx.get("nudge"), fx.get("ring")) for fx in effects] == [(0.9, 0.1, True), (1.9, None, None)]


def test_the_note_reads_ring_beside_a_sound_and_the_complete_script_writes_it_back():
    text = "INT. SHIP - NIGHT\n\nStorm.\n\nMATE\nLightning strikes [[Sound: thunder | Ring | Nudge: 0.1]] the mast [[Sound: crack]] now.\n"
    (_c, number, beat), = fountain.cut(fountain.parse(text, lines=True), text=text).rows()
    assert beat["lines"][0]["text"] == "Lightning strikes the mast now."
    cues = fountain.beat_cues(beat, "s", number, {})
    assert [(c["word"], c.get("ring"), c.get("nudge")) for c in cues] == [(2, True, 0.1), (4, None, None)]
    sounds = {"s-sound-01-1": {"slug": "s-sound-01-1", "dataJson": {"prompt": "thunder"}}, "s-sound-01-2": {"slug": "s-sound-01-2", "dataJson": {"prompt": "crack"}}}
    records = {"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Storm.", "cues": cues}}],
               "lines": {"s-beat-01": [{"slug": "s-line-01-1", "dataJson": {"speaker": "mate", "text": beat["lines"][0]["text"]}}]}, "scenes": {}, "sounds": sounds, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip
    exported = script.fountain_complete(records)
    assert "Lightning strikes [[Sound: thunder | Ring | Nudge: 0.1]] the mast [[Sound: crack]] now." in exported
    (_c, _n, again), = fountain.cut(fountain.parse(exported, lines=True), text=exported).rows()
    assert fountain.beat_cues(again, "s", "01", {}) == cues


@pytest.mark.parametrize("note", ["Ring", "Camera: punch | Ring", "Sound: a | Ring: yes", "Sound: a | Ring | Ring"])
def test_a_ring_alone_with_no_sound_or_with_words_is_no_cue(note):
    assert fountain.cue_parts(note) is None
