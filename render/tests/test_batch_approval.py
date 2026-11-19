"""A batch of stills or sounds (v206): Marvin runs an approval-gated call (an image, a sound effect) only in a run a person approved at one of its
own Approval steps; an approval that `approved_when` passes is nobody's approval and lets nothing paid run. So every paid call of the package is
behind an approval a person answers in the same run, and a batch only queues and leaves out the Keep question."""

import pytest

from tests.test_world_context import BLUEPRINTS

PAID = {("openai_images", "edit"), ("openai_images", "generate"), ("elevenlabs", "sound_effect"), ("elevenlabs", "music"), ("elevenlabs", "synthesize"), ("elevenlabs", "dialogue"), ("elevenlabs", "make_video")}


def _workflows():
    return {slug: b["payload"]["definition"] for slug, b in BLUEPRINTS.items() if b["kind"] == "workflow"}


def test_no_paid_call_follows_an_approval_that_a_condition_answers():
    for slug, flow in _workflows().items():
        acts = flow.get("actions") or []
        for at, step in enumerate(acts):
            if step.get("kind") == "integration" and (step.get("integration"), step.get("action")) in PAID:
                asked = [a for a in acts[:at] if a.get("kind") == "approval"]
                assert asked, (slug, step.get("id"))
                assert not any("approved_when" in a for a in asked), (slug, step.get("id"))  # nobody's approval: Marvin refuses the call


def test_a_batch_queues_with_one_question_and_says_each_item_asks_its_own_go_ahead():
    for batch, noun in (("screenplay-make-stills", "still"), ("screenplay-make-sounds", "sound")):
        flow = _workflows()[batch]
        spend = next(a for a in flow["actions"] if a.get("id") == "spend")
        assert f"Each {noun} then asks for its own go-ahead in Approvals before it spends" in spend["message"] and "Approve all" in spend["message"]
        assert "nothing more is asked" not in spend["message"] and "nothing more is asked" not in BLUEPRINTS[batch]["description"]
        queue = next(a for a in flow["actions"] if a.get("kind") == "repeat")
        assert queue["steps"][0]["data"] == {"status": "queued", "spend_approved": "yes"}  # the flag now means: no Keep question


def test_with_marvin_an_approved_when_is_not_a_persons_approval_and_the_still_asks_and_runs_once_approved():
    """Marvin's own approval step and guard (services/automation), when they can be imported: run where Marvin is."""
    approval = pytest.importorskip("marvin.services.automation.actions.approval")
    integration = pytest.importorskip("marvin.services.automation.actions.integration")
    from marvin.services.automation.approvals import auto_approved

    out = auto_approved([], None)
    assert out["approved"] is True and out["auto"] is True
    assert integration.approved_in_run({"steps": {"spend": {"output": out}}}) is False  # what the batch relied on: Marvin refuses the call
    assert integration.approved_in_run({"_approved": True}) is True  # a run resumed after a person approved its spend step
    spend = next(a for a in _workflows()["screenplay-take-still"]["actions"] if a.get("id") == "spend")
    context = {"entry": {"data": {"spend_approved": "yes"}}}
    assert not (spend.get("approved_when") and approval._holds(spend["approved_when"], context))  # the batch's beat is asked, not passed
    keep = next(a for a in _workflows()["screenplay-take-still"]["actions"] if a.get("id") == "keep")
    assert approval._holds(keep["when"], {"entry": {"data": {"spend_approved": "no"}}}) and not approval._holds(keep["when"], context)
