"""Transitions: cut (nothing), fade (down to black and up) and dissolve (a cross-fade). None of them may change a film's length."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest
from storyrender.manifest import ManifestError
from tests.test_listen_pull import marvin  # noqa: F401  (the fake Marvin the pull reads)

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _rgb(video: Path, at: float) -> tuple[int, int, int]:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


def _last_rgb(video: Path) -> tuple[int, int, int]:
    """The colour of the film's very last frame."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-sseof", "-0.25", "-i", str(video), "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return raw[-3], raw[-2], raw[-1]


def _project(tmp_path: Path, kind: str | None, seconds: float = 1.0, on: tuple[int, ...] = (1, 2)) -> manifest.Manifest:
    project = demo.make(tmp_path / "demo", size=(360, 640))
    raw = json.loads(project.read_text())
    for i in on:
        if kind:
            raw["shots"][i]["transition"] = kind
            raw["shots"][i]["transition_seconds"] = seconds
    project.write_text(json.dumps(raw))
    return manifest.load(project, probe=ffmpeg.duration)


def test_the_manifest_keeps_a_shots_transition_and_defaults_to_a_cut(tmp_path):
    m = _project(tmp_path, "dissolve", 0.8, on=(1,))
    assert [(s.transition, s.transition_seconds) for s in m.shots] == [("cut", 0.0), ("dissolve", 0.8), ("cut", 0.0)]
    (tmp_path / "x.json").write_text(json.dumps({"shots": [{"id": "a", "still": "s.png", "hold": 2, "lines": [], "transition": "fade"}]}))
    (tmp_path / "s.png").write_bytes(b"x")
    assert manifest.load(tmp_path / "x.json", probe=lambda _p: 1.0, need_stills=False).shots[0].transition_seconds == 0.5  # a default length


@pytest.mark.parametrize("bad", [{"transition": "wipe"}, {"transition": "fade", "transition_seconds": 9}, {"transition": "fade", "transition_seconds": -1}])
def test_a_transition_that_does_not_exist_or_is_too_long_is_refused(tmp_path, bad):
    (tmp_path / "s.png").write_bytes(b"x")
    (tmp_path / "x.json").write_text(json.dumps({"shots": [{"id": "a", "still": "s.png", "hold": 2, "lines": [], **bad}]}))
    with pytest.raises(ManifestError, match="transition"):
        manifest.load(tmp_path / "x.json", probe=lambda _p: 1.0, need_stills=False)


def test_a_transition_takes_at_most_half_of_each_shot_and_nothing_is_blended_into_the_first():
    from storyrender.manifest import Line, Manifest, Shot

    shots = [Shot(f"s{i}", Path(f"s{i}.png"), hold=1.0, lines=[Line("x", None, 1.0)]) for i in range(3)]
    for s in shots:
        s.transition, s.transition_seconds = "dissolve", 5.0  # far longer than any shot
    timeline = manifest.plan(Manifest("t", (360, 640), 30, shots))
    edges = build.edges_of(timeline, 30)
    assert (edges[0].blend_in, edges[2].blend_out) == (0, 0)  # nothing before the first shot or after the last
    assert all(e.blend_in + e.blend_out <= build.clip_frames(timeline.shots[i], 30) - 1 for i, e in enumerate(edges))  # never a shot's every frame
    assert edges[0].blend_out == edges[1].blend_in and edges[1].blend_out == edges[2].blend_in  # both sides of a boundary agree


@needs_ffmpeg
@pytest.mark.parametrize("kind", [None, "fade", "dissolve"])
def test_no_transition_changes_the_length_of_the_film(tmp_path, kind):
    m = _project(tmp_path, kind)
    build.render(m, tmp_path / "out.mp4", draft=True, keep=tmp_path / "work")
    planned = manifest.plan(m).duration
    video = float(ffmpeg.probe(tmp_path / "work" / "video.mp4")["format"]["duration"])  # the joined pictures alone, before the sound is put to them
    assert video == pytest.approx(planned, abs=1.5 / 24)  # within a frame of what was planned


@needs_ffmpeg
def test_a_dissolve_blends_the_two_pictures_at_the_boundary_and_leaves_the_rest_alone(tmp_path):
    cut, dissolved = _project(tmp_path / "a", None), _project(tmp_path / "b", "dissolve", 1.0)
    build.render(cut, tmp_path / "cut.mp4", draft=True)
    build.render(dissolved, tmp_path / "dis.mp4", draft=True)
    plan = manifest.plan(cut)
    boundary = plan.shots[1].start  # the cut between the second and the first shot's picture
    before, after = _rgb(tmp_path / "cut.mp4", boundary - 0.2), _rgb(tmp_path / "cut.mp4", boundary + 0.2)
    mixed = _rgb(tmp_path / "dis.mp4", boundary)
    between = [(a + b) / 2 for a, b in zip(before, after, strict=True)]
    assert max(abs(m - x) for m, x in zip(mixed, between, strict=True)) < 40  # roughly half of each at the boundary
    assert mixed != before and mixed != after
    assert _rgb(tmp_path / "dis.mp4", plan.shots[1].start + 1.2) == pytest.approx(_rgb(tmp_path / "cut.mp4", plan.shots[1].start + 1.2), abs=12)  # well into a shot: as before
    assert _rgb(tmp_path / "dis.mp4", 0.3) == pytest.approx(_rgb(tmp_path / "cut.mp4", 0.3), abs=12)  # and before the first boundary


@needs_ffmpeg
def test_a_fade_goes_down_to_black_at_the_boundary(tmp_path):
    cut, faded = _project(tmp_path / "a", None), _project(tmp_path / "b", "fade", 1.0)
    build.render(cut, tmp_path / "cut.mp4", draft=True)
    build.render(faded, tmp_path / "fade.mp4", draft=True)
    boundary = manifest.plan(cut).shots[1].start
    assert sum(_rgb(tmp_path / "fade.mp4", boundary - 0.04)) < 60  # nearly black as the shot ends
    assert sum(_rgb(tmp_path / "fade.mp4", boundary + 0.02)) < 80
    assert sum(_rgb(tmp_path / "cut.mp4", boundary + 0.1)) > 150  # a cut stays bright


# ── what the pull hands on: the story's, a beat's replacing it ──────────────────────────────────────────────────────────────────────────
def test_a_beats_transition_replaces_the_stories_and_a_cut_adds_nothing():
    from storyrender import marvin_pull

    story = {"transition": "dissolve", "transition_seconds": 0.8}
    assert marvin_pull.transition_of({}, story) == {"transition": "dissolve", "transition_seconds": 0.8}  # the story's, for a beat that says nothing
    assert marvin_pull.transition_of({"transition": "fade", "transition_seconds": "1.5"}, story) == {"transition": "fade", "transition_seconds": 1.5}  # the beat's own
    assert marvin_pull.transition_of({"transition": "fade"}, story) == {"transition": "fade", "transition_seconds": 0.8}  # its kind, the story's length
    assert marvin_pull.transition_of({"transition": "cut"}, story) == {}  # a cut beats the story's dissolve: "no transition into this beat"
    assert marvin_pull.transition_of({}, {}) == {} and marvin_pull.transition_of({"transition": "wipe"}, {}) == {}  # nothing set, or not known: a cut
    assert marvin_pull.transition_of({}, {"transition": "fade"}) == {"transition": "fade"}  # no length: the renderer's default


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["fade", "dissolve"])
def test_a_shot_shorter_than_its_two_transitions_still_keeps_a_frame_and_the_film_still_renders(tmp_path, kind):
    """A real story's short beats met a 0.8 s transition on both sides: the whole shot was taken and the encoder was left with nothing."""
    project = demo.make(tmp_path / "demo", size=(360, 640))
    raw = json.loads(project.read_text())
    raw["shots"][1]["lines"] = []
    raw["shots"][1]["hold"] = 16 / 24  # exactly 16 frames of a draft: an even count that two half-takes would use up entirely
    for shot in raw["shots"][1:]:
        shot["transition"], shot["transition_seconds"] = kind, 2.0  # far longer than that shot
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True, keep=tmp_path / "work")
    assert float(ffmpeg.probe(tmp_path / "work" / "video.mp4")["format"]["duration"]) == pytest.approx(manifest.plan(m).duration, abs=1.5 / 24)


@needs_ffmpeg
def test_a_dissolve_renders_at_a_full_size_story_too(tmp_path):
    """The first real story (1080x1920, so 540x960 as a draft) stopped at xfade ("rate of 1/0") where the small demo had not: the two inputs of the
    cross-fade now both get a constant frame rate."""
    project = demo.make(tmp_path / "demo")  # the default size
    raw = json.loads(project.read_text())
    for shot in raw["shots"][1:]:
        shot["transition"], shot["transition_seconds"] = "dissolve", 0.8
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True, keep=tmp_path / "work")
    assert float(ffmpeg.probe(tmp_path / "work" / "video.mp4")["format"]["duration"]) == pytest.approx(manifest.plan(m).duration, abs=1.5 / 24)


# ── how the film starts and ends: FADE IN: on the first beat, FADE OUT. after the last ───────────────────────────────────────
def _timeline(seconds: float, kind: str = "fade", holds: tuple[float, ...] = (2.0, 2.0)):
    from storyrender.manifest import Manifest, Shot

    shots = [Shot(f"s{i}", Path(f"s{i}.png"), hold=hold, lines=[]) for i, hold in enumerate(holds)]
    shots[0].transition, shots[0].transition_seconds = kind, seconds
    return manifest.plan(Manifest("t", (360, 640), 24, shots))


@pytest.mark.parametrize("kind", ["fade", "dissolve"])
def test_the_first_shots_transition_is_a_fade_up_from_black_as_long_as_it_says_and_at_most_half_the_shot(kind):
    edges = build.edges_of(_timeline(0.5, kind), 24)
    assert (edges[0].dip_in, edges[0].blend_in, edges[0].dip_out) == (12, 0, 0)  # the whole length: nothing shares it (a dissolve from nothing is a fade up)
    assert edges[1] == build.Edges()  # and the next shot is not touched
    assert build.edges_of(_timeline(5.0, kind), 24)[0].dip_in == (48 - 1) // 2  # never more than half of the shot


def test_a_first_shot_that_cuts_in_and_a_film_that_ends_on_a_cut_have_no_fade():
    assert build.edges_of(_timeline(0.0, "cut"), 24) == [build.Edges(), build.Edges()]


def test_the_end_fade_of_the_picture_is_inside_the_last_shot_and_leaves_what_its_start_took():
    timeline = _timeline(0.0, "cut")
    assert build.edges_of(timeline, 24, end_fade=1.0)[-1] == build.Edges(dip_out=24)
    assert build.edges_of(timeline, 24, end_fade=30.0)[-1].dip_out == 47  # longer than the shot: all of it but a frame
    timeline.shots[1].shot.transition, timeline.shots[1].shot.transition_seconds = "fade", 1.0
    assert build.edges_of(timeline, 24, end_fade=30.0)[-1] == build.Edges(dip_in=12, dip_out=35)  # the fade into the last shot keeps its frames
    one = _timeline(1.0, "fade", holds=(2.0,))
    assert build.edges_of(one, 24, end_fade=1.0) == [build.Edges(dip_in=23, dip_out=24)]  # a film of one shot fades up and out


def test_the_manifest_keeps_how_the_film_ends_and_refuses_what_is_not_an_ending(tmp_path):
    (tmp_path / "s.png").write_bytes(b"x")
    shot = {"id": "a", "still": "s.png", "hold": 2, "lines": []}

    def load(**top):
        (tmp_path / "x.json").write_text(json.dumps({"shots": [shot], **top}))
        return manifest.load(tmp_path / "x.json", probe=lambda _p: 1.0, need_stills=False)

    assert (load().end_transition, load().end_transition_seconds) == ("cut", 0.0)
    assert (load(end_transition="fade").end_transition, load(end_transition="fade").end_transition_seconds) == ("fade", 0.5)  # a default length
    assert load(end_transition="fade", end_transition_seconds=3).end_transition_seconds == 3.0
    assert load(end_transition="cut", end_transition_seconds=3).end_transition_seconds == 0.0  # a cut has no length
    for bad in ({"end_transition": "dissolve"}, {"end_transition": "fade", "end_transition_seconds": 31}, {"end_transition": "fade", "end_transition_seconds": -1}):
        with pytest.raises(ManifestError, match="end_transition"):
            load(**bad)


@needs_ffmpeg
def test_a_fade_on_the_first_shot_starts_the_film_black_and_reaches_the_picture_at_the_same_length(tmp_path):
    cut, faded = _project(tmp_path / "a", None), _project(tmp_path / "b", "fade", 1.0, on=(0,))
    build.render(cut, tmp_path / "cut.mp4", draft=True, keep=tmp_path / "cut")
    build.render(faded, tmp_path / "fade.mp4", draft=True, keep=tmp_path / "fade")
    assert sum(_rgb(tmp_path / "fade" / "video.mp4", 0.0)) < 30 and sum(_rgb(tmp_path / "cut" / "video.mp4", 0.0)) > 150  # black, where a cut opens on the picture
    assert _rgb(tmp_path / "fade" / "video.mp4", 1.5) == pytest.approx(_rgb(tmp_path / "cut" / "video.mp4", 1.5), abs=12)  # the picture, once the fade is over
    lengths = [float(ffmpeg.probe(tmp_path / name / "video.mp4")["format"]["duration"]) for name in ("cut", "fade")]
    assert lengths[0] == pytest.approx(lengths[1], abs=0.5 / 24) and lengths[1] == pytest.approx(manifest.plan(faded).duration, abs=1.5 / 24)


@needs_ffmpeg
def test_a_film_that_fades_out_ends_on_black_at_the_same_length_and_a_cut_ending_is_as_it_was(tmp_path):
    def project(folder: Path, **top) -> manifest.Manifest:
        path = demo.make(folder / "demo", size=(360, 640))
        path.write_text(json.dumps({**json.loads(path.read_text()), **top}))
        return manifest.load(path, probe=ffmpeg.duration)

    cut, faded = project(tmp_path / "a"), project(tmp_path / "b", end_transition="fade", end_transition_seconds=1.0)
    build.render(cut, tmp_path / "cut.mp4", draft=True, keep=tmp_path / "cut")
    build.render(faded, tmp_path / "fade.mp4", draft=True, keep=tmp_path / "fade")
    end = manifest.plan(cut).duration
    assert sum(_last_rgb(tmp_path / "fade" / "video.mp4")) < 30 and sum(_last_rgb(tmp_path / "cut" / "video.mp4")) > 150
    assert _rgb(tmp_path / "fade" / "video.mp4", end - 1.5) == pytest.approx(_rgb(tmp_path / "cut" / "video.mp4", end - 1.5), abs=12)  # before the fade: the same film
    lengths = [float(ffmpeg.probe(tmp_path / name / "video.mp4")["format"]["duration"]) for name in ("cut", "fade")]
    assert lengths[0] == pytest.approx(lengths[1], abs=0.5 / 24)


# ── what the pull hands on for the two ends of the film ───────────────────────────────────────────────────────────────────────
def _pulled(marvin, tmp_path, story: dict, beats: "str | None" = None, **first_beat) -> dict:
    from storyrender import marvin_pull
    from tests.test_listen_pull import _ROWS, _FakeMarvin, S

    rows = [dict(r) for r in _ROWS]
    rows[0] = {**rows[0], "dataJson": story}
    rows = [{**r, "dataJson": {**r["dataJson"], **first_beat}} if r["slug"] == f"{S}-beat-01" else r for r in rows]
    _FakeMarvin.rows = rows
    try:
        marvin_pull.pull(S, tmp_path, creds=(marvin, "tok"), beats=beats)
    finally:
        _FakeMarvin.rows = _ROWS
    return json.loads((tmp_path / "manifest.json").read_text())


def test_only_the_first_beats_own_transition_opens_the_film_the_storys_is_for_between_beats(marvin, tmp_path):
    story = {"transition": "dissolve", "transition_seconds": 0.8}
    plain = _pulled(marvin, tmp_path / "a", story)["shots"]
    assert "transition" not in plain[0] and plain[1]["transition"] == "dissolve"  # the film opens on the picture, as it always did
    own = _pulled(marvin, tmp_path / "b", story, transition="fade")["shots"]
    assert (own[0]["transition"], own[0]["transition_seconds"]) == ("fade", 0.8)  # FADE IN: the beat's own kind, the story's length
    carded = _pulled(marvin, tmp_path / "c", {**story, "intro_title": "The Last Onion"})["shots"]
    assert carded[0]["id"] == "intro" and carded[1]["transition"] == "dissolve"  # after a title card the first beat is between two shots
    draft = _pulled(marvin, tmp_path / "d", story, beats="1,3", transition="fade")["shots"]
    assert "transition" not in draft[0] and draft[1]["transition"] == "dissolve"  # a draft of some beats does not start where the film does


def test_the_storys_ending_reaches_the_manifest_with_the_length_the_beds_fade_over(marvin, tmp_path):
    assert "end_transition" not in _pulled(marvin, tmp_path / "a", {}) and "end_transition" not in _pulled(marvin, tmp_path / "b", {"end_transition": "cut"})
    faded = _pulled(marvin, tmp_path / "c", {"end_transition": "fade"})
    assert faded["end_transition"] == "fade" and "end_transition_seconds" not in faded  # no length set anywhere: the renderer's default
    assert _pulled(marvin, tmp_path / "d", {"end_transition": "Fade", "transition_seconds": 0.8})["end_transition_seconds"] == 0.8  # the story's transition length
    both = _pulled(marvin, tmp_path / "e", {"end_transition": "fade", "transition_seconds": 0.8, "end_fade_seconds": 3})
    assert both["end_transition_seconds"] == 3.0  # the picture goes with the music and the ambience
    assert "end_transition" not in _pulled(marvin, tmp_path / "f", {"end_transition": "fade"}, beats="1")  # a draft of some beats is not the end of the film
