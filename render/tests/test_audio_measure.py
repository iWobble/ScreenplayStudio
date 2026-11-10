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
