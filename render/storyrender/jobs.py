"""The media kinds of job: what the Storyworld worker image adds to the generic base (`marvin-worker-base`). The image names this
module in WORKER_JOB_MODULES, so importing it registers them. Each is `(job, ctx) -> fields for the job's record`."""

from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import build, ffmpeg, manifest, marvin_pull


def story_of(job: dict) -> str:
    story = (job.get("args") or {}).get("story")
    if not isinstance(story, str) or not story.strip():
        raise JobError("this kind of job needs args.story (the story entry's slug)")
    return story.strip()


@job_kind("audio-cut")
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
    return {"result": {"audio": asset["id"], "seconds": result["seconds"], "timeline": result["timeline"]}, "log": note}
