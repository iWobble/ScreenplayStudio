"""Is a story ready to have pictures and voices made: read from the records, nothing spent, nothing changed but the story's note."""

import json

from marvin_worker.jobs import Context
from storyrender import jobs, ready

GOOD = dict(
    story={"world": "w", "setting": "A reef at night", "premise": "A wreck"},
    worlds={"w"},
    characters=[
        {"slug": "s-val", "title": "Valerie", "speaker": "valerie", "presence": "on screen", "actor": "sarah", "role": "A captain", "costume": "A tricorn", "master": "m1", "voice": "v1"},
        {"slug": "s-nar", "title": "Narrator", "speaker": "narrator", "presence": "voice only", "voice": "v1"},
    ],
    actors={"sarah": {}},
    voices={"v1": {"elevenlabs_voice_id": "abc"}},
    beats=[{"number": "1001", "cast": "s-val", "expression": "braces", "focus": "chart", "scene": "sc1"}],
    lines=[{"speaker": "valerie", "voice": "v1"}, {"speaker": "narrator", "voice": "v1"}],
    scenes=[{"slug": "sc1", "place": "Cabin", "set_dressing": "lantern"}],
    sounds=[{"slug": "snd", "title": "Crack", "prompt": "a crack", "duration_seconds": 1.5, "source": "generated"}],
)


def run(**changes):
    return ready.check(**{**GOOD, **changes})


def test_a_story_with_everything_has_nothing_to_fix_or_look_at():
    assert run() == []


def test_the_story_needs_a_world_that_exists_a_setting_and_a_premise():
    said = [t for _, _, t in run(story={"world": "", "setting": "", "premise": ""})]
    assert len(said) == 3 and "no World" in said[0] and "no Setting" in said[1] and "no Premise" in said[2]
    assert "not in this workspace" in run(story={**GOOD["story"], "world": "gone"})[0][2]


def test_a_character_on_screen_without_an_actor_blocks_and_without_a_costume_is_worth_a_look():
    bare = [{"slug": "s-val", "title": "Valerie", "speaker": "valerie", "presence": "on screen", "master": "m1", "voice": "v1"}]
    found = run(characters=bare)
    assert ("fix", "Characters", "Valerie has no actor: no master picture can be made") in found
    assert any(f[0] == "look" and "no costume" in f[2] for f in found) and any(f[0] == "look" and "no description" in f[2] for f in found)


def test_a_speaker_with_no_voice_or_a_voice_without_an_elevenlabs_id_blocks():
    narrator = {"slug": "s-nar", "title": "Narrator", "speaker": "narrator", "presence": "voice only"}
    found = run(characters=[GOOD["characters"][0], narrator])
    assert ("fix", "Voices", "Narrator speaks 1 line but has no voice: nothing can be recorded") in found
    found = run(voices={"v1": {"elevenlabs_voice_id": ""}})
    assert any("has no ElevenLabs id" in f[2] for f in found)
    found = run(voices={})
    assert any("is not in this workspace" in f[2] for f in found)


def test_a_speaker_with_no_character_needs_a_voice_on_the_lines():
    found = run(lines=GOOD["lines"] + [{"speaker": "mongrel", "voice": ""}])
    assert ("fix", "Voices", "mongrel speaks 1 line and has no Character and no voice on the lines") in found
    assert not [f for f in run(lines=GOOD["lines"] + [{"speaker": "mongrel", "voice": "v1"}]) if f[1] == "Voices"]


def test_beats_with_nobody_in_them_or_a_cast_that_is_not_a_character():
    found = run(beats=[{"number": "1001", "cast": "", "expression": "x", "focus": "y"}, {"number": "1002", "cast": "s-ghost", "expression": "x", "focus": "y"}])
    assert any(f[0] == "look" and "nobody in the cast" in f[2] and "1001" in f[2] for f in found)
    assert any(f[0] == "fix" and "s-ghost" in f[2] for f in found)


def test_expression_and_focus_are_said_to_be_missing_only_as_a_look():
    found = run(beats=[{"number": "1001", "cast": "s-val"}, {"number": "1002", "cast": "s-val", "expression": "x", "focus": "y"}])
    texts = [t for lvl, _, t in found if lvl == "look"]
    assert "1 of 2 beats do not say what the people are doing (expression)" in texts and not [f for f in found if f[0] == "fix"]


def test_sounds_with_no_prompt_block_no_length_and_repeats_are_worth_a_look():
    sounds = [
        {"slug": "a", "title": "A", "prompt": "", "source": "generated"},
        {"slug": "b", "title": "Hum", "prompt": "low voices", "source": "generated"},
        {"slug": "c", "title": "Hum again", "prompt": "Low  voices", "source": "generated", "duration_seconds": 3},
        {"slug": "d", "title": "Mine", "prompt": "", "source": "uploaded"},
    ]
    found = run(sounds=sounds)
    assert ("fix", "Sounds", "1 sound to generate with no prompt: A") in found  # an uploaded sound needs no prompt
    assert any("no length" in f[2] for f in found) and any("described more than once" in f[2] for f in found)


def test_scenes_without_set_dressing_are_listed():
    found = run(scenes=[{"slug": "sc1", "place": "Cabin"}, {"slug": "sc2", "place": "Deck", "set_dressing": "ropes"}])
    assert any("1 of 2 scenes have no set dressing" in f[2] and "Cabin" in f[2] for f in found)


def test_the_report_says_what_to_fix_first_and_how_many():
    found = run(story={"world": "", "setting": "x", "premise": "y"}, scenes=[{"slug": "sc1", "place": "Cabin"}])
    text, fixes, looks = ready.report(found, {"beats": 1}, "now")
    assert (fixes, looks) == (1, 1)
    assert text.index("Fix before making anything (1)") < text.index("Worth a look (1)") and "Story: no World" in text
    assert "Nothing stops" in ready.report([], {"beats": 1}, "now")[0]


class Marvin:
    def __init__(self):
        self.patched = []
        self.records = {
            "story": [{"id": "e0", "slug": "s", "title": "S", "dataJson": {"world": "w"}}],
            "world": [{"id": "w1", "slug": "w", "title": "W", "dataJson": {}}],
            "cast-member": [{"id": "c1", "slug": "s-val", "title": "Valerie", "dataJson": {"story": "s", "speaker": "valerie", "presence": "on screen"}}],
            "speech-line": [{"id": "l1", "slug": "l1", "title": "L", "dataJson": {"story": "s", "speaker": "valerie"}}],
        }

    def query(self, creds, spec, limit=100):
        return self.records["story"] if "entries" in spec else []

    def request(self, creds, path, **kw):
        if path.endswith("/api/platform/entries/query"):
            spec = json.loads(kw["data"])["spec"]
            rows = self.records.get(spec["entry_type"], [])
            want = spec.get("data") or {}
            rows = [r for r in rows if all(r["dataJson"].get(k) == v for k, v in want.items())]
            return json.dumps({"entries": rows if json.loads(kw["data"]).get("offset", 0) == 0 else []}).encode()
        self.patched.append((path, json.loads(kw["data"])))
        return b"{}"


def test_the_job_writes_the_note_on_the_story_and_changes_nothing_else(monkeypatch, tmp_path):
    fake = Marvin()
    monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
    monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
    done = jobs.check_ready({"job": "j", "args": {"story": "s"}}, Context(creds=("http://m", "tok"), work=tmp_path, name="check-ready-1"))
    assert [p[0] for p in fake.patched] == ["/api/platform/entries/e0"]  # only the story
    note = fake.patched[0][1]["dataJson"]["readiness"]
    assert fake.patched[0][1]["dataJson"]["world"] == "w" and note == done["log"]
    assert done["result"]["fix"] >= 3 and "Valerie has no actor" in note and "Valerie speaks 1 line but has no voice" in note


def test_beats_are_named_in_the_order_they_play():
    beats = [{"number": n, "cast": "", "expression": "x", "focus": "y"} for n in ("3002", "1001a", "1001", "1001aa", "1001b")]
    said = [t for _, _, t in run(beats=beats) if "nobody" in t][0]
    assert said.endswith("1001, 1001a, 1001b, 1001aa, 3002")


def _plan_story(**more):
    lines = [{"speaker": "valerie", "voice": "v1", "text": "x" * 600, "source": "generated"}, {"speaker": "valerie", "voice": "v1", "text": "y" * 400, "source": "generated", "audio": "a1"}]
    return run(lines=lines, **more)


def test_without_a_plan_the_check_says_nothing_about_it():
    assert not [f for f in _plan_story() if "plan" in f[2]]


def test_the_lines_still_to_record_are_counted_against_the_characters_left_and_a_recorded_line_is_not():
    found = _plan_story(plan={"tier": "starter", "characters_left": "5000", "resets_at": "2026-12-01T00:00:00+00:00"})
    assert ("look", "Voices", "the 1 lines still to record need about 600 of the 5,000 characters the starter plan has left, until it resets on 2026-12-01") in found
    short = _plan_story(plan={"tier": "free", "characters_left": "300"})
    assert any(f[0] == "fix" and "need about 600 characters and the free plan has 300 left" in f[2] and "stop partway" in f[2] for f in short)


def test_a_library_voice_is_refused_on_a_free_plan_only():
    voices = {"v1": {"elevenlabs_voice_id": "abc", "category": "professional"}}
    free = run(voices=voices, plan={"tier": "free", "characters_left": "10000"})
    assert ("fix", "Voices", "the free ElevenLabs plan refuses library voices when a recording is asked for: v1") in free
    assert not [f for f in run(voices=voices, plan={"tier": "creator", "characters_left": "10000"}) if "library voices" in f[2]]


def test_a_plan_that_could_not_be_read_adds_nothing_and_the_job_passes_the_plan_it_was_given(monkeypatch, tmp_path):
    assert not [f for f in run(plan={"tier": "", "characters_left": "n/a"}) if "plan" in f[2]]
    assert jobs._plan_of({}) is None and jobs._plan_of({"plan_tier": "free", "plan_characters_left": "12"}) == {"tier": "free", "characters_left": "12", "resets_at": ""}
