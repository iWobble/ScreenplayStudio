"""Release C2: a video over a still (three levels), the music's level per beat, ducking under speech, and where a beat's ambience comes from."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest, marvin_pull
from storyrender.manifest import Line, Manifest, ManifestError, Overlay, Shot

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _tone(path: Path, seconds: float, hz: int = 440) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", "-c:a", "libmp3lame", str(path)], check=True)
    return path


def _colour_video(path: Path, colour: str, seconds: float = 1.0, size: str = "64x64") -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30:d={seconds}", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _mean_db(path: Path, start: float, length: float) -> float:
    done = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", done.stderr).group(1).replace("-inf", "-91"))


def _bed_db(path: Path, start: float, length: float, hz: int = 1500) -> float:
    """The level of just the 1500 Hz band, which is where the test's music bed sits and the narration does not."""
    done = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", f"bandpass=f={hz}:width_type=h:w=300,volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", done.stderr).group(1).replace("-inf", "-91"))


def _frame_rgb(video: Path, at: float) -> tuple[int, int, int]:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


def _timeline(*shots: Shot) -> manifest.Timeline:
    return manifest.plan(Manifest("t", (360, 640), 30, list(shots)))


def _shot(sid: str, hold: float, **kw) -> Shot:
    return Shot(sid, Path(f"{sid}.png"), hold=hold, **kw)


# ── the music's level over the film ──────────────────────────────────────────
def _at(expression: str, t: float) -> float:
    """Evaluate music_level's expression the way ffmpeg would."""
    clip = lambda x, lo, hi: max(lo, min(hi, x))  # noqa: E731
    return eval(expression, {"clip": clip, "t": t})  # noqa: S307


def test_no_shot_with_a_level_of_its_own_leaves_the_music_at_the_story_level():
    assert build.music_level(_timeline(_shot("a", 4), _shot("b", 4)), 0.12) is None
    assert build.music_level(_timeline(_shot("a", 4, music_volume=0.12)), 0.12) is None  # the same level is no change


def test_a_beat_can_take_the_music_to_silence_and_back_with_a_short_ramp():
    expr = build.music_level(_timeline(_shot("a", 4), _shot("b", 4, music_volume=0.0), _shot("c", 4)), 0.2)
    assert _at(expr, 0.0) == pytest.approx(0.2) and _at(expr, 3.0) == pytest.approx(0.2)  # before the dip
    assert _at(expr, 4.0) == pytest.approx(0.1)  # half way down at the cut (0.5 s ramp centred on it)
    assert _at(expr, 5.0) == pytest.approx(0.0) and _at(expr, 7.0) == pytest.approx(0.0)  # silent through the beat
    assert _at(expr, 8.0) == pytest.approx(0.1)  # and half way back up at the next cut
    assert _at(expr, 9.0) == pytest.approx(0.2)


def test_neighbouring_beats_at_one_level_are_one_run_and_a_ramp_never_outlasts_a_short_beat():
    expr = build.music_level(_timeline(_shot("a", 3, music_volume=0.5), _shot("b", 3, music_volume=0.5), _shot("c", 0.2, music_volume=0.0)), 0.12)
    assert _at(expr, 2.0) == pytest.approx(0.5)  # a and b make one run: no dip between them
    assert expr.count("clip(") == 1  # a single change
    assert _at(expr, 6.0 + 0.1) == pytest.approx(0.0)  # past the short beat's own ramp, which was held to its length


# ── the overlay filter ───────────────────────────────────────────────────────
@pytest.mark.parametrize("blend", ["screen", "multiply", "overlay", "lighten", "addition"])
def test_a_blend_is_the_blend_filter_with_its_mode_and_opacity(blend):
    f = build.overlay_filter(Overlay(Path("o.mp4"), blend, 0.4), (360, 640), 30)
    assert f"blend=all_mode={blend}:all_opacity=0.400" in f and f.endswith("[v]") and "[base]" in f and "[1:v]scale=360:640" in f


def test_normal_keeps_the_videos_own_transparency_and_only_fades_when_asked():
    plain = build.overlay_filter(Overlay(Path("o.webm")), (360, 640), 30)
    faded = build.overlay_filter(Overlay(Path("o.webm"), "normal", 0.5), (360, 640), 30)
    assert "overlay=shortest=1:format=auto" in plain and "colorchannelmixer" not in plain
    assert "colorchannelmixer=aa=0.500" in faded


# ── the manifest ─────────────────────────────────────────────────────────────
def _load(tmp_path: Path, **raw):
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "o.mp4").write_bytes(b"x")
    (tmp_path / "fx.mp3").write_bytes(b"x")
    body = {"shots": [{"id": "b01", "still": "b.png", "hold": 2, "lines": [], **raw.pop("shot", {})}], **raw}
    (tmp_path / "m.json").write_text(json.dumps(body))
    return manifest.load(tmp_path / "m.json", probe=lambda _p: 1.0, need_stills=False)


def test_the_manifest_keeps_a_shots_overlay_and_music_level_and_the_musics_ducking(tmp_path):
    m = _load(tmp_path, shot={"overlay": {"video": "o.mp4", "blend": "screen", "opacity": 0.6, "id": "rain"}, "music_volume": 0}, music={"audio": "fx.mp3", "volume": 0.2, "duck": "strong"})
    shot = m.shots[0]
    assert (shot.overlay.blend, shot.overlay.opacity, shot.overlay.ref, shot.overlay.video.name) == ("screen", 0.6, "rain", "o.mp4")
    assert shot.music_volume == 0.0 and m.music["duck"] == "strong"


def test_an_overlay_defaults_to_normal_at_full_opacity_and_a_shot_without_one_has_none(tmp_path):
    m = _load(tmp_path, shot={"overlay": {"video": "o.mp4"}})
    assert (m.shots[0].overlay.blend, m.shots[0].overlay.opacity) == ("normal", 1.0)
    assert _load(tmp_path).shots[0].overlay is None and _load(tmp_path).shots[0].music_volume is None


@pytest.mark.parametrize(
    "raw",
    [
        {"shot": {"overlay": {"video": "o.mp4", "blend": "sparkle"}}},
        {"shot": {"overlay": {"video": "o.mp4", "opacity": 1.5}}},
        {"shot": {"overlay": {"blend": "screen"}}},
        {"shot": {"music_volume": 2}},
        {"music": {"audio": "fx.mp3", "duck": "crushing"}},
    ],
)
def test_a_bad_overlay_level_or_ducking_is_refused_with_the_manifest_error(tmp_path, raw):
    with pytest.raises(ManifestError):
        _load(tmp_path, **raw)


# ── what the pull hands on ───────────────────────────────────────────────────
DATA = lambda e: e["dataJson"]  # noqa: E731


def test_the_overlay_comes_from_the_beat_else_its_scene_else_the_story(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: fetched.append(asset) or (tmp_path / "video" / "overlays" / f"{asset}.mp4"))
    scenes = {"rain": {"dataJson": {"overlay": "scene-rain", "overlay_blend": "screen", "overlay_opacity": 0.5}}}
    story = {"overlay": "grain", "overlay_blend": "overlay"}
    pull = lambda beat: marvin_pull._overlay(("u", "t"), tmp_path, beat, scenes, story, DATA, {})  # noqa: E731
    assert pull({"scene": "rain", "overlay": "mine", "overlay_blend": "addition", "overlay_opacity": 0.3}) == {"video": "video/overlays/mine.mp4", "blend": "addition", "opacity": 0.3, "id": "mine"}
    assert pull({"scene": "rain"}) == {"video": "video/overlays/scene-rain.mp4", "blend": "screen", "opacity": 0.5, "id": "scene-rain"}
    assert pull({"scene": "other"}) == {"video": "video/overlays/grain.mp4", "blend": "overlay", "opacity": 1.0, "id": "grain"}  # the story's, at full opacity
    assert pull({}) is not None


def test_a_blend_of_none_switches_the_overlay_off_for_that_beat_or_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "video" / "overlays" / f"{asset}.mp4")
    scenes = {"dry": {"dataJson": {"overlay_blend": "none"}}}
    story = {"overlay": "grain"}
    pull = lambda beat: marvin_pull._overlay(("u", "t"), tmp_path, beat, scenes, story, DATA, {})  # noqa: E731
    assert pull({"scene": "dry"}) is None  # the scene turns the story's grain off
    assert pull({"scene": "dry", "overlay": "mine"}) is not None  # a beat of its own still gets its own
    assert pull({"overlay": "mine", "overlay_blend": "none"}) is None  # and a beat can turn off its own
    assert marvin_pull._overlay(("u", "t"), tmp_path, {}, {}, {}, DATA, {}) is None  # nothing named anywhere


def test_an_overlay_asset_is_fetched_once_however_many_beats_use_it(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: fetched.append(asset) or (tmp_path / "video" / "overlays" / f"{asset}.mp4"))
    taken: dict = {}
    for _ in range(3):
        marvin_pull._overlay(("u", "t"), tmp_path, {}, {}, {"overlay": "grain"}, DATA, taken)
    assert fetched == ["grain"]


@pytest.mark.parametrize(("given", "want"), [(0.5, 0.5), ("0.25", 0.25), (0, 0.0), (1, 1.0), (None, None), ("", None), ("loud", None), (1.5, None), (-1, None)])
def test_a_level_field_is_a_number_from_zero_to_one_or_nothing(given, want):
    assert marvin_pull._unit(given) == want


def _sounds(**levels):
    return {name: {"dataJson": {"audio": f"asset-{name}", **({"volume": level} if level is not None else {})}} for name, level in levels.items()}


def test_a_beats_ambience_comes_from_itself_else_its_scene_else_the_story(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / f"{asset}.mp3")
    sounds = _sounds(wind=0.4, rain=None, hum=0.9)
    scenes = {"storm": {"dataJson": {"ambience": "rain", "ambience_volume": 0.7, "ambience_muffled": True}}}
    story = {"ambience": "hum", "ambience_volume": 0.15}
    pull = lambda beat: marvin_pull._ambience(("u", "t"), tmp_path, beat, scenes, story, sounds, DATA, {}, [])  # noqa: E731
    own = pull({"scene": "storm", "ambience": "wind"})
    assert (own["id"], own["volume"], own["muffled"]) == ("wind", 0.4, False)  # the beat's own: the sound's level, never muffled
    assert pull({"scene": "storm", "ambience": "wind", "ambience_volume": 0.1})["volume"] == 0.1  # the beat's level wins
    scene = pull({"scene": "storm"})
    assert (scene["id"], scene["volume"], scene["muffled"]) == ("rain", 0.7, True)
    default = pull({"scene": "none"})
    assert (default["id"], default["volume"], default["muffled"]) == ("hum", 0.15, False)  # the story's default, at its own level
    assert pull({"scene": "none", "ambience_volume": 0.3})["volume"] == 0.3  # the beat's level applies to the default too


def test_ambience_without_a_take_gives_no_bed_and_is_named_once_as_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / f"{asset}.mp3")
    sounds = {"hum": {"dataJson": {"audio": None}}}
    missing: list = []
    for _ in range(2):
        assert marvin_pull._ambience(("u", "t"), tmp_path, {}, {}, {"ambience": "hum"}, sounds, DATA, {}, missing) is None
    assert marvin_pull._ambience(("u", "t"), tmp_path, {}, {}, {"ambience": "gone"}, sounds, DATA, {}, missing) is None
    assert missing == ["hum", "gone"]
    assert marvin_pull._ambience(("u", "t"), tmp_path, {}, {}, {}, sounds, DATA, {}, missing) is None  # nothing named


def test_the_story_asks_for_ducking_only_with_a_known_strength(tmp_path, monkeypatch):
    row = {"slug": "theme", "dataJson": {"kind": "music", "audio": "asset-1"}}
    monkeypatch.setattr(marvin_pull.marvin_api, "query", lambda creds, spec, limit=100: [row])
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / "theme.mp3")
    got = lambda **story: marvin_pull.music_of(("u", "t"), tmp_path, {"music": "theme", **story}, DATA)  # noqa: E731
    assert "duck" not in got() and "duck" not in got(music_ducking="none") and "duck" not in got(music_ducking="crushing")
    assert got(music_ducking="light")["duck"] == "light" and got(music_ducking="strong")["duck"] == "strong"


# ── real renders ─────────────────────────────────────────────────────────────
def _project(tmp_path: Path, **tweak) -> Path:
    project = demo.make(tmp_path / "demo", size=(360, 640))
    raw = json.loads(project.read_text())
    tweak["edit"](raw, project.parent) if "edit" in tweak else None
    project.write_text(json.dumps(raw))
    return project


@needs_ffmpeg
def test_a_screen_blend_lifts_the_still_toward_the_overlay_and_leaves_the_rest_of_the_film_alone(tmp_path):
    def edit(raw, folder):
        _colour_video(folder / "light.mp4", "white", 1.0, "64x64")  # 1 s, so it also proves the loop over a longer shot
        raw["shots"][0]["overlay"] = {"video": "light.mp4", "blend": "screen", "opacity": 1.0}

    project = _project(tmp_path, edit=edit)
    plain_project = demo.make(tmp_path / "plain", size=(360, 640))
    m, plain = manifest.load(project, probe=ffmpeg.duration), manifest.load(plain_project, probe=ffmpeg.duration)
    build.render(m, tmp_path / "over.mp4", draft=True)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    over_first, plain_first = _frame_rgb(tmp_path / "over.mp4", 0.5), _frame_rgb(tmp_path / "plain.mp4", 0.5)
    assert min(over_first) > 240 and min(plain_first) < 240  # white screened over anything is white
    last = m.shots[-1].id
    assert last != m.shots[0].id and _frame_rgb(tmp_path / "over.mp4", ffmpeg.duration(tmp_path / "over.mp4") - 0.3) == pytest.approx(_frame_rgb(tmp_path / "plain.mp4", ffmpeg.duration(tmp_path / "plain.mp4") - 0.3), abs=12)


@needs_ffmpeg
def test_the_overlay_is_looped_for_a_shot_longer_than_the_video_and_the_clip_keeps_its_length(tmp_path):
    def edit(raw, folder):
        _colour_video(folder / "short.mp4", "white", 0.5)
        raw["shots"][0]["overlay"] = {"video": "short.mp4", "blend": "screen"}

    project = _project(tmp_path, edit=edit)
    m = manifest.load(project, probe=ffmpeg.duration)
    planned = manifest.plan(m).shots[0]
    assert planned.duration > 1.5  # longer than the overlay, so it has to loop
    build.render(m, tmp_path / "out.mp4", draft=True)
    assert min(_frame_rgb(tmp_path / "out.mp4", planned.duration - 0.2)) > 240  # still white near the end of the shot: it looped
    plain = manifest.plan(manifest.load(demo.make(tmp_path / "plain", size=(360, 640)), probe=ffmpeg.duration))
    assert plain.duration == pytest.approx(manifest.plan(m).duration)  # an overlay never changes the film's length


@needs_ffmpeg
def test_a_webm_with_transparency_keeps_it(tmp_path):
    if not build._has_decoder("libvpx-vp9"):
        pytest.skip("no libvpx-vp9 decoder here")
    folder = tmp_path / "demo"
    project = demo.make(folder, size=(360, 640))
    # a webm that is red on its left half and fully clear on its right half
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=1,format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='if(lt(X,32),255,0)'", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", str(folder / "half.webm")],
        check=True,
    )
    raw = json.loads(project.read_text())
    raw["shots"][0]["overlay"] = {"video": "half.webm", "blend": "normal"}
    project.write_text(json.dumps(raw))
    build.render(manifest.load(project, probe=ffmpeg.duration), tmp_path / "out.mp4", draft=True)
    left = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "0.5", "-i", str(tmp_path / "out.mp4"), "-frames:v", "1", "-vf", "crop=iw/4:ih/4:0:ih/2,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    right = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "0.5", "-i", str(tmp_path / "out.mp4"), "-frames:v", "1", "-vf", "crop=iw/4:ih/4:3*iw/4:ih/2,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert left[0] > 180 and left[1] < 90  # the opaque half is red
    assert not (right[0] > 180 and right[1] < 90)  # the clear half shows the still, not red


def _music_project(tmp_path: Path, shots_music, duck=None, hz: int = 220) -> Manifest:
    project = demo.make(tmp_path / "demo", size=(360, 640))
    _tone(project.parent / "bed.mp3", 30.0, hz)
    for voice in (project.parent / "audio").glob("*.wav"):  # the demo's stand-in voices are very quiet: bring them up to a speaking level
        louder = voice.with_name("louder.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-af", "volume=6", str(louder)], check=True)
        louder.replace(voice)
    raw = json.loads(project.read_text())
    raw["music"] = {"audio": "bed.mp3", "volume": 0.8, "fade_in": 0, "fade_out": 0, **({"duck": duck} if duck else {})}
    for shot, level in zip(raw["shots"], shots_music, strict=False):
        if level is not None:
            shot["music_volume"] = level
    project.write_text(json.dumps(raw))
    return manifest.load(project, probe=ffmpeg.duration)


@needs_ffmpeg
def test_the_music_goes_silent_in_a_beat_that_sets_it_to_zero_and_comes_back(tmp_path):
    m = _music_project(tmp_path, [None, 0.0, None], hz=1500)
    plan = manifest.plan(m)
    assert len(plan.shots) >= 3
    build.render(m, tmp_path / "out.mp4", draft=True)
    before, quiet, after = plan.shots[0], plan.shots[1], plan.shots[2]
    window = lambda shot: (shot.start + 0.7, max(0.2, min(shot.duration - 1.0, 1.0)))  # noqa: E731 - clear of the half-second ramps at the cuts
    assert _bed_db(tmp_path / "out.mp4", *window(quiet)) < _bed_db(tmp_path / "out.mp4", *window(before)) - 20  # silent through the beat
    assert _bed_db(tmp_path / "out.mp4", *window(after)) > _bed_db(tmp_path / "out.mp4", *window(quiet)) + 20  # and back for the next


@needs_ffmpeg
def test_ducking_lowers_the_bed_while_someone_speaks(tmp_path):
    plain = _music_project(tmp_path / "a", [None, None, None], hz=1500)  # a bed far from the narration's pitch, so it can be measured on its own
    ducked = _music_project(tmp_path / "b", [None, None, None], duck="strong", hz=1500)
    build.render(plain, tmp_path / "plain.mp4", draft=True)
    build.render(ducked, tmp_path / "ducked.mp4", draft=True)
    shot = manifest.plan(plain).shots[0]
    window = (shot.start + 0.6, max(0.3, min(shot.duration - 1.0, 1.0)))
    assert _bed_db(tmp_path / "ducked.mp4", *window) < _bed_db(tmp_path / "plain.mp4", *window) - 3


def test_a_line_object_still_builds_without_the_new_fields():
    shot = Shot("a", Path("a.png"), hold=1.0, lines=[Line("x", None, 1.0)])
    assert shot.overlay is None and shot.music_volume is None
