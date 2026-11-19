"""The transcript's three forms, from the segments the model returns. Since P6 this module IS the Media package's `mediajobs.text` (InnerOpen/marvin-media): the code moved there
unchanged and Studio's image builds FROM marvin-media-worker, which carries it. The name `storytranscribe.text` stays, as the very same module object (not a
copy of its names), so `from . import text`, an `except text.…` and a test's monkeypatch of one of its functions all reach the code that runs."""

import sys

from mediajobs import text as _shared

sys.modules[__name__] = _shared
