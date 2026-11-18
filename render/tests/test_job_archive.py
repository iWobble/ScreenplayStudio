"""A worker job that finishes leaves Drafts (v224): the package's `screenplay-archive-done-job` archives a job whose Status becomes done. A queued,
running or failed job stays a draft; an audio cut or a filmstrip is archived by its own workflow once its question is answered. Archiving sends
its own `entry_updated`, so every workflow that answers a finished job ignores an update that only moved the job's publish status: a finished
transcription makes its transcript once, and an audio cut or filmstrip asks its question once."""

import pytest

from tests.test_world_context import BLUEPRINTS

GUARD = {"not": {"field": "entry.status", "op": "changed"}}
DONE_JOB = "screenplay-archive-done-job"


def _flow(slug):
    return BLUEPRINTS[slug]["payload"]["definition"]


def _answers_a_finished_job(flow) -> bool:
    conds = flow.get("conditions") or []
    return flow["trigger"].get("event") == "entry_updated" and {"field": "entry.entry_type", "op": "eq", "value": "job"} in conds and any(
        c.get("field") == "entry.data.status" and c.get("value") == "done" for c in conds
    )


def test_a_finished_job_is_archived_by_a_package_workflow_that_only_archives():
    flow = _flow(DONE_JOB)
    assert BLUEPRINTS[DONE_JOB]["kind"] == "workflow"
    assert flow["trigger"] == {"type": "event", "event": "entry_updated"}
    assert flow["conditions"] == [
        {"field": "entry.entry_type", "op": "eq", "value": "job"},
        {"field": "entry.data.status", "op": "changed_to", "value": "done"},  # the moment it finishes, not every later write
        {"field": "entry.status", "op": "eq", "value": "draft"},  # never moves a job someone published, or one in the Trash
        {"not": {"field": "entry.data.kind", "op": "in", "value": ["audio-cut", "filmstrip"]}},  # these ask first: see below
    ]
    assert flow["actions"] == [{"kind": "entry", "op": "archive"}]  # the trigger's own job, nothing else


def test_a_job_that_asks_a_question_is_archived_by_its_own_workflow_once_the_question_is_answered():
    """Marvin settles an approval `stale` when its entry changed after it was asked (approvals.py, the entry's update_at), so archiving the job
    while its question waits would turn "Approve for rendering" into nothing. The two that ask archive the job as their last step instead."""
    for slug in ("screenplay-audio-cut-done", "screenplay-filmstrip-done"):
        acts = _flow(slug)["actions"]
        assert acts[0]["kind"] == "approval" and acts[-1] == {"kind": "entry", "op": "archive"} and "when" not in acts[-1], slug


def test_every_workflow_that_answers_a_finished_job_ignores_the_job_being_put_away():
    answering = [slug for slug, b in BLUEPRINTS.items() if b["kind"] == "workflow" and slug != DONE_JOB and _answers_a_finished_job(_flow(slug))]
    assert {"screenplay-audio-cut-done", "screenplay-filmstrip-done", "screenplay-make-transcript"} <= set(answering)
    for slug in answering:
        conds = _flow(slug)["conditions"]
        assert GUARD in conds or any(c.get("op") == "changed_to" and c.get("field") == "entry.data.status" for c in conds), slug


def _event(*, status="draft", data_status="done", changed=("data.status",), after=None, kind="audio-cut"):
    return {
        "event": {"event_type": "entry_updated", "changed_fields": list(changed), "before": {}, "after": after if after is not None else {"data": {"status": data_status}}},
        "entry": {"entry_type": "job", "status": status, "data": {"kind": kind, "status": data_status, "result": {"files": {"paragraphs": {"id": "p"}}}}, "metadata": {}},
    }


def test_with_marvins_matcher_finishing_fires_once_and_the_archive_echo_fires_nothing():
    """Marvin's own condition matcher (services/automation/matcher.py), when it can be imported: run where Marvin is."""
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    finished = _event(kind="render", changed=("data.status", "data.result", "data.log"))
    echo = _event(kind="render", status="archived", changed=("status",), after={"status": "archived"})
    assert matcher.matches(_flow(DONE_JOB)["conditions"], finished) and not matcher.matches(_flow(DONE_JOB)["conditions"], echo)
    for slug, kind in (("screenplay-audio-cut-done", "audio-cut"), ("screenplay-filmstrip-done", "filmstrip"), ("screenplay-make-transcript", "transcribe")):
        conds = _flow(slug)["conditions"]
        assert matcher.matches(conds, _event(kind=kind)), slug
        assert matcher.matches(conds, _event(kind=kind, status="archived")), slug  # the archive ran first: the job's own event still answers
        assert not matcher.matches(conds, _event(kind=kind, status="archived", changed=("status",), after={"status": "archived"})), slug
    for asks in ("audio-cut", "filmstrip"):
        assert not matcher.matches(_flow(DONE_JOB)["conditions"], _event(kind=asks)), asks
    for still_working in ("queued", "running", "failed"):
        assert not matcher.matches(_flow(DONE_JOB)["conditions"], _event(kind="render", data_status=still_working)), still_working
