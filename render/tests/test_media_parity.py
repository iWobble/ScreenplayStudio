"""Since P6 the render's media helpers are the Media package's (InnerOpen/marvin-media `mediajobs`), not copies: `storyrender.ffmpeg`,
`audio_measure` and `waveform` ARE mediajobs' modules, and `clip`'s describe half is `mediajobs.video`'s. These tests pin that, and check that
Studio's describe jobs still give exactly what Media's media-describe gives on the parity files (design §8.3): Media's own parity test, run in
its exact mode against this checkout (STUDIO_RENDER), on the recordings it generates (a phone's portrait webm with no length in its header, a
stereo wav, a silent mp4, a portrait take with a turn, a camera-off webm).

The parity run needs Media's tests, so a checkout of InnerOpen/marvin-media (as CI and `--with-editable ../MarvinMedia` give), not only the
`mediajobs` an image carries: without one it is skipped, unless STUDIO_REQUIRE_MEDIA_PARITY=1 (CI), where it fails instead."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import mediajobs
import pytest
from mediajobs import audio_measure as m_audio_measure
from mediajobs import ffmpeg as m_ffmpeg
from mediajobs import video as m_video
from mediajobs import waveform as m_waveform

from storyrender import audio_measure, clip, ffmpeg, jobs, waveform

MEDIA = Path(mediajobs.__file__).resolve().parents[1]
RENDER = Path(__file__).resolve().parents[1]


def test_the_render_helpers_are_medias_modules_not_copies():
    assert ffmpeg is m_ffmpeg and audio_measure is m_audio_measure and waveform is m_waveform
    assert jobs.ffmpeg is m_ffmpeg and jobs.audio_measure is m_audio_measure and jobs.waveform is m_waveform  # what the jobs call
    assert clip.describe is m_video.describe and clip.poster is m_video.poster and clip.seconds is m_video.seconds
    assert (clip.POSTER_AT, clip.POSTER_LONG_SIDE, clip.MAX_FPS) == (m_video.POSTER_AT, m_video.POSTER_LONG_SIDE, m_video.MAX_FPS)


def test_a_patch_on_the_old_name_reaches_the_code_that_runs(monkeypatch):
    """A test (or a fix) that replaces storyrender.ffmpeg.probe replaces what mediajobs' own describe calls: one module, not two."""
    monkeypatch.setattr(ffmpeg, "probe", lambda _p: {"format": {"duration": "7.25"}})
    assert m_ffmpeg.probe(Path("x.wav")) == {"format": {"duration": "7.25"}}


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
def test_studios_describe_jobs_give_what_media_describe_gives(tmp_path):
    parity = MEDIA / "tests" / "test_parity.py"
    if not parity.is_file():
        if os.environ.get("STUDIO_REQUIRE_MEDIA_PARITY") == "1":
            pytest.fail(f"no Media checkout with its tests at {MEDIA} (mediajobs is imported from there)")
        pytest.skip(f"mediajobs at {MEDIA} has no tests/test_parity.py (not a checkout of InnerOpen/marvin-media)")
    env = {**os.environ, "STUDIO_RENDER": str(RENDER)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "media"), str(parity)],
        cwd=MEDIA, env=env, capture_output=True, text=True, timeout=280,
    )  # fmt: skip
    said = (done.stdout + done.stderr)[-3000:]
    assert done.returncode == 0, said
    assert " passed" in said and " skipped" not in said and " failed" not in said, said  # every file compared, none passed over
