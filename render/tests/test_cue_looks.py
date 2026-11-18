"""Looks and more camera moves on a word (v218): `[[Look: flash]]`, `[[Look: dip white 1.2]]`, `[[Look: tint sepia]]`… and `[[Camera: whip-pan left]]`,
`[[Camera: sway]]` among a line's words change the picture at the end of the word before the note, for a moment, without changing the film's length
or its sound. And a shake makes room for itself, so its amount shows at zoom 1."""

import json
import subprocess
from array import array
from pathlib import Path

import pytest

from storyrender import build, camera, fountain, manifest, marvin_pull, script, validate
from storyrender.manifest import Line, Manifest, Shot
from tests.test_camera_cues import _area, _centre_x, _square
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _tone

W, H, FPS = 160, 284, 24
STAY = (manifest.Move(), manifest.Move())


def _planned(still: Path, seconds: float, *, cues=(), looks=(), move=STAY) -> manifest.PlannedShot:
    shot = Shot("a", still, hold=seconds, move_from=move[0], move_to=move[1], camera_cues=list(cues), look_cues=list(looks))
    return manifest.plan(Manifest("t", (W, H), FPS, [shot])).shots[0]


def _frames(still: Path, seconds: float, *, cues=(), looks=(), move=STAY, pix="gray") -> list[array]:
    """Each frame of the shot's clip as the render makes it (the move, its cues, then its looks), as raw bytes: one per pixel, or three (rgb24)."""
    planned = _planned(still, seconds, cues=cues, looks=looks, move=move)
    looked = build.looks_filter(planned, (W, H))
    vf = build.zoompan_filter(planned, (W, H), FPS) + (f",{looked}" if looked else "")
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds}", "-i", str(still), "-vf", vf,
         "-frames:v", str(round(seconds * FPS)), "-f", "rawvideo", "-pix_fmt", pix, "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    size = W * H * (3 if pix == "rgb24" else 1)
    return [array("B", raw[i : i + size]) for i in range(0, len(raw), size)]


def _at(frames: list, seconds: float):
    return frames[round(seconds * FPS)]


def _mean(frame: array) -> float:
    return sum(frame) / len(frame)


def _channels(frame: array) -> tuple[float, float, float]:
    n = len(frame) // 3
    return sum(frame[0::3]) / n, sum(frame[1::3]) / n, sum(frame[2::3]) / n


def _sharpness(frame: array) -> float:
    """How hard the edges are: the steps between neighbours, squared (a blur spreads an edge into many small steps)."""
    return sum((frame[i + 1] - frame[i]) ** 2 for i in range(0, len(frame) - 1) if (i + 1) % W)


def _moved(frames: list, still: array) -> list[float]:
    return [sum(abs(a - b) for a, b in zip(f, still, strict=True)) / len(f) for f in frames]


# --- the shake's room (the bug of v212) and the new camera moves -------------------------------------------------------------------------------


@needs_ffmpeg
def test_a_shake_at_zoom_1_shows_its_amount(tmp_path):
    sq = _square(tmp_path / "sq.png")
    default_move = (manifest.Move(), manifest.Move(zoom=1.08))  # a beat's own move when it sets none: it starts at the whole picture

    def most(amount: float) -> float:
        xs = [_centre_x(f) for f in _frames(sq, 1.0, cues=[{"kind": "shake", "amount": amount, "at": 0.0}], move=default_move)]
        return max(abs(x - xs[0]) for x in xs[: round(0.35 * FPS)])

    small, big = most(1.2), most(3)
    assert big > 2.5 and big > 2 * small  # pixels of a 160-wide frame (3% is 4.8 at its height, sampled at 24 frames a second): both moved 1 px before


@needs_ffmpeg
def test_a_whip_pan_sweeps_its_way_much_further_than_a_punch_moves_and_comes_back(tmp_path):
    sq = _square(tmp_path / "sq.png")
    whip = _frames(sq, 1.5, cues=[{"kind": "whip-pan", "x": -1, "at": 0.3}])
    punch = _frames(sq, 1.5, cues=[{"kind": "punch", "at": 0.3}])
    rest = whip[0]
    assert max(_moved(whip, rest)) > 3 * max(_moved(punch, rest))
    xs = [_centre_x(f) for f in whip]
    assert max(xs[round(0.3 * FPS) : round(0.6 * FPS)]) > xs[0] + 15  # the camera looks left: the square goes right
    assert xs[round(1.2 * FPS)] == pytest.approx(xs[0], abs=0.5)  # and settles where it was


@needs_ffmpeg
def test_a_sway_wobbles_for_its_seconds_and_dies_away(tmp_path):
    sq = _square(tmp_path / "sq.png")
    xs = [_centre_x(f) for f in _frames(sq, 2.5, cues=[{"kind": "sway", "amount": 2, "seconds": 1.5, "at": 0.2}])]
    assert max(abs(x - xs[0]) for x in xs[: round(1.7 * FPS)]) > 1.5
    assert all(abs(x - xs[0]) < 0.3 for x in xs[round(1.75 * FPS) :])


def test_the_camera_cues_read_their_new_kinds_with_their_numbers_held_in_range():
    assert camera.cue_of({"kind": "whip-pan", "x": -3, "amount": 2}) == {"kind": "whip-pan", "x": -1, "amount": 0.5}
    assert camera.cue_of({"kind": "Whip-Pan"}) == {"kind": "whip-pan"}
    assert camera.cue_of({"kind": "sway", "amount": 1.5, "seconds": 99}) == {"kind": "sway", "amount": 1.5, "seconds": 10.0}
    assert camera.cue_of({"kind": "sway", "seconds": "slow"}) is None


# --- the looks ---------------------------------------------------------------------------------------------------------------------------------


@needs_ffmpeg
def test_a_flash_brightens_the_picture_at_its_word_and_falls_away(tmp_path):
    grey = _colour(tmp_path / "grey.png", "gray")
    frames = _frames(grey, 1.5, looks=[{"kind": "flash", "at": 0.5}])
    rest = _mean(_at(frames, 0.3))
    assert _mean(_at(frames, 0.55)) > rest + 80  # 0.9 of the way to white
    assert _mean(_at(frames, 0.9)) == pytest.approx(rest, abs=1)


@needs_ffmpeg
def test_a_burn_is_an_orange_flash(tmp_path):
    grey = _colour(tmp_path / "grey.png", "gray")
    r, _g, b = _channels(_at(_frames(grey, 1.0, looks=[{"kind": "burn", "at": 0.3}], pix="rgb24"), 0.36))
    assert r > b + 100


@needs_ffmpeg
def test_a_dip_reaches_black_halfway_and_comes_back(tmp_path):
    grey = _colour(tmp_path / "grey.png", "gray")
    frames = _frames(grey, 2.0, looks=[{"kind": "dip", "seconds": 0.8, "at": 0.5}])
    rest = _mean(_at(frames, 0.3))
    assert _mean(_at(frames, 0.9)) < 8 and _mean(_at(frames, 1.4)) == pytest.approx(rest, abs=1)
    white = _frames(grey, 2.0, looks=[{"kind": "dip", "color": "white", "at": 0.5}])
    assert _mean(_at(white, 0.9)) > 245


@needs_ffmpeg
def test_a_freeze_holds_the_move_then_carries_on(tmp_path):
    sq = _square(tmp_path / "sq.png")
    push = (manifest.Move(), manifest.Move(zoom=1.4))
    areas = [_area(f) for f in _frames(sq, 3.0, looks=[{"kind": "freeze", "seconds": 0.6, "at": 1.0}], move=push)]
    assert areas[round(1.05 * FPS)] == areas[round(1.55 * FPS)]  # held
    assert areas[round(2.2 * FPS)] > areas[round(1.6 * FPS)] > areas[round(0.5 * FPS)]  # moving before, and after


@needs_ffmpeg
def test_a_tint_shifts_the_colour_from_its_word_to_the_end_of_the_beat(tmp_path):
    blue = _colour(tmp_path / "blue.png", "0x3050d0")
    frames = _frames(blue, 1.5, looks=[{"kind": "tint", "color": "sepia", "at": 0.5}], pix="rgb24")
    before, after = _channels(_at(frames, 0.3)), _channels(_at(frames, 1.4))
    assert after[0] > before[0] + 40 and after[2] < before[2] - 40  # warm brown where it was blue
    mono = _channels(_at(_frames(blue, 1.0, looks=[{"kind": "tint", "color": "mono", "at": 0.2}], pix="rgb24"), 0.6))
    assert max(mono) - min(mono) < 6


@needs_ffmpeg
def test_a_blur_starts_soft_and_sharpens_again(tmp_path):
    sq = _square(tmp_path / "sq.png")
    frames = _frames(sq, 2.0, looks=[{"kind": "blur", "amount": 0.8, "seconds": 0.8, "at": 0.5}])
    rest = _sharpness(_at(frames, 0.3))
    assert _sharpness(_at(frames, 0.55)) < 0.3 * rest
    assert _sharpness(_at(frames, 1.5)) == pytest.approx(rest, rel=0.02)


@needs_ffmpeg
def test_a_vignette_darkens_the_edges_and_releases(tmp_path):
    grey = _colour(tmp_path / "grey.png", "gray")
    frames = _frames(grey, 2.0, looks=[{"kind": "vignette", "seconds": 1.0, "at": 0.5}])
    corner = [f[2 * W + 2] for f in frames]
    centre = [f[(H // 2) * W + W // 2] for f in frames]
    assert corner[round(0.85 * FPS)] < corner[round(0.3 * FPS)] - 40
    assert abs(centre[round(0.85 * FPS)] - centre[round(0.3 * FPS)]) < 6
    assert corner[round(1.7 * FPS)] == pytest.approx(corner[round(0.3 * FPS)], abs=1)


@needs_ffmpeg
def test_a_glitch_splits_the_colours_for_a_moment(tmp_path):
    sq = _square(tmp_path / "sq.png")
    frames = _frames(sq, 1.0, looks=[{"kind": "glitch", "at": 0.3}], pix="rgb24")

    def split(frame: array) -> float:  # how far red and blue have parted
        return sum(abs(frame[i] - frame[i + 2]) for i in range(0, len(frame), 3)) / (len(frame) / 3)

    assert split(_at(frames, 0.33)) > split(_at(frames, 0.1)) + 1.5  # the square's edges in red and blue, 2.5% of the frame apart
    assert split(_at(frames, 0.8)) == pytest.approx(split(_at(frames, 0.1)), abs=0.5)


def test_the_looks_are_checked_and_unknown_ones_refused():
    assert camera.look_of({"kind": "Flash", "amount": 3, "seconds": 0.01}) == {"kind": "flash", "amount": 1.0, "seconds": 0.05}
    assert camera.look_of({"kind": "dip", "color": "white", "amount": 0.5}) == {"kind": "dip", "color": "white"}  # a dip has no amount
    assert camera.look_of({"kind": "tint", "color": "Sepia"}) == {"kind": "tint", "color": "sepia"}
    for bad in ({"kind": "sparkle"}, {"kind": "tint", "color": "purple"}, {"kind": "dip", "color": "orange"}, {"kind": "blur", "amount": "lots"}, "flash"):
        assert camera.look_of(bad) is None


def test_the_manifest_refuses_a_bad_look_naming_it_and_plans_a_good_one_on_its_word(tmp_path):
    raw = {"shots": [{"id": "a", "lines": [{"duration": 2.0, "text": "w", "id": "l1"}], "look_cues": [{"kind": "flash", "line": "l1", "line_at": 0.5, "nudge": 0.25}]}]}
    (tmp_path / "m.json").write_text(json.dumps(raw))
    shot = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False).shots[0]
    assert shot.look_cues == [{"kind": "flash", "line": "l1", "at": 0.5, "nudge": 0.25}]
    t = manifest.plan(Manifest("t", (W, H), FPS, [shot]))
    assert t.shots[0].looks == [(pytest.approx(0.3 + 0.5 + 0.25), {"kind": "flash"})] and t.shots[0].camera == []
    raw["shots"][0]["look_cues"][0]["kind"] = "sparkle"
    (tmp_path / "m.json").write_text(json.dumps(raw))
    with pytest.raises(manifest.ManifestError, match="shot a look cue 1"):
        manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_a_look_lands_on_the_picture_that_is_up_at_its_word():
    host = Shot("a", Path(), lines=[Line("w", duration=4.0, ref="l1")], look_cues=[{"kind": "dip", "line": "l1", "at": 3.0}])
    overlay = Shot("b", Path(), starts_during={"line": "l1", "at": 2.0})
    t = manifest.plan(Manifest("t", (W, H), FPS, [host, overlay]))
    assert t.shots[0].looks == [] and t.shots[1].looks == [(pytest.approx(1.0), {"kind": "dip"})]


def test_the_pull_places_a_look_as_its_camera_move_and_leaves_out_an_unknown_one():
    heard = {"l": {"text": "The hammer strikes the wheel.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("The hammer strikes the wheel.".split())]}}
    beat = {"cues": [{"line": "l", "word": 3, "look": {"kind": "flash", "amount": 0.5}, "nudge": 0.1}, {"line": "l", "word": 4, "look": {"kind": "sparkle"}}, {"line": "l", "word": 2, "camera": {"kind": "sway"}}]}
    assert marvin_pull._look_cues(beat, heard, []) == [{"kind": "flash", "amount": 0.5, "line": "l", "line_at": 1.4, "nudge": 0.1}]
    assert marvin_pull._camera_cues(beat, heard, []) == [{"kind": "sway", "line": "l", "line_at": 0.9}]


# --- the Fountain --------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("words", ["flash", "flash 0.6", "flash orange 0.6 0.4", "burn", "dip", "dip white 1.2", "freeze 1", "tint sepia", "tint cold 0.5 2",
                                   "blur 0.6", "blur 2s", "blur 0.6 1.2", "vignette 0.8 2", "glitch 0.4", "sparkle twice"])  # fmt: skip
def test_a_look_note_reads_back_as_it_was_written(words):
    assert fountain.look_words(fountain.look_cue(words)) == words


def test_the_look_grammar_puts_each_word_in_its_slot():
    assert fountain.look_cue("dip white 1.2") == {"kind": "dip", "color": "white", "seconds": 1.2}
    assert fountain.look_cue("blur 0.6") == {"kind": "blur", "amount": 0.6} and fountain.look_cue("blur 2s") == {"kind": "blur", "seconds": 2.0}
    assert fountain.look_cue("freeze 1") == {"kind": "freeze", "seconds": 1.0}
    assert fountain.look_cue("dip orange") == {"kind": "dip", "said": "orange"}  # kept as written, and left out by the render
    assert fountain.camera_cue("whip-pan left") == {"kind": "whip-pan", "x": -1} and fountain.camera_cue("sway 1.5 3") == {"kind": "sway", "amount": 1.5, "seconds": 3.0}


@pytest.mark.parametrize("words", ["whip-pan", "whip-pan left", "whip-pan right 0.5", "sway", "sway 1.5", "sway 1.5 3", "sway 3s"])
def test_a_new_camera_note_reads_back_as_it_was_written(words):
    assert fountain.camera_words(fountain.camera_cue(words)) == words


TEXT = (
    "INT. FORGE - DAY\n\nSparks.\n\nSMITH\nThe hammer strikes [[Sound: clang | Camera: whip-pan left | Look: flash]] the wheel [[Look: dip white 1.2 | Nudge: 0.1]]"
    " and [[Camera: sway | Look: tint sepia]] rests [[Look: blur 2s]] here.\n"
)


def test_look_notes_reach_the_beats_cues_and_the_complete_script_writes_them_back():
    (_c, number, beat), = fountain.cut(fountain.parse(TEXT, lines=True), text=TEXT).rows()
    assert beat["lines"][0]["text"] == "The hammer strikes the wheel and rests here."
    cues = fountain.beat_cues(beat, "s", number, {})
    assert [(c.get("camera"), c.get("look"), c.get("nudge")) for c in cues] == [
        ({"kind": "whip-pan", "x": -1}, {"kind": "flash"}, None),
        (None, {"kind": "dip", "color": "white", "seconds": 1.2}, 0.1),
        ({"kind": "sway"}, {"kind": "tint", "color": "sepia"}, None),
        (None, {"kind": "blur", "seconds": 2.0}, None),
    ]
    records = {"story": {"slug": "s", "title": "T", "dataJson": {}}, "beats": [{"slug": "s-beat-01", "dataJson": {"number": "01", "picture": "Sparks.", "cues": cues}}],
               "lines": {"s-beat-01": [{"slug": "s-line-01-1", "dataJson": {"speaker": "smith", "text": beat["lines"][0]["text"]}}]}, "scenes": {},
               "sounds": {"s-sound-01-1": {"slug": "s-sound-01-1", "dataJson": {"prompt": "clang"}}}, "chapters": {}, "characters": [], "revisions": []}  # fmt: skip
    exported = script.fountain_complete(records)
    assert TEXT.split("SMITH\n")[1].strip() in exported
    (_c, _n, again), = fountain.cut(fountain.parse(exported, lines=True), text=exported).rows()
    assert fountain.beat_cues(again, "s", "01", {}) == cues


def test_the_check_takes_look_notes_as_cues():
    assert [f for f in validate.check(TEXT) if "note" in f.code or "pic" in f.code] == []
    assert fountain.cue_parts("Look: flash | Nudge: -0.2") == {"look": "flash", "nudge": "-0.2"}
    assert fountain.cue_parts("Look") is None  # a Look says which


# --- the film is as long as it was, and sounds the same --------------------------------------------------------------------------------------


@needs_ffmpeg
def test_looks_never_change_the_films_length_nor_its_sound(tmp_path):
    voice = _tone(tmp_path / "v.wav", 2.0, 440)
    sq = _square(tmp_path / "sq.png")
    looks = [{"kind": k, "line": "l1", "at": 0.2 * i} for i, k in enumerate(camera.LOOKS)]

    def film(name: str, with_looks: bool) -> Path:
        shot = Shot("a", sq, lines=[Line("w", voice, 2.0, ref="l1")], look_cues=looks if with_looks else [], camera_cues=[{"kind": "whip-pan", "line": "l1", "at": 1.0}] if with_looks else [])
        out = tmp_path / name
        build.render(Manifest("t", (W, H), FPS, [shot], loudnorm=False), out, draft=True)
        return out

    plain, looked = film("plain.mp4", False), film("looked.mp4", True)
    probe = [json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(f)], capture_output=True, check=True).stdout)["streams"] for f in (plain, looked)]
    assert [s.get("nb_read_frames") for s in probe[0]] == [s.get("nb_read_frames") for s in probe[1]]
    assert _samples(plain) == _samples(looked)
