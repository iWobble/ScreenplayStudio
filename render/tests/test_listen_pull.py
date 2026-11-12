"""`listen` (the sound alone, stitched, with a timeline naming each line) and `pull` (Marvin's recorded lines → a manifest)."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from storyrender import build, camera, ffmpeg, manifest, marvin_pull

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


@needs_ffmpeg
def test_a_lead_in_with_a_sound_effect_puts_the_sound_first_and_the_line_after_it_on_the_timeline(tmp_path):
    _tone(tmp_path / "waves.mp3", 2.5, 220)
    _tone(tmp_path / "a.mp3", 1.0)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "shots": [
                    {"id": "b02", "lead": 3.0, "sfx": [{"id": "harbour", "audio": "waves.mp3", "at": 0, "volume": 0.5}], "lines": [{"id": "line-02-1", "audio": "a.mp3", "text": "Tonight.", "speaker": "narrator"}]},
                    {"id": "b15", "sfx": [{"id": "knife", "audio": "waves.mp3", "at": 0.3}], "lines": []},  # sound only
                ]
            }
        )
    )
    m = manifest.load(tmp_path / "manifest.json", probe=ffmpeg.duration, need_stills=False)

    result = build.listen(m, tmp_path / "rough.mp3")

    first, second = result["timeline"]
    assert first["sounds"][0]["id"] == "harbour" and first["sounds"][0]["start"] == 0 and first["sounds"][0]["end"] == pytest.approx(2.5, abs=0.05)
    assert first["lines"][0]["start"] == pytest.approx(3.0, abs=0.01)  # the line waits for the lead-in
    assert second["sounds"][0]["id"] == "knife" and second["lines"] == [] and second["sounds"][0]["start"] == pytest.approx(first["start"] + 3.0 + 1.0 + 0.35 + 0.3, abs=0.2)
    assert result["seconds"] == pytest.approx(manifest.plan(m).duration, abs=0.3)


def _mean_db(path: Path, start: float, length: float) -> float:
    """How loud a stretch of a file is (ffmpeg's mean volume, dB)."""
    out = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(out.split("mean_volume:")[1].split("dB")[0])


def _ambient_story(tmp_path, *, inside_muffled: bool) -> Path:
    """Silence for narration so only the ambience is heard: an outside shot, then two inside shots (the second one quieter still)."""
    _tone(tmp_path / "sea.mp3", 3.0, 3000)  # a high tone: the muffle must take it down
    shot = lambda sid, volume, muffled: {  # noqa: E731
        "id": sid, "lines": [{"id": f"line-{sid}", "duration": 4.0, "text": "silence"}],
        "ambience": {"id": "harbour", "audio": "sea.mp3", "volume": volume, "muffled": muffled},
    }  # fmt: skip
    (tmp_path / "m.json").write_text(json.dumps({"shots": [shot("out", 0.6, False), shot("in1", 0.3, inside_muffled), shot("in2", 0.1, inside_muffled)]}))
    return tmp_path / "m.json"


@needs_ffmpeg
def test_the_harbour_is_loud_outside_and_muffled_and_low_inside_with_the_cut_no_longer(tmp_path):
    m = manifest.load(_ambient_story(tmp_path, inside_muffled=True), probe=ffmpeg.duration, need_stills=False)
    result = build.listen(m, tmp_path / "cut.mp3")
    plan = manifest.plan(m)
    out_start, in1_start, in2_start = (s.start for s in plan.shots)

    outside = _mean_db(tmp_path / "cut.mp3", out_start + 1.0, 2.0)
    inside = _mean_db(tmp_path / "cut.mp3", in1_start + 1.0, 2.0)
    assert outside - inside > 15  # loud outside; inside is far lower (a lower level, and the highs taken off)
    assert result["seconds"] == pytest.approx(plan.duration, abs=0.3)  # the beds never make the cut longer
    assert [(b["id"], b["muffled"]) for b in result["ambience"]] == [("harbour", False), ("harbour", True)]  # the place changed: two beds
    assert [lv[2] for lv in result["ambience"][1]["levels"]] == [0.3, 0.1]  # one continuous inside bed, a quieter step for the second shot
    assert _mean_db(tmp_path / "cut.mp3", in2_start + 1.0, 2.0) < inside - 4  # ...and it is quieter there


@needs_ffmpeg
def test_muffling_takes_the_highs_off_the_same_sound_at_the_same_level(tmp_path):
    clear = build.listen(manifest.load(_ambient_story(tmp_path, inside_muffled=False), probe=ffmpeg.duration, need_stills=False), tmp_path / "clear.mp3")
    muffled = build.listen(manifest.load(_ambient_story(tmp_path, inside_muffled=True), probe=ffmpeg.duration, need_stills=False), tmp_path / "muffled.mp3")
    start = manifest.plan(manifest.load(tmp_path / "m.json", probe=ffmpeg.duration, need_stills=False)).shots[1].start + 1.0

    assert _mean_db(tmp_path / "clear.mp3", start, 2.0) - _mean_db(tmp_path / "muffled.mp3", start, 2.0) > 12  # a 3 kHz tone through a 700 Hz low-pass
    assert len(clear["ambience"]) == 1 and len(muffled["ambience"]) == 2  # unmuffled, one bed runs under the whole thing


def test_consecutive_shots_with_the_same_sound_share_one_bed_and_a_change_of_place_starts_another():
    amb = lambda audio, muffled=False, volume=0.5: manifest.Ambience(Path(audio), volume, muffled, "x")  # noqa: E731
    shots = [
        manifest.Shot("a", Path(), lines=[manifest.Line("a", duration=2.0)], ambience=amb("sea.mp3")),
        manifest.Shot("b", Path(), lines=[manifest.Line("b", duration=2.0)], ambience=amb("sea.mp3", volume=0.2)),  # same bed, a different level
        manifest.Shot("c", Path(), lines=[manifest.Line("c", duration=2.0)]),  # no ambience: the bed ends
        manifest.Shot("d", Path(), lines=[manifest.Line("d", duration=2.0)], ambience=amb("sea.mp3")),  # the same sound again, but not adjacent
    ]

    runs = build.beds(manifest.plan(manifest.Manifest("t", (1080, 1920), 30, shots)))

    assert len(runs) == 2 and len(runs[0].levels) == 2 and [lv[2] for lv in runs[0].levels] == [0.5, 0.2]


def test_a_timecode_reads_like_a_player(tmp_path):
    assert build.timecode(41.04) == "0:41.0" and build.timecode(75.5) == "1:15.5"


@needs_ffmpeg
def test_a_manifest_with_no_stills_still_needs_them_to_render(tmp_path):
    _tone(tmp_path / "a.mp3", 0.5)
    (tmp_path / "m.json").write_text(json.dumps({"shots": [{"id": "b01", "lines": [{"audio": "a.mp3", "text": "x"}]}]}))
    with pytest.raises(manifest.ManifestError, match="no still"):
        manifest.load(tmp_path / "m.json", probe=ffmpeg.duration)


S = "the-last-onion"
_ROWS = [

                {"slug": S, "title": "The Last Onion", "dataJson": {}},
                {"slug": f"{S}-beat-02", "dataJson": {"story": S, "number": "02"}},
                {"slug": f"{S}-beat-01", "dataJson": {"story": S, "number": "01", "scene": f"{S}-cabin", "ambience_volume": 0.05, "lead_seconds": 2.5, "tail_seconds": 0.5, "sounds": [{"sound": f"{S}-sound-waves", "at": 0, "volume": 0.4}]}},
                {"slug": f"{S}-beat-03", "dataJson": {"story": S, "number": "03", "scene": f"{S}-deck", "hold_seconds": 6, "sounds": [{"sound": f"{S}-sound-waves", "at": 0.3}, {"sound": f"{S}-sound-not-made", "at": 1}, {"sound": "porridge-sound-spoon", "at": 2}]}},
{"slug": "porridge-sound-spoon", "dataJson": {"audio": "asset-1", "volume": 0.5}},  # a library sound: no story, another story's name
                {"slug": f"{S}-sound-waves", "dataJson": {"story": S, "audio": "asset-1", "volume": 0.7}},
                {"slug": f"{S}-cabin", "dataJson": {"story": S, "ambience": f"{S}-sound-waves", "ambience_volume": 0.12, "ambience_muffled": True}},
                {"slug": f"{S}-deck", "dataJson": {"story": S, "ambience": f"{S}-sound-waves"}},
                {"slug": f"{S}-sound-not-made", "dataJson": {"story": S}},
                {"slug": f"{S}-line-01-1", "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "narrator", "text": "One.", "audio": "asset-1"}},
                {"slug": f"{S}-line-02-1", "dataJson": {"story": S, "beat": f"{S}-beat-02", "speaker": "cook", "text": "Two."}},  # not recorded
                {"slug": "other-story-line-01-1", "dataJson": {"story": "other-story", "beat": "x", "audio": "asset-9"}}
]


class _FakeMarvin(BaseHTTPRequestHandler):
    seen_agents: list = []
    audio = b"ID3 not really audio"
    rows = _ROWS

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        wanted = body["spec"]["entries"]
        hits = [e for e in _FakeMarvin.rows if e["slug"] in wanted]
        payload = json.dumps({"entries": hits, "total": len(hits)}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        _FakeMarvin.seen_agents.append(self.headers.get("User-Agent"))
        routes = {
            "/api/platform/entries?limit=500": _FakeMarvin.rows,
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

    assert result["shots"] == 2 and result["lines"] == 1 and result["not_recorded"] == ["the-last-onion-line-02-1", "the-last-onion-sound-not-made"]
    written = json.loads((tmp_path / "manifest.json").read_text())
    shot, silent = written["shots"]
    assert shot["id"] == "b01" and shot["lines"][0]["id"] == "the-last-onion-line-01-1" and shot["lines"][0]["speaker"] == "narrator"
    assert (shot["lead"], shot["tail"], "gap" in shot) == (2.5, 0.5, False)  # the beat's own timing; a blank one keeps the default
    assert shot["sfx"][0]["id"] == "the-last-onion-sound-waves" and shot["sfx"][0]["volume"] == 0.4 and (tmp_path / shot["sfx"][0]["audio"]).read_bytes() == _FakeMarvin.audio  # the beat's volume wins
    assert silent["id"] == "b03" and silent["lines"] == [] and silent["hold"] == 6 and silent["sfx"][0]["volume"] == 0.7  # sound only: the sound's own volume
    assert [fx["id"] for fx in silent["sfx"]] == ["the-last-onion-sound-waves", "porridge-sound-spoon"]  # found by the slug the beat names, whichever story made it
    assert (shot["ambience"]["volume"], shot["ambience"]["muffled"]) == (0.05, True)  # the beat's own level beats the scene's (the cabin goes quiet), still heard from inside
    assert (silent["ambience"]["volume"], silent["ambience"]["muffled"]) == (0.7, False)  # an outside scene with no level of its own: the sound's volume, not muffled
    assert (tmp_path / shot["ambience"]["audio"]).read_bytes() == _FakeMarvin.audio
    assert (tmp_path / shot["lines"][0]["audio"]).read_bytes() == _FakeMarvin.audio
    assert all(agent and "marvin-worker" in agent for agent in _FakeMarvin.seen_agents)  # the default Python agent is refused by Marvin's edge


def test_pull_says_so_when_nothing_is_recorded_or_the_story_is_unknown(marvin, tmp_path):
    with pytest.raises(marvin_pull.PullError, match="no story"):
        marvin_pull.pull("nope", tmp_path, creds=(marvin, "tok"))


def test_pull_passes_a_beats_camera_move_and_keeps_a_silent_held_beat(marvin, tmp_path):
    rows = [dict(r) for r in _ROWS]
    rows.append({"slug": f"{S}-beat-04", "dataJson": {"story": S, "number": "04", "hold_seconds": 4, "move": {"from": {"x": 0.8, "y": 0.38, "zoom": 1.35}, "to": {"x": 0.8, "y": 0.36, "zoom": 1.8}}}})
    rows.append({"slug": f"{S}-beat-05", "dataJson": {"story": S, "number": "05"}})  # nothing to hear and no time asked for: left out
    _FakeMarvin.rows = rows
    try:
        marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    shots = {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}
    assert "b05" not in shots
    assert shots["b04"]["hold"] == 4 and shots["b04"]["lines"] == [] and shots["b04"]["move"]["to"]["zoom"] == 1.8
    assert "move" not in shots["b01"]  # a beat with no move keeps the render's default


def test_pull_gives_each_beat_its_camera_preset_from_itself_else_its_scene_else_the_story_and_a_move_of_its_own_wins(marvin, tmp_path):
    rows = [dict(r) for r in _ROWS]
    rows[0] = {**rows[0], "dataJson": {"camera": "drift"}}  # the story's own
    rows += [
        {"slug": f"{S}-ledge", "dataJson": {"story": S, "camera": "tilt-up"}},
        {"slug": f"{S}-beat-04", "dataJson": {"story": S, "number": "04", "hold_seconds": 2, "camera": "pan-left", "scene": f"{S}-ledge"}},
        {"slug": f"{S}-beat-05", "dataJson": {"story": S, "number": "05", "hold_seconds": 2, "scene": f"{S}-ledge"}},
        {"slug": f"{S}-beat-06", "dataJson": {"story": S, "number": "06", "hold_seconds": 2}},
        {"slug": f"{S}-beat-07", "dataJson": {"story": S, "number": "07", "hold_seconds": 2, "camera": "push-in", "move": {"from": {"x": 0.2, "y": 0.2, "zoom": 1.5}, "to": {"x": 0.3, "y": 0.2, "zoom": 1.5}}}},
        {"slug": f"{S}-beat-08", "dataJson": {"story": S, "number": "08", "hold_seconds": 2, "camera": "wobble"}},
    ]
    _FakeMarvin.rows = rows
    try:
        marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    shots = {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}
    assert shots["b04"]["move"] == camera.move_of("pan-left")  # the beat's own preset
    assert shots["b05"]["move"] == camera.move_of("tilt-up")  # else its scene's
    assert shots["b06"]["move"] == camera.move_of("drift")  # else the story's
    assert shots["b07"]["move"]["from"]["x"] == 0.2  # a move written out beats any preset
    assert shots["b08"]["move"] == camera.move_of("drift")  # a name that is no preset is skipped, so the story's holds


def test_a_beat_with_a_picture_and_nothing_else_plays_for_the_default_hold_and_a_beat_with_nothing_is_named_as_left_out(marvin, tmp_path, monkeypatch):
    def fake_fetch(creds, asset_id, dest_stem, ext):
        dest = Path(str(dest_stem) + ".png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")
        return dest

    monkeypatch.setattr(marvin_pull, "_fetch_asset", fake_fetch)
    rows = [dict(r) for r in _ROWS]
    rows.append({"slug": f"{S}-beat-06", "dataJson": {"story": S, "number": "06", "still": "asset-6"}})  # a quiet establishing shot: a picture, no words, no sound, no hold set
    rows.append({"slug": f"{S}-beat-07", "dataJson": {"story": S, "number": "07"}})  # nothing at all
    _FakeMarvin.rows = rows
    try:
        result = marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
    finally:
        _FakeMarvin.rows = _ROWS
    shots = {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}
    assert shots["b06"]["hold"] == marvin_pull.DEFAULT_HOLD == 4.0 and shots["b06"]["lines"] == []
    assert "b07" not in shots and "07" in result["skipped"] and "06" not in result["skipped"]


def test_pull_passes_a_lines_own_level_and_muffling_and_leaves_a_plain_line_alone(marvin, tmp_path):
    rows = [dict(r, dataJson=dict(r["dataJson"])) for r in _ROWS]
    line = next(r for r in rows if r["slug"] == f"{S}-line-01-1")
    line["dataJson"].update({"volume": 0.4, "muffled": True})
    _FakeMarvin.rows = rows
    try:
        marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
        said = json.loads((tmp_path / "manifest.json").read_text())["shots"][0]["lines"][0]
        assert (said["volume"], said["muffled"]) == (0.4, True)  # whichever take is in use, the line is mixed this way
    finally:
        _FakeMarvin.rows = _ROWS
    marvin_pull.pull("the-last-onion", tmp_path, creds=(marvin, "tok"))
    plain = json.loads((tmp_path / "manifest.json").read_text())["shots"][0]["lines"][0]
    assert "volume" not in plain and "muffled" not in plain
