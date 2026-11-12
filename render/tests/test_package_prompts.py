"""The prompts the package sends to the image model keep their guardrails (a master is a portrait, not a scene; sides are anatomical; a style
reference never brings its people), so an edit to a workflow cannot quietly drop them."""

import json
from pathlib import Path

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
    assert group("story", "ambience") == group("story", "loudness") == "Sound and language"
    for owner in ("scene", "beat"):
        assert group(owner, "ambience") == group(owner, "ambience_volume") == group(owner, "story_ambience_volume") == "Sound"
        assert group(owner, "overlay") == group(owner, "overlay_delay") == "Overlay"  # the same name the story uses
    assert group("beat", "music_volume") == group("beat", "sounds") == "Sound"
    assert group("scene", "story_ambience_muffled") == "Sound"
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
    assert order.index("story") < order.index("found") < order.index("beds") < order.index("make") < order.index("keep") < order.index("check")
    sound = {f["key"]: f for f in blueprints["sound"]["payload"]["schema_json"]["fields"]}
    scene = {f["key"] for f in blueprints["scene"]["payload"]["schema_json"]["fields"]}
    story = {f["key"] for f in blueprints["story"]["payload"]["schema_json"]["fields"]}
    assert set(steps["found"]["add"]["fields"]) <= set(sound) and set(steps["beds"]["columns"]) <= scene and set(steps["bed"]["fields"]) <= story
    statuses = set(sound["status"]["options"])
    wanted = {b["data"]["status"] for b in steps["found"]["add"]["buttons"]} | {a["set"]["status"] for a in steps["found"]["card_actions"]}
    wanted |= {c["query"]["fields"]["status"] for c in steps["check"]["checks"] if "status" in c["query"]["fields"]}
    assert wanted <= statuses  # a button or a check can only name a status the Sound type has
    for slug in [*steps["found"]["approve"], steps["make"]["workflow"], steps["keep"]["workflow"]]:
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
    assert steps.index("fountain_upload") < steps.index("fountain_check") < steps.index("fountain_report") < steps.index("split")
    step = next(s for s in blueprints["narrate-a-story"]["payload"]["steps"] if s["id"] == "fountain_check")
    assert blueprints[step["workflow"]]["kind"] == "workflow"
    shown = next(s for s in blueprints["narrate-a-story"]["payload"]["steps"] if s["id"] == "fountain_report")
    field = next(f for f in blueprints["story"]["payload"]["schema_json"]["fields"] if f["key"] == "fountain_check")
    assert shown["fields"] == ["fountain_check"] and field["readOnly"] is True
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


def test_a_lines_volume_and_muffling_are_its_own_fields_the_take_points_back_to_its_line_and_the_timeline_plays_the_level():
    blueprints = {b["slug"]: b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"]}
    line = {f["key"]: f for f in blueprints["speech-line"]["payload"]["schema_json"]["fields"]}
    assert (line["volume"]["min"], line["volume"]["max"], line["volume"]["slider"]) == (0, 1, True) and line["muffled"]["type"] == "boolean"
    assert line["volume"]["group"] == line["muffled"]["group"] == "Sound"
    take = {f["key"]: f for f in blueprints["take"]["payload"]["schema_json"]["fields"]}
    assert take["line"]["ref"] == "speech-line" and take["line"]["ref_match"] == {"story": "story"}
    lanes = {lane["id"]: lane for lane in blueprints["story-timeline"]["payload"]["lanes"]}
    assert lanes["lines"]["volume"] == "volume"
