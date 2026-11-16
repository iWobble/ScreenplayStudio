"""The prompts the package sends to the image model keep their guardrails (a master is a portrait, not a scene; sides are anatomical; a style
reference never brings its people), so an edit to a workflow cannot quietly drop them."""

import json
from pathlib import Path
from storyrender import camera

PACKAGE = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"


def workflow(slug: str) -> str:
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == slug:
            return json.dumps(b["payload"]["definition"])
    raise AssertionError(slug)


def test_a_master_is_sent_with_the_portrait_guard_and_the_approval_shows_the_same_words():
    made = json.loads(PACKAGE.read_text(encoding="utf-8"))
    flow = next(b for b in made["blueprints"] if b.get("slug") == "screenplay-make-master")["payload"]["definition"]["actions"]
    spend = next(a for a in flow if a.get("id") == "spend")["message"]
    sent = next(a for a in flow if a.get("id") == "master")["args"]["prompt"]
    guard = sent.split("${entry.data.master_prompt}", 1)[1].strip()
    assert "MASTER, NOT A SCENE" in guard and "anatomical left and right" in guard and "never mirror" in guard
    assert guard in spend  # what is approved is what is sent


def test_the_master_prompt_writer_ignores_scene_words_in_the_notes_and_writes_anatomical_sides():
    text = workflow("screenplay-write-master-prompt")
    assert "never a scene" in text and "names a place, weather, scene, other people or an action" in text and "anatomical left or right" in text


def test_a_still_never_draws_people_who_are_only_in_a_reference_picture():
    text = workflow("screenplay-take-still")
    assert "nobody who appears only in a reference picture" in text


def test_a_cover_and_an_actor_sheet_copy_the_style_only():
    assert "do NOT copy its characters, objects or setting" in workflow("screenplay-make-cover")
    assert "Never realistic" in workflow("screenplay-make-actor-sheet")


def test_an_actors_new_voice_reaches_the_characters_who_play_them_unless_given_another_on_purpose():
    flow = json.loads(workflow("screenplay-actor-voice-reaches-characters"))
    assert flow["trigger"]["event"] == "entry_updated"
    assert {"field": "entry.data.voice", "op": "changed"} in flow["conditions"]
    people = next(a for a in flow["actions"] if a.get("id") == "people")
    assert people["query"] == {"entry_type": "cast-member", "data": {"actor": "${entry.slug}"}}
    give = json.dumps(next(a for a in flow["actions"] if a.get("id") == "follow")["steps"])
    assert "${event.before.data.voice}" in give and "shorter_than" in give  # only a voice that was empty or the actor's old one is replaced


def _flow(slug: str) -> dict:
    return json.loads(workflow(slug))


def test_a_batch_approval_covers_every_still_and_sound_so_the_single_workflow_asks_nothing_more_and_uses_the_flag_up():
    for single in ("screenplay-take-still", "screenplay-take-sound"):
        acts = _flow(single)["actions"]
        assert acts[0]["data"] == {"spend_approved": "used"} and acts[0]["when"]["value"] == "yes"  # used up first: a later redo asks again
        asked = [a for a in acts if a.get("kind") == "approval"]
        assert {a["id"] for a in asked} == {"spend", "keep"}
        assert all(a["when"] == {"field": "entry.data.spend_approved", "op": "neq", "value": "yes"} for a in asked)
    for batch, noun in (("screenplay-make-stills", "beat"), ("screenplay-make-sounds", "sound")):
        acts = _flow(batch)["actions"]
        assert len([a for a in acts if a.get("kind") == "approval" and a["id"] == "spend"]) == 1
        queue = next(a for a in acts if a.get("kind") == "repeat")
        assert queue["steps"][0]["data"] == {"status": "queued", "spend_approved": "yes"}
        assert next(a for a in acts if a.get("kind") == "collect")["query"]["entry_type"] == noun


def test_keeping_what_was_made_is_one_approval_that_only_touches_the_made_ones():
    for keep, status in (("screenplay-keep-stills", "made"), ("screenplay-keep-sounds", "recorded")):
        acts = _flow(keep)["actions"]
        assert {"field": "status", "op": "eq", "value": status} in next(a for a in acts if a.get("kind") == "collect")["query"]["where"]
        assert next(a for a in acts if a.get("id") == "keep")["choices"] == ["Keep all", "Leave them"]
        assert next(a for a in acts if a.get("kind") == "repeat")["when"]["value"] == "Keep all"


def test_the_story_timeline_lets_a_made_still_be_kept_or_redone_in_place():
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "story-timeline":
            assert b["payload"]["spine"]["review"] == {"ready": ["made"], "keep": "approved", "redo": "redo"}
            break
    else:
        raise AssertionError("story-timeline")
    requeue = json.dumps(_flow("screenplay-requeue-redo"))
    assert '"redo"' in requeue  # the status the Redo button writes is the one the requeue workflow acts on


def test_writing_the_beat_details_asks_once_then_queues_the_job_and_the_cast_has_age_and_sex_fields():
    flow = _flow("screenplay-write-beat-details")["actions"]
    assert [a.get("id") for a in flow if a.get("kind") == "approval"] == ["none", "spend"]
    job = next(a for a in flow if a.get("kind") == "entry")
    assert job["data"]["kind"] == "write-beat-details" and job["when"]["op"] == "gte"
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "cast-member":
            keys = [f["key"] for f in b["payload"]["schema_json"]["fields"]]
            assert {"age", "sex", "age_state"} <= set(keys) and keys.index("age") < keys.index("speaker")


def test_a_still_is_told_the_changes_from_earlier_beats_and_the_beat_has_the_field_for_them():
    acts = _flow("screenplay-take-still")["actions"]
    changes = next(a for a in acts if a.get("id") == "changes")
    assert {"field": "number", "op": "lte", "value": "${entry.data.number}"} in changes["query"]["where"]  # this beat's own note counts too
    prompt = next(a for a in acts if a.get("kind") == "integration")["args"]["prompt"]
    assert prompt.index("CHANGES THAT HOLD") < prompt.index("THIS MOMENT: ") and "steps.changes.output.text" in prompt
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "beat":
            assert "changes" in [f["key"] for f in b["payload"]["schema_json"]["fields"]]


def test_the_plan_check_looks_at_elevenlabs_for_free_then_queues_the_readiness_job_with_what_it_found():
    flow = _flow("screenplay-check-ready-plan")["actions"]
    look = flow[0]
    assert (look["kind"], look["integration"], look["action"]) == ("integration", "elevenlabs", "get_usage")  # the free usage lookup, nothing that records
    args = next(a for a in flow if a.get("kind") == "entry")["data"]["args"]
    assert args["plan_tier"] == "${steps.plan.output.tier}" and args["plan_characters_left"] == "${steps.plan.output.characters_left}"
    assert not [a for a in flow if a.get("kind") == "approval"]  # free: nothing to approve


def test_an_actor_sheet_may_ask_for_its_own_picture_size_and_says_so_in_the_approval():
    flow = _flow("screenplay-make-actor-sheet")
    assert any(i["name"] == "size" and i["required"] is False for i in flow["trigger"]["inputs"])
    assert next(a for a in flow["actions"] if a.get("kind") == "integration")["args"]["size"] == '${input.size|default:""}'  # empty: the connection's, as before
    assert "Picture size:" in next(a for a in flow["actions"] if a.get("id") == "spend")["message"]


def test_recording_a_take_shows_its_words_and_direction_large_to_read_from():
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b.get("slug") == "takes-of-a-line":
            takes = next(s for s in b["payload"]["steps"] if s["id"] == "takes")
            assert takes["add"]["file"]["script"] == ["spoken", "direction"]
            assert set(takes["add"]["file"]["script"]) <= set(takes["add"]["fields"])  # both are fields of the form the take is made in
            break
    else:
        raise AssertionError("takes-of-a-line")


def test_a_scene_and_a_beat_can_set_the_story_bed_and_the_story_can_duck_its_ambience():
    fields = {}
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b["kind"] == "entry_type" and b["slug"] in ("scene", "beat", "story"):
            fields[b["slug"]] = {f["key"]: f for f in b["payload"]["schema_json"]["fields"]}
    for owner in ("scene", "beat"):
        level = fields[owner]["story_ambience_volume"]
        assert (level["type"], level["min"], level["max"]) == ("number", 0, 1)
    assert fields["scene"]["story_ambience_muffled"]["type"] == "boolean"
    assert fields["story"]["ambience_ducking"]["options"] == ["none", "light", "strong"]
    assert "story_ambience_muffled" not in fields["beat"]  # indoors is the scene's to say, not a beat's


def test_the_story_timeline_names_where_the_story_bed_is_adjusted_and_the_new_level_fields_have_a_slider():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    bed = next(lane for lane in blueprints["story-timeline"]["payload"]["lanes"] if lane["id"] == "ambience")["bed"]
    assert (bed["entry_item_volume"], bed["entry_via_volume"], bed["entry_via_muffled"]) == ("story_ambience_volume", "story_ambience_volume", "story_ambience_muffled")
    for owner in ("scene", "beat"):
        level = next(f for f in blueprints[owner]["payload"]["schema_json"]["fields"] if f["key"] == "story_ambience_volume")
        assert level["slider"] is True and (level["min"], level["max"]) == (0, 1)  # a slider needs both ends


def test_the_takes_setup_can_choose_one_character_and_then_lists_just_their_lines():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    steps = {s["id"]: s for s in blueprints["takes-of-a-line"]["payload"]["steps"]}
    order = [s["id"] for s in blueprints["takes-of-a-line"]["payload"]["steps"]]
    assert order.index("story") < order.index("character") < order.index("line")  # chosen before the lines are listed
    assert steps["character"]["optional"] is True and steps["character"]["entry_type"] == "cast-member" and steps["character"]["as"] == "character"
    assert steps["line"]["scope"] == {"story": "${story}", "beat": "${beat}", "character": "${character}"}  # a skipped step narrows nothing
    for key in ("chapter", "beat"):  # a chosen character lists their lines together: the narrowing steps would only offer chapters and beats they may not speak in
        assert steps[key]["when"] == {"ctx": "character", "op": "unset"}, key
    assert steps["line"]["subtitle"] == ["text", "status"]  # the whole line under its title, then what is left to record, in the list
    assert "character" in [f["key"] for f in blueprints["speech-line"]["payload"]["schema_json"]["fields"]]


def test_the_unused_screenplay_and_beat_sheet_blueprint_is_gone_and_the_story_type_still_has_what_it_added():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    assert "story-narration-fields" not in blueprints
    keys = {f["key"] for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert {"language", "scene_break_seconds"} <= keys and not {"screenplay", "beat_sheet"} & keys  # nothing reads those two


def test_the_types_that_carry_sound_group_it_the_same_way_so_each_has_one_folded_section():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    group = lambda slug, key: next(f for f in blueprints[slug]["payload"]["schema_json"]["fields"] if f["key"] == key).get("group")  # noqa: E731
    assert group("story", "ambience") == "Ambience" and group("story", "music") == "Music" and group("story", "loudness") == "Where it is going"
    for owner in ("scene", "beat"):
        assert group(owner, "ambience") == group(owner, "ambience_volume") == group(owner, "story_ambience_volume") == "Ambience"  # the same names the story uses
        assert group(owner, "overlay") == group(owner, "overlay_delay") == "Overlay"
    assert group("beat", "music_volume") == "Music" and group("beat", "sounds") == "Sound effects"
    assert group("scene", "story_ambience_muffled") == "Ambience" and group("scene", "music_volume") == "Music"
    assert group("sound", "loop") == group("sound", "fade_out") == "Playback" and group("sound", "model") == "Making it"  # its volume is out in the open, beside the take's meters
    for owner in ("speech-line", "take", "cast-member", "actor"):
        assert group(owner, "voice") == "Voice"
    assert group("speech-line", "speed") == group("take", "stability") == "Voice"
    assert group("speech-line", "text") is None and group("take", "spoken") is None  # what is said and how, stay in the open


def test_every_bounded_level_field_has_a_drag_slider_beside_its_box():
    for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]:
        if b["kind"] != "entry_type":
            continue
        for f in b["payload"]["schema_json"]["fields"]:
            if f.get("type") == "number" and f.get("min") is not None and f.get("max") is not None and 0 < f["max"] - f["min"] <= 2:
                assert f.get("slider") is True, (b["slug"], f["key"])  # a level from 0 to 1, or a speed from 0.7 to 1.2
            if f.get("slider"):
                assert f.get("min") is not None and f.get("max") is not None, (b["slug"], f["key"])  # Marvin refuses a slider without both ends


def test_the_sounds_setup_starts_from_what_the_story_has_and_every_field_workflow_and_status_it_names_exists():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    wizard = blueprints["sounds-for-a-story"]["payload"]
    steps = {s["id"]: s for s in wizard["steps"]}
    order = [s["id"] for s in wizard["steps"]]
    assert order.index("story") < order.index("found") < order.index("beds") < order.index("check")
    sound = {f["key"]: f for f in blueprints["sound"]["payload"]["schema_json"]["fields"]}
    scene = {f["key"] for f in blueprints["scene"]["payload"]["schema_json"]["fields"]}
    story = {f["key"] for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert set(steps["found"]["add"]["fields"]) <= set(sound) and set(steps["beds"]["columns"]) <= scene and set(steps["bed"]["fields"]) <= story
    statuses = set(sound["status"]["options"])
    wanted = {b["data"]["status"] for b in steps["found"]["add"]["buttons"]} | {a["set"]["status"] for a in steps["found"]["card_actions"]}
    wanted |= {c["query"]["fields"]["status"] for c in steps["check"]["checks"] if "status" in c["query"]["fields"]}
    assert wanted <= statuses  # a button or a check can only name a status the Sound type has
    assert "make" not in steps and "keep" not in steps  # a batch is a workflow, not a step
    for slug in [*steps["found"]["approve"], "screenplay-make-sounds", "screenplay-keep-sounds"]:
        assert blueprints[slug]["kind"] == "workflow", slug
    assert [b["data"]["source"] for b in steps["found"]["add"]["buttons"]] == ["uploaded", "generated", "generated"]  # an own file is never sent to ElevenLabs
    assert wizard["button"]["step"] in steps and wizard["open"]["view"] in blueprints


def test_a_sound_shows_its_takes_loudness_as_meters_beside_its_volume_slider_and_a_new_take_is_measured():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    fields = blueprints["sound"]["payload"]["schema_json"]["fields"]
    keys = [f["key"] for f in fields]
    assert keys[keys.index("audio") + 1 : keys.index("audio") + 4] == ["level_db", "peak_db", "volume"]  # the take, its meters, then the slider
    by_key = {f["key"]: f for f in fields}
    for key in ("level_db", "peak_db"):
        assert by_key[key]["meter"] is True and by_key[key]["readOnly"] is True and (by_key[key]["min"], by_key[key]["max"]) == (-60, 0)
    assert by_key["volume"]["slider"] is True and not by_key["volume"].get("group")  # out in the open, not folded under Playback
    flow = blueprints["screenplay-measure-sound-level"]["payload"]["definition"]
    assert {"field": "entry.data.audio", "op": "changed"} in flow["conditions"]  # a new or replaced take, and not the job writing its own result back
    args = flow["actions"][0]["data"]["args"]
    assert flow["actions"][0]["data"]["kind"] == "measure-level" and args["level_field"] in by_key and args["peak_field"] in by_key


def test_the_ambience_and_sound_fades_have_a_slider_from_nothing_to_ten_seconds_in_tenths():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    for slug, keys in (("story", ("ambience_fade_in", "ambience_fade_out")), ("beat", ("ambience_fade_in", "ambience_fade_out")), ("sound", ("fade_in", "fade_out"))):
        fields = {f["key"]: f for f in blueprints[slug]["payload"]["schema_json"]["fields"]}
        for key in keys:
            f = fields[key]
            assert f["slider"] is True and (f["min"], f["max"], f["step"]) == (0, 10, 0.1), (slug, key)  # thirty seconds would make a drag too coarse


def test_a_new_line_is_linked_to_its_character_by_speaker_so_the_takes_setup_finds_it():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    flow = blueprints["screenplay-line-character"]["payload"]["definition"]
    assert flow["trigger"]["event"] == "entry_created"
    assert {"field": "entry.data.character", "op": "exists", "value": False} in flow["conditions"]  # one the line already has is kept
    who, setter = flow["actions"]
    assert who["query"]["entry_type"] == "cast-member" and who["query"]["data"] == {"story": "${entry.data.story}", "speaker": "${entry.data.speaker}"}
    assert setter["data"] == {"character": "${steps.who.output.rows.0.slug}"}
    assert "character" in [f["key"] for f in blueprints["speech-line"]["payload"]["schema_json"]["fields"]]


def test_a_scene_has_an_inside_or_outside_field_with_the_three_values_the_headings_make():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    fields = {f["key"]: f for f in blueprints["scene"]["payload"]["schema_json"]["fields"]}
    assert fields["inside_outside"]["type"] == "select" and fields["inside_outside"]["options"] == ["interior", "exterior", "both"]
    keys = list(fields)
    assert keys.index("inside_outside") == keys.index("place") + 1  # right under the place it says something about


def test_a_beat_has_a_time_of_day_field_next_to_its_scene():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    keys = [f["key"] for f in blueprints["beat"]["payload"]["schema_json"]["fields"]]
    assert keys[keys.index("scene") + 1] == "time_of_day"


def test_the_fountain_check_is_a_workflow_a_story_field_and_a_step_before_the_split():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    steps = [s["id"] for s in blueprints["narrate-a-story"]["payload"]["steps"]]
    assert "fountain_report" not in steps and "fountain_upload" not in steps and steps.index("details") < steps.index("fountain_check") < steps.index("split")
    step = next(s for s in blueprints["narrate-a-story"]["payload"]["steps"] if s["id"] == "fountain_check")
    assert blueprints[step["workflow"]]["kind"] == "workflow"
    field = next(f for f in blueprints["story"]["payload"]["schema_json"]["fields"] if f["key"] == "fountain_check")
    assert step["report"]["field"] == "fountain_check" and field["readOnly"] is True  # the report shows under the button: no step of its own
    by_story = blueprints["screenplay-check-fountain"]["payload"]["definition"]["actions"][0]["data"]
    by_text = blueprints["screenplay-check-fountain-text"]["payload"]["definition"]
    assert by_story["kind"] == "check-fountain" and by_story["args"] == {"story": "${entry.slug}"}
    assert by_text["actions"][0]["data"]["args"] == {"text": "${input.text}"} and by_text["trigger"]["inputs"][0]["type"] == "text"


def test_a_take_is_drawn_as_a_waveform_on_the_timeline_from_peaks_the_worker_writes():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    for slug in ("sound", "speech-line", "take"):
        field = next(f for f in blueprints[slug]["payload"]["schema_json"]["fields"] if f["key"] == "waveform")
        assert field["type"] == "json" and field["readOnly"] is True
    lanes = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}
    assert lanes["lines"]["waveform"] == lanes["sounds"]["waveform"] == "waveform"
    flow = blueprints["screenplay-make-waveform"]["payload"]["definition"]
    assert {"field": "entry.data.audio", "op": "changed"} in flow["conditions"]  # a new take, not the job writing its own result back
    assert flow["actions"][0]["data"]["kind"] == "make-waveform" and flow["actions"][0]["data"]["args"]["wave_field"] == "waveform"


def test_a_take_keeps_what_the_worker_hears_in_it_a_new_take_is_described_and_music_fades_show_as_a_slope():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    take = {f["key"]: f for f in blueprints["take"]["payload"]["schema_json"]["fields"]}
    heard = ("format", "level_lufs", "rms_db", "peak_db", "noise_floor_db", "clipped", "lead_silence", "tail_silence", "heard", "language", "words_per_minute", "match")
    assert all(take[k]["readOnly"] is True and take[k]["group"] == "What the worker heard" for k in heard)
    assert "defaultValue" not in take["source"]  # empty until the file says where it came from; the makers of a generated take say so themselves
    flow = blueprints["screenplay-describe-take"]["payload"]["definition"]
    assert {"field": "entry.data.audio", "op": "exists"} in flow["conditions"] and flow["actions"][0]["data"]["kind"] == "describe-audio"
    words = blueprints["screenplay-time-words"]["payload"]["definition"]
    assert {"field": "entry.data.source", "op": "neq", "value": "generated"} in words["conditions"] and words["actions"][0]["data"]["args"]["report"] == "yes"
    bed = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}["music"]["bed"]
    assert (bed["ramp"], bed["item_ramp_in"], bed["item_ramp_out"]) == (0.5, "music_fade_in", "music_fade_out")


def test_a_sound_card_can_take_the_persons_own_file_and_the_make_step_never_makes_a_sound_that_has_one():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    found = next(s for s in blueprints["sounds-for-a-story"]["payload"]["steps"] if s["id"] == "found")
    own = next(a for a in found["card_actions"] if a["label"] == "Use my own sound")
    assert own["file"] == {"field": "audio", "accept": "audio/*", "assets": True}  # upload, or choose from the assets
    assert own["set"] == {"source": "uploaded", "status": "approved"} and "when" not in own  # on every card; its file is kept as it is, nothing is made
    assert len(found["card_actions"]) <= 4 and found["add"]["file"]["assets"] is True
    save = next(b for b in found["add"]["buttons"] if b["label"] == "Save my own sound")
    assert save["skip_required"] is True and save["file"] == "required"  # a sound you bring needs no description of how to make one
    assert not any(b.get("skip_required") for b in found["add"]["buttons"] if b is not save)  # making one still asks for it
    where = blueprints["screenplay-make-sounds"]["payload"]["definition"]["actions"][0]["query"]["where"]
    assert {"field": "audio", "op": "missing"} in where  # a sound with any file is left alone, whatever its source says


def test_a_sound_added_with_its_file_is_prepared_and_measured_as_one_updated_with_a_file_is():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    pairs = {
        "screenplay-own-sound": "screenplay-own-sound-created",
        "screenplay-measure-sound": "screenplay-measure-sound-created",
        "screenplay-measure-sound-level": "screenplay-measure-sound-level-created",
        "screenplay-make-waveform": "screenplay-make-waveform-sound-created",
    }
    for old, new in pairs.items():
        before, after = blueprints[old]["payload"]["definition"], blueprints[new]["payload"]["definition"]
        assert (before["trigger"]["event"], after["trigger"]["event"]) == ("entry_updated", "entry_created")  # the file is there from the start: no update follows
        assert after["actions"] == before["actions"]  # the same job or change
        assert not any(c.get("op") == "changed" for c in after["conditions"])  # nothing has changed on a new entry
        assert blueprints[new]["name"] != blueprints[old]["name"]
    assert {"field": "entry.entry_type", "op": "in", "value": "sound"} in blueprints["screenplay-make-waveform-sound-created"]["payload"]["definition"]["conditions"]  # sounds only: a take or a line has its own


def test_a_lines_volume_and_muffling_are_its_own_fields_the_take_points_back_to_its_line_and_the_timeline_plays_the_level():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    line = {f["key"]: f for f in blueprints["speech-line"]["payload"]["schema_json"]["fields"]}
    assert (line["volume"]["min"], line["volume"]["max"], line["volume"]["slider"]) == (0, 1, True) and line["muffled"]["type"] == "boolean"
    assert line["volume"]["group"] == line["muffled"]["group"] == "Sound"
    take = {f["key"]: f for f in blueprints["take"]["payload"]["schema_json"]["fields"]}
    assert take["line"]["ref"] == "speech-line" and take["line"]["ref_match"] == {"story": "story"}
    assert line["beat"]["ref"] == "beat" and line["beat"]["ref_match"] == {"story": "story"} and line["beat"]["label"] == "Beat"  # moving a line is choosing its beat
    lanes = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}
    assert lanes["lines"]["volume"] == "volume"


def test_music_has_a_level_at_the_story_the_scene_and_the_beat_and_fades_like_ambience():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    fields = lambda slug: {f["key"]: f for f in blueprints[slug]["payload"]["schema_json"]["fields"]}  # noqa: E731
    story, scene, beat = fields("story"), fields("scene"), fields("beat")
    for owner in (story, scene, beat):
        assert (owner["music_volume"]["min"], owner["music_volume"]["max"], owner["music_volume"]["slider"]) == (0, 1, True)
    for key in ("music_fade_in", "music_fade_out"):
        assert story[key]["slider"] and beat[key]["slider"] and beat[key]["max"] == 10
    assert not any("music" in key and "muffled" in key for key in scene)  # a score is not heard through a wall
    bed = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}["music"]["bed"]
    assert (bed["volume"], bed["item_volume"], bed["entry_fade_in"], bed["entry_fade_out"]) == ("music_volume", "music_volume", "music_fade_in", "music_fade_out")


def test_a_story_has_a_takes_button_that_opens_the_takes_setup_on_its_character_step():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    payload = blueprints["takes-of-a-line"]["payload"]
    buttons = {b["entry_type"]: b for b in payload["button"]}
    assert buttons["speech-line"]["step"] == "takes" and buttons["story"] == {"entry_type": "story", "label": "Takes", "key": "story", "step": "character"}
    steps = [s["id"] for s in payload["steps"]]
    assert steps[0] == "story" and steps[1] == "character"  # the story is already chosen, so the setup opens on the next step


def test_a_story_has_buttons_for_casting_and_narrating_that_open_past_the_choices_its_own_fields_answer():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    for slug, label, step in (("casting-call", "Casting", "roles"), ("narrate-a-story", "Narrate", "details")):
        button = blueprints[slug]["payload"]["button"]
        steps = [s["id"] for s in blueprints[slug]["payload"]["steps"]]
        assert (button["entry_type"], button["label"], button["key"], button["step"]) == ("story", label, "story", step)
        assert button["also"]["world"] == "world" and steps.index("world") < steps.index("story") < steps.index(step)  # world and story are already answered when it opens

def test_the_camera_choices_are_the_worker_presets_and_the_timeline_has_a_camera_lane_reading_them():
    from storyrender import camera

    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    for owner in ("beat", "scene", "story"):
        field = {f["key"]: f for f in blueprints[owner]["payload"]["schema_json"]["fields"]}["camera"]
        assert field["type"] == "select" and field["options"] == [p.label for p in camera.PRESETS.values()]  # one table: the options are the presets, as plain text (a select holds text)
        assert all(camera.key_of(option) in camera.PRESETS for option in field["options"])
    lane = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}["camera"]
    assert lane["marks"]["field"] == "camera" and lane["marks"]["via"] == "scene" and lane["marks"]["other"]["field"] == "move"
    assert set(lane["marks"]["icons"]) == {p.label for p in camera.PRESETS.values()}
    assert len(blueprints["story-timeline"]["payload"]["lanes"]) <= 6  # Marvin's lane limit


def test_the_fields_that_hold_fountain_are_declared_fountain_so_their_preview_draws_a_screenplay():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    declared = {(slug, f["key"]) for slug in ("beat", "chapter", "speech-line", "story", "revision") for f in blueprints[slug]["payload"]["schema_json"]["fields"] if f.get("format") == "fountain"}
    assert declared == {("beat", "fountain"), ("chapter", "fountain"), ("speech-line", "fountain"), ("story", "fountain"), ("story", "fountain_front"), ("revision", "proposed"), ("revision", "before")}
    story = {f["key"]: f for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert "format" not in story["fountain_check"]  # the check's report is plain text, not a screenplay


def test_every_forms_groups_are_in_one_piece_with_the_plain_fields_first():
    blueprints = [b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == "entry_type"]
    for blueprint in blueprints:
        runs: list[str | None] = []
        for field in blueprint["payload"]["schema_json"]["fields"]:
            group = field.get("group")
            if not runs or runs[-1] != group:
                runs.append(group)
        named = [g for g in runs if g]
        assert len(named) == len(set(named)), f"{blueprint['slug']}: a group is split into pieces: {runs}"  # a group appears once
        if None in runs:
            assert runs.index(None) == 0 and runs.count(None) == 1, f"{blueprint['slug']}: the plain fields are not all at the top: {runs}"


def test_the_story_form_keeps_what_belongs_together_together():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    story = {f["key"]: f.get("group") for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert {story[k] for k in ("camera", "transition", "transition_seconds", "scene_break_seconds")} == {"Camera and transitions"}  # the transition's length is with the transition
    assert {story[k] for k in ("music", "music_volume", "music_fade_in", "music_fade_out", "music_ducking")} == {"Music"}
    assert {story[k] for k in ("ambience", "ambience_volume", "ambience_fade_in", "ambience_fade_out", "ambience_ducking")} == {"Ambience"}
    assert {story[k] for k in ("format", "platform", "loudness", "target_seconds")} == {"Where it is going"}
    labels = {f["key"]: f["label"] for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert "camera move" in labels["camera"].lower()  # a person looking for the camera moves finds them by that name


def test_the_scene_has_one_reference_picture_field_and_the_unused_photo_id_is_gone():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    scene = {f["key"]: f for f in blueprints["scene"]["payload"]["schema_json"]["fields"]}
    assert "anchor" in scene and "photo_ref" not in scene  # the still workflow reads the anchor; nothing ever read the ChatGPT file id


def test_a_beats_camera_is_chosen_in_one_place_and_the_numbers_start_from_the_choice():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    beat = {f["key"]: f for f in blueprints["beat"]["payload"]["schema_json"]["fields"]}
    assert "presets" not in beat["move"]  # a second dropdown of moves fills the numbers and leaves Camera blank: one way to choose a named move
    suggest = beat["move"]["suggest"]  # the box shows the numbers of the Camera choice until they are changed, and keeps nothing until then
    assert suggest["from"] == "camera"
    assert set(suggest["values"]) == set(beat["camera"]["options"])  # every choice has numbers to start from
    for name, numbers in suggest["values"].items():
        assert numbers == camera.move_of(name), name  # the very numbers the render uses for that choice, so the box never lies
    for owner in ("scene", "story"):
        assert "move" not in {f["key"] for f in blueprints[owner]["payload"]["schema_json"]["fields"]}  # numbers belong to one picture


def test_a_beats_lines_can_be_numbered_and_set_aside_added_from_the_beat_and_the_timeline_follows():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    line = {f["key"]: f for f in blueprints["speech-line"]["payload"]["schema_json"]["fields"]}
    assert line["order"]["type"] == "number" and line["leave_out"]["type"] == "boolean" and line["order"]["group"] == line["leave_out"]["group"] == "In the beat"
    lane = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}["lines"]
    assert lane["order"] == "order" and lane["off"] == "leave_out"  # the Timeline plays them in the render's order and leaves out what it leaves out
    wizard = blueprints["lines-in-a-beat"]["payload"]
    assert wizard["button"]["entry_type"] == "beat" and wizard["button"]["step"] == "lines" and wizard["button"]["key"] == "beat"
    gallery = [s for s in wizard["steps"] if s["id"] == "lines"][0]
    assert gallery["entry_type"] == "speech-line" and gallery["parent_field"] == "beat" and gallery["add"]["data"]["story"] == "${story}"
    assert {"speaker", "text"} <= set(gallery["add"]["fields"])  # a line needs a speaker and words


def test_the_camera_lane_draws_the_moves_that_carry_on_across_a_cut_as_one_block():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    marks = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}["camera"]["marks"]
    assert set(marks["merge"]) == {"Still", "Rocking", "Heavy rocking"}  # a rocking runs on the film's clock; a push in starts afresh at each beat, so it stays a chip each


def test_a_beats_reference_pictures_are_an_asset_picker_and_the_still_workflow_passes_them_as_a_list_with_the_scene_s_anchor():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    beat = {f["key"]: f for f in blueprints["beat"]["payload"]["schema_json"]["fields"]}
    assert beat["references"]["type"] == "asset-list" and beat["references"]["role"] == "reference" and beat["references"]["accept"] == "image/*"
    assert beat["references"]["group"] == "The shot"
    text = json.dumps(blueprints["screenplay-take-still"]["payload"])
    assert '"references": ["${entry.data.references}", "${steps.scene.output.rows.0.data.anchor}"]' in text  # a picker's list, then the anchor (a comma string would split the list's own text)


def test_the_story_says_how_the_film_ends_with_plain_text_options_and_no_default():
    made = json.loads(PACKAGE.read_text(encoding="utf-8"))
    fields = next(b for b in made["blueprints"] if b["kind"] == "entry_type" and b["slug"] == "story")["payload"]["schema_json"]["fields"]
    keys = [f["key"] for f in fields]
    ending = fields[keys.index("end_transition")]
    assert ending["type"] == "select" and ending["options"] == ["cut", "fade"] and "defaultValue" not in ending  # empty until FADE OUT. or a person sets it
    assert keys.index("end_transition") == keys.index("transition_seconds") + 1 and ending["group"] == fields[keys.index("transition")]["group"]


def test_the_playbook_in_the_package_is_the_skill_as_it_is_written():
    made = json.loads(PACKAGE.read_text(encoding="utf-8"))
    playbook = next(b for b in made["blueprints"] if b["kind"] == "playbook" and b["slug"] == "screenplay-studio")["payload"]
    skill = PACKAGE.parents[1] / "skills" / "screenplay-studio"
    assert playbook["skill_md"] == (skill / "SKILL.md").read_text(encoding="utf-8")
    on_disk = {p.relative_to(skill).as_posix(): p.read_text(encoding="utf-8") for p in sorted(skill.rglob("*.md")) if p.name != "SKILL.md"}
    assert playbook["files"] == on_disk  # run scripts/build_playbooks.py after editing the skill: an agent reads the package's copy


def test_a_preview_job_is_named_as_one_and_the_import_keeps_its_name():
    flow = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}["screenplay-import-screenplay"]["payload"]["definition"]
    made = [a for a in flow["actions"] if a.get("entry_type") == "job"]
    preview = next(a for a in made if a.get("when") == {"field": "input.preview", "op": "eq", "value": "yes"})
    real = next(a for a in made if a.get("when") == {"field": "input.preview", "op": "neq", "value": "yes"})
    assert len(made) == 2 and preview["title"].startswith("Preview only: nothing was made") and real["title"] == "Bring in the Fountain: ${entry.title}"
    assert preview["data"] == real["data"] and preview["data"]["args"]["dry_run"] == "${input.preview}"  # the same job: only the name differs


def test_the_fountain_reports_are_big_enough_to_read_and_say_how_to_fix_an_uploaded_file():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    fields = {f["key"]: f for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert fields["fountain_check"]["rows"] >= 16 and fields["split_plan"]["rows"] >= 16
    steps = {s["id"]: s for s in blueprints["narrate-a-story"]["payload"]["steps"]}
    for said in (fields["fountain_check"]["helpText"], steps["fountain_check"]["help"]):
        assert "Story details" in said and "cannot be edited in Marvin" in said and "Nothing needs approving" in said, said
    assert "(above)" not in steps["fountain_check"]["help"]


def test_clearing_a_story_counts_first_then_asks_an_admin_before_anything_is_deleted():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    flow = blueprints["screenplay-clear-story"]["payload"]["definition"]
    assert flow["trigger"] == {"type": "manual", "inputs": [{"name": "story", "label": "Story", "type": "entry", "required": True}]}
    acts = flow["actions"]
    assert [a.get("id") for a in acts] == ["look", "look_all", "nothing", "clear", "trash", "forever", "reset", "music"]
    deletes = [i for i, a in enumerate(acts) if a["kind"] == "delete_entries" and a.get("mode", "preview") != "preview"]
    assert deletes and min(deletes) > [a.get("id") for a in acts].index("clear")  # the question comes before anything goes
    steps = {a["id"]: a for a in acts}
    assert steps["look"]["mode"] == steps["look_all"]["mode"] == "preview"
    assert steps["nothing"]["when"] == {"field": "steps.look.output.total", "op": "lt", "value": 1}
    clear = steps["clear"]
    assert clear["kind"] == "approval" and clear["approvers"] == "admin"
    assert clear["when"] == {"field": "steps.look.output.total", "op": "gte", "value": 1}
    assert clear["choices"] == ["Move them to the Trash", "Delete for good (cannot be undone)", "Leave them"]
    assert "30 days" in clear["detail"] and "cannot" in clear["detail"].lower() and "asset library" in clear["detail"]
    for step, mode, preview, choice in (("trash", "trash", "look", 0), ("forever", "permanent", "look_all", 1)):
        assert steps[step]["mode"] == mode
        assert steps[step]["confirm_total"] == f"${{steps.{preview}.output.total}}"  # the count the approval was asked on
        assert steps[step]["query"] == steps[preview]["query"]  # and the same selection it counted
        assert steps[step]["when"] == {"field": "steps.clear.output.choice", "op": "eq", "value": clear["choices"][choice]}


def test_clearing_a_story_selects_its_records_by_their_story_field_and_frees_trashed_slugs_only_when_deleting_for_good():
    acts = {a["id"]: a for a in _flow("screenplay-clear-story")["actions"]}
    kinds = ["chapter", "scene", "beat", "speech-line", "sound", "cast-member", "take", "casting"]
    assert acts["look"]["query"] == {"entry_types": kinds, "fields": {"story": "${entry.slug}"}}  # the story field, never a slug prefix
    assert "text" not in json.dumps(acts["look"]["query"]) and "query" not in acts["look"]["query"]
    assert "trashed" in acts["look_all"]["query"]["statuses"] and acts["look_all"]["query"]["fields"] == {"story": "${entry.slug}"}
    assert "statuses" not in acts["trash"]["query"]  # a move to the Trash never re-touches what is already there


def test_after_a_clear_the_story_is_set_to_split_again_and_its_score_placeholder_is_let_go():
    acts = {a["id"]: a for a in _flow("screenplay-clear-story")["actions"]}
    ran = {"any": [{"field": "steps.trash.output.deleted", "op": "exists"}, {"field": "steps.forever.output.deleted", "op": "exists"}]}
    reset, music = acts["reset"], acts["music"]
    assert reset["op"] == music["op"] == "set_data" and "entity_slug" not in reset  # the story the run is on
    assert reset["when"] == ran and music["when"] == {"all": [ran, {"field": "entry.data.music", "op": "eq", "value": "${entry.slug}-score"}]}
    # A set_data drops a value that is "" (Marvin never overwrites with nothing), so a single space stands for empty: the setup's
    # `requires` and the import both strip it. The import's step stays off until the split is checked again.
    assert reset["data"]["split_plan"] == " " and music["data"] == {"music": " "}
    assert reset["data"]["readiness"].strip() and reset["data"]["sheet_log"].startswith("${entry.data.sheet_log}\n")
    assert "fountain_check" not in reset["data"]  # the Fountain did not change
    # A leftover "Chapters to bring in" would make the next import bring in only those: the clear lets it go (blank = all).
    from storyrender.jobs import parse_part

    assert reset["data"]["import_part"] == " " and parse_part(reset["data"]["import_part"]) is None


def test_the_narrate_setup_offers_the_clear_right_after_the_import_and_no_other_workflow_deletes_for_good():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    steps = blueprints["narrate-a-story"]["payload"]["steps"]
    ids = [s["id"] for s in steps]
    assert ids[ids.index("import") + 1] == "clear"
    clear = steps[ids.index("clear")]
    assert clear["kind"] == "run" and clear["workflow"] == "screenplay-clear-story" and clear["inputs"] == {"story": "${story}"}
    assert blueprints[clear["workflow"]]["kind"] == "workflow"
    assert "Check the split" in clear["help"] and "Bring in the chapters" in clear["help"] and "30 days" in clear["help"]
    forever = [b["slug"] for b in blueprints.values() if b["kind"] == "workflow" and '"mode": "permanent"' in json.dumps(b["payload"]["definition"])]
    assert forever == ["screenplay-clear-story"]


def _setups() -> tuple[dict, dict]:
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    return blueprints, {slug: {s["id"]: s for s in b["payload"]["steps"]} for slug, b in blueprints.items() if b["kind"] == "wizard"}


def test_an_empty_step_points_to_a_setup_the_package_brings_and_the_voice_step_to_the_form_that_fills_it():
    blueprints, setups = _setups()
    for slug, steps in setups.items():
        for step in steps.values():
            href = (step.get("empty_next") or {}).get("href", "")
            if href.startswith("/workspace/setups/"):
                assert href.rsplit("/", 1)[1] in setups, (slug, step["id"])
    takes, casting = setups["takes-of-a-line"], setups["casting-call"]
    for sid in ("character", "chapter", "beat"):  # nothing to pick before the Fountain is in: say so, and where it is brought in
        assert takes[sid]["empty"] and takes[sid]["empty_next"]["href"] == "/workspace/setups/narrate-a-story", sid
    assert takes["line"]["empty_next"]["href"] == "/workspace/setups/lines-in-a-beat"  # a beat with no words: add a line to it
    assert setups["lines-in-a-beat"]["lines"]["empty_next"]["href"] == "/workspace/setups/narrate-a-story"
    for sid in ("troupe", "candidates"):  # a new actor is made in Open call, not here
        assert casting[sid]["empty_next"]["href"] == "/workspace/setups/open-call", sid
    # "Voice for the lines" needs the role's voice: an earlier form of the same entry shows it, so the page links there when it is empty.
    order = list(casting)
    needs = casting["voice_lines"]["requires"]
    fillers = [s["id"] for s in casting.values() if s["kind"] == "form" and s["entry"] == needs["entry"] and needs["field"] in s["fields"]]
    assert fillers == ["assign"] and order.index("assign") < order.index("voice_lines")


def test_a_paid_button_names_the_service_its_workflow_calls_and_only_the_fields_that_workflow_sends():
    blueprints, setups = _setups()
    fields = lambda slug: {f["key"] for f in blueprints[slug]["payload"]["schema_json"]["fields"]}
    sent = lambda slug, key: "${entry.data." + key in workflow(slug)

    def paid_of(step: dict) -> dict:
        items = step["add"]["buttons"] + step["card_actions"]
        assert all("paid" not in i for i in items if i.get("file") not in (None, "none")), "a button that saves the person's own file sends nothing"
        return {i["label"]: i["paid"] for i in items if "paid" in i}

    takes = paid_of(setups["takes-of-a-line"]["takes"])
    assert set(takes) == {"Make it with ElevenLabs", "Try again"}
    for label, paid in takes.items():
        assert paid["service"] == "ElevenLabs" and set(paid["needs"]) <= set(paid["sends"]) <= fields("take"), label
        assert "direction" not in paid["sends"]  # a note for people: the voice never gets it
        for slug in ("screenplay-make-take", "screenplay-remake-take"):
            assert '"integration": "elevenlabs"' in workflow(slug) and all(sent(slug, key) for key in paid["sends"]), (label, slug)

    sounds = paid_of(setups["sounds-for-a-story"]["found"])
    assert set(sounds) == {"Make this one", "Make it again", "Make it now with ElevenLabs"}
    for label, paid in sounds.items():
        assert paid["service"] == "ElevenLabs" and paid["needs"] == ["prompt"] and set(paid["sends"]) <= fields("sound"), label
        assert all(sent("screenplay-take-sound", key) for key in paid["sends"]) and sent("screenplay-take-music", "prompt"), label
    assert "Make step" not in setups["sounds-for-a-story"]["found"]["added"]  # that step went in v179

    casting = setups["casting-call"]
    master, write = casting["master"]["paid"], casting["master_prompt_write"]["paid"]
    assert master["service"] == "OpenAI Images" and '"integration": "openai_images"' in workflow(casting["master"]["workflow"])
    assert master["entry"] == "role" and master["sends"] == master["needs"] == ["master_prompt"] and sent(casting["master"]["workflow"], "master_prompt")
    assert '"kind": "agent"' in workflow(casting["master_prompt_write"]["workflow"])  # an AI call, by whichever model the workspace runs
    assert write["entry"] == "role" and set(write["needs"]) <= set(write["sends"]) <= fields("cast-member")
    assert all(sent(casting["master_prompt_write"]["workflow"], key) for key in write["sends"])
    assert "paid" not in casting["voice_lines"]  # it only copies the voice onto the lines: nothing leaves the workspace


# The person's sheet as v181 sent it: an animal branch must not change a word of it.
PERSON_SHEET_PROMPT = (
    "A character sheet of one actor on a portrait canvas, the four views arranged in a 2 by 2 grid that fills the whole picture, each view large and "
    "full length with soft ground shadows on a plain warm cream background: front and three-quarter on the top row, side and back on the bottom row, "
    "standing relaxed, the same person in all four. Built on the attached base sheet's proportions and style: keep its construction and scale of head "
    "to body. The second attached picture is an existing actor sheet of this world: draw the faces, hands, hair, skin and cloth exactly in its way, as "
    "flat soft matte shapes: two small dark dot eyes, a small plain nose, a tiny smile, simple brow lines, no skin pores, no arm hair, no shaded nose, "
    "no fine fabric weave; any stubble or beard is one simple flat speckled shape. Never realistic, never glossy. The actor: ${entry.title}, an adult "
    "${entry.data.base}, age ${entry.data.age}. Build: ${entry.data.build} Hair: ${entry.data.hair} Skin tone: ${entry.data.skin_tone} Look: "
    "${entry.data.look} Distinguishing features, the same in every view: ${entry.data.distinguishing_features} Wearing, in every view: "
    "${entry.data.baseline_wardrobe}. Both legs whole, empty hands, no props. ${steps.world.output.rows.0.data.rules}"
)
BASE_SHEET = "${entry.data.world}-base-${entry.data.base}"
ANIMAL = {"field": "entry.data.base", "op": "in", "value": "${input.animal_bases}"}


def _sheet_steps() -> tuple[dict, dict]:
    flow = _flow("screenplay-make-actor-sheet")
    return flow, {a.get("id") or f"{a['kind']}{i}": a for i, a in enumerate(flow["actions"])}


def test_a_persons_sheet_is_sent_as_before_with_arthur_for_the_style_and_never_for_an_animal():
    flow, steps = _sheet_steps()
    person = steps["sheet"]
    assert person["args"]["prompt"] == PERSON_SHEET_PROMPT and person["references"] == BASE_SHEET + ",${input.style_actor}"
    assert PERSON_SHEET_PROMPT in steps["spend"]["message"]  # what is approved is what is sent
    assert next(i for i in flow["trigger"]["inputs"] if i["name"] == "style_actor")["default"] == "arthur"
    for sid in ("spend", "sheet"):
        assert {"not": ANIMAL} in steps[sid]["when"], sid
    for sid in ("spend_animal", "sheet_animal"):
        assert ANIMAL in steps[sid]["when"], sid
    assert next(a for a in flow["actions"] if a.get("kind") == "integration")["id"] == "sheet"


def test_an_animals_sheet_is_three_views_of_a_quadruped_from_its_own_fields_on_the_worlds_base_sheet():
    flow, steps = _sheet_steps()
    inputs = {i["name"]: i for i in flow["trigger"]["inputs"]}
    assert inputs["animal_bases"]["default"] == "dog,cat,horse,bird" and "default" not in inputs["style_animal"]  # arthur is a person
    animal = steps["sheet_animal"]
    sent = animal["args"]["prompt"]
    assert animal["references"] == BASE_SHEET + ",${input.style_animal}"  # an empty style animal is dropped: the base sheet alone
    assert sent in steps["spend_animal"]["message"] and BASE_SHEET in steps["spend_animal"]["message"]
    assert "three full-body views" in sent and "front, right-side profile, back" in sent and "quadruped" in sent
    assert "cream studio background" in sent and "No collar, no clothes, no props, no scenery, no labels, no text" in sent
    assert "no hands or fingers" in sent and "four views" not in sent and "2 by 2" not in sent
    for key in ("base", "age", "build", "look", "distinguishing_features"):
        assert "${entry.data." + key + "}" in sent, key
    for key in ("hair", "skin_tone", "baseline_wardrobe"):
        assert "${entry.data." + key + "}" not in sent, key
    for brand in ("playmobil", "lego", "fisher", "sylvanian", "calico", "schleich", "duplo"):
        assert brand not in sent.lower(), brand
    assert animal["args"]["size"] == '${input.size|default:"1536x1024"}' and "Picture size: ${input.size" in steps["spend_animal"]["message"]


def test_an_actors_sheet_spends_nothing_without_a_build_or_the_base_sheet_and_every_step_runs_under_the_step_limit():
    flow, steps = _sheet_steps()
    assert len(flow["actions"]) <= 10  # Marvin's default steps per workflow: a step past it never runs, so Keep would stop approving
    assert flow["actions"][0] == {"kind": "collect", "id": "base_sheet", "entity": "asset", "query": {"ids": BASE_SHEET, "versions": "all"}}
    lacking = steps["missing"]["when"]["any"]
    assert {"field": "steps.base_sheet.output.count", "op": "lt", "value": 1} in lacking
    assert {"field": "entry.data.build", "op": "shorter_than", "value": 5} in lacking
    assert BASE_SHEET in steps["missing"]["message"] and "no credit was spent" in steps["missing"]["message"]
    ready = {"field": "steps.base_sheet.output.count", "op": "gte", "value": 1}
    for sid in ("spend", "sheet", "spend_animal", "sheet_animal"):
        assert ready in steps[sid]["when"], sid
    made = steps["entry7"]
    assert made["data"]["general_view"] == "${steps.sheet.output.asset.id}${steps.sheet_animal.output.asset.id}"  # whichever was drawn
    assert made["when"] == steps["keep"]["when"] == {
        "any": [{"field": f"steps.{s}.output.asset.id", "op": "exists"} for s in ("sheet", "sheet_animal")]
    }  # nothing drawn: the sheet's picture is never emptied


def test_open_call_offers_to_make_the_sheet_with_ai_right_after_the_sheet_form():
    blueprints, setups = _setups()
    steps = setups["open-call"]
    order = list(steps)
    make = steps["make_sheet"]
    assert order.index("make_sheet") == order.index("sheet") + 1 and make["kind"] == "run"
    assert make["workflow"] == "screenplay-make-actor-sheet" and make["inputs"] == {"actor": "${actor}"}
    assert make["requires"] == {"entry": "actor", "field": "build"} and "build" in steps["sheet"]["fields"]  # the page links back to the form
    paid = make["paid"]
    fields = {f["key"] for f in blueprints["actor"]["payload"]["schema_json"]["fields"]}
    assert paid["service"] == "OpenAI Images" and paid["entry"] == "actor" and set(paid["needs"]) <= set(paid["sends"]) <= fields
    sheet_flow = workflow("screenplay-make-actor-sheet")
    animal = next(a for a in _flow("screenplay-make-actor-sheet")["actions"] if a.get("id") == "sheet_animal")["args"]["prompt"]
    for key in paid["sends"]:  # what the notice shows goes to the model for a person and for an animal alike
        assert "${entry.data." + key in sheet_flow and "${entry.data." + key in animal, key
    assert "next step" in steps["sheet"]["help"] and "Approvals shows the exact prompt" in make["help"]


def _holds(cond, entry: dict) -> bool:
    """Marvin's condition matcher (services/automation/matcher.py), for the operators the package's triggers use, on a plain entry."""
    if isinstance(cond, list):
        return all(_holds(c, entry) for c in cond)
    if "all" in cond or "any" in cond:
        return (all if "all" in cond else any)(_holds(c, entry) for c in cond.get("all") or cond.get("any"))
    if "not" in cond:
        return not _holds(cond["not"], entry)
    actual = entry["entry_type"] if cond["field"] == "entry.entry_type" else entry["data"].get(cond["field"].removeprefix("entry.data."))
    op, value = cond.get("op", "eq"), cond.get("value")
    if op.startswith("changed"):  # an update's diff: `changed` holds the fields the button set, as {key: (before, after)}
        before, after = entry.get("changed", {}).get(cond["field"].removeprefix("entry.data.").removeprefix("entry."), (None, None))
        return {"changed": after is not None, "changed_to": after is not None and after == value, "changed_from": before == value}[op]
    length = len(str(actual)) if actual is not None else 0
    checks = {
        "eq": lambda: actual == value,
        "neq": lambda: actual != value,
        "in": lambda: actual in ([v.strip() for v in value.split(",")] if isinstance(value, str) else value),
        "exists": lambda: (actual is not None) == (value is not False),
        "longer_than": lambda: length > value,
        "shorter_than": lambda: length < value,
    }
    return checks[op]()


def _made_by(event: str, entry: dict) -> list[str]:
    flows = [b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == "workflow"]
    return [
        b["slug"] for b in flows
        if b["payload"]["definition"].get("trigger") == {"type": "event", "event": event} and _holds(b["payload"]["definition"].get("conditions") or [], entry)
    ]  # fmt: skip


def _queued_by_buttons() -> list[tuple[str, str, dict, str]]:
    """(button, event, entry, status word) for every gallery button that leaves an entry queued: an add button makes it (entry_created),
    a card action changes it (entry_updated). Each select field the add form asks for is tried with each of its options."""
    blueprints, setups = _setups()
    out = []
    for steps in setups.values():
        for step in steps.values():
            if step["kind"] != "gallery":
                continue
            fields = {f["key"]: f for f in blueprints[step["entry_type"]]["payload"]["schema_json"]["fields"]}
            add = step.get("add") or {}
            asked = [k for k in add.get("fields", []) if fields[k].get("type") == "select"]
            filled = {k: "words" for k in add.get("fields", []) if fields[k].get("type") in ("text", "textarea")}
            for button in add.get("buttons", []):
                if (button.get("data") or {}).get("status") != "queued":
                    continue
                own = {add["file"]["field"]: "an-asset"} if button.get("file") == "required" else {}
                for choice in ([{}] if not asked else [{k: o} for k in asked for o in fields[k]["options"]]):
                    data = {**filled, **add.get("data", {}), **choice, **own, **button["data"]}
                    out.append((f"{step['id']}: {button['label']} {choice}", "entry_created", {"entry_type": step["entry_type"], "data": data}))
            for card in step.get("card_actions", []):
                if card["set"].get("status") == "queued":
                    for choice in ([{}] if not asked else [{k: o} for k in asked for o in fields[k]["options"]]):
                        data = {**filled, "source": "generated", **choice, **card["set"]}
                        changed = {k: ("draft", v) for k, v in card["set"].items()}
                        out.append((f"{step['id']}: {card['label']} {choice}", "entry_updated", {"entry_type": step["entry_type"], "data": data, "changed": changed}))
    return out


_QUEUED = [{"field": "entry.data.status", "op": op, "value": "queued"} for op in ("eq", "changed_to")]  # a workflow that works off the queue


def test_every_button_that_leaves_an_entry_queued_has_a_workflow_that_hears_how_it_was_queued():
    queued = _queued_by_buttons()
    assert {label.split(" {")[0] for label, *_ in queued} >= {"found: Make it now with ElevenLabs", "takes: Make it with ElevenLabs", "found: Make this one"}
    for label, event, entry in queued:
        takers = [s for s in _made_by(event, entry) if any(q in _flow(s)["conditions"] for q in _QUEUED)]  # measuring may run beside
        assert len(takers) == 1, (label, event, takers)  # one workflow takes it: none leaves it sitting at queued, two would pay twice


def test_a_sound_made_now_is_made_by_the_created_twin_and_an_edit_to_queued_by_the_original_never_both():
    for kind, slug in (("effect", "screenplay-take-sound"), ("ambience", "screenplay-take-sound"), ("music", "screenplay-take-music")):
        sound = {"entry_type": "sound", "data": {"kind": kind, "prompt": "waves", "source": "generated", "status": "queued"}}
        assert _made_by("entry_created", sound) == [slug + "-created"], kind
        assert _made_by("entry_updated", sound) == [slug], kind
        assert _flow(slug + "-created")["actions"] == _flow(slug)["actions"] and _flow(slug + "-created")["conditions"] == _flow(slug)["conditions"]


def _spending_takers() -> list[str]:
    """Every workflow that takes an entry off the queue (its status is queued) and asks to spend first."""
    flows = [b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == "workflow"]
    return [
        b["slug"] for b in flows
        if any(q in (b["payload"]["definition"].get("conditions") or []) for q in _QUEUED)
        and any(a.get("kind") == "approval" and a.get("id") == "spend" for a in b["payload"]["definition"]["actions"])
    ]  # fmt: skip


def test_a_gallery_that_queues_an_entry_shows_the_spend_approval_of_whichever_workflow_takes_it():
    # The approval asked about a sound made with Make it now comes from the created twin: a gallery that named only the original never
    # showed it, and the sound sat at queued with its question somewhere else (Automation, Approvals).
    _, setups = _setups()
    by_step = {s["id"]: s for steps in setups.values() for s in steps.values() if s["kind"] == "gallery"}
    for label, event, entry in _queued_by_buttons():
        step = by_step[label.split(":")[0]]
        asking = [s for s in _made_by(event, entry) if s in _spending_takers()]
        assert set(asking) <= set(step.get("approve") or []), (label, asking, step.get("approve"))  # a sound of your own asks nothing
        if label.split(" {")[0] in ("found: Make it now with ElevenLabs", "found: Make this one", "takes: Make it with ElevenLabs"):
            assert asking, label
    assert set(by_step["found"]["approve"]) == {f"screenplay-take-{k}{t}" for k in ("sound", "music") for t in ("", "-created")}


_RESET = {"field": "steps.spend.output.decision", "op": "in", "value": ["denied", "expired"]}


def test_a_denied_spend_puts_the_entry_back_to_draft_before_anything_else_runs():
    # A run goes on after its approval is answered, with the answer in steps.spend.output.decision; denied (or left to expire) the paid
    # step is refused and the run ends, so without this the entry stayed at queued for good and no button could start it again.
    blueprints, _ = _setups()
    for slug in _spending_takers():
        acts = _flow(slug)["actions"]
        if slug == "screenplay-take-still":  # already past Marvin's ten steps: one more would push its Keep question past a raised limit
            assert not [a for a in acts if a.get("when") == _RESET]
            continue
        assert len(acts) <= 10, slug  # Marvin runs the first ten steps of a workflow unless the workspace raises it
        at = next(n for n, a in enumerate(acts) if a.get("id") == "spend")
        reset = acts[at + 1]
        assert reset["kind"] == "entry" and reset["op"] == "set_data" and reset["data"] == {"status": "draft"} and reset["when"] == _RESET, slug
        assert [a for a in acts if a.get("when") == _RESET] == [reset], slug  # once, and never on the Keep / Redo question
        kind = next(c["value"] for c in _flow(slug)["conditions"] if c["field"] == "entry.entry_type")
        status = next(f for f in blueprints[kind]["payload"]["schema_json"]["fields"] if f["key"] == "status")
        assert "draft" in status["options"], kind  # draft is the not-made-yet status of every type these make
    # approved (Make it, or a take's Cancel, which its own step sets to draft), stale (changed meanwhile: a new run asks again) and a
    # batch's flag (no spend question asked, so no decision) are not in _RESET
    assert len(_spending_takers()) == 7  # six reset; the still is left to the person (set the beat back to draft by hand)


def test_a_beat_has_shot_direction_for_fresh_and_older_workspaces_and_the_still_reads_it():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    own = next(f for f in blueprints["beat"]["payload"]["schema_json"]["fields"] if f["key"] == "direction")
    added = blueprints["beat-direction-field"]
    # an update never changes a type the workspace has: the entry_fields blueprint adds it there, the same field a fresh install gets
    assert added["kind"] == "entry_fields" and added["payload"]["entry_type"] == "beat" and added["payload"]["fields"] == [own]
    assert own["type"] == "textarea" and own["group"] == "The shot"
    slugs = list(blueprints)
    assert slugs.index("beat-direction-field") > slugs.index("beat")
    prompt = next(a["args"]["prompt"] for a in _flow("screenplay-take-still")["actions"] if "prompt" in (a.get("args") or {}))
    line = 'THIS MOMENT: ${entry.data.picture}\nShot direction (where the camera looks): ${entry.data.direction|default:"none"}\n'
    assert prompt.count(line) == 1
