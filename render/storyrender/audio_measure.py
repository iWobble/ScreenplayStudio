"""How long a recording really is, how loud, its peak and its silences (measure-audio, describe-audio, measure-level). Since P6 this module IS the Media package's `mediajobs.audio_measure` (InnerOpen/marvin-media): the code moved there
unchanged and Studio's image builds FROM marvin-media-worker, which carries it. The name `storyrender.audio_measure` stays, as the very same module object (not a
copy of its names), so `from . import audio_measure`, an `except audio_measure.…` and a test's monkeypatch of one of its functions all reach the code that runs."""

import sys

from mediajobs import audio_measure as _shared

sys.modules[__name__] = _shared
