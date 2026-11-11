"""The media kinds of job: what the Storyworld worker image adds to the generic base (`marvin-worker-base`). The image names this
module in WORKER_JOB_MODULES, so importing it registers them. Each is `(job, ctx) -> fields for the job's record`."""

import json
import os
import re
import shutil
from datetime import datetime, timezone
import urllib.request
from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import audio_convert, audio_measure, beat_import, build, captions, chapters, ffmpeg, filmstrip, formats, fountain, manifest, marvin_pull, script, voices


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
    made = script.render(text or script.fountain(records), ctx.work / "script", story)
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


def _implied(ctx: Context, story: str, story_row: dict, fplan, plan: dict, link: list) -> list[tuple[str, tuple[str, str, dict]]]:
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
        out.append(("cast-member", (f"{story}-{speaker}", c["name"], {"cast_id": cast_id, "role": role, "speaker": speaker, "story": story, "presence": "on screen", "status": "draft"})))
    want = {b[2]["scene"] for b in plan["beats"] if b[2].get("scene")} | {add["scene"] for _r, add in link if add.get("scene")}
    have_scenes = {e["slug"] for e in _all(ctx.creds, {"entry_type": "scene", "data": {"story": story}})}
    have_sounds = {e["slug"] for e in _all(ctx.creds, {"entry_type": "sound", "data": {"story": story}})}
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
        where = " and ".join(place["kinds"])
        data = {"story": story, "place": place["name"] + (f" ({where})" if where else ""), "look": ", ".join(place["times"]), "status": "draft"}
        if place["kinds"] == ["interior"]:
            data["ambience_muffled"] = True
        bed = fplan.ambience.get(slug_key)
        if bed:  # the bed under the place: a Sound of its own, made once and named by the scene
            bed_slug = f"{story}-ambience-{slug_key}"
            data["ambience"] = bed_slug
            if bed_slug not in have_sounds:
                out.append(("sound", (bed_slug, bed["title"], {"story": story, "kind": "ambience", "prompt": bed["prompt"], "source": "generated", "loop": True, "status": "draft"})))
        out.append(("scene", (slug, place["name"], {k: v for k, v in data.items() if v not in ("", None)})))
    return out


@job_kind(
    "import-beats",
    description="Read a story's Fountain (its `fountain` text, or the file in `fountain_file`) and make what it implies, with no AI: the chapters, beats and spoken lines (each holding its own part of the text), a Character for each speaker, a Scene for each place, and a draft Sound for each sound the words call for. Makes what is missing and leaves what is there alone; `dry_run` only says what it would make",
    inputs={
        "story": {"type": "string", "description": "the story entry's slug, e.g. devils-due-one-small-boat"},
        "part": {"type": "string", "required": False, "description": "which chapters to make, so a long script is brought in a piece at a time: all (default), 3, 2-4, or 1,3,5. Anything in Marvin outside these chapters is left alone, whatever the mode"},
        "chapter_pages": {"type": "string", "required": False, "description": "when the Fountain has no `#` section lines: about how many pages a chapter should be (default 12); a chapter always ends between two scenes"},
        "dry_run": {"type": "string", "required": False, "description": "yes: say what would be made or changed, write nothing"},
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
    screenplay, fountain_where = _fountain_text(ctx, story, story_data)
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
    text, where = fplan.sheet(parts), fountain_where + (f" (chapters {part_text})" if parts is not None else "")
    if not text.strip():
        raise JobError(f"nothing to read: {where} is empty (write the Fountain in the story's Fountain field, or upload a `.fountain` file as its Fountain file)")
    kind, rows = beat_import.parse_any(text)
    if not rows:
        raise JobError(
            f"found no beats in {where}: is this Fountain? A scene starts with a heading like `INT. KITCHEN - DAY`"
        )
    ctx.note(f"read {len(rows)} beats from {where}")
    have = {e["slug"]: e for kind_ in ("beat", "speech-line") for e in _all(ctx.creds, {"entry_type": kind_, "data": {"story": story}})}
    chapters_have = {e["slug"]: e for e in _all(ctx.creds, {"entry_type": "chapter", "data": {"story": story}})}
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
    dry = _yes(args.get("dry_run"))
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
    extra: list[tuple[str, tuple[str, str, dict]]] = []  # the characters and scenes the screenplay implies that this story does not have yet
    link: list[tuple[dict, str]] = []  # beats that are already there but are in no Scene yet, with the Scene the screenplay puts them in
    for _chapter, number, beat in fplan.rows():
        place = fountain.place_of(beat.get("place", ""))
        rec = have.get(f"{story}-beat-{number}")
        data = rec.get("dataJson") or {} if rec else {}
        add = {}
        if place and not str(data.get("scene") or "").strip():
            add["scene"] = f"{story}-{place['slug']}"
        if beat.get("sounds") and not data.get("sounds"):
            add["sounds"] = [{"sound": f"{story}-sound-{number}-{i}", "at": 0} for i, _c in enumerate(beat["sounds"], 1)]
        if rec and add:
            link.append((rec, add))
    extra = _implied(ctx, story, story_row, fplan, plan, link)
    if not dry and (plan["beats"] or plan["lines"] or plan["updates"] or plan["chapters"] or extra or link):
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
        for rec, add in link:  # a beat made before the scenes and sounds were: put it in its scene and place its sounds (a PATCH replaces dataJson, so send it whole)
            payload = json.dumps({"title": rec.get("title"), "slug": rec["slug"], "dataJson": {**(rec.get("dataJson") or {}), **add}}).encode()
            marvin_api.request(ctx.creds, f"/api/platform/entries/{rec['id']}", method="PATCH", data=payload, content_type="application/json")
        for rec, missing in fill:  # a chapter made before chapters held their own text and summary gets them; a PATCH replaces dataJson, so send it whole
            data = {**(rec.get("dataJson") or {}), **missing}
            payload = json.dumps({"title": rec.get("title"), "slug": rec["slug"], "dataJson": data}).encode()
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
        note += f", and {'would put' if dry else 'put'} {len(link)} beats that were made earlier into their scenes"
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
        "beats_put_in_scenes": len(link),
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
        "split_report": report,
    }
    changed = plan["beats"] or plan["lines"] or plan["chapters"] or plan["updates"] or plan["trash"]
    if not dry:  # the title page is the story's credits; a field already filled in is the person's and is kept
        meta = fountain.title_page(screenplay)
        for key in ("credit", "author", "source", "draft_date", "contact", "copyright"):
            if meta.get(key) and not str(story_data.get(key) or "").strip():
                story_data[key] = meta[key]
        other = "\n".join(f"{k}: {v}" for k, v in meta.items() if k not in ("title", "credit", "author", "source", "draft_date", "contact", "copyright"))
        if other and not str(story_data.get("title_page_other") or "").strip():
            story_data["title_page_other"] = other
        if any(t == "sound" and r[0] == f"{story}-score" for t, r in extra) and not dry and not str(story_data.get("music") or "").strip():
            story_data["music"] = f"{story}-score"  # the placeholder is the story's music until a recording or a generated take replaces it, or it is deleted
        if fplan.front.strip() and not str(story_data.get("fountain_front") or "").strip():
            story_data["fountain_front"] = fplan.front  # what the writer put before the first beat, as written: the export writes it back first
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
