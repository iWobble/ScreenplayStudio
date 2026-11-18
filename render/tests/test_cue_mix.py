"""The mix and the captions at a word (v219): `[[Mix: dead-air 2]]` drops the beds, the music and the sounds already playing to silence for a while,
`[[Mix: duck 0.3 2]]` dips the music and the beds under; the voice is never touched. `[[Emphasis]]` shows the word after it bigger, in the captions."""

import json
import re
from pathlib import Path

import pytest

from storyrender import build, camera, captions, fountain, manifest, marvin_pull, script, validate
from storyrender.manifest import Ambience, Line, Manifest, Sfx, Shot
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone

VOICE, BED, MUSIC, CLANG = 440, 1500, 2200, 3300


def _film(tmp_path: Path, name: str, mix: list[dict], sfx: list[Sfx] = ()) -> list:
    voice, bed, music = _tone(tmp_path / "v.wav", 3.0, VOICE), _tone(tmp_path / "bed.wav", 5.0, BED), _tone(tmp_path / "m.wav", 5.0, MUSIC)
    shot = Shot("a", _colour(tmp_path / "grey.png", "gray"), lead=0.2, tail=0.5, lines=[Line("w", voice, 3.0, ref="l1")], mix_cues=mix, sfx=list(sfx), move_to=manifest.Move())
    film = Manifest("t", (180, 320), 24, [shot], loudnorm=False, music={"audio": str(music), "volume": 0.4}, ambience=Ambience(bed, 0.4))
    out = tmp_path / f"{name}.mp4"
    build.render(film, out, draft=True)
    return _samples(out)


@needs_ffmpeg
def test_dead_air_drops_the_beds_and_music_to_silence_and_brings_them_back_but_not_the_voice(tmp_path):
    plain = _film(tmp_path, "plain", [])
    dead = _film(tmp_path, "dead", [{"kind": "dead-air", "seconds": 1.0, "line": "l1", "at": 0.5}])  # from 0.7 s to 1.7 s, and back by 1.8
    for hz in (BED, MUSIC):
        assert _strength(dead, 1.2, hz) < 0.02 * _strength(plain, 1.2, hz)
        assert _strength(dead, 2.3, hz) == pytest.approx(_strength(plain, 2.3, hz), rel=0.05)
    assert _strength(dead, 1.2, VOICE) == pytest.approx(_strength(plain, 1.2, VOICE), rel=0.03)


@needs_ffmpeg
def test_a_duck_lowers_the_beds_and_music_by_its_amount(tmp_path):
    plain = _film(tmp_path, "plain", [])
    ducked = _film(tmp_path, "duck", [{"kind": "duck", "amount": 0.3, "seconds": 1.2, "line": "l1", "at": 0.5}])
    for hz in (BED, MUSIC):
        assert _strength(ducked, 1.3, hz) == pytest.approx(0.3 * _strength(plain, 1.3, hz), rel=0.1)
        assert _strength(ducked, 2.8, hz) == pytest.approx(_strength(plain, 2.8, hz), rel=0.05)
    assert _strength(ducked, 1.3, VOICE) == pytest.approx(_strength(plain, 1.3, VOICE), rel=0.03)


@needs_ffmpeg
def test_dead_air_silences_the_sounds_but_lets_its_own_ring(tmp_path):
    long_clang, own, later = _tone(tmp_path / "c1.wav", 2.5, CLANG), _tone(tmp_path / "c2.wav", 0.6, 600), _tone(tmp_path / "c3.wav", 0.4, 900)
    sounds = [Sfx(long_clang, at=0.0, duration=2.5), Sfx(own, duration=0.6, line="l1", line_at=0.5), Sfx(later, duration=0.4, line="l1", line_at=0.9)]
    dead = _film(tmp_path, "dead", [{"kind": "dead-air", "seconds": 1.0, "line": "l1", "at": 0.5}], sounds)  # the second on the dead air's own word
    assert _strength(dead, 1.2, CLANG) < 0.01 < _strength(dead, 0.5, CLANG)  # already playing: silenced
    assert _strength(dead, 1.0, 600) > 0.04  # its own sound rings (a tone at ffmpeg's own level is about 0.06)
    assert _strength(dead, 1.3, 900) < 0.01  # one that starts in the silence is silenced too


def test_only_a_sound_that_starts_with_the_dead_air_is_left_alone():
    dead = [(1.0, {"kind": "dead-air", "seconds": 1.0})]
    assert build._hushed(dead, 1.02, 0.5) == "" and build._hushed(dead, 3.0, 1.0) == "" and build._hushed(dead, 0.0, 0.9) == ""
    assert build._hushed(dead, 1.5, 0.2).startswith("volume='(1-1.0000*") and build._hushed(dead, 0.0, 1.5).startswith("volume=")
    assert build._hushed([(1.0, {"kind": "duck"})], 0.0, 5.0) == ""  # a duck leaves the sounds alone


def test_the_mix_gain_is_one_outside_its_window_and_absent_without_a_cue():
    assert build.mix_gain([], ("dead-air", "duck")) is None and build.mix_gain([(1.0, {"kind": "duck"})], ("dead-air",)) is None
    gain = build.mix_gain([(1.0, {"kind": "dead-air", "seconds": 2})], ("dead-air",))
    assert gain == "(1-1.0000*min(clip((t-1.0000)/0.1,0,1),clip((3.1000-t)/0.1,0,1)))"


def test_the_mix_is_checked_and_placed_on_the_films_clock(tmp_path):
    assert camera.mix_of({"kind": "Duck", "amount": 2, "seconds": 99}) == {"kind": "duck", "amount": 1.0, "seconds": 30.0}
    assert camera.mix_of({"kind": "dead-air", "amount": 0.5}) == {"kind": "dead-air"} and camera.mix_of({"kind": "hush"}) is None
    assert camera.mix_of({"kind": "duck", "seconds": "long"}) is None
    raw = {"shots": [{"id": "a", "lines": [{"duration": 2.0, "text": "w", "id": "l1"}], "mix_cues": [{"kind": "duck", "line": "l1", "line_at": 0.5, "nudge": -0.2}]}]}
    (tmp_path / "m.json").write_text(json.dumps(raw))
    shot = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False).shots[0]
    t = manifest.plan(Manifest("t", (180, 320), 24, [Shot("z", Path(), hold=1.0), shot]))
    assert t.mix == [(pytest.approx(1.0 + 0.3 + 0.5 - 0.2), {"kind": "duck"})] and t.shots[1].looks == []
    raw["shots"][0]["mix_cues"][0]["kind"] = "hush"
    (tmp_path / "m.json").write_text(json.dumps(raw))
    with pytest.raises(manifest.ManifestError, match="shot a mix cue 1"):
        manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


# --- emphasis in the captions ----------------------------------------------------------------------------------------------------------------------


def _timeline(scale: float | None = None, *, words: bool = True) -> manifest.Timeline:
    said = "The hammer strikes the wheel."
    timed = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(said.split())] if words else []
    stress = {"line": "l1", "at": 1.0, **({"scale": scale} if scale else {})}  # the start of "strikes"
    shot = Shot("a", Path(), lead=0.2, lines=[Line(said, Path("v.wav"), 2.5, speaker="Smith", ref="l1", words=timed)], emphasis_cues=[stress])
    return manifest.plan(Manifest("t", (1080, 1920), 30, [shot]))


def test_an_emphasised_word_is_bigger_and_highlighted_in_the_captions():
    text = captions.ass(_timeline(), (1080, 1920), {"style": "classic"})
    assert "The hammer {\\fscx130\\fscy130\\1c&H0000D4FF}strikes{\\fscx100\\fscy100\\1c&H00FFFFFF} the" in text
    tinted = captions.ass(_timeline(1.5), (1080, 1920), {"style": "box", "speakers": {"Smith": "#ff0000"}})
    assert "{\\fscx150\\fscy150\\1c&H0000D4FF}strikes{\\fscx100\\fscy100\\1c&H000000FF}" in tinted  # back to the speaker's colour
    swept = captions.ass(_timeline(), (1080, 1920), {"style": "highlight"})
    assert "{\\kf50}{\\fscx130\\fscy130}strikes{\\fscx100\\fscy100}" in swept
    assert "fscx" not in captions.ass(_timeline(), (1080, 1920), {"style": "none"}) and captions.srt(_timeline()).count("strikes") == 1


def test_an_emphasis_on_a_take_without_word_timings_finds_the_word_near_its_place():
    text = captions.ass(_timeline(words=False), (1080, 1920), {})
    assert text.count("fscx130") == 1 and "{\\fscx130\\fscy130\\1c&H0000D4FF}strikes" in text


def test_the_pull_places_an_emphasis_at_the_start_of_the_word_after_its_gap():
    heard = {"l": {"text": "The hammer strikes the wheel.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("The hammer strikes the wheel.".split())]}}
    beat = {"cues": [{"line": "l", "word": 2, "emphasis": True}, {"line": "l", "word": 3, "emphasis": {"scale": 1.6}, "nudge": 0.1}, {"line": "l", "word": 1, "emphasis": False},
                     {"line": "l", "word": 4, "mix": {"kind": "dead-air", "seconds": 2}}]}  # fmt: skip
    assert marvin_pull._emphasis_cues(beat, heard, []) == [{"line": "l", "line_at": 1.0}, {"scale": 1.6, "line": "l", "line_at": 1.5, "nudge": 0.1}]
    assert marvin_pull._mix_cues(beat, heard, []) == [{"kind": "dead-air", "seconds": 2.0, "line": "l", "line_at": 1.9}]


# --- the Fountain ----------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("words", ["dead-air", "dead-air 2", "duck", "duck 0.3", "duck 0.3 2", "duck 2s"])
def test_a_mix_note_reads_back_as_it_was_written(words):
    assert fountain.mix_words(fountain.mix_cue(words)) == words


TEXT = (
    "INT. FORGE - DAY\n\nSparks.\n\nSMITH\nThe hammer [[Emphasis]] strikes [[Sound: clang | Mix: dead-air 2]] the wheel [[Mix: duck 0.3 2 | Nudge: -0.1]]"
    " and [[Emphasis: 1.5 | Look: flash]] rests.\n"
)


def test_mix_and_emphasis_notes_reach_the_beats_cues_and_the_complete_script_writes_them_back():
    (_c, number, beat), = fountain.cut(fountain.parse(TEXT, lines=True), text=TEXT).rows()
    assert beat["lines"][0]["text"] == "The hammer strikes the wheel and rests."
    cues = fountain.beat_cues(beat, "s", number, {})
    assert [(c["word"], c.get("mix"), c.get("emphasis"), c.get("nudge")) for c in cues] == [
        (2, None, True, None), (3, {"kind": "dead-air", "seconds": 2.0}, None, None), (5, {"kind": "duck", "amount": 0.3, "seconds": 2.0}, None, -0.1), (6, None, {"scale": 1.5}, None)
    ]  # fmt: skip
    records = {"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Sparks.", "cues": cues}}],
               "lines": {"s-beat-01": [{"slug": "s-line-01-1", "dataJson": {"speaker": "smith", "text": beat["lines"][0]["text"]}}]}, "scenes": {},
               "sounds": {"s-sound-01-1": {"slug": "s-sound-01-1", "dataJson": {"prompt": "clang"}}}, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip
    exported = script.fountain_complete(records)
    assert "The hammer [[Emphasis]] strikes [[Sound: clang | Mix: dead-air 2]] the wheel [[Mix: duck 0.3 2 | Nudge: -0.1]] and [[Look: flash | Emphasis: 1.5]] rests." in exported
    (_c, _n, again), = fountain.cut(fountain.parse(exported, lines=True), text=exported).rows()
    assert fountain.beat_cues(again, "s", "01", {}) == cues


def test_the_check_takes_mix_and_emphasis_notes_as_cues():
    bare = re.sub(r" ?\[\[[^\]]*\]\]", "", TEXT)
    assert [(f.code, f.problem) for f in validate.check(TEXT)] == [(f.code, f.problem) for f in validate.check(bare)]
    assert fountain.cue_parts("Emphasis") == {"emphasis": ""} and fountain.cue_parts("Emphasis | Nudge: 0.1") == {"emphasis": "", "nudge": "0.1"}
    assert fountain.cue_parts("Emphasis: loudly") is None and fountain.cue_parts("Mix") is None


def test_a_film_with_every_new_cue_kind_keeps_its_own_settings(tmp_path):
    """None of the cue loops reuses a name the manifest's own settings are read from (v212 to v216 lost a film's size, title and loudness that way)."""
    on = {"line": "l1", "line_at": 0.5}
    shot = {
        "id": "a", "lines": [{"duration": 2.0, "text": "w", "id": "l1"}],
        "camera_cues": [{"kind": "whip-pan", "x": -1, **on}, {"kind": "sway", "seconds": 2, **on}],
        "look_cues": [{"kind": k, **on} for k in camera.LOOKS],
        "mix_cues": [{"kind": k, **on} for k in camera.MIXES],
        "emphasis_cues": [{"scale": 1.5, **on}],
    }  # fmt: skip
    (tmp_path / "m.json").write_text(json.dumps({"title": "Wide", "size": [1920, 1080], "loudness": -14, "caption": {"style": "box"}, "end_fade": 2, "shots": [shot]}))
    film = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)
    assert (film.title, film.size, film.loudness, film.caption, film.end_fade) == ("Wide", (1920, 1080), -14.0, {"style": "box"}, 2.0)
    loaded = film.shots[0]
    assert len(loaded.camera_cues) == 2 and len(loaded.look_cues) == len(camera.LOOKS) and len(loaded.mix_cues) == 2 and len(loaded.emphasis_cues) == 1
