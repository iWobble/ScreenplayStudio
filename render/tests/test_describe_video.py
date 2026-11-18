"""A beat's clip is described when it is set or changed: `describe-video` writes its length, size, sound and a poster to the beat and to the
video's own metadata, and queues `transcribe-clip` for a clip with sound; the package's workflows start it on a change of the clip only."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from marvin_worker.jobs import META, Context, JobError

from storyrender import clip, jobs
from tests.test_clip import _clip_file
from tests.test_world_context import BLUEPRINTS

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
FACTS = {"clip_seconds", "clip_width", "clip_height", "clip_has_audio", "clip_poster"}


def _turned(src: Path, out: Path, degrees: int) -> Path:
    """`src` stored as it is with a player's turn on it, as a phone stores a portrait take (side data; a `rotate` tag on an older ffmpeg)."""
    done = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", str(degrees), "-i", str(src), "-c", "copy", str(out)], capture_output=True)
    if done.returncode != 0:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c", "copy", "-metadata:s:v:0", f"rotate={degrees}", str(out)], check=True)
    return out


def _size(image: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(image) as im:
        return im.size


# ── what a clip is ───────────────────────────────────────────────────────────
@needs_ffmpeg
def test_a_clip_with_sound_is_measured_as_a_player_shows_it(tmp_path):
    facts = clip.describe(_clip_file(tmp_path / "c.mp4", 2.0))
    assert facts == {"duration_seconds": pytest.approx(2.0, abs=0.06), "width": 160, "height": 120, "fps": 30.0, "has_audio": True}


@needs_ffmpeg
def test_a_clip_without_sound_says_so(tmp_path):
    facts = clip.describe(_clip_file(tmp_path / "c.mp4", 1.5, sound=False))
    assert facts["has_audio"] is False and facts["duration_seconds"] == pytest.approx(1.5, abs=0.06) and (facts["width"], facts["height"]) == (160, 120)


@needs_ffmpeg
@pytest.mark.parametrize("degrees", [90, -90, 180])
def test_a_phones_turned_take_reads_in_the_shape_it_plays(tmp_path, degrees):
    turned = _turned(_clip_file(tmp_path / "c.mp4", 1.0), tmp_path / "t.mp4", degrees)
    facts = clip.describe(turned)
    assert (facts["width"], facts["height"]) == ((160, 120) if degrees == 180 else (120, 160))
    assert _size(clip.poster(turned, facts["duration_seconds"], tmp_path / "p.jpg")) == (facts["width"], facts["height"])  # the poster is turned too


@needs_ffmpeg
@pytest.mark.parametrize("sound", [True, False])
def test_a_browser_webm_with_no_length_in_its_header_is_measured_and_pictured(tmp_path, sound):
    webm = _clip_file(tmp_path / "c.webm", 2.5, sound=sound, piped=True)
    assert json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(webm)], capture_output=True, text=True).stdout)["format"].get("duration") in (None, "N/A")
    facts = clip.describe(webm)
    assert facts["duration_seconds"] == pytest.approx(2.5, abs=0.1) and facts["has_audio"] is sound and facts["fps"] == pytest.approx(30, abs=0.5)
    poster = clip.poster(webm, facts["duration_seconds"], tmp_path / "p.jpg")
    assert poster.read_bytes()[:2] == b"\xff\xd8" and _size(poster) == (160, 120)


def test_the_poster_is_a_second_in_or_the_middle_of_a_short_clip_and_the_frame_rate_ignores_a_time_base():
    assert clip.poster_at(10) == 1.0 and clip.poster_at(2) == 1.0 and clip.poster_at(1.2) == pytest.approx(0.6) and clip.poster_at(0) == 0
    assert clip._rate("30000/1001") == pytest.approx(29.97, abs=0.01) and clip._rate("1000/1") is None and clip._rate("0/0") is None and clip._rate("") is None
    assert clip._turn({"side_data_list": [{"rotation": -90}]}) == 270 and clip._turn({"tags": {"rotate": "90"}}) == 90 and clip._turn({}) == 0


@needs_ffmpeg
def test_a_picture_with_no_video_in_it_is_refused(tmp_path):
    sound = tmp_path / "s.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", str(sound)], check=True)
    with pytest.raises(Exception, match="no picture"):
        clip.describe(sound)


# ── the job ──────────────────────────────────────────────────────────────────
class _Marvin:
    """The beat, the assets and what the job writes, as Marvin would hold them. `swap_after` changes the beat's clip after that many reads."""

    def __init__(self, data: dict, file: Path | None = None, *, swap_after: int | None = None):
        self.beat = {"id": "beat-id", "slug": "b04", "title": "Beat 4", "dataJson": dict(data)}
        self.file, self.swap_after, self.reads = file, swap_after, 0
        self.patched, self.uploaded, self.deleted, self.made, self.asset_meta = [], [], [], [], {}
        self.assets = {"vid-1": {"id": "vid-1", "name": "me.webm", "mimeType": "video/webm", "metadataJson": {"recording": {"source": "browser"}}}, "old-poster": {"id": "old-poster", "metadataJson": {"kind": "clip-poster", "beat": "b04"}}, "mine": {"id": "mine", "metadataJson": {}}}

    def wire(self, monkeypatch):
        api = jobs.marvin_api
        monkeypatch.setattr(api, "query", self.query)
        monkeypatch.setattr(api, "asset", lambda creds, ref: self.assets[ref])
        monkeypatch.setattr(api, "download_asset", lambda creds, ref, dest: shutil.copy(self.file, dest))
        monkeypatch.setattr(api, "upload_asset", self.upload)
        monkeypatch.setattr(api, "request", self.request)
        monkeypatch.setattr(api, "create_entry", lambda creds, type_id, slug, title, data, status="draft": self.made.append((type_id, slug, title, data)) or {"slug": slug})
        monkeypatch.setattr(api, "update_entry", lambda *a, **k: pytest.fail("the beat is written as it is now, through one PATCH"))
        return self

    def query(self, creds, spec, limit=100):
        self.reads += 1
        if self.swap_after is not None and self.reads > self.swap_after:
            self.beat["dataJson"]["clip"] = "vid-2"
        return [json.loads(json.dumps(self.beat))] if spec.get("entries") == "b04" else []

    def upload(self, creds, file, *, slug, name, mime, description="", metadata=None):
        self.uploaded.append({"slug": slug, "mime": mime, "metadata": metadata, "bytes": file.read_bytes()[:2]})
        made = {"id": f"poster-{len(self.uploaded)}", "metadataJson": metadata or {}}
        self.assets[made["id"]] = made
        return made

    def request(self, creds, path, method="GET", data=None, content_type=None):
        if path == "/api/platform/entry-types":
            return json.dumps([{"slug": "beat", "id": "t-beat"}, {"slug": "job", "id": "t-job"}]).encode()
        if method == "PATCH" and path.startswith("/api/platform/entries/"):
            body = json.loads(data)
            self.patched.append(body["dataJson"])
            self.beat["dataJson"] = body["dataJson"]
        elif method == "PATCH" and path.startswith("/api/platform/assets/"):
            self.asset_meta[path.rsplit("/", 1)[1]] = json.loads(data)["metadata"]
        elif method == "DELETE":
            self.deleted.append(path.rsplit("/", 1)[1])
        return b"{}"


def _run(args: dict, tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)  # a worker hands each job its own scratch folder
    return jobs.describe_video({"job": "describe-clip-1", "args": {"entry": "b04", "field": "clip", **args}}, Context(creds=("http://m", "t"), work=tmp_path, name="describe-clip-1"))


@needs_ffmpeg
def test_the_job_writes_the_clips_facts_to_the_beat_and_the_video_and_asks_for_the_words(tmp_path, monkeypatch):
    m = _Marvin({"clip": "vid-1", "clip_start": 0.5, "clip_poster": "old-poster", "clip_text": "the last clip's words", "clip_words": [{"word": "x"}]}, _clip_file(tmp_path / "src.webm", 2.0, piped=True)).wire(monkeypatch)
    done = _run({"clip": "vid-1"}, tmp_path / "w")
    (beat,) = m.patched
    assert beat["clip"] == "vid-1" and beat["clip_start"] == 0.5  # the clip and the person's own settings are left as they are
    assert beat["clip_seconds"] == pytest.approx(2.0, abs=0.1) and (beat["clip_width"], beat["clip_height"]) == (160, 120) and beat["clip_has_audio"] is True
    assert beat["clip_poster"] == "poster-1" and "clip_text" not in beat and "clip_words" not in beat  # the last clip's words are gone until these are heard
    (poster,) = m.uploaded
    assert poster["slug"] == "describe-clip-1-poster" and poster["mime"] == "image/jpeg" and poster["bytes"] == b"\xff\xd8" and poster["metadata"]["beat"] == "b04"
    assert m.deleted == ["old-poster"]  # the poster this kind made for the last clip goes to the Trash
    video = m.asset_meta["vid-1"]
    assert video["recording"] == {"source": "browser"} and set(video["video"]) == {"duration_seconds", "width", "height", "fps", "has_audio"} and video["video"]["has_audio"] is True
    ((type_id, slug, _title, data),) = m.made
    assert (type_id, slug) == ("t-job", "describe-clip-1-words") and data == {"kind": "transcribe-clip", "args": {"entry": "b04", "field": "clip", "clip": "vid-1"}, "status": "queued"}
    assert done["result"]["transcribe_job"] == "describe-clip-1-words" and "transcribed" in done["log"]


@needs_ffmpeg
def test_a_clip_without_sound_is_described_and_not_sent_to_the_transcriber(tmp_path, monkeypatch):
    m = _Marvin({"clip": "vid-1", "clip_poster": "mine"}, _clip_file(tmp_path / "src.mp4", 1.0, sound=False)).wire(monkeypatch)
    done = _run({"clip": "vid-1"}, tmp_path / "w")
    assert m.patched[0]["clip_has_audio"] is False and m.made == [] and "no sound" in done["log"]
    assert m.deleted == []  # a picture the job did not make is never trashed


def test_an_emptied_clip_empties_what_the_last_one_left_and_trashes_its_poster(tmp_path, monkeypatch):
    left = {"clip_seconds": 3.0, "clip_width": 640, "clip_height": 480, "clip_has_audio": True, "clip_poster": "old-poster", "clip_text": "hi", "clip_words": []}
    m = _Marvin({"clip": "", "clip_corner": "top-left", **left}).wire(monkeypatch)
    done = _run({"clip": None}, tmp_path)
    assert m.patched == [{"clip": "", "clip_corner": "top-left"}] and m.deleted == ["old-poster"] and set(done["result"]["cleared"]) == set(left)
    m = _Marvin({"clip_corner": "top-left"}).wire(monkeypatch)
    assert "nothing to empty" in _run({}, tmp_path)["log"] and m.patched == []  # a beat that never had one is not written


def test_a_job_for_a_clip_since_replaced_does_nothing(tmp_path, monkeypatch):
    m = _Marvin({"clip": "vid-2"}).wire(monkeypatch)
    done = _run({"clip": "vid-1"}, tmp_path)
    assert done["result"]["skipped"] is True and m.patched == [] and m.uploaded == [] and m.made == []


@needs_ffmpeg
def test_a_clip_replaced_while_it_is_looked_at_is_not_written_over(tmp_path, monkeypatch):
    m = _Marvin({"clip": "vid-1"}, _clip_file(tmp_path / "src.mp4", 1.0), swap_after=1).wire(monkeypatch)
    done = _run({"clip": "vid-1"}, tmp_path / "w")
    assert done["result"]["skipped"] is True and m.patched == [] and m.made == [] and m.deleted == ["poster-1"]  # its own new poster is put away


def test_a_file_that_is_not_a_video_fails_the_job_and_leaves_the_beat(tmp_path, monkeypatch):
    m = _Marvin({"clip": "vid-1"}).wire(monkeypatch)
    m.assets["vid-1"] = {"id": "vid-1", "name": "still.png", "mimeType": "image/png"}
    with pytest.raises(JobError, match="is not a video"):
        _run({"clip": "vid-1"}, tmp_path)
    assert m.patched == []


def test_the_job_declares_what_it_takes():
    meta = META["describe-video"]
    assert meta["inputs"]["entry"]["type"] == "string" and meta["inputs"]["clip"]["required"] is False and "ffmpeg" in meta["needs"]


# ── what starts it ───────────────────────────────────────────────────────────
def _flow(slug):
    return BLUEPRINTS[slug]["payload"]["definition"]


def test_a_change_of_the_clip_and_only_that_queues_the_job():
    flow = _flow("screenplay-describe-clip")
    assert flow["trigger"] == {"type": "event", "event": "entry_updated"}
    assert flow["conditions"] == [{"field": "entry.entry_type", "op": "eq", "value": "beat"}, {"field": "entry.data.clip", "op": "changed"}]
    created = _flow("screenplay-describe-clip-created")
    assert created["trigger"] == {"type": "event", "event": "entry_created"} and {"field": "entry.data.clip", "op": "longer_than", "value": 0} in created["conditions"]
    for f in (flow, created):
        (act,) = f["actions"]
        assert act["op"] == "create" and act["entry_type"] == "job" and act["data"] == {"kind": "describe-video", "args": {"entry": "${entry.slug}", "field": "clip", "clip": "${entry.data.clip}"}, "status": "queued"}


def test_with_marvins_matcher_the_jobs_own_writes_and_archiving_never_set_it_off_again():
    """Marvin's own condition matcher, when it can be imported: run where Marvin is."""
    matcher = pytest.importorskip("marvin.services.automation.matcher")
    conds = _flow("screenplay-describe-clip")["conditions"]

    def ev(changed, data, entry_type="beat"):
        return {"event": {"event_type": "entry_updated", "changed_fields": changed, "before": {}, "after": {}}, "entry": {"entry_type": entry_type, "status": "draft", "data": data}}

    assert matcher.matches(conds, ev(["data.clip"], {"clip": "vid-1"})) and matcher.matches(conds, ev(["data.clip"], {"clip": None}))
    assert not matcher.matches(conds, ev([f"data.{k}" for k in (*FACTS, "clip_text", "clip_words")], {"clip": "vid-1"}))
    assert not matcher.matches(conds, ev(["status"], {"clip": "vid-1"})) and not matcher.matches(conds, ev(["status"], {"kind": "describe-video"}, "job"))


def test_the_beat_holds_the_facts_after_its_clip_settings_and_none_can_be_edited():
    fields = BLUEPRINTS["beat"]["payload"]["schema_json"]["fields"]
    keys = [f["key"] for f in fields]
    added = ["clip_seconds", "clip_width", "clip_height", "clip_has_audio", "clip_poster", "clip_text", "clip_words"]
    assert keys[keys.index("clip_end") + 1 : keys.index("clip_end") + 1 + len(added)] == added
    by_key = {f["key"]: f for f in fields}
    assert all(by_key[k]["readOnly"] is True and by_key[k]["helpText"].startswith("Filled in for you") for k in added)
    assert [by_key[k]["type"] for k in added] == ["number", "number", "number", "boolean", "asset", "textarea", "json"] and by_key["clip_text"]["label"] == "What you said"


def test_a_render_reads_none_of_the_facts(tmp_path):
    """The facts never reach the manifest, so a beat's render (with or without a clip) is what it was."""
    facts = {"clip_seconds": 3.0, "clip_width": 640, "clip_height": 480, "clip_has_audio": True, "clip_poster": "p", "clip_text": "hi", "clip_words": [{"word": "hi", "start": 0, "end": 1}]}
    assert clip.from_beat(facts, lambda a: tmp_path / a, tmp_path, "b04", []) is None
    (tmp_path / "vid-1").write_bytes(b"x")
    assert clip.from_beat({"clip": "vid-1", "clip_corner": "top-left", **facts}, lambda a: tmp_path / a, tmp_path, "b04", []) == {"video": "vid-1", "id": "vid-1", "corner": "top-left"}
