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
    webm: bytes = b""
    taken_slugs: list = []

    def _json(self, status, body):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/platform/entries"):
            return self._json(200, FakeMarvin.entries)
        if self.path == "/api/platform/assets/take-1":
            return self._json(200, {"mimeType": "audio/mpeg"})
        if self.path == "/api/platform/assets/voice-1":
            return self._json(200, {"id": "voice-1", "slug": "granny-voice", "name": "Granny voice.webm", "mimeType": "video/webm"})
        if self.path == "/api/platform/assets/pic-1":
            return self._json(200, {"id": "pic-1", "slug": "pic", "name": "pic.png", "mimeType": "image/png"})
        if self.path == "/api/platform/assets/voice-1/file":
            self.send_response(200)
            self.end_headers()
            return self.wfile.write(FakeMarvin.webm)
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
        if any(f'name="slug"\r\n\r\n{taken}\r\n'.encode() in body for taken in FakeMarvin.taken_slugs):
            return self._json(409, {"detail": "A database constraint was violated."})
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
        rec = tmp_path / "r.webm"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=1", "-c:a", "libopus", str(rec)], check=True)
        FakeMarvin.webm = rec.read_bytes()
    FakeMarvin.uploads = []
    FakeMarvin.taken_slugs = []
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
def test_audio_cut_of_a_story_in_chapters_lists_where_each_starts_and_says_what_youtube_would_refuse(marvin):
    chapter = lambda n, title: {"id": f"c{n}", "slug": f"{STORY}-chapter-0{n}", "title": title, "dataJson": {"story": STORY, "number": f"0{n}"}}  # noqa: E731
    FakeMarvin.entries += [
        chapter(1, "The Voyage"),
        chapter(2, "The Island"),
        {"id": "e5", "slug": f"{STORY}-beat-02", "dataJson": {"story": STORY, "number": "02", "chapter": f"{STORY}-chapter-02"}},
        {"id": "e6", "slug": f"{STORY}-line-02-1", "dataJson": {"story": STORY, "beat": f"{STORY}-beat-02", "speaker": "narrator", "text": "Two.", "audio": "take-1"}},
    ]
    _data(f"{STORY}-beat-01")["chapter"] = f"{STORY}-chapter-01"

    serve.run_job({"kind": "audio-cut", "job": "render-job-1", "args": {"story": STORY}}, marvin)

    data = _data("render-job-1")
    lines = data["result"]["chapters"].splitlines()
    assert lines[0] == "0:00 The Voyage" and lines[1].endswith("The Island") and len(lines) == 2
    assert "YouTube needs at least 3 chapters" in data["log"]


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


def _convert_job(entry, field, **more):
    FakeMarvin.entries.append({"id": "e9", "slug": "convert-job-1", "dataJson": {"kind": "convert-audio", "status": "claimed", "args": {"entry": entry, "field": field, **more}}})
    return {"kind": "convert-audio", "job": "convert-job-1", "args": {"entry": entry, "field": field, **more}}


def _actor(asset="voice-1"):
    FakeMarvin.entries.append({"id": "e8", "slug": "granny", "title": "Granny", "dataJson": {"role": "actor", "voice_sample": asset}})


@needs_ffmpeg
def test_convert_audio_makes_an_mp3_of_a_browser_recording_and_points_the_field_at_it(marvin):
    _actor()
    serve.run_job(_convert_job("granny", "voice_sample"), marvin)

    assert _data("convert-job-1")["status"] == "done"
    result = _data("convert-job-1")["result"]
    assert result["converted"] is True and result["format"] == "mp3" and result["from"] == "voice-1" and 0.8 < result["seconds"] < 1.3
    assert _data("granny") == {"role": "actor", "voice_sample": "asset-new"}  # the field now holds the new asset, the rest is kept
    (content_type, body), = FakeMarvin.uploads
    assert b'filename="converted.mp3"' in body and b"Content-Type: audio/mpeg" in body and b"Granny voice.mp3" in body and b"granny-voice-mp3" in body


@needs_ffmpeg
def test_convert_audio_of_a_recording_already_converted_once_takes_the_next_free_slug(marvin):
    _actor()
    FakeMarvin.taken_slugs = ["granny-voice-mp3", "granny-voice-mp3-2"]
    serve.run_job(_convert_job("granny", "voice_sample"), marvin)

    assert _data("convert-job-1")["status"] == "done"
    (_, body), = FakeMarvin.uploads
    assert b"granny-voice-mp3-3" in body


@needs_ffmpeg
def test_convert_audio_can_make_m4a(marvin):
    _actor()
    serve.run_job(_convert_job("granny", "voice_sample", format="M4A"), marvin)

    assert _data("convert-job-1")["result"]["format"] == "m4a"
    (_, body), = FakeMarvin.uploads
    assert b'filename="converted.m4a"' in body and b"Content-Type: audio/mp4" in body


def test_convert_audio_leaves_a_file_that_is_already_that_format(marvin):
    FakeMarvin.entries.append({"id": "e8", "slug": "granny", "dataJson": {"voice_sample": "take-1"}})
    serve.run_job(_convert_job("granny", "voice_sample"), marvin)

    result = _data("convert-job-1")["result"]
    assert result["converted"] is False and "already mp3" in _data("convert-job-1")["log"]
    assert FakeMarvin.uploads == [] and _data("granny")["voice_sample"] == "take-1"


@pytest.mark.parametrize(
    "entry, field, more, said",
    [
        ("", "voice_sample", {}, "“entry” is needed"),
        ("granny", "", {}, "“field” is needed"),
        ("nobody", "voice_sample", {}, "no entry"),
        ("granny", "empty_field", {}, "nothing in"),
        ("granny", "voice_sample", {"format": "wav"}, "not a format"),
        ("granny", "picture", {}, "not a sound"),
    ],
)
def test_convert_audio_says_why_on_the_record_when_it_cannot(marvin, entry, field, more, said):
    FakeMarvin.entries.append({"id": "e8", "slug": "granny", "dataJson": {"voice_sample": "voice-1", "picture": "pic-1"}})
    serve.run_job(_convert_job(entry, field, **more), marvin)

    data = _data("convert-job-1")
    assert data["status"] == "failed" and said in data["log"] and FakeMarvin.uploads == []


def test_convert_audio_declares_what_it_takes_and_needs():
    from marvin_worker import jobs as worker_jobs

    (contract,) = worker_jobs.describe_kinds(["convert-audio"])

    assert set(contract["inputs"]) == {"entry", "field", "format"} and contract["needs"] == ["ffmpeg"]
    assert contract["produces"] == ["audio/mpeg", "audio/mp4"]


def _measure_job(entry, **more):
    FakeMarvin.entries.append({"id": "e7", "slug": "measure-job-1", "dataJson": {"kind": "measure-audio", "status": "claimed", "args": {"entry": entry, **more}}})
    return {"kind": "measure-audio", "job": "measure-job-1", "args": {"entry": entry, **more}}


def _take(asset="voice-1", **data):
    FakeMarvin.entries.append({"id": "e6", "slug": "granny-take-1", "title": "Take 1", "dataJson": {"line": "granny-line", "audio": asset, "status": "recorded", **data}})


@needs_ffmpeg
def test_measure_audio_writes_the_real_length_of_a_recording_to_the_take(marvin):
    _take()
    serve.run_job(_measure_job("granny-take-1"), marvin)

    assert _data("measure-job-1")["status"] == "done"
    assert _data("measure-job-1")["result"]["seconds"] == _data("granny-take-1")["duration_seconds"]
    assert 0.8 < _data("granny-take-1")["duration_seconds"] < 1.3
    assert _data("granny-take-1")["line"] == "granny-line" and _data("granny-take-1")["status"] == "recorded"  # the rest is kept
    assert FakeMarvin.uploads == []  # nothing is uploaded: the file is left as it is


@needs_ffmpeg
def test_measure_audio_can_write_to_another_field_and_read_another(marvin):
    _actor()
    serve.run_job(_measure_job("granny", field="voice_sample", seconds_field="sample_seconds"), marvin)

    assert 0.8 < _data("granny")["sample_seconds"] < 1.3 and _data("granny")["voice_sample"] == "voice-1"


def test_measure_audio_of_an_entry_with_no_recording_says_why_on_the_record(marvin):
    _take(asset="")
    serve.run_job(_measure_job("granny-take-1"), marvin)

    assert _data("measure-job-1")["status"] == "failed" and "nothing in" in str(_data("measure-job-1"))


def test_measure_audio_of_a_picture_is_refused(marvin):
    _take(asset="pic-1")
    serve.run_job(_measure_job("granny-take-1"), marvin)

    assert _data("measure-job-1")["status"] == "failed" and "not a sound" in str(_data("measure-job-1"))


def test_measure_audio_needs_an_entry():
    from marvin_worker import jobs as worker_jobs

    (contract,) = worker_jobs.describe_kinds(["measure-audio"])
    assert contract["inputs"]["entry"].get("required", True) is True and contract["inputs"]["field"]["required"] is False
    with pytest.raises(Exception):
        worker_jobs.check_args("measure-audio", {})
