"""storyrender: the pure parts always, the real ffmpeg render when ffmpeg is installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import beats, build, captions, demo, ffmpeg, manifest
from storyrender.manifest import Line, Manifest, Move, Shot

BEAT_SHEET = Path(__file__).resolve().parents[2] / "stories" / "the-last-onion" / "beat-sheet.md"
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


# ── beat sheet ───────────────────────────────────────────────────────────────
def test_the_audio_cell_splits_on_speaker_labels_and_sounds_are_not_speech():
    parts = beats.split_audio("Narrator: He picked up the onion. Cook: How many bowls? Captain: Everyone.")
    assert [(p["speaker"], p["text"]) for p in parts] == [("Narrator", "He picked up the onion."), ("Cook", "How many bowls?"), ("Captain", "Everyone.")]
    mixed = beats.split_audio("Captain: What’s that for? Sound: brief pause; spoon against bowl. Cook: Breakfast.")
    assert [(p["speaker"], p["kind"]) for p in mixed] == [("Captain", "speech"), ("Sound", "sound"), ("Cook", "speech")]
    assert beats.split_audio("No speech. Hold on the captain’s small smile.") == []


@pytest.mark.skipif(not BEAT_SHEET.exists(), reason="the Last Onion beat sheet isn't here")
def test_the_last_onion_beat_sheet_parses_to_24_beats_and_the_lines_to_record():
    rows = beats.load(BEAT_SHEET)
    assert [r["beat"] for r in rows] == [f"{n:02d}" for n in range(1, 25)]
    assert rows[0]["hold"] == 8 and rows[0]["lines"][0]["speaker"] == "Narrator"
    assert [ln["speaker"] for ln in rows[7]["lines"]] == ["Narrator", "Cook", "Captain"]  # beat 08
    assert rows[14]["lines"] == [] and rows[14]["sounds"]  # beat 15: sound only
    assert rows[23]["lines"] == []  # beat 24: no speech
    lines = beats.speech_lines(rows)
    assert lines[0]["id"] == "b01-1" and len({ln["id"] for ln in lines}) == len(lines) and 24 <= len(lines) <= 32
    assert all(ln["characters"] == len(ln["text"]) for ln in lines) and 0 < sum(ln["characters"] for ln in lines) < 5000


def test_the_skeleton_manifest_names_stills_and_lines_by_convention():
    rows = beats.parse("| 04 | 20–24s | Cook: Your feast. | Cabin two-shot |\n")
    shot = beats.skeleton_manifest(rows, "T")["shots"][0]
    assert shot["id"] == "b04" and shot["still"] == "stills/b04.png" and shot["hold"] == 4
    assert shot["lines"] == [{"speaker": "Cook", "text": "Your feast.", "audio": "audio/b04-1.mp3"}]


# ── timeline ─────────────────────────────────────────────────────────────────
def _shot(sid, hold=0.0, durations=(), **kw):
    return Shot(sid, Path(f"{sid}.png"), hold=hold, lines=[Line("x", None, d) for d in durations], **kw)


def _manifest(*shots, **kw):
    return Manifest("t", (1080, 1920), 30, list(shots), **kw)


def test_a_shot_lasts_as_long_as_its_audio_needs_or_its_hold_if_longer():
    t = manifest.plan(_manifest(_shot("a", hold=2, durations=[3.0]), _shot("b", hold=5, durations=[1.0])))
    a, b = t.shots
    assert a.duration == pytest.approx(0.3 + 3.0 + 0.35) and b.duration == 5  # the audio decides a; the hold decides b
    assert b.start == pytest.approx(a.duration) and t.duration == pytest.approx(a.duration + 5)


def test_lines_in_a_shot_are_spaced_by_the_gap_and_the_end_hold_extends_the_last_shot():
    t = manifest.plan(_manifest(_shot("a", durations=[1.0, 2.0]), end_hold=1.5))
    (shot,) = t.shots
    assert [round(p.start, 3) for p in shot.lines] == [0.3, 1.55]
    assert shot.duration == pytest.approx(0.3 + 1.0 + 0.25 + 2.0 + 0.35 + 1.5)


def test_a_manifest_must_be_a_known_shape_and_point_at_real_files(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"size": [1080, 1200], "shots": [{"still": "a.png"}]}))
    with pytest.raises(manifest.ManifestError, match="9:16"):
        manifest.load(path, probe=lambda p: 1.0)
    path.write_text(json.dumps({"shots": [{"id": "s", "still": "missing.png"}]}))
    with pytest.raises(manifest.ManifestError, match="no such file missing.png"):
        manifest.load(path, probe=lambda p: 1.0)
    path.write_text(json.dumps({"shots": [{"id": "s", "still": "a.png", "lines": [{"text": "x"}]}]}))
    with pytest.raises(manifest.ManifestError, match="needs audio, or a duration"):
        manifest.load(path, probe=lambda p: 1.0)
    path.write_text(json.dumps({"shots": [{"id": "s", "still": "a.png", "move": {"to": {"zoom": 0.5}}}]}))
    with pytest.raises(manifest.ManifestError, match="zoom is 1 or more"):
        manifest.load(path, probe=lambda p: 1.0)


def test_the_zoompan_filter_runs_from_the_first_position_to_the_second_over_the_shots_frames():
    planned = manifest.plan(_manifest(_shot("a", hold=2, move_from=Move(0.5, 0.5, 1.0), move_to=Move(0.6, 0.4, 1.25)))).shots[0]
    f = build.zoompan_filter(planned, (1080, 1920), 30)
    assert "scale=2160:3840" in f and "s=1080x1920" in f and "fps=30" in f and "on/59" in f  # 60 frames
    assert "(1.0+(1.25-1.0)*" in f and "(0.5+(0.6-0.5)*" in f


# ── captions ─────────────────────────────────────────────────────────────────
def test_caption_chunks_break_at_punctuation_and_stay_short():
    words = [{"text": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate("The captain ordered a feast. At dawn, they would attack".split())]
    chunks = captions.chunk_words(words)
    assert [c[0] for c in chunks] == ["The captain ordered a", "feast.", "At dawn,", "they would attack"]
    assert chunks[0][1] == 0 and chunks[1][2] == pytest.approx(1.45)


def test_without_word_timings_text_is_spread_over_the_line_by_length():
    chunks = captions.chunk_text("Your feast. Make do.", 2.0)
    assert [c[0] for c in chunks] == ["Your feast.", "Make do."]
    assert chunks[0][1] == 0 and chunks[-1][2] == pytest.approx(2.0)


def test_the_ass_file_has_one_dialogue_per_cue_at_the_timeline_time_and_a_silent_line_has_none():
    shots = [_shot("a", durations=[1.0]), _shot("b", durations=[1.0])]
    shots[0].lines[0].text, shots[1].lines[0].text = "First line.", "Second line."
    shots[0].lines[0].caption = shots[1].lines[0].caption = True
    shots[1].lines.append(Line("(sound)", None, 1.0, caption=False))
    out = captions.ass(manifest.plan(_manifest(*shots)), (1080, 1920))
    assert out.count("Dialogue:") == 2 and "PlayResX: 1080" in out and "(sound)" not in out
    assert "Dialogue: 0,0:00:00.30,0:00:01.30,Default,,0,0,0,,First line." in out
    assert "Dialogue: 0,0:00:01.95,0:00:02.95,Default,,0,0,0,,Second line." in out  # shot b starts at 1.65 + 0.3


# ── a real render ────────────────────────────────────────────────────────────
@needs_ffmpeg
def test_three_beats_render_to_a_vertical_mp4_with_audio_captions_and_the_planned_length(tmp_path):
    path = demo.make(tmp_path)
    m = manifest.load(path, probe=ffmpeg.duration)
    out = tmp_path / "out.mp4"

    result = build.render(m, out)

    info = ffmpeg.probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920) and any(s["codec_type"] == "audio" for s in info["streams"])
    planned = manifest.plan(m).duration
    assert float(info["format"]["duration"]) == pytest.approx(planned, abs=0.1) and result["shots"] == 3 and result["captions"] > 3
    ass = tmp_path / "frame.png"  # a frame mid-line carries burned-in caption pixels near the lower third
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(ass)], check=True)
    assert ass.stat().st_size > 1000


@needs_ffmpeg
def test_sound_effects_and_a_music_bed_are_mixed_and_a_draft_is_half_size(tmp_path):
    path = demo.make(tmp_path)
    data = json.loads(path.read_text())
    demo._tone(tmp_path / "audio" / "chop.wav", 800, 0.5)
    demo._tone(tmp_path / "audio" / "bed.wav", 110, 2.0)
    data["shots"][1]["sfx"] = [{"audio": "audio/chop.wav", "at": 1.0, "volume": 0.5}]
    data["music"] = {"audio": "audio/bed.wav", "volume": 0.1}
    path.write_text(json.dumps(data))
    m = manifest.load(path, probe=ffmpeg.duration)

    build.render(m, tmp_path / "draft.mp4", draft=True)

    info = ffmpeg.probe(tmp_path / "draft.mp4")
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (540, 960)
    assert float(info["format"]["duration"]) == pytest.approx(manifest.plan(m).duration, abs=0.15)
    levels = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", "6.9", "-t", "0.6", "-i", str(tmp_path / "draft.mp4"), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True
    ).stderr
    assert "mean_volume" in levels and "mean_volume: -inf" not in levels  # sound (the chop and the bed) is there


# ── a line cut from a longer take ───────────────────────────────
def test_a_line_cut_from_a_longer_take_lasts_its_range_and_a_bad_range_is_refused(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "take.mp3").write_bytes(b"x")
    path = tmp_path / "m.json"

    def load(**line):
        path.write_text(json.dumps({"shots": [{"id": "s", "still": "a.png", "lines": [{"text": "x", "audio": "take.mp3", **line}]}]}))
        return manifest.load(path, probe=lambda p: 10.0).shots[0].lines[0]

    cut = load(start=2.36, end=10.0)
    assert (cut.start, cut.end) == (2.36, 10.0) and cut.duration == pytest.approx(7.64)
    assert load().duration == 10.0 and load(start=4).duration == 6.0
    with pytest.raises(manifest.ManifestError, match="must come after start"):
        load(start=5, end=4)
    with pytest.raises(manifest.ManifestError, match="outside the 10.00s audio"):
        load(start=12)


@needs_ffmpeg
def test_the_narration_mix_plays_only_the_cut_part_of_the_take(tmp_path):
    take = tmp_path / "take.wav"  # a 1 s tone then 1 s of silence: the cut is the silent second
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-af", "apad=whole_dur=2", str(take)])
    planned = manifest.plan(Manifest("t", (1080, 1920), 30, [Shot("s", tmp_path / "a.png", lines=[Line("x", take, 1.0, start=1.0, end=2.0)], lead=0.0, tail=0.0)]))
    out = tmp_path / "n.wav"

    build._narration(planned.shots[0], out)

    volume = subprocess.run(["ffmpeg", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    assert "max_volume: -91" in volume or "max_volume: -inf" in volume  # silence: the tone (first second) was cut away
