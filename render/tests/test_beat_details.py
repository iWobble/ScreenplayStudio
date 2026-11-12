"""The AI proposes each beat's expression and focus from its words: only an empty field is filled, a bad answer writes nothing, a preview writes nothing."""

import json

from marvin_worker.jobs import Context
from storyrender import jobs


def beat(n, picture="Chet clutches the logbook.", **more):
    return {"id": f"id-{n}", "slug": f"s-beat-{n}", "title": f"Beat {n}", "dataJson": {"story": "s", "number": str(n), "picture": picture, "cast": "s-chet", "scene": "s-cabin", **more}}


class Marvin:
    def __init__(self, beats, answer):
        self.records = {
            "story": [{"id": "e0", "slug": "s", "title": "The Reef", "dataJson": {"setting": "A wreck at night", "premise": "A wreck"}}],
            "beat": beats,
            "cast-member": [
                {"id": "c1", "slug": "s-chet", "title": "Chet", "dataJson": {"story": "s", "role": "Man, 20s", "costume": "patched shirt", "props": "a logbook"}},
                {"id": "c2", "slug": "s-narrator", "title": "Narrator", "dataJson": {"story": "s", "presence": "voice only", "role": "NARRATOR secret"}},
            ],
            "scene": [{"id": "sc1", "slug": "s-cabin", "title": "Cabin", "dataJson": {"story": "s", "place": "Captain's cabin"}}],
            "speech-line": [{"id": "l1", "slug": "l1", "title": "L", "dataJson": {"story": "s", "beat": "s-beat-1", "speaker": "chet", "text": "The hull is groaning!"}}],
        }
        self.answer, self.asked, self.patched = answer, [], []

    def query(self, creds, spec, limit=100):
        return self.records["story"] if "entries" in spec else []

    def request(self, creds, path, **kw):
        if path == "/api/platform/entries/query":
            body = json.loads(kw["data"])
            rows = self.records.get(body["spec"]["entry_type"], [])
            want = body["spec"].get("data") or {}
            rows = [r for r in rows if all(r["dataJson"].get(k) == v for k, v in want.items())]
            return json.dumps({"entries": rows if body.get("offset", 0) == 0 else []}).encode()
        if path.startswith("/api/ai/agents/"):
            self.asked.append((path, json.loads(kw["data"])["message"]))
            return json.dumps({"answer": self.answer(len(self.asked)) if callable(self.answer) else self.answer}).encode()
        self.patched.append((path, json.loads(kw["data"])))
        return b"{}"


def go(monkeypatch, tmp_path, beats, answer, **args):
    fake = Marvin(beats, answer)
    monkeypatch.setattr(jobs.marvin_api, "query", fake.query)
    monkeypatch.setattr(jobs.marvin_api, "request", fake.request)
    done = jobs.write_beat_details({"job": "j", "args": {"story": "s", **args}}, Context(creds=("http://m", "tok"), work=tmp_path, name="write-beat-details-1"))
    return fake, done


def test_it_fills_only_the_empty_fields_and_never_what_a_person_wrote(monkeypatch, tmp_path):
    beats = [beat(1), beat(2, expression="Her own words.", focus="")]
    answer = json.dumps([{"number": "1", "expression": "Chet grips the logbook and stares at the door.", "focus": "the logbook"}, {"number": "2", "expression": "OVERWRITES", "focus": "a compass"}])
    fake, done = go(monkeypatch, tmp_path, beats, "```json\n" + answer + "\n```")  # a fenced answer is still read
    patched = {p[0].rsplit("/", 1)[-1]: p[1]["dataJson"] for p in fake.patched}
    assert patched["id-1"]["expression"].startswith("Chet grips") and patched["id-1"]["focus"] == "the logbook"
    assert patched["id-2"]["expression"] == "Her own words." and patched["id-2"]["focus"] == "a compass"  # the person's text stays; the empty focus is filled
    assert patched["id-1"]["story"] == "s" and patched["id-1"]["picture"]  # nothing else changed
    assert done["result"]["written"] == 2 and "proposals" in done["log"]


def test_a_question_holds_ten_beats_and_the_cast_lines_and_place_go_with_them_but_a_narrator_does_not(monkeypatch, tmp_path):
    beats = [beat(n) for n in range(1, 26)]
    fake, done = go(monkeypatch, tmp_path, beats, lambda n: "[]")
    assert len(fake.asked) == 3 and done["result"]["written"] == 0 and len(done["result"]["skipped"]) == 25  # nothing usable: nothing written, and it says so
    first = fake.asked[0][1]
    assert fake.asked[0][0] == "/api/ai/agents/chat/run" and "BEAT 1\n" in first and "BEAT 10\n" in first and "BEAT 11\n" not in first
    assert "Captain's cabin" in first and "Chet: Man, 20s, wears patched shirt, carries a logbook" in first and "CHET: The hull is groaning!" in first
    assert "NARRATOR secret" not in first and "run it again" in done["log"]
    assert fake.patched == []


def test_a_preview_writes_nothing_but_shows_what_it_would(monkeypatch, tmp_path):
    fake, done = go(monkeypatch, tmp_path, [beat(1)], json.dumps([{"number": "1", "expression": "Chet looks up.", "focus": ""}]), dry_run="yes")
    assert fake.patched == [] and done["result"]["written"] == 1 and "Would write" in done["log"] and "1: Chet looks up." in done["log"]


def test_nothing_waiting_asks_nothing(monkeypatch, tmp_path):
    fake, done = go(monkeypatch, tmp_path, [beat(1, expression="x", focus="y"), beat(2, picture="")], "[]")
    assert fake.asked == [] and done["result"]["written"] == 0 and "Nothing to write" in done["log"]


def test_the_limit_leaves_the_rest_for_another_run_and_beats_go_in_the_order_they_play(monkeypatch, tmp_path):
    beats = [beat(3), beat(1), beat(2)]
    fake, done = go(monkeypatch, tmp_path, beats, json.dumps([{"number": "1", "expression": "a", "focus": ""}, {"number": "2", "expression": "b", "focus": ""}]), limit="2")
    assert done["result"]["left"] == 1 and "1 more beat wait" in done["log"] and "BEAT 3" not in fake.asked[0][1]
    assert {p[0].rsplit("/", 1)[-1] for p in fake.patched} == {"id-1", "id-2"}


def test_a_replies_with_text_around_the_list_or_broken_json_is_handled():
    assert jobs._parse_beat_details('Here you go: [{"number": "1", "expression": "x", "focus": "y"}] Done.') == {"1": {"expression": "x", "focus": "y"}}
    assert jobs._parse_beat_details("no list here") == {} and jobs._parse_beat_details("[{broken") == {} and jobs._parse_beat_details('{"number": "1"}') == {}


def test_only_the_story_is_needed_to_run_it_the_rest_is_optional():
    from marvin_worker.jobs import check_args, describe_kinds

    inputs = describe_kinds(["write-beat-details"])[0]["inputs"]
    assert {k: v["required"] for k, v in inputs.items()} == {"story": True, "limit": False, "dry_run": False, "agent": False}
    check_args("write-beat-details", {"story": "s"})  # nothing else asked for: no complaint
