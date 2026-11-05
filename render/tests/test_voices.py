"""ElevenLabs voices → Marvin records (storyrender.voices): the pure parts."""

from storyrender import voices

ROGER = {"gender": "male", "age": "middle_aged", "accent": "american", "descriptive": "classy", "use_case": "conversational", "language": "en"}


def test_a_voices_short_name_is_what_comes_before_the_description():
    assert voices.short_name("Roger - Laid-Back, Casual, Resonant") == "Roger"
    assert voices.short_name("Connery – Deep & Immersive Documentary") == "Connery"
    assert voices.short_name("Brandon") == "Brandon" and voices.short_name("") == "voice"


def test_the_slug_is_voice_and_the_name_and_a_second_of_the_same_name_gets_a_number():
    taken = {"voice-roger"}
    assert voices.slug_for("Roger - x", taken) == "voice-roger-2"
    assert voices.slug_for("Talia - Chill", taken) == "voice-talia"
    assert voices.slug_for("William Gomes Pro ElevenLabs voice", set()) == "voice-william-gomes-pro-elevenlabs-voice"


def test_the_labels_become_tags_in_a_stable_order_without_repeats():
    assert voices.tags_for(ROGER) == ["male", "middle-aged", "american", "classy", "conversational"]
    assert voices.tags_for({"gender": "male", "age": "male"}) == ["male"]
    assert voices.tags_for(None) == []


def test_the_summary_says_who_it_sounds_like_then_what_it_suits():
    assert voices.summary_for(ROGER) == "Male, middle-aged, american; conversational, classy"
    assert voices.summary_for({"use_case": "social_media"}) == "Social media"
    assert voices.summary_for({}) == ""


def test_only_voices_marvin_has_no_record_of_are_new():
    listed = [{"voice_id": "a", "name": "A"}, {"voice_id": "b", "name": "B"}, {"name": "no id"}]
    assert [v["voice_id"] for v in voices.new_voices(listed, {"a"})] == ["b"]


def test_a_blank_or_unfilled_search_is_no_search():
    assert voices.search_term("  chill ") == "chill"
    assert voices.search_term("") == "" and voices.search_term(None) == "" and voices.search_term("${inputs.search}") == ""
