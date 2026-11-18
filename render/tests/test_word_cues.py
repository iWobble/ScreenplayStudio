"""Cues on a word (v211): a Sound, Camera or Pic note among the words of a speech marks the word it stands at. The voice never reads it, the
captions never show it; the import keeps where it stood (`cues` on the beat, an overlay beat for a Pic), the render places the sound at the end of
the word before the note and brings the picture in at the start of the word after it, and the complete script writes the note back in its place."""

import json
from pathlib import Path

import pytest

from storyrender import build, fountain, manifest, marvin_pull, script, validate
from storyrender.manifest import Line, Manifest, Sfx, Shot
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_listen_pull import _ROWS, S, _FakeMarvin, marvin  # noqa: F401
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone
from tests.test_script_roundtrip import _records_from
from tests.test_transitions import _rgb

FLASH = """Title: The Flash

INT. ARCHIVE - NIGHT

A screen glows in the dark.

NARRATOR
Voyager 1, launched in 1977, [[Pic: a small 1970s probe drifts in dark space, sepia]] had needed thirty-five years to get that far.

The forge roars.

SMITH
The hammer strikes [[Sound: clang | Camera: punch 1.08]] the wheel. It rings[[Sound: a long ring]].
"""


def _speech(text: str) -> list[dict]:
    return [e for e in fountain.parse(text) if e["t"] == "dialogue"]


def test_a_note_among_the_words_marks_the_word_and_is_never_spoken():
    narrator, smith = _speech(FLASH)
    assert narrator["text"] == "Voyager 1, launched in 1977, had needed thirty-five years to get that far."
    assert narrator["cues"] == [{"word": 5, "pic": "a small 1970s probe drifts in dark space, sepia"}]
    assert smith["text"] == "The hammer strikes the wheel. It rings."  # two sentences in one line, two notes
    assert smith["cues"] == [{"word": 3, "sound": "clang", "camera": "punch 1.08"}, {"word": 7, "sound": "a long ring"}]


@pytest.mark.parametrize(
    ("speech", "words", "cues"),
    [
        ("[[Sound: bell]] Start here.", "Start here.", [{"word": 0, "sound": "bell"}]),  # before the first word
        ("Stop here. [[Camera: shake 2]]", "Stop here.", [{"word": 2, "camera": "shake 2"}]),  # after the last
        ("Stop here.\n[[Pic: the door, wide]]", "Stop here.", [{"word": 2, "pic": "the door, wide"}]),  # on a line of its own inside the speech
        ("Fine. [sighs] [[Sound: door]] Go on.", "Fine. [sighs] Go on.", [{"word": 1, "sound": "door"}]),  # a v3 tag is not a word said
        ("A [[Note: only a note]] note.", "A note.", []),  # any other note is only a note, as before
    ],
)
def test_a_cue_at_the_start_the_end_on_its_own_line_and_after_a_tag(speech, words, cues):
    (said,) = _speech(f"INT. ROOM - DAY\n\nA door.\n\nBOB\n{speech}\n")
    assert " ".join(said["text"].split()) == words and said.get("cues", []) == cues


def test_the_check_reads_a_pic_note_inside_a_speech_and_still_says_one_inline_in_action_is_only_a_note():
    codes = [f.code for f in validate.check(FLASH)]
    assert "pic-unread" not in codes and not [f for f in validate.check(FLASH) if f.level == "error"]
    action = FLASH.replace("The forge roars.", "The forge roars. [[Pic: inline in the action]]")
    assert [f.code for f in validate.check(action) if f.code == "pic-unread"] == ["pic-unread"]
    assert not fountain.lint(FLASH)


def test_a_pic_note_among_the_words_makes_a_beat_of_its_own_numbered_after_its_line_and_the_sheet_carries_it():
    plan = fountain.cut(fountain.parse(FLASH, lines=True), text=FLASH)
    rows = [(n, b.get("starts_during"), b["picture"]) for _c, n, b in plan.rows()]
    assert rows == [("01", None, "Interior: Archive, night. A screen glows in the dark."), ("01a", {"line": 1, "word": 5}, "a small 1970s probe drifts in dark space, sepia"), ("02", None, "The forge roars.")]
    assert "| 01a | — | No speech. | a small 1970s probe drifts in dark space, sepia |" in plan.sheet()
    two = FLASH.replace("had needed", "had needed [[Pic: a calendar, 2012]]")
    assert [n for _c, n, _b in fountain.cut(fountain.parse(two, lines=True), text=two).rows()] == ["01", "01a", "01b", "02"]


def test_the_import_keeps_the_words_clean_and_records_the_cues_the_overlay_beat_and_the_sound_to_make(casting):  # noqa: F811
    fake, ctx = casting(FLASH)
    run(ctx)
    made = {m["slug"]: m["dataJson"] for m in fake.made}
    assert made["s-line-01-1"]["text"] == "Voyager 1, launched in 1977, had needed thirty-five years to get that far."
    assert made["s-line-02-1"]["text"] == "The hammer strikes the wheel. It rings."
    assert made["s-beat-01"]["cues"] == [{"line": "s-line-01-1", "word": 5, "pic": "s-beat-01a"}]
    assert made["s-beat-02"]["cues"] == [
        {"line": "s-line-02-1", "word": 3, "sound": "s-sound-02-1", "camera": {"kind": "punch", "amount": 1.08}},
        {"line": "s-line-02-1", "word": 7, "sound": "s-sound-02-2"},
    ]
    assert "sounds" not in made["s-beat-02"]  # a sound on a word is placed there, never also from the beat's start
    assert (made["s-sound-02-1"]["prompt"], made["s-sound-02-1"]["status"]) == ("clang", "draft")  # a placeholder: nothing is made or paid for
    overlay = made["s-beat-01a"]
    assert overlay["starts_during"] == {"line": "s-line-01-1", "word": 5} and overlay["direction"] == "a small 1970s probe drifts in dark space, sepia"
    assert overlay["hold_seconds"] == 0 and overlay["scene"] == made["s-beat-01"]["scene"]


def test_the_complete_script_writes_each_note_back_where_it_stood_and_reads_back_the_same(casting):  # noqa: F811
    fake, ctx = casting(FLASH)
    run(ctx)
    exported = script.fountain_complete(_records_from(fake))
    assert "Voyager 1, launched in 1977, [[Pic: a small 1970s probe drifts in dark space, sepia]] had needed" in exported
    assert "The hammer strikes [[Sound: clang | Camera: punch 1.08]] the wheel. It rings. [[Sound: a long ring]]" in exported
    assert exported.count("a small 1970s probe") == 1  # the overlay is the note among the words, not a picture of its own as well
    plan = lambda text: [(n, b.get("starts_during"), [(ln["text"], ln.get("cues")) for ln in b["lines"]]) for _c, n, b in fountain.cut(fountain.parse(text, lines=True), text=text).rows()]  # noqa: E731
    assert plan(exported) == plan(FLASH)
    again, ctx2 = casting(exported)
    run(ctx2)
    beats = lambda f: {m["slug"]: m["dataJson"].get("cues") for m in f.made if m["entryTypeId"] == "T-beat"}  # noqa: E731
    assert beats(again) == beats(fake)


def test_a_refresh_gives_the_cues_to_a_beat_that_has_none_and_never_places_a_sound_twice(casting):  # noqa: F811
    first, ctx = casting(FLASH)
    run(ctx)
    beats = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": {k: v for k, v in m["dataJson"].items() if k != "cues"}} for m in first.made if m["entryTypeId"] == "T-beat"}
    beats["s-beat-02"]["dataJson"]["sounds"] = [{"sound": "s-sound-02-2", "at": 0}]  # an import before v211 placed the ring from the beat's start
    again, ctx2 = casting(FLASH)
    again.records = dict(beats)
    done = run(ctx2, mode="refresh")
    patched = {p[0]: p[1]["dataJson"] for p in again.patched if p[0].startswith("id-")}
    assert patched["id-s-beat-01"]["cues"] == [{"line": "s-line-01-1", "word": 5, "pic": "s-beat-01a"}]
    assert patched["id-s-beat-02"]["cues"] == [{"line": "s-line-02-1", "word": 3, "sound": "s-sound-02-1", "camera": {"kind": "punch", "amount": 1.08}}]  # the ring stays where it was
    assert patched["id-s-beat-02"]["sounds"] == [{"sound": "s-sound-02-2", "at": 0}]
    assert "s-sound-02-2 is in its Sound effects from the start" in done["log"]


def test_where_a_cue_falls_in_its_line_from_the_word_timings_or_estimated_from_the_text():
    line = {"text": "The hammer strikes the wheel.", "words": [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("The hammer strikes the wheel.".split())]}
    assert marvin_pull.word_place(line, 3, after=True) == ("at", 1.4)  # the sound at the end of "strikes"
    assert marvin_pull.word_place(line, 3, after=False) == ("at", 1.5)  # the picture at the start of "the"
    assert marvin_pull.word_place(line, 0, after=True) == ("at", 0.0) and marvin_pull.word_place(line, 9, after=False) == ("at", 2.4)
    bare = {"text": "The hammer strikes the wheel.", "words": []}
    assert marvin_pull.word_place(bare, 3, after=True) == ("share", round(len("The hammer strikes") / len(bare["text"]), 4))
    assert marvin_pull.word_place(bare, 3, after=False) == ("share", round(len("The hammer strikes ") / len(bare["text"]), 4))


def test_the_pull_places_a_cue_sound_and_an_overlay_on_their_words_and_says_when_it_had_to_estimate(marvin, tmp_path):  # noqa: F811
    rows = [dict(r) for r in _ROWS]
    rows = [{**r, "dataJson": {**r["dataJson"], "cues": [{"line": f"{S}-line-01-1", "word": 1, "sound": f"{S}-sound-waves"}]}} if r["slug"] == f"{S}-beat-01" else r for r in rows]
    rows.append({"slug": f"{S}-beat-01a", "dataJson": {"story": S, "number": "01a", "still": "asset-1", "hold_seconds": 0, "starts_during": {"line": f"{S}-line-01-1", "word": 0}}})
    _FakeMarvin.rows = rows
    try:
        pulled = marvin_pull.pull(S, tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    shots = {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}
    cue = next(fx for fx in shots["b01"]["sfx"] if fx.get("line"))
    assert cue["line"] == f"{S}-line-01-1" and cue["line_share"] == 1.0  # "One." has no word timings: the end of its only word is the end of the text
    overlay = shots["b01a"]
    assert overlay["starts_during"] == {"line": f"{S}-line-01-1", "share": 0.0} and "hold" not in overlay
    assert (overlay["transition"], overlay["transition_seconds"]) == ("dissolve", marvin_pull.OVERLAY_DISSOLVE)
    assert pulled["estimated"] == [f"{S}-line-01-1 word 1", f"{S}-line-01-1 word 0"]


def test_an_overlay_whose_line_has_no_take_plays_as_a_silent_beat_of_its_own():
    assert marvin_pull._starts_during({"starts_during": {"line": "x-line-01-1", "word": 2}}, {}, []) is None


def _plan(*shots: Shot) -> manifest.Timeline:
    return manifest.plan(Manifest("t", (360, 640), 24, list(shots)))


def test_the_plan_places_a_sound_and_a_picture_on_their_words_and_the_overlay_adds_no_time():
    host = Shot("a", Path(), lines=[Line("words", duration=4.0, ref="l1")], sfx=[Sfx(Path("x.wav"), duration=0.5, line="l1", line_at=1.4)])
    overlay = Shot("b", Path(), starts_during={"line": "l1", "at": 1.5})
    after = Shot("c", Path(), lines=[Line("more", duration=1.0, ref="l2")])
    t = _plan(host, overlay, after)
    plain = _plan(Shot("a", Path(), lines=[Line("words", duration=4.0, ref="l1")]), after)
    assert t.duration == pytest.approx(plain.duration)  # the overlay adds no time
    assert t.shots[0].sfx_at == [pytest.approx(0.3 + 1.4)]  # seconds from the beat's sound start: the line's lead, then into the line
    assert t.shots[1].start == pytest.approx(0.3 + 1.5) and t.shots[0].duration == pytest.approx(1.8)  # the first picture gives way at the word
    assert t.shots[2].start == pytest.approx(t.shots[2].audio_start)  # and the overlay lasts until the next picture
    estimated = _plan(Shot("a", Path(), lines=[Line("w", duration=4.0, ref="l1")]), Shot("b", Path(), starts_during={"line": "l1", "share": 0.25}), after)
    assert estimated.shots[1].start == pytest.approx(0.3 + 1.0)
    held = _plan(host, Shot("b", Path(), hold=5.0, starts_during={"line": "l1", "at": 1.5}), after)
    assert held.shots[2].audio_start == pytest.approx(0.3 + 1.5 + 5.0)  # a hold keeps it up past the end of the speech, counted from the word


def test_an_overlay_whose_line_is_not_in_the_film_is_an_ordinary_shot():
    t = _plan(Shot("a", Path(), lines=[Line("w", duration=1.0, ref="l1")]), Shot("b", Path(), hold=4.0, starts_during={"line": "elsewhere", "at": 0.5}))
    assert t.shots[1].start == t.shots[1].audio_start and t.shots[1].duration == 4.0


@needs_ffmpeg
def test_the_render_plays_the_sound_after_its_word_and_brings_the_picture_in_at_the_next(tmp_path):
    voice, clang = _tone(tmp_path / "v.wav", 3.0, 440), _tone(tmp_path / "c.wav", 0.3, 1320)
    red, blue = _colour(tmp_path / "red.png", "red"), _colour(tmp_path / "blue.png", "blue")
    shots = [
        Shot("a", red, lines=[Line("words", voice, 3.0, ref="l1")], lead=0.2, sfx=[Sfx(clang, duration=0.3, line="l1", line_at=1.0)], move_to=manifest.Move()),
        Shot("b", blue, starts_during={"line": "l1", "at": 1.8}, transition="dissolve", transition_seconds=0.2, move_to=manifest.Move()),
    ]
    m = Manifest("t", (180, 320), 24, shots, loudnorm=False)
    film = tmp_path / "film.mp4"
    build.render(m, film, draft=True, keep=tmp_path / "work")
    sound = _samples(film)
    assert _strength(sound, 1.0, 1320) < 0.01 < _strength(sound, 1.35, 1320)  # the clang starts at 0.2 + 1.0 s, not with the beat
    assert _rgb(film, 1.75)[0] > 150 and _rgb(film, 2.25)[2] > 150  # red until the word at 0.2 + 1.8 s, then blue (a 0.2 s dissolve round it)
    assert _strength(sound, 2.5, 440) > 0.03  # the voice runs on under the new picture


def test_an_overlay_beat_does_not_stop_a_revised_fountain_being_fitted_by_what_it_says(casting):  # noqa: F811
    first, ctx = casting(FLASH)
    run(ctx)
    made = {m["slug"]: {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": dict(m["dataJson"])} for m in first.made if m["entryTypeId"] in ("T-beat", "T-line")}
    assert "fountain" not in made["s-beat-01a"]["dataJson"]  # the overlay has no piece of the text of its own
    revised = FLASH.replace("The forge roars.", "Sparks fly.\n\n===\n\nThe forge roars.")
    again, ctx2 = casting(revised)
    again.records = dict(made)
    done = run(ctx2, mode="refresh")
    assert done["result"]["revision"]["new"]  # fitted by what each beat says, not by number
    assert [m["slug"] for m in again.made if m["entryTypeId"] == "T-beat"] == ["s-beat-01b"]  # the new picture after 01 (01a is the overlay's)
