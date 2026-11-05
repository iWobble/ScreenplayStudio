"""The media kinds of job, run through the generic worker core: what `audio-cut` writes back to Marvin's records."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from marvin_worker import serve

from storyrender import jobs  # noqa: F401 — importing registers the kinds

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
STORY = "the-last-onion"


class FakeMarvin(BaseHTTPRequestHandler):
    """A Marvin that remembers: records in memory, an asset upload kept, a PATCH merged."""

    entries: list = []
    uploads: list = []
    trashed: list = []
    audio: bytes = b""

    def _json(self, status, body):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/platform/entries"):
            return self._json(200, FakeMarvin.entries)
        if self.path == "/api/platform/assets/take-1":
            return self._json(200, {"mimeType": "audio/mpeg"})
        if self.path == "/api/platform/assets/take-1/file":
            self.send_response(200)
            self.end_headers()
            return self.wfile.write(FakeMarvin.audio)
        self._json(404, {})

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/api/platform/entries/query":
            wanted = json.loads(body)["spec"]["entries"]
            hits = [e for e in FakeMarvin.entries if e["slug"] == wanted]
            return self._json(200, {"entries": hits, "total": len(hits)})
        FakeMarvin.uploads.append((self.headers["Content-Type"], body))
        self._json(201, {"id": "asset-new", "publicUrl": "https://assets.example/cut.mp3"})

    def do_PATCH(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        row = next(e for e in FakeMarvin.entries if f"/{e['id']}" in self.path)
        row["dataJson"] = body["dataJson"]
        self._json(200, row)

    def do_DELETE(self):  # noqa: N802
        FakeMarvin.trashed.append(self.path.rsplit("/", 1)[-1])
        self._json(200, {"status": "ok"})

    def log_message(self, *args):
        pass


@pytest.fixture
def marvin(tmp_path):
    if shutil.which("ffmpeg"):
        tone = tmp_path / "t.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame", str(tone)], check=True)
        FakeMarvin.audio = tone.read_bytes()
    FakeMarvin.uploads = []
    FakeMarvin.entries = [
        {"id": "e0", "slug": STORY, "title": "The Last Onion", "dataJson": {}},
        {"id": "e1", "slug": f"{STORY}-beat-01", "dataJson": {"story": STORY, "number": "01"}},
        {"id": "e2", "slug": f"{STORY}-line-01-1", "dataJson": {"story": STORY, "beat": f"{STORY}-beat-01", "speaker": "narrator", "text": "One.", "audio": "take-1"}},
        {"id": "e3", "slug": f"{STORY}-line-01-2", "dataJson": {"story": STORY, "beat": f"{STORY}-beat-01", "speaker": "cook", "text": "Not yet."}},
        {"id": "e4", "slug": "render-job-1", "dataJson": {"kind": "audio-cut", "args": {"story": STORY}, "status": "claimed"}},
    ]
    server = HTTPServer(("127.0.0.1", 0), FakeMarvin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield (f"http://127.0.0.1:{server.server_port}", "tok")
    server.shutdown()


def _data(slug):
    return next(e for e in FakeMarvin.entries if e["slug"] == slug)["dataJson"]


@needs_ffmpeg
def test_audio_cut_stitches_the_recorded_lines_and_writes_audio_timeline_and_status_back(marvin):
    serve.run_job({"kind": "audio-cut", "job": "render-job-1", "args": {"story": STORY}}, marvin)

    data = _data("render-job-1")
    assert data["status"] == "done" and data["kind"] == "audio-cut"  # the rest of the record is kept
    assert data["result"]["url"] == "https://assets.example/cut.mp3"  # what an approval's player plays
    assert data["result"]["audio"] == "asset-new" and data["result"]["timeline"][0]["lines"][0]["id"] == f"{STORY}-line-01-1"
    assert f"{STORY}-line-01-2" in data["log"]  # the line with no take yet is named, not silently dropped
    (content_type, body), = FakeMarvin.uploads
    assert content_type.startswith("multipart/form-data") and b'filename="render-job-1.mp3"' in body and b"Content-Type: audio/mpeg" in body


@needs_ffmpeg
def test_audio_cut_of_a_story_that_isnt_there_says_why_on_the_record(marvin):
    serve.run_job({"kind": "audio-cut", "job": "render-job-1", "args": {"story": "no-such-story"}}, marvin)

    assert _data("render-job-1")["status"] == "failed" and "no-such-story" in _data("render-job-1")["log"]


def test_audio_cut_needs_a_story(marvin):
    serve.run_job({"kind": "audio-cut", "job": "render-job-1", "args": {}}, marvin)

    assert _data("render-job-1")["status"] == "failed" and "“story” is needed" in _data("render-job-1")["log"]


def test_audio_cut_declares_its_contract_so_a_worker_can_tell_marvin_what_it_takes_and_needs():
    from marvin_worker import jobs as worker_jobs

    (contract,) = worker_jobs.describe_kinds(["audio-cut"])

    assert contract["inputs"]["story"]["required"] is True and contract["produces"] == ["audio/mpeg"] and contract["needs"] == ["ffmpeg"]
    assert "story" in worker_jobs.META["audio-cut"]["inputs"]


needs_screenplain = pytest.mark.skipif(shutil.which("screenplain") is None, reason="screenplain not installed")


@needs_screenplain
def test_script_makes_fountain_pdf_and_html_and_names_them_on_the_story(marvin):
    FakeMarvin.entries.append({"id": "e5", "slug": "render-job-2", "dataJson": {"kind": "script", "args": {"story": STORY}, "status": "claimed"}})

    serve.run_job({"kind": "script", "job": "render-job-2", "args": {"story": STORY}}, marvin)

    data = _data("render-job-2")
    assert data["status"] == "done" and data["result"]["beats"] == 1 and set(data["result"]["urls"]) == {"fountain", "pdf", "html", "breakdown"}
    uploaded = b"".join(body for _type, body in FakeMarvin.uploads)
    assert b"Content-Type: application/pdf" in uploaded and b"Content-Type: text/html" in uploaded and b"%PDF" in uploaded
    assert all(f"script_{kind}" in _data(STORY) for kind in ("fountain", "pdf", "html", "breakdown"))  # named on the story, where a publish step finds them


def test_script_of_a_story_that_isnt_there_says_why_on_the_record(marvin):
    FakeMarvin.entries.append({"id": "e5", "slug": "render-job-2", "dataJson": {"kind": "script", "args": {"story": "nope"}, "status": "claimed"}})

    serve.run_job({"kind": "script", "job": "render-job-2", "args": {"story": "nope"}}, marvin)

    assert _data("render-job-2")["status"] == "failed" and "nope" in _data("render-job-2")["log"]


def test_script_declares_what_it_takes_gives_and_needs():
    from marvin_worker import jobs as worker_jobs

    (contract,) = worker_jobs.describe_kinds(["script"])

    assert contract["inputs"]["story"]["required"] is True and contract["needs"] == ["screenplain"]
    assert contract["produces"] == ["text/plain", "application/pdf", "text/html"]


@needs_screenplain
def test_making_the_script_again_trashes_the_copies_it_replaces(marvin):
    story = next(e for e in FakeMarvin.entries if e["slug"] == STORY)
    story["dataJson"] = {**story["dataJson"], "script_pdf": "old-pdf", "script_html": "old-html", "script_fountain": "asset-new"}
    FakeMarvin.entries.append({"id": "e6", "slug": "render-job-3", "dataJson": {"kind": "script", "args": {"story": STORY}, "status": "claimed"}})
    FakeMarvin.trashed.clear()

    serve.run_job({"kind": "script", "job": "render-job-3", "args": {"story": STORY}}, marvin)

    assert sorted(FakeMarvin.trashed) == ["old-html", "old-pdf"]  # the fountain's id did not change, so it is not trashed


def test_import_voices_needs_no_arguments():
    from marvin_worker import jobs as worker_jobs

    (contract,) = worker_jobs.describe_kinds(["import-voices"])
    assert contract["inputs"]["search"]["required"] is False
    worker_jobs.check_args("import-voices", {})  # raises if an argument were needed
