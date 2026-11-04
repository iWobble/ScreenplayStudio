"""`listen` (the sound alone, stitched, with a timeline naming each line) and `pull` (Marvin's recorded lines → a manifest)."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from storyrender import build, ffmpeg, manifest, marvin_pull

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def _tone(path: Path, seconds: float, hz: int = 440) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", "-c:a", "libmp3lame", str(path)], check=True
    )
    return path


@needs_ffmpeg
def test_listen_stitches_the_lines_with_the_planned_timing_and_names_each_one(tmp_path):
    _tone(tmp_path / "a.mp3", 1.0)
    _tone(tmp_path / "b.mp3", 0.5, 660)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "shots": [
                    {"id": "b01", "lines": [{"id": "line-01-1", "audio": "a.mp3", "text": "One.", "speaker": "narrator"}]},
                    {"id": "b02", "lines": [{"id": "line-02-1", "audio": "b.mp3", "text": "Two.", "speaker": "cook"}]},
                ]
            }
        )
    )
    m = manifest.load(tmp_path / "manifest.json", probe=ffmpeg.duration, need_stills=False)  # no stills: only the sound is made

    result = build.listen(m, tmp_path / "rough.mp3")

    planned = manifest.plan(m)
    assert result["seconds"] == pytest.approx(planned.duration, abs=0.3)
    first, second = (shot["lines"][0] for shot in result["timeline"])
    assert (first["id"], first["speaker"], first["start"]) == ("line-01-1", "narrator", pytest.approx(manifest.LEAD, abs=0.01))
    assert second["id"] == "line-02-1" and second["start"] == pytest.approx(planned.shots[1].start + manifest.LEAD, abs=0.01)
    assert second["end"] - second["start"] == pytest.approx(0.5, abs=0.05)


def test_a_timecode_reads_like_a_player(tmp_path):
    assert build.timecode(41.04) == "0:41.0" and build.timecode(75.5) == "1:15.5"


@needs_ffmpeg
def test_a_manifest_with_no_stills_still_needs_them_to_render(tmp_path):
    _tone(tmp_path / "a.mp3", 0.5)
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "b01", "lines": [{"audio": "a.mp3", "text": "x"}]}]}))
    with pytest.raises(manifest.ManifestError, match="no still"):
        manifest.load(tmp_path / "m.json", probe=ffmpeg.duration)


class _FakeMarvin(BaseHTTPRequestHandler):
    seen_agents: list = []
    audio = b"ID3 not really audio"

    def do_GET(self):  # noqa: N802
        _FakeMarvin.seen_agents.append(self.headers.get("User-Agent"))
        S = "the-last-onion"
        routes = {
            "/api/platform/entries?limit=500": [
                {"slug": S, "title": "The Last Onion", "dataJson": {}},
                {"slug": f"{S}-beat-02", "dataJson": {"story": S, "number": "02"}},
                {"slug": f"{S}-beat-01", "dataJson": {"story": S, "number": "01"}},
                {"slug": f"{S}-line-01-1", "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "narrator", "text": "One.", "audio": "asset-1"}},
                {"slug": f"{S}-line-02-1", "dataJson": {"story": S, "beat": f"{S}-beat-02", "speaker": "cook", "text": "Two."}},  # not recorded
                {"slug": "other-story-line-01-1", "dataJson": {"story": "other-story", "beat": "x", "audio": "asset-9"}},
            ],
            "/api/platform/assets/asset-1": {"mimeType": "audio/mpeg"},
        }
        if self.path == "/api/platform/assets/asset-1/file":
            body = self.audio
        elif self.path in routes:
            body = json.dumps(routes[self.path]).encode()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def marvin():
    server = HTTPServer(("127.0.0.1", 0), _FakeMarvin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeMarvin.seen_agents = []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_pull_writes_a_manifest_of_the_recorded_lines_in_beat_order_and_names_the_rest(marvin, tmp_path):
    result = marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))

    assert result["shots"] == 1 and result["lines"] == 1 and result["not_recorded"] == ["the-last-onion-line-02-1"]
    written = json.loads((tmp_path / "manifest.json").read_text())
    (shot,) = written["shots"]
    assert shot["id"] == "b01" and shot["lines"][0]["id"] == "the-last-onion-line-01-1" and shot["lines"][0]["speaker"] == "narrator"
    assert (tmp_path / shot["lines"][0]["audio"]).read_bytes() == _FakeMarvin.audio
    assert all(agent and "marvin-worker" in agent for agent in _FakeMarvin.seen_agents)  # the default Python agent is refused by Marvin's edge


def test_pull_says_so_when_nothing_is_recorded_or_the_story_is_unknown(marvin, tmp_path):
    with pytest.raises(marvin_pull.PullError, match="no story"):
        marvin_pull.pull("nope", tmp_path, creds=(marvin, "tok"))
