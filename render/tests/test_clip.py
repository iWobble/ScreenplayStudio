"""A beat's clip: a video of the author over the still, picture-in-picture, with its own sound (clip.py)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, clip, demo, ffmpeg, manifest, marvin_pull
from storyrender.manifest import Line, Manifest, ManifestError, Shot
from tests.test_listen_pull import _ROWS, S, _FakeMarvin, marvin  # noqa: F401  (the fake Marvin the pull reads)

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")

SIZE = (360, 640)
RED, BLUE = (255, 0, 0), (0, 0, 255)


# ── helpers ──────────────────────────────────────────────────────────────────
def _clip_file(path: Path, seconds: float = 2.0, *, colour: str = "red", sound: bool = True, piped: bool = False) -> Path:
    """A test clip: one colour (landscape, as a webcam's is), with a 440 Hz tone when it has sound. `piped` writes a webm as a browser does, with
    no length in its header."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=160x120:r=30:d={seconds}"]
    if sound:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if piped:
        cmd += ["-c:v", "libvpx", *(["-c:a", "libopus"] if sound else []), "-f", "webm", "pipe:1"]
        path.write_bytes(subprocess.run(cmd, capture_output=True, check=True).stdout)
        return path
    subprocess.run([*cmd, "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if sound else []), "-shortest", str(path)], check=True)
    return path


def _still(path: Path, colour: str = "blue") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={colour}:s={SIZE[0]}x{SIZE[1]}", "-frames:v", "1", str(path)], check=True)
    return path


def _project(tmp_path: Path, clip_raw: dict | None, *, hold: float = 0.5, lines: list | None = None, **shot) -> Path:
    """One shot over a blue still that does not move (so a pixel stays put), with `clip_raw` as its clip."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _still(tmp_path / "still.png")
    s = {"id": "b04", "still": "still.png", "hold": hold, "lines": lines or [], "move": {"from": {"x": 0.5, "y": 0.5, "zoom": 1}, "to": {"x": 0.5, "y": 0.5, "zoom": 1}}, **shot}
    if clip_raw is not None:
        s["clip"] = clip_raw
    (tmp_path / "m.json").write_text(json.dumps({"title": "t", "size": list(SIZE), "fps": 30, "loudnorm": False, "shots": [s]}))
    return tmp_path / "m.json"


def _frame(video: Path, at: float, size: tuple[int, int] = SIZE) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True
    ).stdout[: size[0] * size[1] * 3]


def _px(frame: bytes, x: int, y: int, width: int = SIZE[0]) -> tuple[int, int, int]:
    i = (y * width + x) * 3
    return frame[i], frame[i + 1], frame[i + 2]


def _near(got: tuple[int, int, int], want: tuple[int, int, int], tol: int = 40) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(got, want, strict=True))


def _mean_db(path: Path, start: float, length: float) -> float:
    done = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", done.stderr).group(1).replace("-inf", "-91"))


def _load(tmp_path: Path, clip_raw: dict, probe=lambda _p: 2.0, **kw) -> Manifest:
    (tmp_path / "still.png").write_bytes(b"x")
    (tmp_path / "c.webm").write_bytes(b"x")
    shot = {"id": "b04", "still": "still.png", "hold": 1, "lines": [], "clip": {"video": "c.webm", **clip_raw}, **kw}
    (tmp_path / "m.json").write_text(json.dumps({"shots": [shot]}))
    return manifest.load(tmp_path / "m.json", probe=probe)


# ── the settings ─────────────────────────────────────────────────────────────
def test_a_clip_defaults_to_a_circle_in_the_bottom_right_at_028_with_its_sound(tmp_path):
    m = _load(tmp_path, {})
    c = m.shots[0].clip
    assert (c.look, c.corner, c.shape, c.size, c.audio, c.volume, c.start, c.end, c.duration) == ("pip", "bottom-right", "circle", 0.28, True, 1.0, 0.0, None, 2.0)
    assert m.notes == []


def test_a_shot_without_a_clip_has_none(tmp_path):
    (tmp_path / "still.png").write_bytes(b"x")
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "a", "still": "still.png", "hold": 1, "lines": []}]}))
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0)
    assert m.shots[0].clip is None and m.notes == []


def test_a_clip_keeps_its_settings_and_its_trim_sets_its_length(tmp_path):
    c = _load(tmp_path, {"corner": "Top-Left", "shape": "rounded", "size": "0.4", "audio": False, "volume": 0.5, "start": 0.5, "end": 1.5}, probe=lambda _p: 3.0).shots[0].clip
    assert (c.corner, c.shape, c.size, c.audio, c.volume, c.start, c.end, c.duration) == ("top-left", "rounded", 0.4, False, 0.5, 0.5, 1.5, 1.0)
    assert _load(tmp_path, {"start": 1}, probe=lambda _p: 3.0).shots[0].clip.duration == 2.0  # to the file's end
    assert _load(tmp_path, {"end": 3.02}, probe=lambda _p: 3.0).shots[0].clip.duration == 3.0  # a hair past the end is the end


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ({"size": 0.1}, "size is 0.15–0.5"),
        ({"size": 0.6}, "size is 0.15–0.5"),
        ({"size": "big"}, "size is a number"),
        ({"corner": "middle"}, "corner is top-left"),
        ({"shape": "star"}, "shape is circle"),
        ({"look": "tiny"}, "look is pip, full"),
        ({"volume": 1.5}, "volume is 0–1"),
        ({"start": -1}, "start is 0 or more"),
        ({"start": 1, "end": 1}, "end 1s must come after start 1s"),
        ({"start": 2.5}, "past the end of the 2.00s clip"),
        ({"end": 2.5}, "past the end of the 2.00s clip"),
    ],
)
def test_a_bad_clip_setting_is_refused_naming_the_beat(tmp_path, raw, says):
    with pytest.raises(ManifestError, match=r"shot b04 clip: .*" + re.escape(says)):
        _load(tmp_path, raw)


def test_a_clip_whose_file_is_missing_or_unreadable_is_left_out_and_said(tmp_path):
    (tmp_path / "still.png").write_bytes(b"x")
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "b04", "still": "still.png", "hold": 1, "lines": [], "clip": {"video": "gone.webm"}}]}))
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 2.0)
    assert m.shots[0].clip is None and len(m.notes) == 1 and "shot b04 clip" in m.notes[0] and "gone.webm" in m.notes[0]
    assert manifest.plan(m).duration == pytest.approx(1.0)  # its own hold stands
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "b04", "still": "still.png", "lines": [], "clip": {"video": "gone.webm"}}]}))
    m = manifest.load(tmp_path / "m.json", probe=lambda _p: 2.0)
    assert manifest.plan(m).duration == pytest.approx(clip.FALLBACK_HOLD) and "held 4 s instead" in m.notes[0]  # the clip was all it had: the picture is held, never a blink

    def broken(_p):
        raise ffmpeg.FfmpegError("ffprobe can't read c.webm: Invalid data")

    m = _load(tmp_path, {}, probe=broken)
    assert m.shots[0].clip is None and "Invalid data" in m.notes[0] and "plays without it" in m.notes[0]


def test_the_full_frame_look_is_not_built_yet_so_it_plays_in_a_corner_and_says_so(tmp_path):
    m = _load(tmp_path, {"look": "full"})
    assert m.shots[0].clip.look == "pip" and "full-frame" in m.notes[0] and "b04" in m.notes[0]


# ── the plan ─────────────────────────────────────────────────────────────────
def test_a_beat_lasts_as_long_as_its_clip_when_that_is_longer_than_its_speech_or_hold(tmp_path):
    m = _load(tmp_path, {}, probe=lambda _p: 3.0)
    assert manifest.plan(m).duration == pytest.approx(3.0)
    spoken = Manifest("t", SIZE, 30, [Shot("a", Path("a.png"), lines=[Line("Hi.", duration=1.0)], clip=m.shots[0].clip)])
    assert manifest.plan(spoken).duration == pytest.approx(3.0)  # longer than lead + line + tail (1.65 s)
    m.shots[0].lines = [Line("Long.", duration=4.0)]
    assert manifest.plan(m).duration == pytest.approx(0.3 + 4.0 + 0.35)  # speech longer than the clip: the speech decides, the clip plays alongside
    trimmed = _load(tmp_path, {"start": 0.5, "end": 2.0}, probe=lambda _p: 3.0)
    assert manifest.plan(trimmed).duration == pytest.approx(1.5)
    held = _load(tmp_path, {}, probe=lambda _p: 1.0, hold=5)
    assert manifest.plan(held).duration == pytest.approx(5.0)  # a longer hold still holds


def test_the_clips_sound_is_a_voice_for_the_ducking_and_a_piece_of_the_mix_from_the_picture_start(tmp_path, monkeypatch):
    monkeypatch.setattr(clip, "_has_sound", lambda _p: True)
    m = _load(tmp_path, {"start": 0.5, "volume": 0.8}, probe=lambda _p: 2.5)
    t = manifest.plan(m)
    assert build.speech_windows(t) == [(0.0, 2.0)]
    file, at, volume, cut, fades, length = build._pieces(t.shots[0])[-1]
    assert (file.name, at, volume, fades, length) == ("c.webm", 0.0, 0.8, "", 2.0) and "atrim=start=0.5000" in cut
    m.shots[0].clip.audio = False
    assert build.speech_windows(manifest.plan(m)) == [] and build._pieces(manifest.plan(m).shots[0]) == []
    monkeypatch.setattr(clip, "_has_sound", lambda _p: False)  # a clip with no sound in it: nothing to mix, nothing to duck under
    m.shots[0].clip.audio = True
    assert build.speech_windows(manifest.plan(m)) == [] and build._pieces(manifest.plan(m).shots[0]) == []


# ── the filter graph ─────────────────────────────────────────────────────────
def _a_clip(**kw) -> clip.Clip:
    return clip.Clip(Path("c.webm"), kw.pop("duration", 2.0), **kw)


@pytest.mark.parametrize(("corner", "x", "y"), [("top-left", 11, 11), ("top-right", 245, 11), ("bottom-left", 11, 525), ("bottom-right", 245, 525)])
def test_the_clip_sits_in_its_corner_a_3_percent_margin_in(corner, x, y):
    b = clip.box(_a_clip(corner=corner), SIZE)
    assert (b.side, b.border, b.outer, b.x, b.y) == (100, 2, 104, x, y)  # 0.28 of 360 is 100.8: an even 100, a border of 2, 11 px in (3% of 360)


def test_the_filter_lays_the_clip_over_the_picture_after_cropping_it_square_and_cutting_its_part():
    graph = clip.video_filter(_a_clip(start=0.5, end=1.5, duration=1.0), 2, SIZE, 30, 4.0, "[v]", "[vc]")
    assert graph.startswith("[2:v]setpts=PTS-STARTPTS,trim=start=0.5000:end=1.5000,setpts=PTS-STARTPTS,fps=30,crop='min(iw,ih)':'min(iw,ih)',scale=100:100")
    assert "[v]format=rgba[clipb];[clipb][clipp]overlay=x=245:y=525:eof_action=pass" in graph and graph.endswith("[vc]")
    assert "fade=t=out:st=0.750:d=0.250:alpha=1" in graph  # it fades away over its last quarter second


def test_the_shapes_differ_only_in_their_rounding():
    circle, rounded, square = (clip.video_filter(_a_clip(shape=s), 1, SIZE, 30, 4.0, "[v]", "[vc]") for s in clip.SHAPES)
    assert "-50)" in circle and "-18)" in rounded and "-0)" in square  # the corner radius: half the side, 0.18 of it, none


# ── real renders ─────────────────────────────────────────────────────────────
@needs_ffmpeg
@pytest.mark.parametrize("corner", clip.CORNERS)
def test_the_clip_shows_in_its_corner_only_inside_its_circle_and_the_rest_of_the_frame_is_the_still(tmp_path, corner):
    _clip_file(tmp_path / "c.mp4")
    m = manifest.load(_project(tmp_path, {"video": "c.mp4", "corner": corner}), probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4")
    frame = _frame(tmp_path / "out.mp4", 0.8)
    for other in clip.CORNERS:
        b = clip.box(_a_clip(corner=other), SIZE)
        middle = _px(frame, b.x + b.outer // 2, b.y + b.outer // 2)
        assert _near(middle, RED if other == corner else BLUE), (other, middle)
        assert _near(_px(frame, b.x + 4, b.y + 4), BLUE), other  # a corner of its square is outside the circle: the still
    assert _near(_px(frame, SIZE[0] // 2, SIZE[1] // 2), BLUE)


@needs_ffmpeg
def test_the_clip_plays_from_the_beats_start_its_sound_is_heard_and_it_is_gone_when_it_ends(tmp_path):
    _clip_file(tmp_path / "c.mp4", 1.0)
    m = manifest.load(_project(tmp_path, {"video": "c.mp4"}, hold=2.0), probe=ffmpeg.duration)
    made = build.render(m, tmp_path / "out.mp4")
    assert made["planned_seconds"] == pytest.approx(2.0)
    b = clip.box(_a_clip(), SIZE)
    centre = (b.x + b.outer // 2, b.y + b.outer // 2)
    assert _near(_px(_frame(tmp_path / "out.mp4", 0.05), *centre), RED)  # from the first frames
    assert _near(_px(_frame(tmp_path / "out.mp4", 1.5), *centre), BLUE)  # it ended at 1 s: the still alone
    assert _mean_db(tmp_path / "out.mp4", 0.1, 0.7) > -30  # its tone is in the film
    assert _mean_db(tmp_path / "out.mp4", 1.2, 0.7) < -60  # and stops with it


@needs_ffmpeg
def test_a_clip_with_no_sound_or_its_sound_off_renders_silent(tmp_path):
    (tmp_path / "quiet").mkdir()
    _clip_file(tmp_path / "quiet" / "c.mp4", 1.0, sound=False)
    m = manifest.load(_project(tmp_path / "quiet", {"video": "c.mp4"}), probe=ffmpeg.duration)
    build.render(m, tmp_path / "quiet.mp4")
    assert _near(_px(_frame(tmp_path / "quiet.mp4", 0.5), *_centre()), RED) and _mean_db(tmp_path / "quiet.mp4", 0.1, 0.7) < -60
    (tmp_path / "off").mkdir()
    _clip_file(tmp_path / "off" / "c.mp4", 1.0)
    m = manifest.load(_project(tmp_path / "off", {"video": "c.mp4", "audio": False}), probe=ffmpeg.duration)
    build.render(m, tmp_path / "off.mp4")
    assert _mean_db(tmp_path / "off.mp4", 0.1, 0.7) < -60


def _centre(corner: str = "bottom-right", size: tuple[int, int] = SIZE) -> tuple[int, int]:
    b = clip.box(_a_clip(corner=corner), size)
    return b.x + b.outer // 2, b.y + b.outer // 2


@needs_ffmpeg
def test_a_browser_webm_with_no_length_in_its_header_is_trimmed_and_plays_with_its_sound_beside_a_line(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    _clip_file(tmp_path / "c.webm", 2.0, piped=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=0.5", str(tmp_path / "line.wav")], check=True)
    m = manifest.load(_project(tmp_path, {"video": "c.webm", "start": 0.5, "corner": "top-left"}, lines=[{"text": "Hi.", "audio": "line.wav"}]), probe=ffmpeg.duration)
    assert m.shots[0].clip.duration == pytest.approx(1.5, abs=0.06)
    made = build.render(m, tmp_path / "out.mp4")
    assert made["planned_seconds"] == pytest.approx(1.5, abs=0.06)  # the clip outlasts the line (0.3 + 0.5 + 0.35)
    assert _near(_px(_frame(tmp_path / "out.mp4", 1.0), *_centre("top-left")), RED)
    assert _mean_db(tmp_path / "out.mp4", 1.0, 0.4) > -30  # the clip's sound after the line has ended


@needs_ffmpeg
def test_a_browser_webm_with_no_sound_and_no_length_in_its_header_is_measured_by_its_picture(tmp_path):
    _clip_file(tmp_path / "c.webm", 1.0, sound=False, piped=True)
    m = manifest.load(_project(tmp_path, {"video": "c.webm"}), probe=ffmpeg.duration)  # the probe listens, and there is nothing to hear
    assert m.notes == [] and m.shots[0].clip.duration == pytest.approx(1.0, abs=0.06)
    build.render(m, tmp_path / "out.mp4")
    assert _near(_px(_frame(tmp_path / "out.mp4", 0.5), *_centre()), RED) and _mean_db(tmp_path / "out.mp4", 0.1, 0.7) < -60


@needs_ffmpeg
def test_a_draft_shows_the_clip_in_its_corner_of_the_smaller_frame(tmp_path):
    _clip_file(tmp_path / "c.mp4", 1.0)
    m = manifest.load(_project(tmp_path, {"video": "c.mp4", "corner": "top-right"}), probe=ffmpeg.duration)
    build.render(m, tmp_path / "draft.mp4", draft=True)
    half = (SIZE[0] // 2, SIZE[1] // 2)
    frame = _frame(tmp_path / "draft.mp4", 0.5, half)
    assert _near(_px(frame, *_centre("top-right", half), width=half[0]), RED) and _near(_px(frame, *_centre("bottom-right", half), width=half[0]), BLUE)


@needs_ffmpeg
def test_a_clip_rides_over_an_overlay_and_through_a_dissolve_and_keeps_the_films_length(tmp_path):
    project = demo.make(tmp_path / "demo", size=SIZE)
    raw = json.loads(project.read_text())
    _clip_file(project.parent / "c.mp4", 1.0)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=30:d=1", "-pix_fmt", "yuv420p", str(project.parent / "o.mp4")], check=True)
    raw["shots"][1].update({"clip": {"video": "c.mp4", "corner": "top-left"}, "overlay": {"video": "o.mp4", "blend": "screen"}, "transition": "dissolve", "transition_seconds": 0.5})
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration)
    t = manifest.plan(m)
    made = build.render(m, tmp_path / "out.mp4", draft=True)
    assert made["measured_seconds"] == pytest.approx(t.duration, abs=0.1)
    half = (SIZE[0] // 2, SIZE[1] // 2)
    frame = _frame(tmp_path / "out.mp4", t.shots[1].start + 0.6, half)
    r, g, b = _px(frame, *_centre("top-left", half), width=half[0])
    assert r > 200 and g < 120 and b < 120  # red, over the screened overlay


@needs_ffmpeg
def test_a_render_without_a_clip_issues_exactly_the_commands_it_did_before(tmp_path, monkeypatch):
    """No clip, nothing new: every shot's picture is the one -vf (or the overlay graph) it always was, and no command names a clip filter."""
    seen = []
    real = ffmpeg.run
    monkeypatch.setattr(ffmpeg, "run", lambda cmd, **kw: seen.append(cmd) or real(cmd, **kw))
    m = manifest.load(demo.make(tmp_path / "demo", size=SIZE), probe=ffmpeg.duration)
    build.render(m, tmp_path / "out.mp4", draft=True)
    joined = [" ".join(map(str, c)) for c in seen]
    assert not any("clipv" in c or "maskedmerge" in c or "alphamerge" in c for c in joined)
    shots = [c for c in seen if "zoompan" in " ".join(map(str, c))]
    assert len(shots) == len(m.shots) and all("-vf" in c and "-filter_complex" not in c for c in shots)


# ── the pull ─────────────────────────────────────────────────────────────────
def test_from_beat_hands_on_the_file_and_only_the_settings_that_are_set(tmp_path):
    fetched = []

    def fetch(asset):
        fetched.append(asset)
        return tmp_path / "video" / "clips" / "b04.webm"

    notes: list[str] = []
    beat = {"clip": "asset-7", "clip_corner": " Top-Left ", "clip_size": 0.3, "clip_audio": False, "clip_volume": "", "clip_start": 0, "clip_end": None}
    assert clip.from_beat(beat, fetch, tmp_path, "beat 04", notes) == {"video": "video/clips/b04.webm", "id": "asset-7", "corner": "top-left", "size": 0.3, "audio": False, "start": 0}
    assert clip.from_beat({"clip_corner": "top-left"}, fetch, tmp_path, "beat 04", notes) is None and fetched == ["asset-7"] and notes == []


def test_a_clip_that_cannot_be_fetched_is_left_out_and_said(tmp_path):
    def fetch(_asset):
        raise RuntimeError("404 not found")

    notes: list[str] = []
    assert clip.from_beat({"clip": "gone"}, fetch, tmp_path, "beat 04", notes) is None
    assert notes == ["beat 04: its clip could not be fetched (404 not found), so it plays without it"]


def test_the_pull_gives_a_clip_beat_with_no_still_a_plain_card_and_no_default_hold(marvin, tmp_path):
    rows = [dict(r) for r in _ROWS]
    rows += [
        {"slug": f"{S}-beat-04", "dataJson": {"story": S, "number": "04", "clip": "asset-1", "clip_corner": "top-left", "clip_size": 0.35}},
        {"slug": f"{S}-beat-05", "dataJson": {"story": S, "number": "05", "clip": "asset-gone"}},  # cannot be fetched: nothing else to show, so left out
    ]
    _FakeMarvin.rows = rows
    try:
        result = marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    shots = {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}
    four = shots["b04"]
    assert four["clip"] == {"video": "video/clips/b04.mp3", "id": "asset-1", "corner": "top-left", "size": 0.35} and (tmp_path / four["clip"]["video"]).is_file()
    assert four["still"] == "stills/b04-card.png" and (tmp_path / four["still"]).is_file() and "hold" not in four
    assert "b05" not in shots and "05" in result["skipped"] and any("beat 05" in n for n in result["notes"])
    assert all("clip" not in s for k, s in shots.items() if k != "b04")  # a beat without one gets no clip key at all


def test_the_timeline_view_reads_the_clip_from_the_fields_the_pull_reads():
    # The Marvin Timeline (story-timeline, spine.clip, v227) lays a beat's clip as the render does: the same fields, its sound in the lines lane.
    package = json.loads((Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json").read_text(encoding="utf-8"))
    blueprints = {b["slug"]: b for b in package["blueprints"]}
    spec = blueprints["story-timeline"]["payload"]["spine"]["clip"]
    assert spec["field"] == "clip" and spec["lane"] == "lines"
    assert {key: spec[key] for key, _ in clip.FIELDS} == dict(clip.FIELDS)
    beat = {f["key"] for f in blueprints["beat"]["payload"]["schema_json"]["fields"]}
    described = {spec[k] for k in ("seconds", "has_audio", "poster", "text", "words", "width", "height")}  # what describe-video fills in (v226)
    assert {"clip", *dict(clip.FIELDS).values(), *described} <= beat
