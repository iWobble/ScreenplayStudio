"""A beat's moving shot (v231): ElevenLabs' `make_video` (plugin 0.4.0, Marvin #303) makes a short video from the beat's still, after a
paid approval, and Keep makes it the beat's overlay. Only package records change: the overlay is a renderer feature the beat already had,
so a film renders exactly as before (test_unchanged_render's goldens are untouched).

Marvin's own matcher and checkers are used when they can be imported (run where Marvin is): CI has no Marvin and skips them."""

import pytest

from tests.test_world_context import BLUEPRINTS

MAKE, REQUEUE, FAILED = "screenplay-make-beat-video", "screenplay-requeue-moving-shot", "screenplay-moving-shot-failed"
ADDED = ["gen_video_status", "gen_video_prompt", "gen_video_seconds", "gen_video", "gen_video_note", "gen_video_previous_overlay"]


def _flow(slug):
    return BLUEPRINTS[slug]["payload"]["definition"]


def _beat_fields():
    return {f["key"]: f for f in BLUEPRINTS["beat"]["payload"]["schema_json"]["fields"]}


def _steps(actions):
    """Every step, a parallel step's branch steps after it, in the order they run."""
    for step in actions:
        yield step
        for branch in step.get("branches") or []:
            yield from _steps(branch["steps"])


def _step(slug, step_id):
    return next(s for s in _steps(_flow(slug)["actions"]) if s.get("id") == step_id)


def _writes(slug):
    return [s for s in _steps(_flow(slug)["actions"]) if s.get("op") == "set_data"]


# ── the beat's fields ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_beat_holds_the_moving_shot_after_its_overlay_and_only_its_words_and_length_can_be_edited():
    fields = BLUEPRINTS["beat"]["payload"]["schema_json"]["fields"]
    keys = [f["key"] for f in fields]
    at = keys.index("overlay_delay") + 1
    assert keys[at : at + len(ADDED)] == ADDED
    by = _beat_fields()
    assert {by[k]["group"] for k in ADDED} == {"Moving shot"}
    assert [by[k]["type"] for k in ADDED] == ["select", "textarea", "select", "asset", "text", "asset"]
    assert [k for k in ADDED if by[k].get("readOnly")] == ["gen_video_status", "gen_video", "gen_video_note", "gen_video_previous_overlay"]
    assert by["gen_video_status"]["options"] == ["draft", "queued", "ready", "kept", "redo", "failed"] and by["gen_video_status"]["defaultValue"] == "draft"
    assert by["gen_video_seconds"]["options"] == ["4", "6", "8"] and by["gen_video_seconds"]["defaultValue"] == "6"  # all Veo makes
    assert by["gen_video"]["accept"] == "video/mp4" and by["gen_video_previous_overlay"]["accept"] == by["overlay"]["accept"]
    # It says that Keep replaces the overlay, and where the one replaced is kept.
    for key in ("gen_video", "gen_video_previous_overlay", "overlay"):
        assert "Overlay before the moving shot" in by[key]["helpText"] or by[key]["label"] == "Overlay before the moving shot"
    assert "in place of" in by["overlay"]["helpText"] and "in place of" in by["gen_video"]["helpText"]


# ── what starts it ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_it_starts_when_the_moving_shot_is_queued_and_a_retry_stands_down_once_it_is_not():
    flow = _flow(MAKE)
    assert flow["trigger"] == {"type": "event", "event": "entry_updated"}
    assert flow["conditions"] == [
        {"field": "entry.entry_type", "op": "eq", "value": "beat"},
        {"field": "entry.data.gen_video_status", "op": "changed_to", "value": "queued"},  # an edit while it waits starts no second run
        {"field": "entry.data.gen_video_status", "op": "eq", "value": "queued"},  # set back meanwhile: a retry is superseded
        {"field": "entry.data.still", "op": "longer_than", "value": 0},
        {"field": "entry.data.shows", "op": "neq", "value": "Plain card"},
        {"field": "entry.data.status", "op": "neq", "value": "queued"},  # take-still fires on every write while its still is queued
    ]


def test_nothing_before_the_call_changes_the_status_and_nothing_writes_the_stills_own():
    acts = _flow(MAKE)["actions"]
    at = next(i for i, s in enumerate(acts) if s.get("kind") == "integration")
    before = [s for s in _steps(acts[:at]) if s.get("op") == "set_data"]
    assert [s for s in before if "gen_video_status" in s["data"] and "when" not in s] == []
    assert all(s["when"]["value"] == ["denied", "expired", "stale"] for s in before if "gen_video_status" in s["data"])  # only a refusal
    for slug in (MAKE, REQUEUE, FAILED):
        assert not any("status" in s["data"] for s in _writes(slug)), slug  # a beat's Status is its still's


# ── the paid call and its two questions ──────────────────────────────────────────────────────────────────────────────
def test_the_call_follows_a_spend_question_with_the_still_its_words_and_its_length():
    acts = _flow(MAKE)["actions"]
    kinds = [s["kind"] for s in acts]
    assert kinds == ["parallel", "approval", "entry", "integration", "entry", "approval", "parallel"]
    assert len(acts) <= 10 and all(sum(len(b["steps"]) for b in s["branches"]) <= 10 for s in acts if s["kind"] == "parallel")
    spend = _step(MAKE, "spend")
    assert "approved_when" not in spend and spend["image"] == "${steps.look.output.branches.still.output.rows.0.url}"  # a URL, not an id
    assert [f["name"] for f in spend["fields"]] == ["prompt", "seconds"]
    assert spend["fields"][1]["value"] == '${entry.data.gen_video_seconds|default:"6"}'
    assert "in place of any overlay" in spend["message"] and "a guess" in spend["message"] and "Pro plan" in spend["message"]
    refused = acts[2]
    assert refused["when"] == {"field": "steps.spend.output.decision", "op": "in", "value": ["denied", "expired", "stale"]}  # stale as denied
    assert refused["data"]["gen_video_status"] == "draft"
    make = _step(MAKE, "make")
    approved = {"field": "steps.spend.output.decision", "op": "eq", "value": "approved"}
    assert (make["integration"], make["action"], make["source"], make["when"]) == ("elevenlabs", "make_video", "${entry.data.still}", approved)
    args = make["args"]
    assert args["prompt"] == "${steps.spend.output.fields.prompt}" and args["duration_seconds"] == "${steps.spend.output.fields.seconds}"
    assert (args["model_id"], args["resolution"], args["generate_audio"]) == ("veo-3.1-fast-generate-001", "720p", False)  # the estimate reads them
    assert all(s.get("when") == approved for s in acts[3:])  # a refused question runs nothing after it


def test_the_film_shape_picks_the_videos_shape():
    shape = _step(MAKE, "make")["args"]["aspect_ratio"]
    for fmt, want in (("wide-16x9", "16:9"), ("short-9x16", "9:16"), ("portrait-4x5", "4:5"), ("square-1x1", "1:1")):
        assert f'"{fmt}","{want}"' in shape
    assert shape.endswith('|default:"9:16"}')  # a story with no shape is a tall Short, as its stills are


def test_the_length_made_is_written_back_and_the_keep_question_plays_the_video():
    ready = _flow(MAKE)["actions"][4]
    assert ready["data"] == {"gen_video_seconds": "${steps.make.output.duration_seconds|round|trim}", "gen_video_status": "ready", "gen_video_note": ""}
    keep = _step(MAKE, "keep")
    assert keep["image"] == "${steps.make.output.asset.url}" and keep["choices"] == ["Keep", "Redo"] and keep["redo"] == "Redo"
    assert [f["name"] for f in keep["fields"]] == ["prompt", "seconds"]  # Redo with changes carries both to the next question
    assert "REPLACES any overlay" in keep["message"] and "Overlay before the moving shot" in keep["message"]


def test_keep_makes_it_the_overlay_played_once_and_remembers_the_one_it_replaced_first():
    answer = _flow(MAKE)["actions"][6]
    assert [b["name"] for b in answer["branches"]] == ["remember", "keep", "redo", "not_kept"]  # remember runs before keep writes
    (remember,) = answer["branches"][0]["steps"]
    assert remember["data"] == {"gen_video_previous_overlay": "${entry.data.overlay}"}
    assert {"field": "entry.data.overlay", "op": "neq", "value": "${entry.data.gen_video}"} in remember["when"]  # a second Keep keeps the first one's
    (keep,) = answer["branches"][1]["steps"]
    assert keep["when"] == {"field": "steps.keep.output.choice", "op": "eq", "value": "Keep"}
    data = keep["data"]
    assert data["overlay"] == data["gen_video"] == "${steps.make.output.asset.id}"
    assert (data["overlay_play"], data["overlay_blend"], data["overlay_opacity"], data["overlay_fade"], data["overlay_delay"]) == ("once", "normal", 1, 0, 0)
    assert data["gen_video_status"] == "kept"
    (redo,) = answer["branches"][2]["steps"]
    assert redo["data"] == {"gen_video_status": "redo"}
    (not_kept,) = answer["branches"][3]["steps"]
    assert {"field": "entry.data.gen_video_status", "op": "eq", "value": "ready"} in not_kept["when"]  # queued again since: left alone


def test_every_choice_written_is_one_the_field_offers():
    by = _beat_fields()
    for slug in (MAKE, REQUEUE, FAILED):
        for step in _writes(slug):
            for key, value in step["data"].items():
                if by[key]["type"] == "select" and "${" not in str(value):
                    assert value in by[key]["options"], (slug, key, value)


def test_a_redo_is_queued_again_by_a_workflow_of_its_own():
    flow = _flow(REQUEUE)
    assert flow["conditions"] == [{"field": "entry.entry_type", "op": "eq", "value": "beat"}, {"field": "entry.data.gen_video_status", "op": "changed_to", "value": "redo"}]
    wait, now, queue = flow["actions"]
    assert wait == {"kind": "wait", "for": "2m"} and queue["data"] == {"gen_video_status": "queued"}
    assert queue["when"] == {"field": "steps.now.output.rows.0.data.gen_video_status", "op": "eq", "value": "redo"}


def test_a_failure_is_written_by_an_on_error_workflow_so_a_clip_still_being_made_is_checked_again():
    """A workflow with on_failure steps runs without the integration's error policy (Marvin: engine._error_mode), so `still_generating`
    would fail at once instead of being checked again. The make workflow has none; this one writes the reason."""
    assert "on_failure" not in _flow(MAKE)
    flow = _flow(FAILED)
    assert flow["trigger"] == {"type": "on_error", "automation": MAKE}
    first, gave_up = flow["actions"]
    assert first["entity_id"] == gave_up["entity_id"] == "${event.trigger_entity_id}"
    assert first["data"]["gen_video_status"] == gave_up["data"]["gen_video_status"] == "failed"
    assert first["data"]["gen_video_note"] == '${event.error|replace:"elevenlabs.make_video failed: ",""}'
    assert "instead of paying for another" in gave_up["data"]["gen_video_note"]


# ── the button ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_make_a_moving_shot_is_on_the_cards_of_the_beats_that_have_a_still():
    wizard = BLUEPRINTS["moving-shots"]["payload"]
    assert wizard["button"] == {"entry_type": "story", "label": "Moving shots", "key": "story", "step": "shots"}
    shots = next(s for s in wizard["steps"] if s["id"] == "shots")
    assert (shots["kind"], shots["entry_type"], shots["parent_field"], shots["where"]) == ("gallery", "beat", "story", [{"field": "still", "op": "exists"}])
    assert shots["approve"] == [MAKE]  # its questions are asked on the step
    (button,) = shots["card_actions"]
    assert button["label"] == "Make a moving shot" and button["set"] == {"gen_video_status": "queued"}
    assert button["when"] == {"field": "gen_video_status", "op": "neq", "value": "queued"}  # not while one is asked for
    assert button["paid"]["service"] == "ElevenLabs" and button["paid"]["sends"] == ["gen_video_prompt", "gen_video_seconds"]


# ── with Marvin ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _beat_event(changed, after, data, entry_type="beat"):
    base = {"still": "still-1", "status": "approved", "gen_video_status": "queued"}
    return {
        "event": {"event_type": "entry_updated", "changed_fields": changed, "before": {}, "after": {"data": after}},
        "entry": {"entry_type": entry_type, "status": "draft", "data": {**base, **data}},
    }


def test_with_marvins_matcher_only_the_change_to_queued_starts_it():
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    conds = _flow(MAKE)["conditions"]
    queued = (["data.gen_video_status"], {"gen_video_status": "queued"})
    assert matcher.matches(conds, _beat_event(*queued, {}))
    assert not matcher.matches(conds, _beat_event(["data.direction"], {"direction": "closer"}, {}))  # an edit while it waits
    assert not matcher.matches(conds, _beat_event(*queued, {"gen_video_status": "draft"}))  # the retry after it was set back
    assert not matcher.matches(conds, _beat_event(*queued, {"still": ""}))
    assert not matcher.matches(conds, _beat_event(*queued, {"status": "queued"}))  # its still is being made
    assert not matcher.matches(conds, _beat_event(*queued, {"shows": "Plain card"}))
    assert not matcher.matches(conds, _beat_event(*queued, {}, "sound"))
    assert not matcher.matches(conds, _beat_event(["data.gen_video_status"], {"gen_video_status": "redo"}, {"gen_video_status": "redo"}))
    requeue = _flow(REQUEUE)["conditions"]
    assert matcher.matches(requeue, _beat_event(["data.gen_video_status"], {"gen_video_status": "redo"}, {"gen_video_status": "redo"}))
    assert not matcher.matches(requeue, _beat_event(*queued, {}))


def test_with_marvins_matcher_a_failure_is_written_unless_a_check_is_still_to_come():
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    errors = pytest.importorskip("marvin.services.integrations.errors")
    flow = _flow(FAILED)
    first, gave_up = flow["actions"]

    def ev(handled, handling):
        return {"event": {"handled": handled, "handling": handling, "trigger_entity_type": "entry", "error": "elevenlabs.make_video failed: x"}}

    row = type("Row", (), {"attempt": 0, "max_attempts": 8})()
    scheduled, used_up = errors._summary("ElevenLabs", ["retry"], row), errors._summary("ElevenLabs", ["exhausted"], row)
    assert "retries used up" in used_up  # the words the workflow looks for are Marvin's
    moderated, slow, last = ev(False, []), ev(True, [scheduled]), ev(True, [used_up])
    assert matcher.matches(flow["conditions"], moderated) and matcher.matches(first["when"], moderated) and not matcher.matches(gave_up["when"], moderated)
    assert not matcher.matches(flow["conditions"], slow)  # checked again later: it stays queued
    assert matcher.matches(flow["conditions"], last) and matcher.matches(gave_up["when"], last) and not matcher.matches(first["when"], last)
    assert matcher.interpolate(first["data"]["gen_video_note"], {"event": {"error": "elevenlabs.make_video failed: declined"}}) == "declined"


def test_with_marvin_the_workflows_and_the_setup_pass_its_own_checks():
    definition = pytest.importorskip("marvin.schemas.group.automation_definition")
    validation = pytest.importorskip("marvin.services.automation.validation")
    wizards = pytest.importorskip("marvin.services.blueprints.wizards")
    for slug in (MAKE, REQUEUE, FAILED):
        definition.AutomationDefinition.model_validate(_flow(slug))
        assert validation.validate_definition(_flow(slug)) == [], slug
    assert wizards.payload_problem(BLUEPRINTS["moving-shots"]["payload"], "moving-shots") is None
