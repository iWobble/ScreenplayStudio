"""The media kinds of job: what the Storyworld worker image adds to the generic base (`marvin-worker-base`). The image names this
module in WORKER_JOB_MODULES, so importing it registers them. Each is `(job, ctx) -> fields for the job's record`."""

import json
import urllib.request
from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import build, ffmpeg, filmstrip, manifest, marvin_pull, script, voices


def story_of(job: dict) -> str:
    story = (job.get("args") or {}).get("story")
    if not isinstance(story, str) or not story.strip():
        raise JobError("this kind of job needs args.story (the story entry's slug)")
    return story.strip()


@job_kind(
    "audio-cut",
    description="Stitch a story's recorded speech lines, sound effects and scene ambience into one mp3 with a timeline naming each line",
    inputs={"story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"}},
    produces=["audio/mpeg"],
    needs=["ffmpeg"],
)
def audio_cut(job: dict, ctx: Context) -> dict:
    """The recorded lines of a story stitched into one mp3, with a timeline naming each line (see `listen`)."""
    story, name = story_of(job), job["job"]
    pulled = marvin_pull.pull(story, ctx.work / "story", creds=ctx.creds)
    ctx.note(f"pulled {pulled['lines']} recorded lines in {pulled['shots']} shots")
    m = manifest.load(Path(pulled["manifest"]), probe=ffmpeg.duration, need_stills=False)
    result = build.listen(m, ctx.work / f"{name}.mp3")
    ctx.note(f"mixed the audio: {result['seconds']} s")
    asset = marvin_api.upload_asset(
        ctx.creds,
        Path(result["output"]),
        slug=f"{name}-audio",
        name=f"Audio cut of {story} ({name})",
        mime="audio/mpeg",
        description=f"The recorded lines of {story}, stitched with the timing a render would have.",
        metadata={"seconds": result["seconds"], "lines": pulled["lines"], "kind": "audio-cut"},
    )
    note = f"{pulled['lines']} lines, {result['seconds']} s."
    if pulled["not_recorded"]:
        note += f" Not recorded yet, so left out: {', '.join(pulled['not_recorded'])}."
    return {"result": {"audio": asset["id"], "url": asset.get("publicUrl"), "seconds": result["seconds"], "timeline": result["timeline"], "ambience": result["ambience"]}, "log": note}


SCRIPT_FILES = {"fountain": "text/plain", "pdf": "application/pdf", "html": "text/html", "breakdown": "text/html"}


@job_kind(
    "script",
    description="Make a story's screenplay from its records: scene headings, action, voice-over and dialogue with directions, sound cues. A Fountain file, a PDF in Courier 12 and an HTML page, plus a breakdown page: who speaks and appears, where, which sounds",
    inputs={"story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"}},
    produces=list(dict.fromkeys(SCRIPT_FILES.values())),
    needs=["screenplain"],
)
def make_script(job: dict, ctx: Context) -> dict:
    """The story's records as a screenplay, kept as assets and named on the story (`script_fountain`, `script_pdf`, `script_html`)."""
    story, name = story_of(job), job["job"]
    try:
        records = script.pull_records(story, ctx.creds)
    except LookupError as e:
        raise JobError(str(e)) from e
    title = records["story"].get("title") or story
    ctx.note(f"read {len(records['beats'])} beats")
    made = script.render(script.fountain(records), ctx.work / "script", story)
    made["breakdown"] = ctx.work / "script" / f"{story}-breakdown.html"
    made["breakdown"].write_text(script.breakdown_html(script.breakdown(records)), encoding="utf-8")
    assets = {
        kind: marvin_api.upload_asset(
            ctx.creds,
            made[kind],
            slug=f"{name}-script-{kind}",
            name=f"{title}: script ({kind})",
            mime=mime,
            description=f"The screenplay of {title}, made from its records.",
            metadata={"kind": "script", "story": story, "format": kind},
        )
        for kind, mime in SCRIPT_FILES.items()
    }
    before = {kind: (records["story"].get("dataJson") or {}).get(f"script_{kind}") for kind in assets}
    marvin_api.update_entry(ctx.creds, story, {f"script_{kind}": asset["id"] for kind, asset in assets.items()})
    for kind, old in before.items():  # the script is made from the records, so the last copy is not kept: it goes to the Trash (restorable), not piled up beside the new one
        if old and old != assets[kind]["id"]:
            try:
                marvin_api.request(ctx.creds, f"/api/platform/assets/{old}", method="DELETE")
            except marvin_api.MarvinError:
                pass  # an old copy that cannot be trashed must not fail a script that was made
    pages = {"pdf": made["pdf"].name}
    return {
        "result": {**{kind: asset["id"] for kind, asset in assets.items()}, "urls": {kind: asset.get("publicUrl") for kind, asset in assets.items()}, "beats": len(records["beats"])},
        "log": f"{len(records['beats'])} beats, written as {', '.join(SCRIPT_FILES)}. {pages['pdf']} is the one to share.",
    }


@job_kind(
    "filmstrip",
    description="Make a story's filmstrip to review before rendering: one page that plays the story's sound while it shows each beat's still, moved as the render will move it, with captions and a strip to jump along",
    inputs={"story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"}},
    produces=["text/html"],
    needs=["ffmpeg"],
)
def make_filmstrip(job: dict, ctx: Context) -> dict:
    """The story's recorded lines and stills as a page to watch, kept on the story as `filmstrip`; the old one goes to the Trash."""
    story, name = story_of(job), job["job"]
    pulled = marvin_pull.pull(story, ctx.work / "story", creds=ctx.creds)
    ctx.note(f"pulled {pulled['shots']} shots, {pulled['lines']} recorded lines")
    m = manifest.load(Path(pulled["manifest"]), probe=ffmpeg.duration)  # stills are needed: a beat with none is named, not skipped
    made = filmstrip.make(m, ctx.work / "filmstrip")
    ctx.note(f"mixed the sound and built the page: {made['seconds']} s, {made['shots']} shots")
    title = m.title or story
    asset = marvin_api.upload_asset(
        ctx.creds,
        made["html"],
        slug=f"{name}-filmstrip",
        name=f"{title}: filmstrip",
        mime="text/html",
        description=f"The filmstrip of {title}: its sound with each beat's still, as the render will cut it. Open it in its own tab to play it.",
        metadata={"kind": "filmstrip", "story": story, "seconds": made["seconds"], "shots": made["shots"]},
    )
    rows = marvin_pull.marvin_api.entries(ctx.creds)
    before = next(((e.get("dataJson") or {}).get("filmstrip") for e in rows if e.get("slug") == story), None)
    marvin_api.update_entry(ctx.creds, story, {"filmstrip": asset["id"]})
    if before and before != asset["id"]:
        try:
            marvin_api.request(ctx.creds, f"/api/platform/assets/{before}", method="DELETE")
        except marvin_api.MarvinError:
            pass  # an old copy that cannot be trashed must not fail a filmstrip that was made
    note = f"{made['shots']} shots, {made['seconds']} s. Open the filmstrip asset in its own tab (Open Raw) to play it."
    if pulled["not_recorded"]:
        note += f" Not recorded yet, so left out: {', '.join(pulled['not_recorded'])}."
    return {"result": {"filmstrip": asset["id"], "url": asset.get("publicUrl"), "seconds": made["seconds"], "shots": made["shots"]}, "log": note}


@job_kind(
    "import-voices",
    description="Bring the voices on the workspace's ElevenLabs key into Marvin as voice records, with a preview clip to hear and the labels (gender, age, accent, style) as tags. Voices already imported are left alone",
    inputs={"search": {"type": "string", "required": False, "description": "only voices whose name or labels match this (leave blank for all)"}},
    produces=["audio/mpeg"],
)
def import_voices(job: dict, ctx: Context) -> dict:
    """New ElevenLabs voices → `voice` records (create only, matched by ElevenLabs voice id, so running it again adds just the new ones)."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    term = voices.search_term(args.get("search"))
    asked = {"limit": 100, **({"search": term} if term else {})}
    out = ctx.marvin("platform", "integrations", "run", "elevenlabs", "list_voices", "--data", json.dumps(asked))
    listed = ((out or {}).get("result") or out or {}).get("voices") or []
    ctx.note(f"{len(listed)} voices on the key")
    rows = marvin_api.entries(ctx.creds)
    known = {str((e.get("dataJson") or {}).get("elevenlabs_voice_id")) for e in rows if (e.get("dataJson") or {}).get("elevenlabs_voice_id")}
    taken = {e.get("slug") for e in rows}
    type_id = next((t["id"] for t in json.loads(marvin_api.request(ctx.creds, "/api/platform/entry-types")) if t.get("slug") == "voice"), None)
    if type_id is None:
        raise JobError("this workspace has no “voice” entry type: install the Screenplay Studio package first")
    tag_ids: dict[str, str] = {}
    made: list[str] = []
    for v in voices.new_voices(listed, known):
        slug = voices.slug_for(v.get("name") or "", taken)
        taken.add(slug)
        data = {"elevenlabs_voice_id": v["voice_id"], "category": v.get("category") or "", "language": (v.get("labels") or {}).get("language") or ""}
        if v.get("preview_url"):  # ElevenLabs' own sample clip of the voice; the file keeps its .mp3 name so Marvin types it as audio
            clip = ctx.work / f"{v['voice_id']}.mp3"
            req = urllib.request.Request(v["preview_url"], headers={"User-Agent": marvin_api.USER_AGENT})
            clip.write_bytes(urllib.request.urlopen(req, timeout=60).read())  # noqa: S310 — an https address ElevenLabs gave us
            asset = marvin_api.upload_asset(ctx.creds, clip, slug=f"{slug}-clip", name=f"{voices.short_name(v.get('name') or '')} (voice preview)", mime="audio/mpeg", description=f"ElevenLabs' preview clip of the voice {v.get('name')}.")
            data["preview"] = asset["id"]
        body = {"entryTypeId": type_id, "title": v.get("name") or slug, "slug": slug, "status": "draft", "summary": voices.summary_for(v.get("labels")), "dataJson": {k: x for k, x in data.items() if x}}
        entry = json.loads(marvin_api.request(ctx.creds, "/api/platform/entries", method="POST", data=json.dumps(body).encode(), content_type="application/json"))
        for name in voices.tags_for(v.get("labels")):
            if name not in tag_ids:
                tag_ids[name] = str((ctx.marvin("platform", "tags", "create", "--name", name) or {}).get("id"))
            ctx.marvin("platform", "tags", "attach", tag_ids[name], "--entry", entry["id"])
        made.append(v.get("name") or slug)
    note = f"{len(made)} new voice(s): {', '.join(made)}." if made else "No new voices: everything on the key is already in Marvin."
    return {"result": {"listed": len(listed), "created": made, "already": len(listed) - len(made)}, "log": f"{len(listed)} voices on the key. {note}"}
