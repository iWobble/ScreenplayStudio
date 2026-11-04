"""Word timings a take carries, for captions (marvin_pull.spoken_words)."""

from storyrender import marvin_pull

WORDS = [{"text": "Make", "start": 0.0, "end": 0.3}, {"text": "do.", "start": 0.35, "end": 0.7}]


def test_the_voice_services_word_timings_are_passed_on():
    assert marvin_pull.spoken_words({"text": "Make do.", "words": WORDS}) == WORDS


def test_a_delivery_tag_is_not_a_caption_word():
    tagged = [{"text": "[sighs]", "start": 0.0, "end": 0.4}, *WORDS]
    assert marvin_pull.spoken_words({"text": "Make do.", "words": tagged}) == WORDS


def test_a_caption_that_differs_from_the_spoken_text_gets_no_timings():
    assert marvin_pull.spoken_words({"text": "Make do.", "caption": "Make it work.", "words": WORDS}) == []


def test_a_caption_equal_to_the_text_keeps_them():
    assert marvin_pull.spoken_words({"text": "Make do.", "caption": "Make do.", "words": WORDS}) == WORDS


def test_no_words_or_odd_words_is_an_empty_list():
    assert marvin_pull.spoken_words({"text": "x"}) == []
    assert marvin_pull.spoken_words({"text": "x", "words": "nope"}) == []
    assert marvin_pull.spoken_words({"text": "x", "words": [{"start": 1}, "a"]}) == []
