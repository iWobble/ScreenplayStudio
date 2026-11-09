"""The pure part of the convert-audio job: which format, whether a file already is one, whether it is a sound, what to call the result."""

import pytest

from storyrender import audio_convert as ac


@pytest.mark.parametrize("asked, fmt", [(None, "mp3"), ("", "mp3"), ("MP3", "mp3"), (".m4a", "m4a"), (" M4A ", "m4a")])
def test_format_of(asked, fmt):
    assert ac.format_of(asked) == fmt


def test_a_format_it_cannot_make_is_refused_with_the_choices():
    with pytest.raises(ac.ConvertError, match="mp3 or m4a"):
        ac.format_of("wav")


@pytest.mark.parametrize(
    "mime, name, fmt, already",
    [
        ("audio/mpeg", "x.mp3", "mp3", True),
        ("audio/mp4", "x.m4a", "m4a", True),
        ("audio/x-m4a", "x.m4a", "m4a", True),
        ("audio/webm;codecs=opus", "x.webm", "mp3", False),
        ("video/webm", "recording.webm", "mp3", False),
        (None, "clip.mp3", "mp3", True),
        (None, "clip.webm", "mp3", False),
        ("audio/mpeg", "x.mp3", "m4a", False),
    ],
)
def test_is_already(mime, name, fmt, already):
    assert ac.is_already(mime, name, fmt) is already


@pytest.mark.parametrize(
    "mime, name, audio",
    [
        ("audio/webm", "a.webm", True),
        ("video/webm", "recording.webm", True),  # a browser types an audio-only recording this way
        ("audio/ogg", "a.ogg", True),
        ("image/png", "a.png", False),
        ("application/pdf", "a.pdf", False),
        (None, "a.opus", True),
        (None, "a.png", False),
    ],
)
def test_is_audio(mime, name, audio):
    assert ac.is_audio(mime, name) is audio


def test_the_converted_name_swaps_the_ending():
    assert ac.named("Granny voice.webm", "mp3") == "Granny voice.mp3"
    assert ac.named("no ending", "m4a") == "no ending.m4a"
    assert ac.named(None, "mp3") == "Recording.mp3"
