"""The `transcribe` kind of job: an audio (or video) asset in Marvin to text, with faster-whisper on this machine's CPU. Free: no service, no key.

The text is kept as assets (the words, the words with times, and the same as JSON), named on the job's result, so a transcript is something to open,
download or hand to the next step (a script). The model is read once per worker and cached on disk (`HF_HOME`, a volume in the container), so
only the first job after a new model is chosen waits for a download.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from marvin_worker import marvin_api
from marvin_worker.jobs import Context, JobError, job_kind

from . import align, text

MODEL = os.environ.get("WHISPER_MODEL", "small")
"""tiny, base, small, medium or large-v3: bigger is more exact and slower. `small` is about 4x real time on 10 CPU cores."""
THREADS = int(os.environ.get("WHISPER_THREADS", "0"))  # 0: all cores
_models: dict[str, object] = {}


def load_model(name: str):
    """The model, read once and kept (CPU, int8: no GPU needed)."""
    if name not in _models:
        from faster_whisper import WhisperModel

        _models[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS)
    return _models[name]


def transcribe_file(model, audio: Path, out: Path, *, language: str | None = None, hotwords: str | None = None, note=lambda _t: None, every: int = 50) -> dict:
    """Run `model` over `audio`, writing `out`.txt as the segments arrive (a failure part-way leaves what was heard), then the timestamped,
    paragraph and JSON forms. Returns {language, seconds, segments, files}."""
    segments_iter, info = model.transcribe(str(audio), language=language or None, hotwords=hotwords or None, vad_filter=True, beam_size=5)
    note(f"{info.language} ({info.language_probability:.0%}), {info.duration:.0f} s of audio")
    segments: list[dict] = []
    started = time.monotonic()
    partial = out.with_suffix(".txt")
    with partial.open("w", encoding="utf-8") as live:
        for s in segments_iter:
            row = {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            segments.append(row)
            live.write(row["text"] + "\n")
            live.flush()
            if len(segments) % every == 0:
                note(f"{s.end:.0f} of {info.duration:.0f} s heard, {time.monotonic() - started:.0f} s in")
    files = {
        "text": partial,
        "timestamped": out.with_name(out.name + ".timestamped.txt"),
        "paragraphs": out.with_name(out.name + ".paragraphs.txt"),
        "json": out.with_name(out.name + ".json"),
    }
    files["timestamped"].write_text(text.timestamped(segments), encoding="utf-8")
    files["paragraphs"].write_text(text.paragraphs(segments), encoding="utf-8")
    files["json"].write_text(json.dumps({"language": info.language, "duration": info.duration, "segments": segments}, ensure_ascii=False), encoding="utf-8")
    return {"language": info.language, "seconds": round(info.duration, 1), "segments": len(segments), "files": files}


MIME = {"text": "text/plain", "timestamped": "text/plain", "paragraphs": "text/plain", "json": "application/json"}
LABEL = {"text": "transcript", "timestamped": "transcript with times", "paragraphs": "transcript in paragraphs", "json": "transcript (JSON)"}


@job_kind(
    "transcribe",
    description="Turn a recording into text with faster-whisper, on this machine's CPU (free). The words, the words with times, the words in paragraphs, and the same as JSON, kept as files",
    inputs={
        "audio": {"type": "asset", "accepts": ["audio/*", "video/*"], "description": "the recording: an audio or video asset (its slug or id)"},
        "language": {"type": "string", "required": False, "description": "the spoken language as a code, e.g. en; empty to detect it"},
        "hotwords": {"type": "string", "required": False, "description": "names and unusual words to listen for, e.g. the characters' names, so they are spelled right"},
        "model": {"type": "string", "required": False, "description": "tiny, base, small, medium or large-v3 (default small)"},
    },
    produces=["text/plain", "application/json"],
    needs=["faster-whisper"],
)
def transcribe(job: dict, ctx: Context) -> dict:
    """An asset's speech as text, kept as assets and named on the job's result."""
    args = job.get("args") or {}
    asset_id, name = str(args.get("audio") or ""), job["job"]
    if not asset_id:
        raise JobError("transcribe needs an audio asset")
    record = marvin_api.asset(ctx.creds, asset_id)
    ext = Path(str(record.get("originalFilename") or "audio.wav")).suffix or ".wav"
    source = ctx.work / f"source{ext}"
    marvin_api.download_asset(ctx.creds, asset_id, source)
    ctx.note(f"downloaded {record.get('name') or asset_id} ({source.stat().st_size / 1e6:.1f} MB)")
    model = load_model(str(args.get("model") or MODEL))
    made = transcribe_file(model, source, ctx.work / name, language=str(args.get("language") or "") or None, hotwords=str(args.get("hotwords") or "") or None, note=ctx.note)
    uploaded = {}
    for kind, path in made["files"].items():
        asset = marvin_api.upload_asset(
            ctx.creds,
            path,
            slug=f"{name}-{kind}",
            name=f"{LABEL[kind].capitalize()}: {record.get('name') or asset_id}",
            mime=MIME[kind],
            description=f"Speech in {record.get('name') or asset_id}, as text (faster-whisper).",
            metadata={"kind": "transcript", "source": asset_id, "language": made["language"], "seconds": made["seconds"]},
        )
        uploaded[kind] = {"id": asset["id"], "url": asset.get("publicUrl")}
    ctx.note(f"{made['segments']} segments")
    result = {"language": made["language"], "seconds": made["seconds"], "segments": made["segments"], "files": uploaded, "url": uploaded["paragraphs"]["url"]}
    return {"result": result, "log": f"{made['segments']} segments, {made['language']}, {made['seconds']} s of audio."}


def heard_words(model, audio: Path, *, language: str | None = None, hotwords: str | None = None) -> tuple[list[dict], str]:
    """Every word faster-whisper hears in `audio` with its own start and end ([{text, start, end}]), and the language."""
    segments, info = model.transcribe(str(audio), language=language or None, hotwords=hotwords or None, vad_filter=True, beam_size=5, word_timestamps=True)
    words = [{"text": str(w.word).strip(), "start": float(w.start), "end": float(w.end)} for s in segments for w in (getattr(s, "words", None) or []) if str(w.word).strip()]
    return words, str(getattr(info, "language", "") or "")


@job_kind(
    "time-words",
    description="Listen to the recording in a take and write when each word is spoken to the recording's metadata, so a caption follows the voice exactly (a take made by ElevenLabs has this already; an uploaded or recorded one does not). The words shown are the line's own written words: what is heard only gives their times",
    inputs={
        "entry": {"type": "string", "description": "the take's slug (or any entry with a recording in its audio field)"},
        "field": {"type": "string", "required": False, "description": "the field holding the recording (audio by default)"},
        "language": {"type": "string", "required": False, "description": "the spoken language as a code, e.g. en; empty to detect it"},
        "model": {"type": "string", "required": False, "description": "tiny, base, small, medium or large-v3 (default small)"},
        "report": {"type": "string", "required": False, "description": "yes to also write what was heard on the entry: the words (heard), the language, the pace (words_per_minute) and how much of the written text was said (match, percent)"},
    },
    produces=[],
    needs=["faster-whisper"],
)
def time_words(job: dict, ctx: Context) -> dict:
    """A take's recording → the time of each word of its text, written into the recording's metadata as `words`."""
    args = (job.get("args") or {}) if isinstance(job.get("args"), dict) else {}
    slug = str(args.get("entry") or "").strip()
    field = str(args.get("field") or "audio").strip()
    if not slug:
        raise JobError("this kind of job needs args.entry (the take's slug)")
    row = next(iter(marvin_api.query(ctx.creds, {"entries": slug}, limit=1)), None)
    if row is None:
        raise JobError(f"no entry “{slug}”")
    data = row.get("dataJson") or row.get("data") or {}
    held = data.get(field)
    if not held or not isinstance(held, str):
        raise JobError(f"“{slug}” has nothing in “{field}”: record or upload a sound there first")
    script = str(data.get("spoken") or data.get("text") or "").strip()
    if not script and data.get("line"):  # a take says what its line says
        line = next(iter(marvin_api.query(ctx.creds, {"entries": str(data["line"])}, limit=1)), None)
        script = str(((line or {}).get("dataJson") or {}).get("text") or "").strip()
    record = marvin_api.asset(ctx.creds, held)
    ext = Path(str(record.get("originalFilename") or "audio.wav")).suffix or ".wav"
    source = ctx.work / f"timing{ext}"
    marvin_api.download_asset(ctx.creds, record.get("id") or held, source)
    heard, language = heard_words(load_model(str(args.get("model") or MODEL)), source, language=str(args.get("language") or "") or None, hotwords=script or None)
    words = align.script_times(script, heard)
    if not words:
        raise JobError(f"no speech was heard in “{record.get('name') or held}”")
    merged = {**(record.get("metadataJson") or {}), "words": words, "words_from": "faster-whisper", "words_language": language}
    marvin_api.request(ctx.creds, f"/api/platform/assets/{record.get('id') or held}", method="PATCH", data=json.dumps({"metadata": merged}).encode(), content_type="application/json")
    told = ""
    if str(args.get("report") or "").strip().lower() in ("yes", "true", "1"):
        report = {"heard": " ".join(str(h["text"]) for h in heard).strip(), "language": language, "words_per_minute": align.words_per_minute(heard)}
        if script:
            report["match"] = align.match_percent(script, heard)
        marvin_api.update_entry(ctx.creds, slug, report)
        told = f"; {report['words_per_minute']} words a minute" + (f", {report['match']}% of the written words said" if "match" in report else "")
    note = f"{len(words)} words timed in {record.get('name') or held}" + ("" if script else " (heard, as the take has no written text)") + told
    ctx.note(note)
    return {"result": {"entry": slug, "asset": record.get("id") or held, "words": len(words), "language": language, "from_text": bool(script)}, "log": note + "."}
