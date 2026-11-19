"""Every file a Studio job uploads says what made it, so a workflow that acts on a person's own new recordings (the Media package's) can leave the
workers' files alone: each carries a `kind` in its metadata, and one made from a single other asset names it in `derived_from` (Marvin then records
it as that asset's version). The voice previews `import-voices` brought in carried nothing, and looked like a person's upload."""

import ast
import io
import json
from pathlib import Path

from marvin_worker.jobs import Context

from storyrender import audio_convert, jobs

SOURCES = [Path(jobs.__file__), Path(__file__).parents[2] / "transcribe" / "storytranscribe" / "jobs.py"]


def _uploads(path: Path) -> list[tuple[int, ast.Call]]:
    calls = [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "upload_asset"]
    return [(c.lineno, c) for c in calls]


def _metadata_keys(call: ast.Call) -> set[str]:
    meta = next((k.value for k in call.keywords if k.arg == "metadata"), None)
    return {k.value for k in meta.keys if isinstance(k, ast.Constant)} if isinstance(meta, ast.Dict) else set()


def test_every_upload_a_job_makes_names_its_kind():
    """A new upload added to a job without a `kind` fails here (the worker's own `metadata.worker` stamp is a second guard, not a reason to skip it)."""
    found = {(p.parent.name, line): _metadata_keys(call) for p in SOURCES for line, call in _uploads(p)}
    assert len(found) == 9, sorted(found)  # the audit: 8 in storyrender, 1 in storytranscribe
    assert [where for where, keys in found.items() if "kind" not in keys] == []


def test_a_file_made_from_one_recording_names_it_and_the_rest_do_not():
    """Converted audio, a transcript's files and a clip's poster are each made from one asset: a version of it. An audio cut, a script, a
    filmstrip, subtitles and a video are made from a whole story, so they are no one asset's version."""
    derived = sorted(p.parent.name for p in SOURCES for _line, call in _uploads(p) if "derived_from" in _metadata_keys(call))
    assert derived == ["storyrender", "storyrender", "storytranscribe"]


class _Voices(Context):
    def marvin(self, *args: str) -> object:
        if args[:3] == ("platform", "integrations", "run"):
            return {"result": {"voices": [{"voice_id": "el-123", "name": "Brian - Deep, Resonant", "preview_url": "https://example.test/brian.mp3", "labels": {}}]}}
        return {"id": "tag-1"}


def test_a_voice_preview_says_it_is_one(tmp_path, monkeypatch):
    api, uploaded = jobs.marvin_api, []
    monkeypatch.setattr(api, "entries", lambda creds: [])
    monkeypatch.setattr(jobs.urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b"ID3 preview"))

    def request(creds, path, *, method="GET", data=None, content_type=None, **_kw):
        if path == "/api/platform/entry-types":
            return json.dumps([{"slug": "voice", "id": "type-voice"}]).encode()
        return json.dumps({"id": "entry-1"}).encode()

    monkeypatch.setattr(api, "request", request)
    monkeypatch.setattr(api, "upload_asset", lambda creds, file, **kw: uploaded.append(kw) or {"id": "preview-1"})

    jobs.import_voices({"job": "import-voices-1", "args": {}}, _Voices(creds=("http://m", "t"), work=tmp_path))

    (preview,) = uploaded
    assert preview["metadata"] == {"kind": "voice-preview", "voice": preview["slug"].removesuffix("-clip"), "elevenlabs_voice_id": "el-123"}


def test_converted_audio_is_a_version_of_the_recording(tmp_path, monkeypatch):
    api, uploaded, written = jobs.marvin_api, [], []
    source = {"id": "a6e76f6c-1362-43f3-8bfa-c11642c974d2", "slug": "take-3", "name": "take 3.webm", "mimeType": "audio/webm"}
    monkeypatch.setattr(api, "query", lambda creds, spec, limit=100: [{"slug": "line-1-take-3", "dataJson": {"audio": "take-3"}}])
    monkeypatch.setattr(api, "asset", lambda creds, ref: source)
    monkeypatch.setattr(api, "download_asset", lambda creds, ref, dest: dest.write_bytes(b"webm"))
    monkeypatch.setattr(audio_convert, "convert", lambda src, out, fmt: out.write_bytes(b"mp3") and 2.5)
    monkeypatch.setattr(api, "upload_asset", lambda creds, file, **kw: uploaded.append(kw) or {"id": "converted-1"})
    monkeypatch.setattr(api, "update_entry", lambda creds, slug, changes: written.append(changes))

    jobs.convert_audio({"job": "convert-1", "args": {"entry": "line-1-take-3", "field": "audio"}}, Context(creds=("http://m", "t"), work=tmp_path))

    (made,) = uploaded
    assert made["metadata"]["kind"] == "converted-audio" and made["metadata"]["derived_from"] == source["id"] == made["metadata"]["from"]
    assert written == [{"audio": "converted-1"}]
