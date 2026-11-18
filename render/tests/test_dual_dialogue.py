"""Dual dialogue: two people speaking at once (`NAME ^` in the Fountain). The import marks the second line `simultaneous`; the scripts write the `^`
back; the render starts it when the line before starts, and the captions show both."""

import subprocess
from pathlib import Path

import pytest

from storyrender import build, captions, fountain, manifest, script
from storyrender.manifest import Line, Manifest, Shot
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_overlay_music import needs_ffmpeg
from tests.test_picture_lead import _colour, _samples, _strength, _tone
from tests.test_script_roundtrip import _records_from

DUAL = """Title: Two at once

INT. FORGE - DAY

Brick and Steel glare at the anvil.

BRICK
Screw retirement.

STEEL ^
Screw retirement.

NARRATOR
They meant it.

BRICK (V.O.)
Never.

STEEL (V.O.) ^
Never!
"""


def _said(text: str) -> list[tuple[str, str, bool]]:
    return [(e["name"], e["text"], bool(e.get("dual"))) for e in fountain.parse(text) if e["t"] == "dialogue"]


def test_the_complete_and_production_scripts_write_the_caret_and_the_import_reads_the_same_lines_again(casting):  # noqa: F811
    fake, ctx = casting(DUAL)
    run(ctx)
    lines = [m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-line"]
    assert [(d["text"], bool(d.get("simultaneous"))) for d in lines] == [("Screw retirement.", False), ("Screw retirement.", True), ("They meant it.", False), ("Never.", False), ("Never!", True)]
    records = _records_from(fake)
    complete = script.fountain_complete(records)
    assert "\nSTEEL ^\n" in complete and "\nSTEEL (V.O.) ^\n" in complete and "BRICK ^" not in complete
    assert _said(complete) == _said(DUAL)  # nothing dropped, the same two marked
    production = script.fountain(records)
    assert "\nSTEEL ^\n" in production and _said(production) == _said(DUAL)
    written = script.fountain_as_written(records)  # the text each beat kept, as written
    assert "\nSTEEL ^\n" in written and _said(written) == _said(DUAL)
    again, ctx2 = casting(complete)
    run(ctx2)
    assert [bool(m["dataJson"].get("simultaneous")) for m in again.made if m["entryTypeId"] == "T-line"] == [False, True, False, False, True]


def _shot(*lines: Line, **kw) -> Shot:
    return Shot("a", Path(), lines=list(lines), lead=0.3, gap=0.25, tail=0.35, **kw)


def test_a_simultaneous_line_starts_with_the_line_before_and_the_next_follows_the_later_of_the_two():
    t = manifest.plan(Manifest("t", (360, 640), 24, [_shot(Line("a", duration=2.0), Line("b", duration=3.0, simultaneous=True), Line("c", duration=1.0))]))
    a, b, c = t.shots[0].lines
    assert a.start == b.start == 0.3
    assert c.start == pytest.approx(0.3 + 3.0 + 0.25)  # after b, the longer of the two
    assert t.duration == pytest.approx(c.start + 1.0 + 0.35)
    nudged = manifest.plan(Manifest("t", (360, 640), 24, [_shot(Line("a", duration=2.0), Line("b", duration=1.0, simultaneous=True, nudge=0.5))]))
    assert nudged.shots[0].lines[1].start == pytest.approx(0.8)  # its nudge moves it from the shared start
    assert nudged.duration == pytest.approx(0.3 + 2.0 + 0.35)  # the beat lasts until the later end
    assert manifest.overlaps(t) == []  # two at once on purpose is not reported
    plain = manifest.plan(Manifest("t", (360, 640), 24, [_shot(Line("a", duration=2.0), Line("b", duration=3.0))]))
    assert plain.shots[0].lines[1].start == 0.3 + 2.0 + 0.25  # without the flag: as before


def test_a_simultaneous_line_as_the_first_of_its_shot_has_nothing_to_join_and_starts_at_the_lead():
    t = manifest.plan(Manifest("t", (360, 640), 24, [_shot(Line("a", duration=1.0, simultaneous=True))]))
    assert t.shots[0].lines[0].start == 0.3


def test_the_captions_show_both_lines_at_once():
    t = manifest.plan(Manifest("t", (360, 640), 24, [_shot(Line("Screw retirement.", duration=2.0, speaker="Brick"), Line("Never!", duration=1.5, speaker="Steel", simultaneous=True))]))
    cues = captions.cues(t)
    assert [c[0] for c in cues] == ["Screw retirement.", "Never!"] and cues[0][1] == cues[1][1] == 0.3
    events = [ln for ln in captions.ass(t, (360, 640)).splitlines() if ln.startswith("Dialogue:")]
    assert len(events) == 2 and all(",0:00:00.30," in e for e in events)  # two events at once: the subtitle renderer stacks them


@needs_ffmpeg
def test_two_simultaneous_voices_are_heard_together(tmp_path):
    a, b = _tone(tmp_path / "a.wav", 1.5, 440), _tone(tmp_path / "b.wav", 1.0, 880)
    still = _colour(tmp_path / "grey.png", "gray")
    m = Manifest("t", (180, 320), 24, [Shot("a", still, lines=[Line("a", a, 1.5), Line("b", b, 1.0, simultaneous=True)], move_to=manifest.Move())], loudnorm=False)
    film = tmp_path / "film.mp4"
    build.render(m, film, draft=True)
    sound = _samples(film)
    assert _strength(sound, 0.8, 440) > 0.03 and _strength(sound, 0.8, 880) > 0.03
    assert _strength(sound, 1.6, 880) < 0.01 < _strength(sound, 1.6, 440)
