"""The media kinds of job: what the Storyworld worker image adds to the generic base (`marvin-worker-base`). The image names this
module in WORKER_JOB_MODULES, so importing it registers them. Each is `(job, ctx) -> fields for the job's record`."""

from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import build, ffmpeg, manifest, marvin_pull, script


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
    m = manifest.load(Path(pulled["manifest"]), probe=ffmpeg.duration, need_stills=False)
    result = build.listen(m, ctx.work / f"{name}.mp3")
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
