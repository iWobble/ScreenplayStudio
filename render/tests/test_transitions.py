"""Transitions: cut (nothing), fade (down to black and up) and dissolve (a cross-fade). None of them may change a film's length."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest
from storyrender.manifest import ManifestError

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _rgb(video: Path, at: float) -> tuple[int, int, int]:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


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


def test_a_transition_takes_at_most_half_of_each_shot_and_the_first_shot_has_none():
    from storyrender.manifest import Line, Manifest, Shot

    shots = [Shot(f"s{i}", Path(f"s{i}.png"), hold=1.0, lines=[Line("x", None, 1.0)]) for i in range(3)]
    for s in shots:
        s.transition, s.transition_seconds = "dissolve", 5.0  # far longer than any shot
    timeline = manifest.plan(Manifest("t", (360, 640), 30, shots))
    edges = build.edges_of(timeline, 30)
    assert (edges[0].blend_in, edges[2].blend_out) == (0, 0)  # nothing before the first shot or after the last
    assert all(e.blend_in <= build.clip_frames(timeline.shots[i], 30) // 2 for i, e in enumerate(edges))  # never more than half of a shot
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
