"""audio_measure: the real length of a recording, including one a browser wrote without a length in its header."""

import shutil
import subprocess
from pathlib import Path

import pytest

from storyrender import audio_measure, ffmpeg

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed")


def _tone(path: Path, seconds: float, *args: str) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", *args, str(path)], check=True)
    return path


def _streamed_webm(path: Path, seconds: float) -> Path:
    """Written to a pipe, as MediaRecorder does: the file cannot be seeked back to, so its header never learns its length."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libopus", "-f", "webm", "pipe:1"]
    path.write_bytes(subprocess.run(cmd, check=True, capture_output=True).stdout)
    return path


def test_the_length_of_an_mp3_is_read_from_its_header(tmp_path):
    assert audio_measure.seconds(_tone(tmp_path / "t.mp3", 2.0, "-c:a", "libmp3lame")) == pytest.approx(2.0, abs=0.1)


def test_the_length_of_a_wav_is_read_from_its_header(tmp_path):
    assert audio_measure.seconds(_tone(tmp_path / "t.wav", 1.5)) == pytest.approx(1.5, abs=0.05)


def test_a_streamed_browser_webm_with_no_length_in_its_header_is_measured_by_decoding_it(tmp_path):
    rec = _streamed_webm(tmp_path / "r.webm", 3.0)

    assert audio_measure.seconds(rec) == pytest.approx(3.0, abs=0.15)
    assert audio_measure.decoded_seconds(rec) == pytest.approx(3.0, abs=0.15)


def test_a_file_that_is_not_sound_says_so(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not a recording")

    with pytest.raises(ffmpeg.FfmpegError):
        audio_measure.seconds(notes)


def test_the_renders_probe_listens_to_a_recording_whose_header_has_no_length_even_when_it_is_named_mp3(tmp_path):
    """The pull saves a take as .mp3 when it cannot tell: a browser recording (webm) then has no length in its header and the probe used to
    stop the render with "has no duration"."""
    streamed = _streamed_webm(tmp_path / "granny-advice-line-01-1.mp3", 2.0)
    assert "duration" not in ffmpeg.probe(streamed).get("format", {})  # the header says nothing
    assert ffmpeg.duration(streamed) == pytest.approx(2.0, abs=0.15)


def test_the_probe_still_reads_a_header_length_when_there_is_one(tmp_path):
    assert ffmpeg.duration(_tone(tmp_path / "t.mp3", 1.5, "-c:a", "libmp3lame")) == pytest.approx(1.5, abs=0.1)


def test_a_file_that_is_not_sound_still_says_so(tmp_path):
    junk = tmp_path / "x.mp3"
    junk.write_bytes(b"not audio at all")
    with pytest.raises(ffmpeg.FfmpegError):
        ffmpeg.duration(junk)


def test_the_level_and_peak_of_a_tone_are_what_it_was_made_at_and_a_louder_one_reads_louder(tmp_path):
    quiet = _tone(tmp_path / "quiet.wav", 1.0, "-af", "volume=-12dB")
    loud = _tone(tmp_path / "loud.wav", 1.0)
    (q_mean, q_peak), (l_mean, l_peak) = audio_measure.levels(quiet), audio_measure.levels(loud)
    assert l_peak - q_peak == pytest.approx(12, abs=1)  # 12 dB lower reads 12 dB lower
    assert l_mean - q_mean == pytest.approx(12, abs=1)
    assert q_peak < 0 and l_peak < 0 and q_mean < q_peak  # below full scale; the average of a tone is under its peak
    assert l_peak - l_mean == pytest.approx(3, abs=1)  # a sine's peak is 3 dB above its average


def test_a_silent_recording_reads_at_the_floor_not_minus_infinity(tmp_path):
    silent = tmp_path / "silent.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", str(silent)], check=True)
    assert audio_measure.levels(silent) == (audio_measure.LEVEL_FLOOR, audio_measure.LEVEL_FLOOR)


def test_a_file_that_is_not_sound_cannot_have_a_level(tmp_path):
    (tmp_path / "x.txt").write_text("not sound")
    with pytest.raises(ffmpeg.FfmpegError):
        audio_measure.levels(tmp_path / "x.txt")


def test_the_runner_in_the_compose_file_offers_every_kind_the_studio_defines():
    """A kind the image has but WORKER_KINDS leaves out is never run: its jobs wait for ever (measure-level did, once)."""
    import re

    from marvin_worker import jobs as worker_jobs
    from storyrender import jobs  # noqa: F401  (importing it registers the kinds)

    compose = (Path(__file__).resolve().parents[2] / "docker" / "compose.yml").read_text(encoding="utf-8")
    offered = {k for line in re.findall(r"WORKER_KINDS:\s*(\S+)", compose) for k in line.split(",")}
    studio = {k for k, handler in worker_jobs.HANDLERS.items() if getattr(handler, "__module__", "").startswith("storyrender.jobs")}
    assert studio and studio <= offered, f"not offered by any container: {sorted(studio - offered)}"
