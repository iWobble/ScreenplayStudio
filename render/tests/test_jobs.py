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

    assert _data("render-job-1")["status"] == "failed" and "args.story" in _data("render-job-1")["log"]
