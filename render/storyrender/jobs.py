"""The media kinds of job: what the Storyworld worker image adds to the generic base (`marvin-worker-base`). The image names this
module in WORKER_JOB_MODULES, so importing it registers them. Each is `(job, ctx) -> fields for the job's record`."""

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
import urllib.request
from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import audio_convert, audio_measure, beat_import, build, captions, cards, chapters, ffmpeg, filmstrip, formats, fountain, manifest, marvin_pull, numbering, ready, script, validate, voices, waveform


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
    done = {"audio": asset["id"], "url": asset.get("publicUrl"), "seconds": result["seconds"], "timeline": result["timeline"], "ambience": result["ambience"]}
    listing, problems = chapters.youtube(chapters.markers(m))
    if listing:  # a story cut into chapters: the lines for the video description, and what would stop YouTube using them
        done["chapters"] = listing
        note += f" {len(listing.splitlines())} chapter markers." + "".join(f" {p}" for p in problems)
    return {"result": done, "log": note}


@job_kind(
    "convert-audio",
    description="Turn a recording held in an entry's audio field (a browser's webm or ogg) into an mp3 or m4a that plays anywhere, and point the field at the new file; the original stays in the library",
    inputs={
        "entry": {"type": "string", "description": "the entry's slug, e.g. the actor or the speech line holding the recording"},
        "field": {"type": "string", "description": "the field holding the recording, e.g. voice_sample or audio"},
        "format": {"type": "string", "required": False, "description": "mp3 (the default) or m4a"},
    },
    produces=["audio/mpeg", "audio/mp4"],
    needs=["ffmpeg"],
)
def convert_audio(job: dict, ctx: Context) -> dict:
    """A recording in an entry's asset field → mp3 or m4a; the field points at the new asset. A file already in that format is left alone."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug, field = str(args.get("entry") or "").strip(), str(args.get("field") or "").strip()
    if not slug or not field:
        raise JobError("this kind of job needs args.entry (the entry's slug) and args.field (the field holding the recording)")
    try:
        fmt = audio_convert.format_of(args.get("format"))
    except audio_convert.ConvertError as e:
        raise JobError(str(e)) from e
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    held = (row.get("dataJson") or row.get("data") or {}).get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    source = marvin_api.asset(ctx.creds, held)
    mime, name = source.get("mimeType"), source.get("name") or source.get("slug") or ""
    if audio_convert.is_already(mime, name, fmt):
        return {"result": {"entry": slug, "field": field, "format": fmt, "asset": source.get("id") or held, "converted": False}, "log": f"“{name}” is already {fmt}: nothing to do."}
    if not audio_convert.is_audio(mime, name):
        raise JobError(f"“{name}” ({mime or 'unknown type'}) is not a sound")
    ext = audio_convert.FORMATS[fmt][0]
    src = ctx.work / f"source{Path(name).suffix or '.bin'}"
    marvin_api.download_asset(ctx.creds, source.get("id") or held, src)
    out = ctx.work / f"converted{ext}"
    try:
        seconds = audio_convert.convert(src, out, fmt)
    except ffmpeg.FfmpegError as e:
        raise JobError(f"could not read “{name}” as sound: {e}") from e
    ctx.note(f"converted {name} to {fmt}: {seconds:.1f} s")
    base = f"{source.get('slug') or str(held)[:8]}-{fmt}"
    for attempt in range(1, 7):  # converting the same recording again (for another entry) finds the slug taken: number it
        try:
            asset = marvin_api.upload_asset(
                ctx.creds,
                out,
                slug=base if attempt == 1 else f"{base}-{attempt}",
                name=audio_convert.named(name, fmt),
                mime=audio_convert.FORMATS[fmt][1],
                description=f"{name}, converted to {fmt} for {slug}.",
                metadata={"seconds": round(seconds, 2), "kind": "converted-audio", "from": source.get("id") or held},
            )
            break
        except marvin_api.MarvinError as e:
            if "answered 409" not in str(e) or attempt == 6:
                raise
    marvin_api.update_entry(ctx.creds, slug, {field: asset["id"]})
    return {"result": {"entry": slug, "field": field, "format": fmt, "asset": asset["id"], "from": source.get("id") or held, "seconds": round(seconds, 2), "converted": True}, "log": f"{name} → {audio_convert.named(name, fmt)}, {seconds:.1f} s. “{field}” on {slug} now holds it; the original stays in the library."}


@job_kind(
    "measure-audio",
    description="Read how long the recording in an entry's audio field really is and write it to the entry (a browser's recording or an upload has no length stored anywhere else). Nothing is changed in the file",
    inputs={
        "entry": {"type": "string", "description": "the entry's slug, e.g. the take holding the recording"},
        "field": {"type": "string", "required": False, "description": "the field holding the recording (audio by default)"},
        "seconds_field": {"type": "string", "required": False, "description": "the number field the length is written to (duration_seconds by default)"},
    },
    produces=[],
    needs=["ffmpeg"],
)
def measure_audio(job: dict, ctx: Context) -> dict:
    """A recording in an entry's asset field → its length in seconds, written to the entry's number field."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug = str(args.get("entry") or "").strip()
    field = str(args.get("field") or "audio").strip()
    target = str(args.get("seconds_field") or "duration_seconds").strip()
    if not slug:
        raise JobError("this kind of job needs args.entry (the entry's slug)")
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    held = (row.get("dataJson") or row.get("data") or {}).get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    source = marvin_api.asset(ctx.creds, held)
    name = source.get("name") or source.get("slug") or "recording"
    if not audio_convert.is_audio(source.get("mimeType"), name):
        raise JobError(f"“{name}” ({source.get('mimeType') or 'unknown type'}) is not a sound")
    src = ctx.work / f"measure{Path(name).suffix or '.bin'}"
    marvin_api.download_asset(ctx.creds, source.get("id") or held, src)
    try:
        seconds = round(audio_measure.seconds(src), 3)
    except ffmpeg.FfmpegError as e:
        raise JobError(f"could not read “{name}” as sound: {e}") from e
    marvin_api.update_entry(ctx.creds, slug, {target: seconds})
    return {"result": {"entry": slug, "field": field, "seconds_field": target, "seconds": seconds}, "log": f"{name}: {seconds:.2f} s, written to {target} on {slug}"}


@job_kind(
    "measure-level",
    description="Listen to the recording in an entry's audio field and write how loud it is: its average level and its loudest moment, in dB below full scale (a quiet one reads about -40, a very loud one about -6). A sound's page draws them as meters beside its volume slider. Nothing is changed in the file.",
    inputs={
        "entry": {"type": "string", "description": "the entry's slug, e.g. the sound holding the recording"},
        "field": {"type": "string", "required": False, "description": "the field holding the recording (audio by default)"},
        "level_field": {"type": "string", "required": False, "description": "the number field the average level is written to (level_db by default)"},
        "peak_field": {"type": "string", "required": False, "description": "the number field the loudest moment is written to (peak_db by default)"},
    },
    produces=[],
    needs=["ffmpeg"],
)
def measure_level(job: dict, ctx: Context) -> dict:
    """A recording in an entry's asset field → its average level and peak in dB, written to the entry's two number fields."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug = str(args.get("entry") or "").strip()
    field = str(args.get("field") or "audio").strip()
    level_field = str(args.get("level_field") or "level_db").strip()
    peak_field = str(args.get("peak_field") or "peak_db").strip()
    if not slug:
        raise JobError("this kind of job needs args.entry (the entry's slug)")
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    held = (row.get("dataJson") or row.get("data") or {}).get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    source = marvin_api.asset(ctx.creds, held)
    name = source.get("name") or source.get("slug") or "recording"
    if not audio_convert.is_audio(source.get("mimeType"), name):
        raise JobError(f"“{name}” ({source.get('mimeType') or 'unknown type'}) is not a sound")
    src = ctx.work / f"level{Path(name).suffix or '.bin'}"
    marvin_api.download_asset(ctx.creds, source.get("id") or held, src)
    try:
        level, peak = audio_measure.levels(src)
    except ffmpeg.FfmpegError as e:
        raise JobError(f"could not read “{name}” as sound: {e}") from e
    marvin_api.update_entry(ctx.creds, slug, {level_field: level, peak_field: peak})
    return {"result": {"entry": slug, "field": field, "level_db": level, "peak_db": peak}, "log": f"{name}: average {level:.1f} dB, peak {peak:.1f} dB, written to {level_field} and {peak_field} on {slug}"}


@job_kind(
    "describe-audio",
    description="Listen to the recording in a take and write what it says about itself: its make (codec, rate, mono or stereo), how loud it sounds (LUFS, average level) and its loudest moment, the quietest stretch (its noise floor), whether it hit the ceiling, the silence before the first sound and after the last, and where it came from (recorded in the browser, uploaded or generated) when the take does not say. Nothing is changed in the file",
    inputs={
        "entry": {"type": "string", "description": "the entry's slug, e.g. the take holding the recording"},
        "field": {"type": "string", "required": False, "description": "the field holding the recording (audio by default)"},
    },
    produces=[],
    needs=["ffmpeg"],
)
def describe_audio(job: dict, ctx: Context) -> dict:
    """A recording in an entry's audio field → its make, loudness, peak, lead and tail silence and (when empty) its source, written to the entry."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug = str(args.get("entry") or "").strip()
    field = str(args.get("field") or "audio").strip()
    if not slug:
        raise JobError("this kind of job needs args.entry (the entry's slug)")
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    data = row.get("dataJson") or row.get("data") or {}
    held = data.get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    asset = marvin_api.asset(ctx.creds, held)
    name = asset.get("name") or asset.get("slug") or "recording"
    if not audio_convert.is_audio(asset.get("mimeType"), name):
        raise JobError(f"“{name}” ({asset.get('mimeType') or 'unknown type'}) is not a sound")
    src = ctx.work / f"describe{Path(name).suffix or '.bin'}"
    marvin_api.download_asset(ctx.creds, asset.get("id") or held, src)
    try:
        seconds = round(audio_measure.seconds(src), 3)
        lead, tail = audio_measure.silence_edges(src, seconds)
        heard = audio_measure.loudness(src)
        _mean, peak = audio_measure.levels(src)
        make = audio_measure.format_summary(audio_measure.probe_audio(src))
        spread = audio_measure.stats(src)
    except ffmpeg.FfmpegError as e:
        raise JobError(f"could not read “{name}” as sound: {e}") from e
    found: dict = {"format": make, "peak_db": peak, "lead_silence": lead, "tail_silence": tail}
    if spread:  # the average level, the quietest stretch (what a standard calls the noise floor) and whether the loudest moment hit the ceiling
        found.update(rms_db=spread["rms_db"], noise_floor_db=spread["noise_floor_db"], clipped="yes" if peak >= audio_measure.CLIP_DB else "no")
    if heard:
        found["level_lufs"] = heard[0]
    if not str(data.get("source") or "").strip():  # a take that says where it came from is believed; one that does not is told by its file
        found["source"] = audio_measure.source_of(asset.get("metadataJson"))
    marvin_api.update_entry(ctx.creds, slug, found)
    say = f"{name}: {make}; {found.get('level_lufs', '?')} LUFS, peak {peak:.1f} dB" + (f", noise floor {found['noise_floor_db']:.1f} dB" if "noise_floor_db" in found else "") + (", clipped" if found.get("clipped") == "yes" else "") + f"; {lead:g} s of silence before, {tail:g} s after" + (f"; source {found['source']}" if "source" in found else "")
    return {"result": {"entry": slug, "field": field, **found}, "log": say}


@job_kind(
    "make-waveform",
    description="Work out a recording's waveform and write it to the entry: the loudest and quietest point of each of 240 stretches, in the audiowaveform JSON format, so the Timeline can draw the take in its block. Nothing is changed in the file.",
    inputs={
        "entry": {"type": "string", "description": "the entry's slug, e.g. the sound or the line holding the recording"},
        "field": {"type": "string", "required": False, "description": "the field holding the recording (audio by default)"},
        "wave_field": {"type": "string", "required": False, "description": "the field the waveform is written to (waveform by default)"},
    },
    produces=[],
    needs=["ffmpeg"],
)
def make_waveform(job: dict, ctx: Context) -> dict:
    """A recording in an entry's asset field → its peaks, written to the entry's json field."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug = str(args.get("entry") or "").strip()
    field = str(args.get("field") or "audio").strip()
    target = str(args.get("wave_field") or "waveform").strip()
    if not slug:
        raise JobError("this kind of job needs args.entry (the entry's slug)")
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    held = (row.get("dataJson") or row.get("data") or {}).get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    source = marvin_api.asset(ctx.creds, held)
    name = source.get("name") or source.get("slug") or "recording"
    if not audio_convert.is_audio(source.get("mimeType"), name):
        raise JobError(f"“{name}” ({source.get('mimeType') or 'unknown type'}) is not a sound")
    src = ctx.work / f"wave{Path(name).suffix or '.bin'}"
    marvin_api.download_asset(ctx.creds, source.get("id") or held, src)
    try:
        wave = waveform.peaks(src)
    except ffmpeg.FfmpegError as e:
        raise JobError(f"could not read “{name}” as sound: {e}") from e
    marvin_api.update_entry(ctx.creds, slug, {target: wave})
    return {"result": {"entry": slug, "field": field, "wave_field": target, "points": wave["length"]}, "log": f"{name}: {wave['length']} peaks written to {target} on {slug}"}


SCRIPT_FILES = {"fountain": "text/plain", "pdf": "application/pdf", "html": "text/html", "breakdown": "text/html"}


@job_kind(
    "script",
    description="Make a story's screenplay from its records: scene headings, action, voice-over and dialogue with directions, sound cues. A Fountain file, a PDF in Courier 12 and an HTML page, plus a breakdown page: who speaks and appears, where, which sounds",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"},
        "version": {"type": "string", "required": False, "description": "production (default): a production script made from the records, with the beat numbers, sound cues and directions. written: the Fountain as it was written, made again from the text each beat kept of it (for a story made from Fountain). complete: every detail the records hold (title page, characters with costume and props, scenes with place, light and ambience, beats with hold, focus and sounds, lines with direction) as a Fountain that can be brought in again"},
    },
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
    version = str((job.get("args") or {}).get("version") or "production").strip().lower()
    if version not in ("production", "written", "complete"):
        raise JobError(f"version “{version}” is not production, written or complete")
    text = script.fountain_as_written(records) if version == "written" else script.fountain_complete(records) if version == "complete" else None
    if version == "written" and text is None:
        ctx.note("this story's beats hold no Fountain text of their own (it was not made from Fountain): made the production script instead")
    made = script.render(script.stamp_revision(text or script.fountain(records), records["story"]), ctx.work / "script", story)
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
    if pulled.get("skipped"):
        ctx.note(f"left out, because they have no words, no sound, no hold and no picture: beat {', '.join(pulled['skipped'])}")
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


def _all(creds, spec: dict, page: int = 200) -> list[dict]:
    """Every record matching a spec. Marvin answers a page at a time (and caps how many), so ask page after page until one comes back empty:
    a long script has more lines than any one answer holds, and a list that stops short would make the importer make the rest twice."""
    out: list[dict] = []
    for n in range(0, 5000):
        body = json.dumps({"spec": spec, "limit": page, "offset": n * page}).encode()
        rows = json.loads(marvin_api.request(creds, "/api/platform/entries/query", method="POST", data=body, content_type="application/json")).get("entries", [])
        if not rows:
            break
        out += rows
    return out


def parse_part(text) -> "set[int] | None":
    """`all` or empty -> None (every chapter); `3` -> {3}; `2-4` -> {2, 3, 4}; `1,3,5-6` -> a mix."""
    t = str(text or "").strip().lower()
    if t in ("", "all"):
        return None
    out: set[int] = set()
    for piece in t.split(","):
        lo, _, hi = piece.strip().partition("-")
        try:
            a, b = int(lo), int(hi or lo)
        except ValueError:
            raise JobError(f"part “{text}” is not a chapter number, a range like 2-4, or a list like 1,3,5") from None
        if b < a or a < 1:
            raise JobError(f"part “{text}” is not a chapter number, a range like 2-4, or a list like 1,3,5")
        out |= set(range(a, b + 1))
    return out


def _chapter_of(story: str, slug: str) -> "int | None":
    """The chapter a record belongs to, from its slug: `<story>-beat-3012` and `<story>-line-3012-1` are chapter 3, `<story>-chapter-03` is 3."""
    rest = slug[len(story) + 1 :] if slug.startswith(story + "-") else slug
    m = re.match(r"(?:beat|line)-(\d+)", rest)
    if m:
        return int(m.group(1)) // 1000
    m = re.match(r"chapter-(\d+)", rest)
    return int(m.group(1)) if m else None


def _story_records(creds, story: str) -> tuple[list[dict], list[dict], list[dict]]:
    """The story's chapters, beats and spoken lines as Marvin holds them now."""
    ask = lambda kind: _all(creds, {"entry_type": kind, "data": {"story": story}})  # noqa: E731
    return ask("chapter"), ask("beat"), ask("speech-line")


def _yes(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "y")


MAX_FOUNTAIN_BYTES = 20_000_000


def _fountain_text(ctx: Context, story: str, story_data: dict) -> tuple[str, str]:
    """The story's Fountain and where it came from: its `fountain` text, else the file in `fountain_file` (any size a file can be uploaded at). Both a text and a file is a mistake to say, not to guess at."""
    text, asset = str(story_data.get("fountain") or ""), str(story_data.get("fountain_file") or "").strip()
    if text.strip() and asset:
        raise JobError(f"{story} has Fountain text and an uploaded Fountain file: the text is the one to edit, so empty it to read the file, or remove the file to read the text")
    if text.strip():
        return text, f"{story}'s Fountain field"
    if asset:
        file = ctx.work / "fountain.txt"
        marvin_api.download_asset(ctx.creds, asset, file)
        if file.stat().st_size > MAX_FOUNTAIN_BYTES:
            raise JobError(f"the uploaded Fountain file is {file.stat().st_size // 1_000_000} MB: that is not a screenplay (20 MB at most)")
        return file.read_text(encoding="utf-8", errors="replace"), f"{story}'s uploaded Fountain file"
    raise JobError(f"nothing to read: {story} has no Fountain. Write or paste it in the story's Fountain field, or upload a .fountain file")


def _cast_for(story: str, beat: dict, characters: list[dict], people: dict, data: dict) -> dict:
    """What a beat is missing of its cast: the Characters in its picture (who speaks in it, who its action names), and the master pictures they go by.
    A beat that has a cast is left as it is, apart from the masters when it has no reference pictures yet; one that has reference pictures keeps them
    (a picture of the place, say) and gains the masters after them. A Character with no master yet adds only to the cast, and a later import fills the rest."""
    slugs = [str((people.get(h) or {}).get("slug") or f"{story}-{h}") for h in fountain.cast_of(beat, characters)]
    have_cast = [s.strip() for s in str(data.get("cast") or "").split(",") if s.strip()]
    out: dict = {}
    if slugs and not have_cast:
        out["cast"] = ",".join(slugs)
    present = have_cast or slugs
    held = _asset_refs(data.get("references"))  # a picker's list of assets, or the comma text an older beat holds
    if not have_cast or not held:
        by_slug = {str(e.get("slug")): e for e in people.values()}
        masters = [str((by_slug[s].get("dataJson") or {}).get("master") or "").strip() for s in present if s in by_slug]
        more = [m for m in masters if m and m not in held]
        if more:
            out["references"] = held + more  # a list: the field is an asset picker, so the masters show there beside any picture the person added
    return out


def _asset_refs(value: object) -> list[str]:
    """The assets in a reference field: its list, or an older beat's comma text, without blanks."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    return [str(x).strip() for x in items if str(x).strip()]


MAX_BEFORE_CHARS = 200_000  # a revision keeps the text it replaced up to this size (a long script is kept in its file)


def _setting_from(fplan) -> str:
    """Where a story is set, when its title page does not say: the first sentence of the first chapter's synopsis (`= The ship strikes the reef.`), else its first place with the
    time of day. Short and plain: the picture workflows read it as the story's setting, and it is the person's to rewrite."""
    first = next((c.summary for c in fplan.chapters if c.summary), "")
    if first:
        return re.split(r"(?<=[.!?])\s+", first.strip())[0]
    place = next(iter(fplan.places.values()), None)
    if not place:
        return ""
    where = " and ".join(place["kinds"])
    return f"{place['name']}" + (f" ({where})" if where else "") + (f", {', '.join(place['times'])}" if place["times"] else "")


def _story_gaps(story_data: dict) -> list[str]:
    """What a story still lacks that the picture workflows read, in words a person can act on."""
    asked = (("world", "no World: choose one, its rules and style decide how every picture looks"), ("setting", "no Setting: say where and when it happens (a `Setting:` line on the title page, or the Setting field)"),
             ("premise", "no Premise: one or two sentences saying what the story is about (a `Premise:` line on the title page, or the Premise field)"))
    return [why for key, why in asked if not str(story_data.get(key) or "").strip()]


def _character_slug(story: str, speaker: str, people: dict) -> str:
    """The Character a speaker is: the story's cast-member whose `speaker` is this handle, else the slug the import gives a Character it makes."""
    found = people.get(str(speaker).lower())
    return str(found["slug"]) if found and found.get("slug") else f"{story}-{str(speaker).lower()}"


def _people_fill(ctx: Context, story: str, fplan) -> list[tuple[dict, dict]]:
    """Characters made before they had Age, Sex and Age state as fields, given what the screenplay says of them. Only a field that is empty is
    filled (never one a person set), and only when the screenplay says it (a sex only when the pronouns or a word like boy or woman do)."""
    said = {c["handle"].lower(): c for c in fplan.characters}
    out: list[tuple[dict, dict]] = []
    for rec in _all(ctx.creds, {"entry_type": "cast-member", "data": {"story": story}}):
        data = rec.get("dataJson") or {}
        found = said.get(str(data.get("speaker") or "").lower())
        if not found:
            continue
        wanted = {"age": found["age"], "sex": found["sex"], "age_state": fountain.age_state(found["age"])}
        missing = {k: v for k, v in wanted.items() if v and not str(data.get(k) or "").strip()}
        if missing:
            out.append((rec, missing))
    return out


def _made_for_a_beat(story: str, slug: str) -> bool:
    """A Sound the import made for one beat's own words (`story-sound-1002-1`), as against a bed, a score or one that was uploaded."""
    return bool(re.fullmatch(rf"{re.escape(story)}-sound-\d+[a-z]*-\d+", slug))


def _implied(ctx: Context, story: str, story_row: dict, fplan, plan: dict, link: list, fresh: bool = False) -> list[tuple[str, tuple[str, str, dict]]]:
    """The characters and scenes a screenplay implies: a Character for each speaker, with what the screenplay says of them (name, age, sex, the sentences
    that introduce them), and a Scene for each place its headings name (inside or outside, the time of day), which the new beats are put in. One that
    exists is left as it is. Nothing is cast, dressed or lit: what the writer did not say is left empty."""
    out: list[tuple[str, tuple[str, str, dict]]] = []
    have_chars = {str((e.get("dataJson") or {}).get("speaker") or "").lower() for e in _all(ctx.creds, {"entry_type": "cast-member", "data": {"story": story}})}
    for c in fplan.characters:
        speaker = c["handle"].lower()
        if speaker in have_chars:
            continue
        who = {"female": "Woman", "male": "Man"}.get(c["sex"], "")
        role = ", ".join(x for x in (who, c["age"]) if x)
        role = f"{role}. {c['description']}" if role and c["description"] else (c["description"] or role)
        cast_id = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or speaker
        said = {"age": c["age"], "sex": c["sex"], "age_state": fountain.age_state(c["age"])}  # what the screenplay says of them, as fields (the empty ones left out)
        data = {"cast_id": cast_id, "role": role, "speaker": speaker, "story": story, "presence": "voice only" if re.search(r"narrat|announcer|^voice$", c["cue"], re.I) else "on screen", "status": "draft"}
        out.append(("cast-member", (f"{story}-{speaker}", c["name"], {**data, **{k: v for k, v in said.items() if v}})))
    want = {b[2]["scene"] for b in plan["beats"] if b[2].get("scene")} | {add["scene"] for _r, add in link if add.get("scene")}
    have_scenes = {e["slug"] for e in _all(ctx.creds, {"entry_type": "scene", "data": {"story": story}})}
    have_sounds = {e["slug"] for e in _all(ctx.creds, {"entry_type": "sound", "data": {"story": story}}) if not (fresh and _made_for_a_beat(story, e["slug"]))}
    new_numbers = {str(b[2].get("number")) for b in plan["beats"]} | {str((r.get("dataJson") or {}).get("number")) for r, add in link if add.get("sounds")}
    for _chapter, number, beat in fplan.rows():  # a Sound to click, upload to or generate for each sound the beat's words call for
        if number not in new_numbers:
            continue
        for i, cue in enumerate(beat.get("sounds") or [], 1):
            slug = f"{story}-sound-{number}-{i}"
            if slug not in have_sounds:
                out.append(("sound", (slug, cue["title"], {"story": story, "kind": cue["kind"], "prompt": cue["prompt"], "source": "generated", "status": "draft"})))
    score = f"{story}-score"
    if not str((story_row.get("dataJson") or {}).get("music") or "").strip() and score not in have_sounds:  # a placeholder for the music under the film: delete it if there is no score
        said = " ".join(c.summary for c in fplan.chapters if c.summary)
        out.append(("sound", (score, f"{story_row.get('title') or story} score", {"story": story, "kind": "music", "prompt": f"Background music for the film “{story_row.get('title') or story}”." + (f" What happens: {said}" if said else ""), "source": "generated", "loop": True, "status": "draft"})))
    for slug_key, place in fplan.places.items():
        slug = f"{story}-{slug_key}"
        if slug not in want or slug in have_scenes:
            continue
        kind = fountain.kind_of_places(place["kinds"])  # INT. / EXT. kept as a field of its own, not as words in the place
        data = {"story": story, "place": place["name"], "inside_outside": kind, "look": ", ".join(place["times"]), "status": "draft"}
        if kind == "interior":  # heard from inside: its own bed and the story's run on muffled, until someone unticks them
            data["ambience_muffled"] = True
            data["story_ambience_muffled"] = True
        bed = fplan.ambience.get(slug_key)
        if bed:  # the bed under the place: a Sound of its own, made once and named by the scene
            bed_slug = f"{story}-ambience-{slug_key}"
            data["ambience"] = bed_slug
            if bed_slug not in have_sounds:
                out.append(("sound", (bed_slug, bed["title"], {"story": story, "kind": "ambience", "prompt": bed["prompt"], "source": "generated", "loop": True, "status": "draft"})))
        out.append(("scene", (slug, place["name"], {k: v for k, v in data.items() if v not in ("", None)})))
    return out


def _made_from_the_text(ctx: Context, story: str) -> dict[str, list[dict]]:
    """Everything the current Fountain made for a story, by kind: its chapters, beats, spoken lines, the takes of those lines and the sounds made for single beats.
    Characters, scenes, ambience beds, the score and anything uploaded are not in it: they are the story's own, whatever the text says."""
    own = {"chapter": [], "beat": [], "speech-line": [], "take": [], "sound": []}
    for kind in ("chapter", "beat", "speech-line", "sound"):
        own[kind] = [e for e in _all(ctx.creds, {"entry_type": kind, "data": {"story": story}}) if kind != "sound" or _made_for_a_beat(story, e["slug"])]
    own["take"] = [e for e in _all(ctx.creds, {"entry_type": "take", "data": {"story": story}}) if str(e.get("slug") or "").startswith(f"{story}-line-")]
    return own


def _replace_note(made: dict[str, list[dict]]) -> str:
    counts = {k: len(v) for k, v in made.items()}
    return (
        f"REPLACE: applying this moves everything made from the current text to the Trash, where it can be restored ({counts['beat']} beats, {counts['speech-line']} lines, "
        f"{counts['take']} takes, {counts['sound']} sounds made for single beats and {counts['chapter']} chapters), and brings the revision in afresh, numbered from 1001. "
        "Characters, scenes, ambience beds, the score, masters and voices stay."
    )


def _retire(ctx: Context, made: dict[str, list[dict]], tag: str) -> int:
    """Move each record to the Trash under a slug of its own (`-before-rev2`): a trashed record still holds its slug, and the new beats need the same slugs."""
    done = 0
    for kind in ("take", "speech-line", "beat", "sound", "chapter"):
        for rec in made[kind]:
            body = json.dumps({"title": rec.get("title"), "slug": f"{rec['slug']}-{tag}", "dataJson": rec.get("dataJson") or {}}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="PATCH", data=body, content_type="application/json")
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="DELETE")
            done += 1
    return done


def _revision_text(ctx: Context, slug: str, row: dict) -> str:
    """The Fountain a revision record holds: its `proposed` text, else the file in its `file` field (up to the same 20 MB a story's file may be)."""
    d = row.get("dataJson") or {}
    text, asset = str(d.get("proposed") or ""), str(d.get("file") or "").strip()
    if text.strip() and asset:
        raise JobError(f"the revision {slug} has both text and a file: keep one")
    if text.strip():
        return text
    if asset:
        file = ctx.work / "revision.txt"
        marvin_api.download_asset(ctx.creds, asset, file)
        if file.stat().st_size > MAX_FOUNTAIN_BYTES:
            raise JobError(f"the revision's file is {file.stat().st_size // 1_000_000} MB: that is not a screenplay (20 MB at most)")
        return file.read_text(encoding="utf-8", errors="replace")
    raise JobError(f"the revision {slug} holds no Fountain: paste it in Proposed Fountain or upload a file")


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _story_text_now(ctx: Context, story: str, story_data: dict) -> str:
    """The Fountain the story holds now ("" when it has none yet): what a revision is compared with, and what it must still match when it is applied."""
    try:
        return _fountain_text(ctx, story, story_data)[0]
    except JobError:
        return ""


def _revision_of(ctx: Context, job: dict) -> tuple[str, dict, str, dict]:
    slug = str((job.get("args") or {}).get("revision") or "").strip()
    rows = marvin_api.query(ctx.creds, {"entries": slug}, limit=1) if slug else []
    if not rows:
        raise JobError(f"no revision “{slug}” in this workspace")
    story = str((rows[0].get("dataJson") or {}).get("story") or "").strip()
    story_rows = marvin_api.query(ctx.creds, {"entries": story}, limit=1) if story else []
    if not story_rows:
        raise JobError(f"the revision {slug} names no story that exists (its Story field says “{story}”)")
    return slug, rows[0], story, story_rows[0]


def _patch_entry(ctx: Context, row: dict, data: dict) -> None:
    body = json.dumps({"title": row.get("title"), "slug": row.get("slug"), "dataJson": data}).encode()
    marvin_api.request(ctx.creds, f"/api/platform/entries/{row['id']}", method="PATCH", data=body, content_type="application/json")


BEAT_DETAILS_BATCH = 10  # beats in one question to the AI
BEAT_DETAILS_LIMIT = 40  # beats in one run


def _beat_details_message(story_row: dict, characters: list[dict], batch: list[dict], lines_of: dict[str, list[str]], scenes: dict[str, str]) -> str:
    """The question: for each beat, what the people are doing and the one thing the picture is about, as a JSON list."""
    data = story_row.get("dataJson") or {}
    people = "\n".join(
        f"- {c.get('title')}: {', '.join(x for x in (str(c.get('role') or '').strip(), 'wears ' + str(c['costume']).strip() if c.get('costume') else '', 'carries ' + str(c['props']).strip() if c.get('props') else '') if x)}"
        for c in characters
        if str(c.get("presence") or "") != "voice only"
    )
    cast_names = {str(c.get("slug")): str(c.get("title")) for c in characters}
    beats = []
    for b in batch:
        who = ", ".join(cast_names.get(s.strip(), s.strip()) for s in str(b.get("cast") or "").split(",") if s.strip()) or "nobody named"
        said = "\n    ".join(lines_of.get(str(b.get("slug")), []))
        beats.append(f"BEAT {b.get('number')}\n  place: {scenes.get(str(b.get('scene')), '')}\n  people in it: {who}\n  what happens: {str(b.get('picture') or '').strip()}" + (f"\n  spoken:\n    {said}" if said else ""))
    return (
        "You write two short fields for each beat (one still picture) of a narrated, illustrated story. An image model reads them with the beat's own words.\n\n"
        f"STORY: {story_row.get('title')}. Setting: {data.get('setting') or ''} Premise: {data.get('premise') or ''}\n\nCHARACTERS\n{people or '(none)'}\n\n"
        + "\n\n".join(beats)
        + "\n\nFor each beat write:\n"
        "- expression: what the people in the frame are doing and how they look (pose, face, body), in one or two plain sentences, from the beat's words. Say nothing of the place, weather, light or clothes (other fields hold those), add nobody who is not in the beat, and keep left and right as written. When nobody is in the frame (a view of a place or an object), expression is an empty string, never a sentence saying no one is visible.\n"
        "- focus: the one object the picture is about, in a few words (a logbook, a compass, a coin); an empty string when nothing in particular.\n"
        "Use only what the beat says or clearly implies. Answer with ONLY a JSON list, one object per beat, no code fence and no other text: "
        '[{"number": "1001", "expression": "...", "focus": "..."}]'
    )


def _parse_beat_details(answer: str) -> dict[str, dict]:
    """{beat number: {expression, focus}} from the AI's answer; anything that is not a list of such objects gives nothing."""
    text = str(answer or "")
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return {}
    try:
        items = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    out: dict[str, dict] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("number") or "").strip():
            out[str(item["number"]).strip()] = {"expression": str(item.get("expression") or "").strip()[:400], "focus": str(item.get("focus") or "").strip()[:120]}
    return out


def _ask(ctx: Context, message: str, agent: str = "chat") -> str:
    """One question to a plain-completion agent of this workspace; its answer."""
    body = json.dumps({"message": message, "register": "professional"}).encode()
    reply = json.loads(marvin_api.request(ctx.creds, f"/api/ai/agents/{agent}/run", method="POST", data=body, content_type="application/json"))
    return str(reply.get("answer") or reply.get("response") or reply.get("message") or reply.get("content") or "")


@job_kind(
    "write-beat-details",
    description="Propose what the people are doing (expression) and the one thing the picture is about (focus) for the beats of a story that lack them, from each beat's words, with the workspace AI (a plain completion, ten beats to a question). Only an empty field is filled, never one a person wrote; a person edits the result. dry_run shows what would be written. It spends no image or voice credit",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"},
        "limit": {"type": "string", "required": False, "description": f"most beats to write in one run (default {BEAT_DETAILS_LIMIT})"},
        "dry_run": {"type": "string", "required": False, "description": "yes: write nothing, say what would be written"},
        "agent": {"type": "string", "required": False, "description": "a plain-completion agent of the workspace to ask (default chat)"},
    },
    produces=[],
)
def write_beat_details(job: dict, ctx: Context) -> dict:
    story, args = story_of(job), job.get("args") or {}
    rows = marvin_api.query(ctx.creds, {"entries": story}, limit=1)
    if not rows:
        raise JobError(f"no story “{story}” in this workspace")
    story_row = {**rows[0], "title": rows[0].get("title")}
    dry = _yes(args.get("dry_run"))
    try:
        limit = max(1, int(args.get("limit") or BEAT_DETAILS_LIMIT))
    except ValueError:
        raise JobError("limit is a whole number of beats, like 20") from None
    rec = lambda e: {**(e.get("dataJson") or {}), "slug": e.get("slug"), "title": e.get("title"), "_row": e}  # noqa: E731
    beats = sorted((rec(e) for e in _all(ctx.creds, {"entry_type": "beat", "data": {"story": story}})), key=lambda b: numbering.order_key(b.get("number")))
    waiting = [b for b in beats if str(b.get("picture") or "").strip() and not cards.is_plain(b) and not (str(b.get("expression") or "").strip() and str(b.get("focus") or "").strip())]  # a plain card has no picture to describe
    if not waiting:
        return {"result": {"story": story, "written": 0}, "log": "Every beat that says what happens already has its expression and focus. Nothing to write."}
    todo = waiting[:limit]
    characters = [rec(e) for e in _all(ctx.creds, {"entry_type": "cast-member", "data": {"story": story}})]
    scenes = {str(e.get("slug")): str((e.get("dataJson") or {}).get("place") or "") for e in _all(ctx.creds, {"entry_type": "scene", "data": {"story": story}})}
    lines_of: dict[str, list[str]] = {}
    for e in _all(ctx.creds, {"entry_type": "speech-line", "data": {"story": story}}):
        d = e.get("dataJson") or {}
        lines_of.setdefault(str(d.get("beat")), []).append(f"{str(d.get('speaker') or '').upper()}: {str(d.get('text') or '').strip()}")
    agent = str(args.get("agent") or "chat").strip() or "chat"
    written, skipped, shown = 0, [], []
    for at in range(0, len(todo), BEAT_DETAILS_BATCH):
        batch = todo[at : at + BEAT_DETAILS_BATCH]
        answer = _parse_beat_details(_ask(ctx, _beat_details_message(story_row, characters, batch, lines_of, scenes), agent))
        for b in batch:
            found = answer.get(str(b.get("number")))
            if not found:
                skipped.append(str(b.get("number")))
                continue
            new = {k: v for k, v in found.items() if v and not str(b.get(k) or "").strip()}  # only an empty field is filled
            if not new:
                continue
            shown.append(f"{b.get('number')}: {new.get('expression', '')}" + (f" [focus: {new['focus']}]" if new.get("focus") else ""))
            if not dry:
                row = b["_row"]
                _patch_entry(ctx, row, {**(row.get("dataJson") or {}), **new})
            written += 1
    left = len(waiting) - len(todo)
    log = f"{'Would write' if dry else 'Wrote'} expression and focus for {written} beat{'s' if written != 1 else ''} of “{story_row.get('title')}”" + (" (nothing was changed)" if dry else "") + ". They are proposals: read them and edit what is off."
    if skipped:
        log += f" The AI gave nothing usable for {len(skipped)} (beats {', '.join(skipped[:8])}): run it again."
    if left:
        log += f" {left} more beat{'s' if left != 1 else ''} wait: run it again."
    return {"result": {"story": story, "written": written, "skipped": skipped, "left": left}, "log": log + "\n\n" + "\n".join(shown)}


def _plan_of(args: dict) -> dict | None:
    """The plan the run was given (a workflow looked it up), or None when it was not asked: the check then says nothing about the plan."""
    given = args.get("plan_characters_left")
    left = "" if given is None else str(given).strip()  # 0 is an answer (nothing left), not "not given"
    tier = str(args.get("plan_tier") or "").strip()
    if not left and not tier:
        return None
    return {"tier": tier, "characters_left": left, "resets_at": str(args.get("plan_resets_at") or "").strip()}


@job_kind(
    "check-ready",
    description="Say whether a story is ready to have pictures and voices made, and change nothing but the story's Readiness note: what stops a picture or a recording (no World, no actor, no voice, a voice ElevenLabs has no id for) and what is worth a look (no costume, no set dressing, sounds with no length). It makes no picture, calls no AI and spends nothing",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug, e.g. the-last-onion"},
        "plan_tier": {"type": "string", "required": False, "description": "the ElevenLabs plan (from its free usage lookup): with plan_characters_left, the check says whether the lines still to record fit"},
        "plan_characters_left": {"type": "number", "required": False, "description": "characters left on the plan this period (a number, 0 included)"},
        "plan_resets_at": {"type": "string", "required": False, "description": "when the plan's allowance resets"},
    },
    produces=[],
)
def check_ready(job: dict, ctx: Context) -> dict:
    story = story_of(job)
    rows = marvin_api.query(ctx.creds, {"entries": story}, limit=1)
    if not rows:
        raise JobError(f"no story “{story}” in this workspace")
    story_row = rows[0]
    row = lambda e: {**(e.get("dataJson") or {}), "slug": e.get("slug"), "title": e.get("title")}  # noqa: E731
    of_story = lambda kind: [row(e) for e in _all(ctx.creds, {"entry_type": kind, "data": {"story": story}})]  # noqa: E731
    everywhere = lambda kind: {str(e.get("slug")): row(e) for e in _all(ctx.creds, {"entry_type": kind})}  # noqa: E731
    characters, beats, lines = of_story("cast-member"), of_story("beat"), of_story("speech-line")
    scenes, sounds = of_story("scene"), of_story("sound")
    found = ready.check(
        row(story_row), worlds=set(everywhere("world")), characters=characters, actors=everywhere("actor"), voices=everywhere("voice"),
        beats=beats, lines=lines, scenes=scenes, sounds=sounds, plan=_plan_of(job.get("args") or {}),
    )
    counts = {"Characters": len(characters), "beats": len(beats), "lines": len(lines), "scenes": len(scenes), "sounds": len(sounds)}
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text, fixes, looks = ready.report(found, counts, when)
    data = dict(story_row.get("dataJson") or {})
    data["readiness"] = text
    _patch_entry(ctx, story_row, data)
    return {"result": {"story": story, "fix": fixes, "look": looks}, "log": text}


@job_kind(
    "check-fountain",
    description="Check a Fountain for mistakes before it is imported, and change nothing but a story's Fountain check note: a speaker in lower case (read as action), a note or a ( left open, a scene number used for two places, a transition without its colon, a Hold or a Sound time that is not a number, a speaker spelled two ways, characters you cannot see, a missing Setting or Premise. Each comes with its line and what to write. Reads the text only: no records are made and nothing is paid for. Give it a story (its Fountain field or uploaded file), or the text itself, or an uploaded file.",
    inputs={
        "story": {"type": "string", "required": False, "description": "a story's slug: check the Fountain it holds, and write the report in its Fountain check note"},
        "text": {"type": "string", "required": False, "description": "the Fountain text itself, to check before it is put anywhere (an AI's draft, a file pasted in)"},
        "asset": {"type": "string", "required": False, "description": "an uploaded file (its slug or id) holding the Fountain"},
    },
    produces=[],
)
def check_fountain(job: dict, ctx: Context) -> dict:
    """A Fountain → the mistakes in it, with line numbers and fixes, as a report and as data."""
    args = job.get("args") or {}
    story, text, asset = str(args.get("story") or "").strip(), str(args.get("text") or ""), str(args.get("asset") or "").strip()
    if not (story or text.strip() or asset):
        raise JobError("this kind of job needs a story, the text, or an uploaded file to check (args.story, args.text or args.asset)")
    story_row = None
    if story:
        rows = marvin_api.query(ctx.creds, {"entries": story}, limit=1)
        if not rows:
            raise JobError(f"no story “{story}” in this workspace")
        story_row = rows[0]
        if not text.strip() and not asset:
            text, _ = _fountain_text(ctx, story, dict(story_row.get("dataJson") or {}))
    if not text.strip() and asset:
        file = ctx.work / "check.fountain"
        marvin_api.download_asset(ctx.creds, asset, file)
        if file.stat().st_size > MAX_FOUNTAIN_BYTES:
            raise JobError("that file is too big to be a screenplay (20 MB at most)")
        text = file.read_text(encoding="utf-8", errors="replace")
    findings = validate.check(text)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body, errors, looks = validate.report(findings, text)
    note = f"{body}\n\nChecked {when}."
    if story_row is not None:
        data = dict(story_row.get("dataJson") or {})
        data["fountain_check"] = note
        _patch_entry(ctx, story_row, data)
    stops = len(validate.blocking(findings))
    result = {"errors": errors, "looks": looks, "import_stops": stops, "report": body, "findings": [f.__dict__ for f in findings[:200]]}
    if story:
        result["story"] = story
    return {"result": result, "log": note}


@job_kind(
    "check-revision",
    description="Say what a revision would do to its story, and change nothing: the Fountain the revision holds is fitted to the beats already made by what they say, and the revision record is given the result (beats unchanged, reworded, new with their numbers, gone; lines to record; pictures to make) and the digest of the story's text it was compared with",
    inputs={"revision": {"type": "string", "description": "the revision record's slug"}},
    produces=[],
)
def check_revision(job: dict, ctx: Context) -> dict:
    slug, rev, story, story_row = _revision_of(ctx, job)
    if (rev.get("dataJson") or {}).get("status") not in (None, "", "draft"):
        raise JobError(f"the revision {slug} is already {(rev.get('dataJson') or {}).get('status')}: only a draft can be checked")
    replace = str((rev.get("dataJson") or {}).get("how") or "edit").strip().lower() == "replace"
    ran = import_beats({"job": job["job"], "args": {"story": story, "revision": slug, "mode": "refresh", **({"fresh": "yes"} if replace else {})}}, ctx)
    res, found = ran["result"], ran["result"].get("revision") or {}
    made = _made_from_the_text(ctx, story) if replace else {}
    if replace:
        ran = {**ran, "log": _replace_note(made) + "\n\n" + ran["log"]}
        found = {"same": 0, "reworded": 0, "removed": made["beat"], "new": []}
    data = dict(rev.get("dataJson") or {})
    data.update(
        {
            "base_digest": _digest(_story_text_now(ctx, story, story_row.get("dataJson") or {})),
            "report": ran["log"],
            "same": found.get("same", 0),
            "reworded": found.get("reworded", 0),
            "removed": len(found.get("removed") or []),
            "new_beats": ", ".join(found.get("new") or []) if not replace else "numbered afresh",
            "beats_to_make": len(res.get("beats_made") or []) if isinstance(res.get("beats_made"), list) else res.get("beats_made", 0),
            "lines_to_record": res.get("lines_made", 0),
            "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
    )
    _patch_entry(ctx, rev, data)
    return {"result": {"revision": slug, "story": story, **{k: data[k] for k in ("same", "reworded", "removed", "new_beats", "beats_to_make", "lines_to_record")}}, "log": ran["log"]}


@job_kind(
    "apply-revision",
    description="Make a checked revision the story's Fountain and bring it in: the story's text becomes the revision's (its number and date are set, and shown on the printed script), the beats already made are fitted to it by what they say (new beats numbered after the beat before, nothing already made lost), and the revision is marked applied. Refuses when the story's text changed after the revision was checked",
    inputs={"revision": {"type": "string", "description": "the revision record's slug"}},
    produces=[],
)
def apply_revision(job: dict, ctx: Context) -> dict:
    slug, rev, story, story_row = _revision_of(ctx, job)
    rd, sd = dict(rev.get("dataJson") or {}), dict(story_row.get("dataJson") or {})
    if rd.get("status") not in (None, "", "draft"):
        raise JobError(f"the revision {slug} is already {rd.get('status')}")
    if not str(rd.get("base_digest") or "").strip():
        raise JobError(f"the revision {slug} has not been checked yet: run “Screenplay: check a revision” first, so you see what it would do")
    if _digest(_story_text_now(ctx, story, sd)) != rd["base_digest"]:
        raise JobError(f"the story's Fountain changed after the revision {slug} was checked: check it again, so the comparison is about what is there now")
    new_text = _revision_text(ctx, slug, rev)
    replace = str(rd.get("how") or "edit").strip().lower() == "replace"
    before = {k: sd.get(k) for k in ("fountain", "fountain_file", "revision", "revision_date")}
    replaced_text = _story_text_now(ctx, story, sd)
    rd["before"] = replaced_text if len(replaced_text) <= MAX_BEFORE_CHARS else ""  # what the story said until now: to go back, make a revision of it
    number, today = int(sd.get("revision") or 0) + 1, datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if str(rd.get("proposed") or "").strip():
        sd.update({"fountain": new_text, "fountain_file": None})
    else:
        sd.update({"fountain": "", "fountain_file": str(rd["file"])})
    sd.update({"revision": number, "revision_date": today})
    _patch_entry(ctx, story_row, sd)
    if replace:
        retired = _retire(ctx, _made_from_the_text(ctx, story), f"before-rev{number}")
        ctx.note(f"moved {retired} records made from the earlier text to the Trash")
    try:
        ran = import_beats({"job": job["job"], "args": {"story": story, "mode": "add" if replace else "refresh"}}, ctx)
    except Exception:
        _patch_entry(ctx, story_row, {**dict(story_row.get("dataJson") or {}), **before})  # the story keeps the text it had: nothing was half applied
        if replace:
            ctx.note(f"the import failed after the earlier records went to the Trash: restore them from there (their slugs end in -before-rev{number})")
        raise
    rd.update({"status": "applied", "number": number, "applied_at": today})
    _patch_entry(ctx, rev, rd)
    ctx.note(f"revision {number} applied to {story}")
    return {"result": {"revision": slug, "story": story, "number": number, "import": ran["result"].get("revision")}, "log": ran["log"]}


@job_kind(
    "import-beats",
    description="Read a story's Fountain (its `fountain` text, or the file in `fountain_file`) and make what it implies, with no AI: the chapters, beats and spoken lines (each holding its own part of the text), a Character for each speaker, a Scene for each place, and a draft Sound for each sound the words call for. Makes what is missing and leaves what is there alone; `dry_run` only says what it would make",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug, e.g. devils-due-one-small-boat"},
        "revision": {"type": "string", "required": False, "description": "a revision record's slug: read the Fountain that revision holds instead of the story's own and say what bringing it in would do. Always a preview: nothing is written to the story"},
        "part": {"type": "string", "required": False, "description": "which chapters to make, so a long script is brought in a piece at a time: all (default), 3, 2-4, or 1,3,5. Anything in Marvin outside these chapters is left alone, whatever the mode"},
        "chapter_pages": {"type": "string", "required": False, "description": "when the Fountain has no `#` section lines: about how many pages a chapter should be (default 12); a chapter always ends between two scenes"},
        "dry_run": {"type": "string", "required": False, "description": "yes: say what would be made or changed, write nothing"},
        "accept_errors": {"type": "string", "required": False, "description": "yes: go on although the Fountain check found mistakes the import would read differently from what was meant (see the check-fountain job); by default the import stops and lists them"},
        "mode": {"type": "string", "required": False, "description": "add (default): make what is missing, change nothing that exists. refresh: also bring existing beats and lines nothing has been made from (no still, no recording) in line with the Fountain"},
    },
    produces=[],
)
def import_beats(job: dict, ctx: Context) -> dict:
    """The records a story's Fountain implies: chapters, beats and spoken lines, characters, scenes and sounds."""
    story, args = story_of(job), job.get("args") or {}
    rows_of_story = marvin_api.query(ctx.creds, {"entries": story}, limit=1)
    if not rows_of_story:
        raise JobError(f"no story “{story}” in this workspace")
    story_row = rows_of_story[0]
    story_data = dict(story_row.get("dataJson") or {})
    report, parts, part_text = "", None, ""
    revision_slug = str(args.get("revision") or "").strip()
    if revision_slug:  # checking a proposed revision: its text stands in for the story's, and nothing is written to the story
        rows_of_revision = marvin_api.query(ctx.creds, {"entries": revision_slug}, limit=1)
        if not rows_of_revision:
            raise JobError(f"no revision “{revision_slug}” in this workspace")
        screenplay, fountain_where = _revision_text(ctx, revision_slug, rows_of_revision[0]), f"the revision {revision_slug}"
    else:
        screenplay, fountain_where = _fountain_text(ctx, story, story_data)
    found = validate.check(screenplay)
    stop = validate.blocking(found)
    if stop and not (_yes(args.get("dry_run")) or revision_slug or _yes(args.get("accept_errors"))):  # a preview and a revision check only say; making records stops
        raise JobError(
            "the Fountain has mistakes the import would read differently from what was meant, so nothing was made:\n\n"
            + validate.report(stop, screenplay)[0]
            + "\n\nFix them (the Check the Fountain step, or `python -m storyrender check file.fountain`) or run the import again with accept_errors: yes"
        )
    part_text = args.get("part") or story_data.get("import_part")  # asked for in the run, else what the story says to bring in
    parts = parse_part(part_text)
    try:
        pages = float(args.get("chapter_pages") or fountain.CHAPTER_PAGES)
    except ValueError:
        raise JobError("chapter_pages is a number of pages, like 12") from None
    fplan = fountain.cut(fountain.parse(screenplay, lines=True), chapter_pages=pages, text=screenplay)
    if not fplan.chapters:
        raise JobError(fplan.warnings[0])
    if fplan.single:
        parts = None  # one chapter is the whole story: there is nothing to pick between
    elif parts is not None and (absent := sorted(parts - {c.number for c in fplan.chapters})):
        have_nums = ", ".join(str(c.number) for c in fplan.chapters)
        raise JobError(f"there is no chapter {', '.join(map(str, absent))} in the screenplay; its chapters are {have_nums}.\n\n{fplan.report()}")
    report = fplan.report(parts)
    if lost := fountain.check(fplan):
        raise JobError("the cut would lose part of the screenplay, so nothing was made: " + "; ".join(lost) + "\n\n" + report)
    fresh = _yes(args.get("fresh"))  # a replace: what was made before is being retired, so nothing is fitted to it and the numbers start again
    made_pieces, made_count = {}, 0  # the beats already made from this Fountain, and the piece of it each holds: a revised Fountain is fitted to them by what it says
    for e in ([] if fresh else _all(ctx.creds, {"entry_type": "beat", "data": {"story": story}})):
        d_ = e.get("dataJson") or {}
        made_count += 1
        if str(d_.get("number") or "").strip() and str(d_.get("fountain") or "").strip():
            made_pieces[str(d_["number"]).strip()] = str(d_["fountain"])
    try:  # only when every beat made has its piece: a story made before beats kept them is matched by number, as it was
        revision = fountain.align(fplan, made_pieces) if made_count and len(made_pieces) == made_count else None
    except ValueError as e:
        raise JobError(str(e)) from e
    if revision and (revision["new"] or revision["reworded"] or revision["removed"]):
        report += (
            f"\n\nRevision of what was brought in before: {revision['same']} beats unchanged, {revision['reworded']} reworded (they keep their number, picture and recording; a refresh updates or flags them), "
            f"{len(revision['new'])} new ({', '.join(revision['new'][:12])}{'…' if len(revision['new']) > 12 else ''}: numbered after the beat before, so nothing is renumbered), {len(revision['removed'])} gone from the text."
        )
    text, where = fplan.sheet(parts), fountain_where + (f" (chapters {part_text})" if parts is not None else "")
    if not text.strip():
        raise JobError(f"nothing to read: {where} is empty (write the Fountain in the story's Fountain field, or upload a `.fountain` file as its Fountain file)")
    kind, rows = beat_import.parse_any(text)
    if not rows:
        raise JobError(
            f"found no beats in {where}: is this Fountain? A scene starts with a heading like `INT. KITCHEN - DAY`"
        )
    fountain.mark_cards(rows, fplan)  # centred text is a plain card: the beat shows its words and no picture is described, so none is ever made
    ctx.note(f"read {len(rows)} beats from {where}")
    have = {e["slug"]: e for kind_ in ("beat", "speech-line") for e in ([] if fresh else _all(ctx.creds, {"entry_type": kind_, "data": {"story": story}}))}
    chapters_have = {e["slug"]: e for e in ([] if fresh else _all(ctx.creds, {"entry_type": "chapter", "data": {"story": story}}))}
    # A chapter inserted before others shifts their numbers (unless every title carries its own number), and the beats made under the old
    # numbers would then no longer match the screenplay. Say so in the plan, before anything is made.
    wrote = {c.number: c.title.strip().lower() for c in fplan.chapters}
    moved = sorted(
        (n, str(rec.get("title") or ""), next(c.title for c in fplan.chapters if c.number == n))
        for slug, rec in chapters_have.items()
        if (n := _chapter_of(story, slug)) in wrote and str(rec.get("title") or "").strip().lower() not in ("", wrote[n])
    )
    if moved and not fplan.single:
        lines = "; ".join(f"chapter {n} is “{old}” in Marvin but “{new}” in the screenplay" for n, old, new in moved[:6])
        report += (
            f"\n\nCheck the numbering: {lines}{'…' if len(moved) > 6 else ''}. If a chapter was inserted or moved, the chapters after it have new numbers, "
            "and bringing them in would add beats beside the old ones. Number the section titles in the screenplay (`## 03 The heist`) so a chapter keeps its "
            "number wherever it sits; if the title was only reworded, ignore this."
        )
    if parts is not None:  # a piece of the story: what is in the other pieces is not this run's to keep, trash or change
        have = {k: v for k, v in have.items() if _chapter_of(story, k) in parts}
        chapters_have = {k: v for k, v in chapters_have.items() if _chapter_of(story, k) in parts}
    refresh = str(args.get("mode") or "").strip().lower() == "refresh"
    plan = beat_import.import_plan(story, rows, have, refresh=refresh, chapters=chapters_have)
    dry = _yes(args.get("dry_run")) or bool(revision_slug)
    fill: list[tuple[dict, dict]] = []  # chapters that already exist but hold none of the Fountain text or summary yet, with what they should hold
    fountain.attach_source(plan, fplan, story)  # every beat and line made holds its own piece of the text, and the transition written before it
    chapter_summaries = {c.number: c.summary for c in fplan.chapters if c.summary}
    slices = None if fplan.single else fountain.chapter_texts(screenplay, fplan)
    if slices is None and not fplan.single:
        ctx.note("could not match the Fountain text to its chapters one for one, so no chapter holds its own text: the story's Fountain stays whole")
    wanted = {n: t for n, t in (slices or {}).items() if parts is None or n in parts}
    extras = {n: {k: v for k, v in (("fountain", wanted.get(n)), ("summary", chapter_summaries.get(n))) if v} for n in {*wanted, *chapter_summaries} if parts is None or n in parts}
    plan["chapters"] = [(slug, title, {**extras.get(n, {}), **data} if (n := _chapter_of(story, slug)) in extras else data) for slug, title, data in plan["chapters"]]
    fill = [
        (rec, missing)
        for slug, rec in chapters_have.items()
        if (n := _chapter_of(story, slug)) in extras and (missing := {k: v for k, v in extras[n].items() if not str((rec.get("dataJson") or {}).get(k) or "").strip()})
    ]
    people = {str((e.get("dataJson") or {}).get("speaker") or "").lower(): e for e in _all(ctx.creds, {"entry_type": "cast-member", "data": {"story": story}})}
    extra: list[tuple[str, tuple[str, str, dict]]] = []  # the characters and scenes the screenplay implies that this story does not have yet
    link: list[tuple[dict, dict]] = []  # records that are already there and lack something the Fountain gives them (a Scene, sounds, their own piece of the text), with what to add
    hand_set: list[str] = []  # beats whose transition a person changed, so the script's line is not followed
    for _chapter, number, beat in fplan.rows():
        place = fountain.place_of(beat.get("place", ""))
        rec = have.get(f"{story}-beat-{number}")
        data = rec.get("dataJson") or {} if rec else {}
        add = {}
        if place and not str(data.get("scene") or "").strip():
            add["scene"] = f"{story}-{place['slug']}"
        if beat.get("sounds") and not data.get("sounds"):
            add["sounds"] = [{"sound": f"{story}-sound-{number}-{i}", "at": c.get("at", 0)} for i, c in enumerate(beat["sounds"], 1)]
        if rec and beat.get("fountain") and (not str(data.get("fountain") or "").strip() or (revision is not None and str(data.get("fountain")).strip() != beat["fountain"].strip())):
            add["fountain"] = beat["fountain"]  # a beat made before it kept its own piece of the text gets it; a revised text gives the beat it is the new piece (it is made from the text, not edited)
        if rec:
            followed, said = fountain.follow_transition(data, beat)
            add.update(followed)
            if said:
                hand_set.append(f"beat {number} {said}")
            if (seconds := fountain.transition_seconds(beat)) and not data.get("transition_seconds"):
                add["transition_seconds"] = seconds
            add.update(_cast_for(story, beat, fplan.characters, people, data))
        if rec and add:
            link.append((rec, add))
        for i, ln in enumerate(beat.get("lines") or [], 1):
            line_rec = have.get(f"{story}-line-{number}-{i}")
            held = str((line_rec.get("dataJson") or {}).get("fountain") or "").strip() if line_rec else ""
            line_add: dict = {}
            if line_rec and ln.get("fountain") and (not held or (revision is not None and held != ln["fountain"].strip())):
                line_add = {"fountain": ln["fountain"], **({"simultaneous": True} if ln.get("dual") else {})}
            if line_rec and ln.get("speaker") and not str((line_rec.get("dataJson") or {}).get("character") or "").strip():
                line_add["character"] = _character_slug(story, ln["speaker"], people)  # a line made before lines named their Character gets it
            if line_add:
                link.append((line_rec, line_add))  # one change per record: a PATCH replaces dataJson, so two would undo each other
    rows_by_number = {str(number): beat for _chapter, number, beat in fplan.rows()}
    for _slug, _title, data in plan["beats"]:  # a beat made now is cast the same way: who speaks in it and who its action names, with their masters
        if beat := rows_by_number.get(str(data.get("number"))):
            data.update(_cast_for(story, beat, fplan.characters, people, data))
    for _slug, _title, data in plan["lines"]:  # a line made now names its Character, so a setup can offer "just the narrator's lines"
        if data.get("speaker"):
            data.setdefault("character", _character_slug(story, str(data["speaker"]), people))
    extra = _implied(ctx, story, story_row, fplan, plan, link, fresh=fresh)
    people = [] if fresh else _people_fill(ctx, story, fplan)  # a replace starts afresh: its Characters are made new
    if not dry and (plan["beats"] or plan["lines"] or plan["updates"] or plan["chapters"] or extra or link or people):
        types = {t["slug"]: t["id"] for t in json.loads(marvin_api.request(ctx.creds, "/api/platform/entry-types"))}
        for needed in ("beat", "speech-line") + (("chapter",) if plan["chapters"] else ()):
            if needed not in types:
                raise JobError(f"this workspace has no “{needed}” entry type: install the Screenplay Studio package first")
        done_count = 0
        extra = [(t, r) for t, r in extra if t in types]  # an older workspace without these types simply goes without
        for type_slug, (slug, title, data) in extra + [("chapter", c) for c in plan["chapters"]] + [("beat", b) for b in plan["beats"]] + [("speech-line", ln) for ln in plan["lines"]]:
            body = json.dumps({"entryTypeId": types[type_slug], "title": title, "slug": slug, "status": "draft", "dataJson": data}).encode()
            marvin_api.request(ctx.creds, "/api/platform/entries", method="POST", data=body, content_type="application/json")
            done_count += 1
            if done_count % 10 == 0:
                ctx.note(f"{done_count} records written")
        for slug, record_id, title, data in plan["updates"]:  # a PATCH replaces dataJson and renames by title unless the slug is named: send both whole
            body = json.dumps({"title": title, "slug": slug, "dataJson": data}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{record_id}", method="PATCH", data=body, content_type="application/json")
        refreshed = {slug: (title, data) for slug, _id, title, data in plan["updates"]}  # what a record holds after the updates above: the base of any further change to it
        for rec, add in link:  # a beat made before the scenes and sounds were: put it in its scene and place its sounds (a PATCH replaces dataJson, so send it whole)
            title, held = refreshed.get(rec["slug"], (rec.get("title"), rec.get("dataJson") or {}))
            merged = {k: v for k, v in {**held, **add}.items() if not (v is None and k in add)}  # None takes a field out (a transition whose line is gone)
            payload = json.dumps({"title": title, "slug": rec["slug"], "dataJson": merged}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="PATCH", data=payload, content_type="application/json")
        for rec, missing in fill:  # a chapter made before chapters held their own text and summary gets them; a PATCH replaces dataJson, so send it whole
            data = {**(rec.get("dataJson") or {}), **missing}
            payload = json.dumps({"title": rec.get("title"), "slug": rec["slug"], "dataJson": data}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="PATCH", data=payload, content_type="application/json")
        for rec, missing in people:  # a Character made before Age and Sex were fields gets them from the screenplay (a PATCH replaces dataJson, so send it whole)
            payload = json.dumps({"title": rec.get("title"), "slug": rec["slug"], "dataJson": {**(rec.get("dataJson") or {}), **missing}}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="PATCH", data=payload, content_type="application/json")
        for slug, record_id in plan["trash"]:  # DELETE moves an entry to the Trash, where it can be restored
            marvin_api.request(ctx.creds, f"/api/platform/entries/{record_id}", method="DELETE")
    verb, uverb = ("would make", "would update") if dry else ("made", "updated")
    note = f"{verb} {len(plan['beats'])} beats and {len(plan['lines'])} spoken lines"
    held = sum(1 for c in plan["chapters"] if c[2].get("fountain")) + sum(1 for _r, m in fill if m.get("fountain"))
    if held:
        note += f" (each of {held} chapters {'would hold' if dry else 'holds'} its own part of the Fountain text)"
    if plan["chapters"] or plan["have"]["chapters"]:
        note += f" and {len(plan['chapters'])} chapters ({plan['have']['chapters']} already there)"
    if extra:
        made = {t: [r[1] for u, r in extra if u == t] for t in ("cast-member", "scene", "sound")}
        note += f", {len(made['cast-member'])} characters ({', '.join(made['cast-member'])}), {len(made['scene'])} scenes ({', '.join(made['scene'])}) and {len(made['sound'])} sounds to fill in ({', '.join(made['sound'][:8])}{'…' if len(made['sound']) > 8 else ''})"
    if link:
        note += f", and {'would fill' if dry else 'filled'} in {len(link)} records made earlier (their scene, sounds, cast, reference pictures and own piece of the Fountain)"
    if refresh:
        note += f"; {uverb} {len(plan['updates'])} that nothing had been made from; {plan['same']} already matched"
    note += f". {plan['have']['beats']} beats and {plan['have']['lines']} lines were already there" + (" (the rest left alone)." if not refresh else ".")
    if plan["kept"]:
        note += f" Kept as they are, because a still or recording was made from them ({len(plan['kept'])}): " + "; ".join(f"{s} ({why})" for s, why in plan["kept"][:6]) + ("…" if len(plan["kept"]) > 6 else ".")
    short = lambda slug: slug.replace(f"{story}-", "", 1).replace("-", " ")  # noqa: E731  "beat 07", "line 07 1", "chapter 03"
    if plan["trash"]:
        note += f" {'Would move' if dry else 'Moved'} to the Trash, no longer in the script and nothing made from them ({len(plan['trash'])}): " + ", ".join(short(s) for s, _ in plan["trash"][:10]) + ("…" if len(plan["trash"]) > 10 else ".")
    if plan["orphans_kept"]:
        note += f" Gone from the script but kept, because something was made from them ({len(plan['orphans_kept'])}): " + "; ".join(f"{short(s)} ({why})" for s, why in plan["orphans_kept"][:8]) + ("…" if len(plan["orphans_kept"]) > 8 else ".")
    if plan["gone"] and not refresh:
        note += f" In Marvin but not in the script, not touched in Add mode ({len(plan['gone'])}): " + ", ".join(short(s) for s in plan["gone"][:8]) + ("…" if len(plan["gone"]) > 8 else ".")
    if plan["sounds"]:
        note += f" {len(plan['sounds'])} sound cues were not imported (sounds are placed from the library): " + "; ".join(plan["sounds"][:5]) + ("…" if len(plan["sounds"]) > 5 else "")
    if plan["problems"]:
        note += " " + "; ".join(plan["problems"]) + "."
    if hand_set:
        note += " Transitions kept as they are: " + "; ".join(hand_set[:8]) + ("…" if len(hand_set) > 8 else ".")
    result = {
        "format": kind,
        "mode": "refresh" if refresh else "add",
        "dry_run": dry,
        "beats_made": len(plan["beats"]),
        "lines_made": len(plan["lines"]),
        "chapters_made": [c[0] for c in plan["chapters"]],
        "characters_made": [r[0] for t, r in extra if t == "cast-member"],
        "scenes_made": [r[0] for t, r in extra if t == "scene"],
        "sounds_made": [r[0] for t, r in extra if t == "sound"],
        "records_filled_in": len(link),
        "updated": [u[0] for u in plan["updates"]],
        "already_matched": plan["same"],
        "kept_because_worked_on": [{"slug": s, "why": why} for s, why in plan["kept"]],
        "not_in_the_sheet": plan["gone"],
        "trashed": [s for s, _ in plan["trash"]],
        "kept_though_gone": [{"slug": s, "why": why} for s, why in plan["orphans_kept"]],
        "beats_existing": plan["have"]["beats"],
        "lines_existing": plan["have"]["lines"],
        "sound_cues_not_imported": plan["sounds"],
        "problems": plan["problems"],
        "part": str(part_text or "all"),
        "revision": revision,
        "split_report": report,
    }
    changed = plan["beats"] or plan["lines"] or plan["chapters"] or plan["updates"] or plan["trash"]
    meta = fountain.title_page(screenplay)
    credits = ("credit", "author", "source", "draft_date", "contact", "copyright", "setting", "premise")  # the title page is the story's credits; a field already filled in is the person's and is kept
    filled = {k: meta[k] for k in credits if meta.get(k) and not str(story_data.get(k) or "").strip()}
    settings = {**fountain.story_settings(meta), **({"end_transition": fplan.end_transition} if fplan.end_transition else {})}  # the cards and transitions the script says: the same rule
    filled.update({k: v for k, v in settings.items() if not str(story_data.get(k) or "").strip()})
    if not str(story_data.get("setting") or "").strip() and "setting" not in filled and (said := _setting_from(fplan)):
        filled["setting"] = said  # nothing said where it is set: the first scene's synopsis, else its place; the person's own words replace it
    gaps = _story_gaps({**story_data, **filled})
    if gaps:
        note += "\n\nThe story still lacks: " + "; ".join(gaps) + "."
    if filled.get("setting") and not meta.get("setting"):
        note += f"\n\nSetting taken from the screenplay: “{filled['setting'][:160]}”."
    result["story_gaps"] = gaps
    if not dry:
        story_data.update(filled)
        other = "\n".join(f"{k}: {v}" for k, v in meta.items() if k not in ("title", *credits, *fountain.SETTING_KEYS))
        if other and not str(story_data.get("title_page_other") or "").strip():
            story_data["title_page_other"] = other
        if any(t == "sound" and r[0] == f"{story}-score" for t, r in extra) and not dry and not str(story_data.get("music") or "").strip():
            story_data["music"] = f"{story}-score"  # the placeholder is the story's music until a recording or a generated take replaces it, or it is deleted
        if fplan.front.strip() and not str(story_data.get("fountain_front") or "").strip():
            story_data["fountain_front"] = fplan.front  # what the writer put before the first beat, as written: the export writes it back first
    if revision_slug:  # a check says what it found and leaves the story as it is
        return {"result": result, "log": (report + "\n\n" + note) if report else note}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story_data["split_plan"] = f"{stamp} · {'preview' if dry else 'import'}, chapters {part_text or 'all'}\n\n{report}\n\n{note}"  # kept on the story, where a wizard step (or the person) reads it before and after importing
    bits = [f"+{len(plan['beats'])} beats, +{len(plan['lines'])} lines" + (f", +{len(plan['chapters'])} chapters" if plan["chapters"] else "")]
    if plan["updates"]:
        bits.append(f"{len(plan['updates'])} updated")
    if plan["trash"]:
        bits.append("trashed: " + ", ".join(short(s) for s, _ in plan["trash"][:12]) + ("…" if len(plan["trash"]) > 12 else ""))
    if plan["orphans_kept"]:
        bits.append("kept though gone from the script (something was made from them): " + ", ".join(short(s) for s, _ in plan["orphans_kept"][:8]))
    if plan["kept"]:
        bits.append("differ from the script but kept (a picture or recording was made): " + ", ".join(short(s) for s, _ in plan["kept"][:8]))
    if changed and not dry:
        via = f" · from the Fountain{' (chapters ' + str(part_text) + ')' if parts is not None else ''}"
        entry = f"{stamp} · {'refresh' if refresh else 'add'}{via} · " + " · ".join(bits)
        story_data["sheet_log"] = (str(story_data.get("sheet_log") or "").rstrip() + "\n" + entry).strip()
    body = json.dumps({"title": story_row.get("title"), "slug": story_row.get("slug"), "dataJson": story_data}).encode()
    marvin_api.request(ctx.creds, f"/api/platform/entries/{story_row['id']}", method="PATCH", data=body, content_type="application/json")
    return {"result": result, "log": (report + "\n\n" + note) if report else note}



PREVIEW_SIZE = "720:1280"


def _keep_subtitles(ctx: Context, story: str, name: str, title: str, text: str) -> None:
    """The captions as a subtitle file (SubRip) kept on the story as `subtitles`, for a platform that takes them as a file; the previous one goes to
    the Trash. A story with no captions gets none, and a failure here never fails a video that was made."""
    if not text.strip():
        return
    file = ctx.work / f"{name}.srt"
    file.write_text(text, encoding="utf-8")
    try:
        asset = marvin_api.upload_asset(ctx.creds, file, slug=f"{name}-subtitles", name=f"{title}: subtitles", mime="application/x-subrip", description=f"The captions of {title} as a subtitle file.", metadata={"kind": "subtitles", "story": story})
        before = next((((e.get("dataJson") or {}).get("subtitles")) for e in marvin_api.query(ctx.creds, {"entries": story}, limit=1)), None)
        marvin_api.update_entry(ctx.creds, story, {"subtitles": asset["id"]})
        if before and before != asset["id"]:
            try:
                marvin_api.request(ctx.creds, f"/api/platform/assets/{before}", method="DELETE")
            except marvin_api.MarvinError:
                pass  # an old file that cannot be trashed must not fail the render
        ctx.note("kept the captions as a subtitle file on the story")
    except marvin_api.MarvinError as e:
        ctx.note(f"could not keep the subtitle file ({e})")


@job_kind(
    "render",
    description="Make a story's video from its approved stills and recorded lines (1080x1920, captions burned in) and keep it on the story as `video`. By default a smaller 720x1280 copy goes to Marvin (its upload limit is 100 MB) and the full-quality file is kept in the worker's output folder; `approve_beats` first marks every beat of the story approved, which is what approving the filmstrip means",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug"},
        "quality": {"type": "string", "required": False, "description": "draft: a quick look to check an overlay or a level (fast encode, 720x1280, replaces the story's video; no full-quality file is kept). preview (default): upload a 720x1280 copy. full: upload the 1080x1920 file (Marvin refuses an upload over its asset limit, 100 MB by default)"},
        "beats": {"type": "string", "required": False, "description": "only these beats, as a quick look: 3, 2-4, 1,3,5 or 4a (an inserted beat). Always a draft; it is kept as its own video file and never replaces the story's video"},
        "approve_beats": {"type": "string", "required": False, "description": "yes: mark every beat of the story approved before rendering"},
    },
    produces=["video/mp4"],
    needs=["ffmpeg"],
)
def render_video(job: dict, ctx: Context) -> dict:
    """The story as a vertical narrated video, kept as the story's `video`; the previous one goes to the Trash."""
    story, name, args = story_of(job), job["job"], job.get("args") or {}
    only = str(args.get("beats") or "").strip()  # a quick look at some beats: 3, 2-4, 1,3,5
    if _yes(args.get("approve_beats")) and not only:
        marked = 0
        for beat in marvin_api.query(ctx.creds, {"entry_type": "beat", "data": {"story": story}}, limit=1000):
            if (beat.get("dataJson") or {}).get("status") != "approved":
                marvin_api.update_entry(ctx.creds, beat["slug"], {"status": "approved"})
                marked += 1
        ctx.note(f"marked {marked} beats approved")
    quality = str(args.get("quality") or "preview").strip().lower()
    draft = quality == "draft" or bool(only)  # a quick look: fast encode, a smaller copy, no full-quality file kept (some beats are always one)
    pulled = marvin_pull.pull(story, ctx.work / "story", creds=ctx.creds, **({"beats": only} if only else {}), **({"placeholders": True} if draft else {}))
    ctx.note(f"pulled {pulled['shots']} shots, {pulled['lines']} recorded lines")
    if pulled.get("placeholders"):
        ctx.note(f"no still yet for beat {', '.join(pulled['placeholders'])}: a plain card stands in for it in this draft")
    m = manifest.load(Path(pulled["manifest"]), probe=ffmpeg.duration)
    full = ctx.work / f"{name}.mp4"
    made = build.render(m, full, draft=draft)
    size_mb = full.stat().st_size / 1e6
    ctx.note(f"rendered {made['measured_seconds']} s, {made['shots']} shots, {size_mb:.0f} MB")
    kept = ""
    out_dir = os.environ.get("STUDIO_OUT_DIR", "").strip()
    if out_dir and not draft:
        try:  # a copy that cannot be kept (a folder the worker may not write to) must not fail a video that was made
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            keep = Path(out_dir) / f"{story}-{name}.mp4"
            shutil.copyfile(full, keep)
            kept = str(keep)
            ctx.note(f"kept the full-quality file at {kept}")
        except OSError as e:
            ctx.note(f"could not keep the full-quality file in {out_dir} ({e.strerror or e}); the video goes to Marvin without it. Make that folder writable by the worker's user")
    upload = full
    if quality != "full":
        upload = ctx.work / f"{name}-preview.mp4"
        ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(full), "-vf", f"scale={PREVIEW_SIZE}", "-c:v", "libx264", "-crf", "28", "-preset", "medium", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(upload)])
        ctx.note(f"made the 720x1280 copy for Marvin: {upload.stat().st_size / 1e6:.0f} MB")
    title = m.title or story
    try:
        asset = marvin_api.upload_asset(
            ctx.creds,
            upload,
            slug=f"{name}-video",
            name=f"{title}: video" + (f" (draft of beat {only})" if only else "" if quality == "full" else " (draft)" if draft else " (preview quality)"),
            mime="video/mp4",
            description=f"The video of {title}, rendered from its approved stills and recorded lines.",
            metadata={"kind": "video", "story": story, "seconds": made["measured_seconds"], "shots": made["shots"], "quality": "full" if quality == "full" and not only else "draft" if draft else "preview", **({"beats": only} if only else {})},
        )
    except marvin_api.MarvinError as e:
        raise JobError(f"the video was made but Marvin would not take the upload ({e}). " + (f"The full-quality file is at {kept}. " if kept else "") + "Use quality preview, or raise Marvin's asset size limit") from e
    before = None
    if not only:  # a look at some beats is its own file in the library: it never replaces the story's video
        before = next((((e.get("dataJson") or {}).get("video")) for e in marvin_api.query(ctx.creds, {"entries": story}, limit=1)), None)
        marvin_api.update_entry(ctx.creds, story, {"video": asset["id"]})
    if before and before != asset["id"]:
        try:
            marvin_api.request(ctx.creds, f"/api/platform/assets/{before}", method="DELETE")
        except marvin_api.MarvinError:
            pass  # an old copy that cannot be trashed must not fail a video that was made
    if not only:  # a look at some beats makes no subtitle file of its own
        _keep_subtitles(ctx, story, name, title, captions.srt(manifest.plan(m)))
    story_data = (next(iter(marvin_api.query(ctx.creds, {"entries": story}, limit=1)), None) or {}).get("dataJson") or {}
    warning = None if only else formats.length_warning(made["measured_seconds"], story_data)  # past what the platform takes, in plain words
    note = f"{made['measured_seconds']} s, {made['shots']} shots." + (f" Full-quality file: {kept}." if kept else "") + (f" {warning}" if warning else "")
    if pulled["not_recorded"]:
        note += f" Not recorded yet, so left out: {', '.join(pulled['not_recorded'])}."
    return {"result": {"video": asset["id"], "url": asset.get("publicUrl"), "seconds": made["measured_seconds"], "shots": made["shots"], "quality": "full" if quality == "full" and not only else "draft" if draft else "preview", "kept": kept, **({"beats": only} if only else {}), **({"warning": warning} if warning else {})}, "log": note}
