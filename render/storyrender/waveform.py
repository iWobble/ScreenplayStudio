"""A recording's waveform, as the peaks the Timeline draws in its block (make-waveform). Since P6 this module IS the Media package's `mediajobs.waveform` (InnerOpen/marvin-media): the code moved there
unchanged and Studio's image builds FROM marvin-media-worker, which carries it. The name `storyrender.waveform` stays, as the very same module object (not a
copy of its names), so `from . import waveform`, an `except waveform.…` and a test's monkeypatch of one of its functions all reach the code that runs."""

import sys

from mediajobs import waveform as _shared

sys.modules[__name__] = _shared
