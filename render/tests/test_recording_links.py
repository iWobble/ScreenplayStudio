"""v233 (Media design P8): a beat, take, sound and speech line name the Recording of their file (`recording`, kept by the Media package's
worker), and the `screenplay-link-*` workflows ask Media's `media-link` to keep it and copy the Recording's facts into the fields Studio has
always kept them in (the mirror, MarvinMedia's mediajobs/mirror.py). Every one needs the Recording type (Media) and arrives switched off: the
older describe and measure workflows stay, and switching over is a flip by hand (P9 to P12).

Retriggering, through Marvin's own condition matcher (run where Marvin is; skipped elsewhere): a link workflow starts on its file changing,
on a new entry with a file, or on the entry leaving the queue with a file; never on the worker's own writes (the Recording and the mirrored
facts), nor on a title, archive or publish change. And no other Studio workflow starts on those writes, except the take's length reaching
its line (intended) and the workflows that wait on a queued entry, which is why the worker never writes a queued one (MarvinMedia #6).

The renderer and the pull never read `recording` (test_unchanged_pull pins the pull with Recordings and refs present, in three shapes)."""

import json
from types import SimpleNamespace

import pytest

from tests.test_world_context import BLUEPRINTS

TYPES = ("beat", "take", "sound", "speech-line")
LINKS = {  # slug: (entry type, the field holding the file, the mirror map, transcribe)
    "screenplay-link-clip": ("beat", "clip", "beat-clip", True),
    "screenplay-link-clip-created": ("beat", "clip", "beat-clip", True),
    "screenplay-link-take": ("take", "audio", "take", False),
    "screenplay-link-take-created": ("take", "audio", "take", False),
    "screenplay-link-sound": ("sound", "audio", "sound", False),
    "screenplay-link-sound-created": ("sound", "audio", "sound", False),
    "screenplay-link-line": ("speech-line", "audio", "line", False),
}
# What media-link writes on each map (MarvinMedia mediajobs/mirror.py OWNED, m4), plus `recording` itself.
MIRRORED = {
    "beat-clip": ("clip_seconds", "clip_width", "clip_height", "clip_has_audio", "clip_poster", "clip_text", "clip_words"),
    "take": ("duration_seconds", "waveform", "peak_db", "format", "level_lufs", "noise_floor_db", "clipped", "lead_silence", "tail_silence"),
    "sound": ("level_db", "peak_db", "waveform", "duration_seconds"),
    "line": ("duration_seconds", "waveform"),
}
OLD = ("screenplay-describe-clip", "screenplay-describe-clip-created", "screenplay-measure-take", "screenplay-describe-take", "screenplay-measure-sound",
       "screenplay-measure-sound-created", "screenplay-measure-sound-level", "screenplay-measure-sound-level-created", "screenplay-make-waveform-sound-created",
       "screenplay-take-length")  # fmt: skip


def _fields(slug: str) -> dict:
    return {f["key"]: f for f in BLUEPRINTS[slug]["payload"]["schema_json"]["fields"]}


def _flow(slug: str) -> dict:
    return BLUEPRINTS[slug]["payload"]["definition"]


# ── the field ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", TYPES)
def test_each_type_names_its_recording_in_a_field_only_the_worker_fills(slug):
    field = _fields(slug)["recording"]
    assert {k: field[k] for k in ("label", "type", "ref", "readOnly")} == {"label": "Recording (kept by Media)", "type": "text", "ref": "recording", "readOnly": True}
    assert field["helpText"].startswith("Filled in for you: a worker keeps it") and "Nothing to edit" in field["helpText"]
    assert "required" not in field and "defaultValue" not in field  # optional: an entry without Media is whole without it


def test_the_field_sits_with_the_facts_it_stands_for():
    keys = [f["key"] for f in BLUEPRINTS["beat"]["payload"]["schema_json"]["fields"]]
    assert keys[keys.index("clip_words") + 1] == "recording" and _fields("beat")["recording"]["group"] == "Clip"
    for slug in ("take", "sound", "speech-line"):
        keys = [f["key"] for f in BLUEPRINTS[slug]["payload"]["schema_json"]["fields"]]
        assert keys[keys.index("waveform") + 1] == "recording" and _fields(slug)["recording"]["group"] == "Made by Marvin", slug


def test_the_types_are_schemas_marvin_accepts():
    schema = pytest.importorskip("marvin.schemas.platform.entry_type_schema")
    for slug in TYPES:
        schema.EntryTypeSchemaDefinition.model_validate(BLUEPRINTS[slug]["payload"]["schema_json"])


# ── the workflows ────────────────────────────────────────────────────────────
def test_the_link_workflows_are_new_need_medias_recording_type_and_arrive_switched_off():
    links = [slug for slug in BLUEPRINTS if slug.startswith("screenplay-link-")]
    assert links == list(LINKS)
    for slug in LINKS:
        b = BLUEPRINTS[slug]
        assert b["kind"] == "workflow" and b["requires"] == ["entry_type:recording"], slug
        assert "enabled" not in json.dumps(b) and b["description"].startswith(("Needs the Media package.", "A ")), slug
        assert "Arrives switched off" in b["description"], slug
    for slug in OLD:  # the older ones stay as they were: switching over is a flip by hand, and so is going back
        assert slug in BLUEPRINTS and BLUEPRINTS[slug]["requires"] == [], slug


@pytest.mark.parametrize("slug", list(LINKS))
def test_each_queues_media_link_for_its_entry_with_the_file_it_saw(slug):
    entry_type, field, mirror, transcribe = LINKS[slug]
    flow = _flow(slug)
    (act,) = flow["actions"]
    args = {"entry": "${entry.slug}", "field": field, "asset": f"${{entry.data.{field}}}", "mirror": mirror}
    if transcribe:
        args["transcribe"] = True
    assert act["kind"] == "entry" and act["op"] == "create" and act["entry_type"] == "job" and act["status"] == "draft"
    assert act["data"] == {"kind": "media-link", "args": args, "status": "queued"}
    assert flow["conditions"][0] == {"field": "entry.entry_type", "op": "eq", "value": entry_type}
    if slug.endswith("-created"):
        assert flow["trigger"] == {"type": "event", "event": "entry_created"}
        assert flow["conditions"][1:] == [{"field": f"entry.data.{field}", "op": "longer_than", "value": 0}]  # an empty text "exists" to the matcher
    else:
        assert flow["trigger"] == {"type": "event", "event": "entry_updated"}
        assert flow["conditions"][1:] == [{"any": [
            {"field": f"entry.data.{field}", "op": "changed"},
            {"all": [{"field": "entry.data.status", "op": "changed_from", "value": "queued"}, {"field": f"entry.data.{field}", "op": "longer_than", "value": 0}]},
        ]}]  # fmt: skip


def test_the_link_workflows_pass_marvins_own_checks():
    validation = pytest.importorskip("marvin.services.automation.validation")
    for slug in LINKS:
        assert validation.structural_issues(_flow(slug)) == [], slug
        assert validation.validate_definition(_flow(slug)) == [], slug


# ── what starts them, through Marvin's matcher ──────────────────────────────
def _updated(entry_type: str, old: dict, new: dict, *, status=("draft", "draft"), title=("Beat 4", "Beat 4")) -> dict:
    """The context Marvin's engine gives a workflow for one write: the diff from Marvin's own entry_service._diff (only the changed fields)
    and the entry as it is after the write."""
    entry_service = pytest.importorskip("marvin.services.entries.entry_service")
    before = SimpleNamespace(status=status[0], title=title[0], slug="e1", data_json=old)
    after = SimpleNamespace(status=status[1], title=title[1], slug="e1", data_json=new)
    changed, was, now = entry_service._diff(before, after)
    return {"event": {"event_type": "entry_updated", "changed_fields": changed, "before": was, "after": now},
            "entry": {"entry_type": entry_type, "status": status[1], "title": title[1], "slug": "e1", "data": new, "metadata": {}}}  # fmt: skip


def _mirror_write(mirror: str, data: dict) -> dict:
    """The entry after media-link's write: its Recording named and every mirrored fact changed."""
    return {**data, "recording": "rec-new", **{k: f"new-{k}" for k in MIRRORED[mirror]}}


def _created(entry_type: str, data: dict) -> dict:
    return {"event": {"event_type": "entry_created"}, "entry": {"entry_type": entry_type, "status": "draft", "data": data}}


@pytest.mark.parametrize("slug", [s for s in LINKS if not s.endswith("-created")])
def test_a_change_of_the_file_or_leaving_the_queue_with_one_starts_it_and_the_workers_writes_never_do(slug):
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    entry_type, field, mirror, _ = LINKS[slug]
    conds = _flow(slug)["conditions"]
    data = {field: "file-2", "status": "draft"}
    assert matcher.matches(conds, _updated(entry_type, {**data, field: "file-1"}, data))
    assert matcher.matches(conds, _updated(entry_type, data, {**data, field: None}))  # emptied: the job empties the facts
    assert matcher.matches(conds, _updated(entry_type, {**data, "status": "queued"}, {**data, "status": "made"}))
    assert not matcher.matches(conds, _updated(entry_type, {field: "", "status": "queued"}, {field: "", "status": "draft"}))
    assert not matcher.matches(conds, _updated(entry_type, data, {**data, "status": "queued"}))
    for status in ("draft", "queued", "recorded", "in_use", "made", "approved", "redo"):
        now = {**data, "status": status}
        assert not matcher.matches(conds, _updated(entry_type, now, _mirror_write(mirror, now))), (slug, status)
        assert not matcher.matches(conds, _updated(entry_type, now, now, title=("Beat 4", "Beat four"), status=("draft", "archived")))  # a title, an archive
    assert not matcher.matches(conds, _updated("story", {**data, field: "file-1"}, data))


@pytest.mark.parametrize("slug", [s for s in LINKS if s.endswith("-created")])
def test_a_new_entry_with_a_file_starts_it_and_one_without_does_not(slug):
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    entry_type, field, _, _ = LINKS[slug]
    conds = _flow(slug)["conditions"]
    assert matcher.matches(conds, _created(entry_type, {field: "file-1"}))
    for empty in ({field: ""}, {field: None}, {}):
        assert not matcher.matches(conds, _created(entry_type, empty)), empty


def test_the_job_is_told_the_file_the_entry_held_and_an_emptied_one_as_nothing():
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    (act,) = _flow("screenplay-link-clip")["actions"]
    ctx = {"entry": {"slug": "b04", "title": "Beat 4", "data": {"clip": "0c11b0a1-0000-4000-8000-000000000001"}}}
    assert matcher.interpolate(act["data"]["args"], ctx) == {"entry": "b04", "field": "clip", "asset": "0c11b0a1-0000-4000-8000-000000000001", "mirror": "beat-clip", "transcribe": True}
    assert matcher.interpolate(act["data"]["args"], {"entry": {"slug": "b04", "data": {}}})["asset"] in (None, "")  # media-link: empty both ways
    assert matcher.interpolate(act["title"], ctx) == "Link the clip: Beat 4"


@pytest.mark.parametrize("mirror", list(MIRRORED))
def test_no_other_studio_workflow_starts_on_the_workers_writes_unless_the_entry_is_queued(mirror):
    """Every entry_updated workflow in the package, with the mirror's write (the Recording and every mirrored fact changed at once), for every
    status, source and kind the type allows: only the take's length reaching its line (intended), and the workflows that wait on a queued
    entry (make a still, a sound, a take), which Media's worker never writes for that reason."""
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    entry_type = {"beat-clip": "beat", "take": "take", "sound": "sound", "line": "speech-line"}[mirror]
    fields = _fields(entry_type)
    options = {k: [o["value"] if isinstance(o, dict) else o for o in fields[k].get("options", [])] or [None] for k in ("status", "source", "kind") if k in fields}
    hits: set[tuple[str, str]] = set()
    for status in options.get("status", [None]):
        for source in options.get("source", [None]):
            for kind in options.get("kind", [None]):
                data = {"status": status, "source": source, "kind": kind, "clip": "c", "audio": "a", "line": "l", "story": "s", "speaker": "S",
                        "voice": "v", "character": "c", "text": "t", "spoken": "t", "delivery_text": "", "duration_seconds": 3, "shows": "Still"}  # fmt: skip
                for slug, b in BLUEPRINTS.items():
                    flow = (b["payload"].get("definition") or {}) if b["kind"] == "workflow" else {}
                    if (flow.get("trigger") or {}).get("event") == "entry_updated" and matcher.matches(flow.get("conditions") or [], _updated(entry_type, data, _mirror_write(mirror, data))):
                        hits.add((slug, status))
    allowed_queued = {"screenplay-take-still", "screenplay-take-sound", "screenplay-take-music", "screenplay-own-sound", "screenplay-take-line"}
    assert {h for h in hits if h[1] != "queued"} == ({("screenplay-take-length", "in_use")} if mirror == "take" else set())
    assert {slug for slug, status in hits if status == "queued"} <= allowed_queued
