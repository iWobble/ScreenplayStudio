"""Running ffmpeg and ffprobe: probing durations and running a command with its stderr on failure. Since P6 this module IS the Media package's `mediajobs.ffmpeg` (InnerOpen/marvin-media): the code moved there
unchanged and Studio's image builds FROM marvin-media-worker, which carries it. The name `storyrender.ffmpeg` stays, as the very same module object (not a
copy of its names), so `from . import ffmpeg`, an `except ffmpeg.…` and a test's monkeypatch of one of its functions all reach the code that runs."""

import sys

from mediajobs import ffmpeg as _shared

sys.modules[__name__] = _shared
