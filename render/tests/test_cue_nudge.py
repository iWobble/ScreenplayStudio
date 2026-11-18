"""A cue's nudge (v216): a sound or a camera move on a word, moved later (+) or earlier (-) than the word puts it, from the Timeline's Sounds lane
(the cue row's `nudge`) or the note (`[[Sound: clang | Camera: punch | Nudge: 0.1]]`). An overlay picture is not moved by it."""

from pathlib import Path

import pytest

from storyrender import build, fountain, manifest, marvin_pull, script
from storyrender.manifest import Line, Manifest, Sfx, Shot
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone


def _plan(*shots: Shot) -> manifest.Timeline:
    return manifest.plan(Manifest("t", (180, 320), 24, list(shots)))


def _host(nudge: float, at: float = 1.0) -> Shot:
    sound = Sfx(Path("x.wav"), duration=0.3, line="l1", line_at=at, line_nudge=nudge)
    return Shot("b", Path(), lines=[Line("w", duration=3.0, ref="l1")], sfx=[sound], camera_cues=[{"kind": "punch", "line": "l1", "at": at, **({"nudge": nudge} if nudge else {})}])


def test_a_nudge_moves_the_cue_sound_and_its_camera_move_later_or_earlier_than_the_word():
    before = Shot("a", Path(), lines=[Line("v", duration=2.0, ref="l0")])
    for nudge in (0.0, 0.25, -0.4):
        t = _plan(before, _host(nudge))
        word = t.shots[1].lines[0].start + 1.0  # the end of the word before the note
        assert t.shots[1].audio_start + t.shots[1].sfx_at[0] == pytest.approx(word + nudge)
        assert t.shots[1].start + t.shots[1].camera[0][0] == pytest.approx(word + nudge)
        assert "nudge" not in t.shots[1].camera[0][1]


def test_a_nudge_never_starts_a_sound_before_the_film_nor_a_camera_move_before_its_beats_picture():
    t = _plan(_host(-5.0, at=0.5))
    assert t.shots[0].audio_start + t.shots[0].sfx_at[0] == 0.0
    before = Shot("a", Path(), lines=[Line("v", duration=2.0, ref="l0")])
    t = _plan(before, _host(-2.0, at=0.2))
    assert t.shots[1].audio_start + t.shots[1].sfx_at[0] == pytest.approx(t.shots[1].lines[0].start + 0.2 - 2.0)  # a sound may reach back
    assert t.shots[1].camera == [(0.0, {"kind": "punch"})] and t.shots[0].camera == []  # the move waits for its own picture


def test_an_overlay_picture_is_placed_by_its_own_beat_and_not_by_a_nudge():
    assert marvin_pull._cue_nudge({"pic": "s-beat-01a", "nudge": 0.5}) == {"nudge": 0.5}  # (the pull only gives it to the sound and the camera)
    assert marvin_pull._starts_during({"starts_during": {"line": "l", "word": 1}, "nudge": 9}, {"l": {"text": "a b", "words": []}}, []) == {"line": "l", "share": 0.6667}  # at the start of "b", as without a nudge


def test_the_pull_gives_the_cue_rows_nudge_to_its_sound_and_camera_move():
    heard = {"l": {"text": "The hammer strikes the wheel.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("The hammer strikes the wheel.".split())]}}
    beat = {"cues": [{"line": "l", "word": 3, "camera": {"kind": "punch"}, "nudge": -0.1}, {"line": "l", "word": 4, "camera": {"kind": "shake"}}]}
    assert marvin_pull._camera_cues(beat, heard, []) == [{"kind": "punch", "line": "l", "line_at": 1.4, "nudge": -0.1}, {"kind": "shake", "line": "l", "line_at": 1.9}]


def test_the_note_reads_the_nudge_beside_a_sound_or_camera_and_the_complete_script_writes_it_back():
    text = "INT. FORGE - DAY\n\nSparks.\n\nSMITH\nThe hammer strikes [[Sound: clang | Camera: punch | Nudge: 0.1]] the wheel [[Sound: ring | Nudge: -0.25s]] hard.\n"
    (_c, number, beat), = fountain.cut(fountain.parse(text, lines=True), text=text).rows()
    assert beat["lines"][0]["text"] == "The hammer strikes the wheel hard."
    cues = fountain.beat_cues(beat, "s", number, {})
    assert [(c["word"], c.get("nudge")) for c in cues] == [(3, 0.1), (5, -0.25)]
    sounds = {"s-sound-01-1": {"slug": "s-sound-01-1", "dataJson": {"prompt": "clang"}}, "s-sound-01-2": {"slug": "s-sound-01-2", "dataJson": {"prompt": "ring"}}}
    records = {"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Sparks.", "cues": cues}}],
               "lines": {"s-beat-01": [{"slug": "s-line-01-1", "dataJson": {"speaker": "smith", "text": beat["lines"][0]["text"]}}]}, "scenes": {}, "sounds": sounds, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip
    exported = script.fountain_complete(records)
    assert "The hammer strikes [[Sound: clang | Camera: punch | Nudge: 0.1]] the wheel [[Sound: ring | Nudge: -0.25]] hard." in exported
    (_c, _n, again), = fountain.cut(fountain.parse(exported, lines=True), text=exported).rows()
    assert fountain.beat_cues(again, "s", "01", {}) == cues


@pytest.mark.parametrize("note", ["[[Nudge: -0.4]]", "[[Pic: a door | Nudge: 0.2]]", "[[Sound: a | Nudge: soon]]"])
def test_a_nudge_alone_with_a_pic_or_without_a_number_is_no_cue(note):
    assert fountain.cue_parts(note[2:-2]) is None


@needs_ffmpeg
def test_the_render_plays_the_sound_at_its_word_plus_the_nudge(tmp_path):
    voice, clang = _tone(tmp_path / "v.wav", 3.0, 440), _tone(tmp_path / "c.wav", 0.3, 1320)
    still = _colour(tmp_path / "grey.png", "gray")
    shot = Shot("a", still, lines=[Line("w", voice, 3.0, ref="l1")], lead=0.2, sfx=[Sfx(clang, duration=0.3, line="l1", line_at=1.0, line_nudge=0.5)], move_to=manifest.Move())
    film = tmp_path / "film.mp4"
    build.render(Manifest("t", (180, 320), 24, [shot], loudnorm=False), film, draft=True)
    sound = _samples(film)
    assert _strength(sound, 1.35, 1320) < 0.01 < _strength(sound, 1.85, 1320)  # at 0.2 + 1.0 + 0.5 s, not at the word


def test_the_manifest_reads_a_cues_nudge_on_its_sound_and_camera_move(tmp_path):
    import json

    (tmp_path / "x.wav").write_bytes(b"")
    raw = {"shots": [{"id": "a", "lines": [{"duration": 2.0, "text": "w", "id": "l1"}], "sfx": [{"audio": "x.wav", "line": "l1", "line_at": 0.5, "nudge": -0.2}],
                      "camera_cues": [{"kind": "shake", "line": "l1", "line_at": 0.5, "nudge": 0.3}]}]}  # fmt: skip
    (tmp_path / "m.json").write_text(json.dumps(raw))
    shot = manifest.load(tmp_path / "m.json", probe=lambda _p: 0.4, need_stills=False).shots[0]
    assert shot.sfx[0].line_nudge == -0.2 and shot.camera_cues[0]["nudge"] == 0.3
    raw["shots"][0]["sfx"][0]["nudge"] = 99
    (tmp_path / "m.json").write_text(json.dumps(raw))
    with pytest.raises(manifest.ManifestError):
        manifest.load(tmp_path / "m.json", probe=lambda _p: 0.4, need_stills=False)
