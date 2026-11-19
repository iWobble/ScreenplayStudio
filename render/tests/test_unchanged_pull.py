"""What the pull makes of a story in Marvin is pinned: the manifest it writes, the files it downloads (in order) and what it reports, to the
character, for a story that uses most of what a beat can hold. `test_unchanged_render.py` pins manifest → ffmpeg; this pins entries → manifest,
the half the Media package's Recordings come near (see the Media package design, "Proving renders don't change").

The story is pulled three times, and every shape must give the same bytes:
- `legacy`: the records as they are today.
- `recordings`: the same, plus a Recording entry for each file and a `recording` ref on each beat, take, line and sound that names one.
- `stale`: Recordings whose facts differ from the files' (another length, other words) and a ref that points at another file's Recording.
The pull reads none of them, so none of them may change what it writes.

Marvin is a fake HTTP server (no network), and ffmpeg is not run. To refresh the golden file after a change that is *meant* to change what the pull writes:
STORYRENDER_GOLDEN=1 pytest tests/test_unchanged_pull.py (and say why in the PR)."""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from storyrender import ffmpeg, marvin_pull

GOLDEN = Path(__file__).parent / "data" / "unchanged_pull.json"
S = "the-harbour-light"
L = {n: f"{S}-line-{n}" for n in ("01-1", "01-2", "01-3", "01-4", "02-1", "07-1")}


def _words(text: str, step: float = 0.4) -> list[dict]:
    return [{"text": w, "start": round(i * step, 2), "end": round(i * step + step - 0.05, 2)} for i, w in enumerate(text.split())]


# Each asset: its type, and what its record's metadata holds (a take's word timings, a clip's facts). Its file is "file:<id>".
ASSETS: dict[str, dict] = {
    "still-01": {"mimeType": "image/png"},
    "still-02": {"mimeType": "image/jpeg"},
    "still-03": {"mimeType": "image/webp"},
    "still-05": {"mimeType": "image/png"},
    "still-07": {"mimeType": "image/png"},
    "take-01-1": {"mimeType": "audio/mpeg", "metadataJson": {"words": _words("The lamp is out tonight.")}},
    "take-01-1-second": {"mimeType": "audio/mpeg", "metadataJson": {"words": _words("The lamp is out.")}},  # a take the line does not use
    "take-01-2": {"mimeType": "audio/webm"},  # recorded in the browser: no word timings, so its cues are placed by share
    "take-01-4": {"mimeType": "audio/mpeg"},
    "take-02-1": {"mimeType": "audio/wav", "metadataJson": {"words": [{"text": "[sighs]", "start": 0.0, "end": 0.3}, *_words("Wait for the tide.")]}},
    "take-07-1": {"mimeType": "audio/ogg", "metadataJson": {"words": [*_words("[whispers] There she is."), {"start": 2.0, "end": 2.1}]}},
    "sfx-bell": {"mimeType": "audio/mpeg"},
    "sfx-thunder": {"mimeType": "audio/wav"},
    "amb-wind": {"mimeType": "audio/mpeg"},
    "amb-waves": {"mimeType": "audio/ogg"},
    "amb-foghorn": {"mimeType": "audio/mpeg"},
    "amb-gulls": {"mimeType": "audio/mpeg"},
    "music-theme": {"mimeType": "audio/mpeg"},
    "clip-keeper-at-the-lamp": {"mimeType": "video/webm", "metadataJson": {"video": {"duration_seconds": 6.2, "width": 1080, "height": 1920, "fps": 30, "has_audio": True}}},
    "overlay-rain-loop": {"mimeType": "video/mp4"},
    "overlay-sparks": {"mimeType": "image/gif"},
    "icon-lighthouse": {"mimeType": "image/png"},
    "poster-03": {"mimeType": "image/jpeg", "metadataJson": {"kind": "clip-poster"}},
}

ROWS: list[dict] = [
    {"slug": S, "title": "The Harbour Light", "dataJson": {
        "format": "square-1x1", "loudness": "-14", "caption_style": "highlight", "caption_position": "top", "caption_size": "large",
        "caption_color": "FFEE00", "caption_highlight_color": "#ff8800", "transition": "dissolve", "transition_seconds": 0.7,
        "end_transition": "fade", "end_fade_seconds": 2, "start_fade_seconds": 1, "music": "harbour-theme", "music_volume": 0.1,
        "music_ducking": "light", "music_fade_out": 3, "ambience": f"{S}-sound-gulls", "ambience_volume": 0.2, "ambience_fade_in": 1.5,
        "ambience_ducking": "strong", "scene_break_seconds": 0.8, "intro_title": "The Harbour Light", "intro_subtitle": "A night on the quay",
        "outro_title": "The End", "camera": "drift", "line_lead": 0.4, "line_tail": 0.5, "picture_lead": 0.2, "card_color": "#102030",
    }},
    {"slug": f"{S}-chapter-2", "title": "Morning", "dataJson": {"story": S, "number": 2}},
    {"slug": f"{S}-chapter-1", "title": "Night", "dataJson": {"story": S, "number": 1}},
    {"slug": f"{S}-cast-keeper", "dataJson": {"story": S, "speaker": "Keeper", "caption_color": "#88CCFF"}},
    {"slug": f"{S}-cast-mara", "dataJson": {"story": S, "speaker": "mara", "caption_color": "not a colour"}},
    {"slug": f"{S}-lamp-room", "dataJson": {"story": S, "ambience": f"{S}-sound-wind", "ambience_volume": 0.3, "ambience_muffled": True, "camera": "push-in", "music_volume": 0.05, "story_ambience_muffled": True}},
    {"slug": f"{S}-quay", "dataJson": {"story": S, "ambience": f"{S}-sound-waves", "overlay": "overlay-rain-loop", "overlay_blend": "screen", "overlay_opacity": 0.5, "overlay_play": "loop", "overlay_fade": 0.4, "story_ambience_volume": 0.15}},
    # 01: a still, two spoken lines (one with word timings, one without), one not recorded, one set aside; placed sounds (one starts before the
    # beat, one rings over), and cues on words: a sound, a camera move, a look, a mix and an emphasis.
    {"slug": f"{S}-beat-01", "dataJson": {
        "story": S, "number": "01", "still": "still-01", "scene": f"{S}-lamp-room", "chapter": f"{S}-chapter-1", "lead_seconds": 0.5, "gap_seconds": 0.3,
        "sounds": [{"sound": f"{S}-sound-bell", "at": -0.5, "volume": 0.8}, {"sound": "library-thunder", "at": 1.2, "ring": True}, {"sound": f"{S}-sound-not-made", "at": 2}],
        "cues": [
            {"line": L["01-1"], "word": 2, "sound": f"{S}-sound-bell", "volume": 0.4, "nudge": 0.1},
            {"line": L["01-1"], "word": 3, "sound": "library-thunder", "ring": True},
            {"line": L["01-1"], "word": 1, "camera": {"kind": "punch"}},
            {"line": L["01-1"], "word": 4, "look": {"kind": "flash"}, "nudge": -0.2},
            {"line": L["01-2"], "word": 1, "mix": {"kind": "duck", "amount": 0.3}},
            {"line": L["01-2"], "word": 2, "emphasis": {"scale": 1.4}},
        ],
    }},
    {"slug": L["01-1"], "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "keeper", "text": "The lamp is out tonight.", "audio": "take-01-1", "order": 1}},
    {"slug": L["01-2"], "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "mara", "text": "Then light it, quick.", "audio": "take-01-2", "order": 2, "volume": 0.9, "muffled": True, "nudge": -0.2}},
    {"slug": L["01-3"], "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "keeper", "text": "No oil.", "order": 3}},  # not recorded
    {"slug": L["01-4"], "dataJson": {"story": S, "beat": f"{S}-beat-01", "speaker": "keeper", "text": "Another way.", "audio": "take-01-4", "order": 4, "leave_out": True}},
    {"slug": f"{L['01-1']}-take-2", "dataJson": {"story": S, "line": L["01-1"], "speaker": "keeper", "audio": "take-01-1-second"}},  # a take: never a line of its own
    # 02: comes in at a word of the line before, with its own bed heard clear over the quay's, its own music level and transition.
    {"slug": f"{S}-beat-02", "dataJson": {
        "story": S, "number": "02", "still": "still-02", "scene": f"{S}-quay", "transition": "fade", "transition_seconds": 1.0, "ambience": f"{S}-sound-foghorn",
        "ambience_volume": 0.6, "ambience_heard": "clear", "ambience_fade_in": 0.5, "music_volume": 0.2, "music_fade_in": 0.5, "story_ambience_volume": 0.1,
        "hold_seconds": 5, "starts_during": {"line": L["01-2"], "word": 3}, "overlay": "overlay-sparks", "overlay_blend": "add", "overlay_opacity": 0.8, "overlay_delay": 0.5,
    }},
    {"slug": L["02-1"], "dataJson": {"story": S, "beat": f"{S}-beat-02", "speaker": "keeper", "text": "Wait for the tide.", "caption": "Wait for the tide.", "audio": "take-02-1", "simultaneous": True}},
    # 03: the keeper's clip over a still in the quay, with every clip setting and every fact a describe job writes (the pull reads only the settings).
    {"slug": f"{S}-beat-03", "dataJson": {
        "story": S, "number": "03", "still": "still-03", "scene": f"{S}-quay", "camera": "pan-left",
        "clip": "clip-keeper-at-the-lamp", "clip_look": "PIP", "clip_corner": "Top-Right", "clip_size": 0.3, "clip_shape": "Circle", "clip_audio": True,
        "clip_volume": 0.7, "clip_start": 0.5, "clip_end": 4.5,
        "clip_seconds": 6.2, "clip_width": 1080, "clip_height": 1920, "clip_has_audio": True, "clip_poster": "poster-03", "clip_text": "Here we go.",
        "clip_words": [{"word": "Here", "start": 0.6, "end": 0.8}, {"word": "we", "start": 0.8, "end": 0.9}, {"word": "go.", "start": 0.9, "end": 1.2}],
        "sounds": [{"sound": f"{S}-sound-waves", "at": 0}],
    }},
    # 04: a plain card with its own words.
    {"slug": f"{S}-beat-04", "dataJson": {"story": S, "number": "04", "shows": "Plain card", "info_title": "Later that night", "hold_seconds": 2, "chapter": f"{S}-chapter-2"}},
    # 05: an info card over a still, with an icon, and a camera move written out in numbers.
    {"slug": f"{S}-beat-05", "dataJson": {
        "story": S, "number": "05", "still": "still-05", "info_label": "FACT", "info_title": "Built 1842", "info_text": "The light burned for 120 years.",
        "info_icon": "icon-lighthouse", "info_dim": 0.6, "overlay_fade": 0.5, "hold_seconds": 3,
        "move": {"from": {"x": 0.4, "y": 0.5, "zoom": 1.1}, "to": {"x": 0.6, "y": 0.45, "zoom": 1.3}, "rock": {"degrees": 1.5, "seconds": 5, "heave": 0.01}},
    }},
    {"slug": f"{S}-beat-06", "dataJson": {"story": S, "number": "06"}},  # nothing to show or hear: left out
    # 07: back in the lamp room (a scene break before it), a line whose take has a delivery tag and a malformed word.
    {"slug": f"{S}-beat-07", "dataJson": {"story": S, "number": "07", "still": "still-07", "scene": f"{S}-lamp-room", "tail_seconds": 1.0, "picture_lead": 0.0, "camera": "wobble", "sounds": [{"sound": "library-thunder", "at": -1.5, "ring": True, "volume": 0.5}]}},
    {"slug": L["07-1"], "dataJson": {"story": S, "beat": f"{S}-beat-07", "speaker": "Keeper", "text": "There she is.", "audio": "take-07-1"}},
    # sounds: the library's, found by slug whichever story made them
    {"slug": f"{S}-sound-bell", "dataJson": {"story": S, "kind": "effect", "audio": "sfx-bell", "volume": 0.5, "fade_out": 0.2, "duration_seconds": 1.5}},
    {"slug": "library-thunder", "dataJson": {"kind": "effect", "audio": "sfx-thunder", "volume": 0.7, "duration_seconds": 13}},
    {"slug": f"{S}-sound-wind", "dataJson": {"story": S, "kind": "ambience", "audio": "amb-wind", "volume": 0.4, "fade_in": 2}},
    {"slug": f"{S}-sound-waves", "dataJson": {"story": S, "kind": "ambience", "audio": "amb-waves"}},
    {"slug": f"{S}-sound-foghorn", "dataJson": {"story": S, "kind": "ambience", "audio": "amb-foghorn", "volume": 0.5, "fade_out": 1.0}},
    {"slug": f"{S}-sound-gulls", "dataJson": {"story": S, "kind": "ambience", "audio": "amb-gulls", "volume": 0.3, "fade_out": 1}},
    {"slug": "harbour-theme", "dataJson": {"kind": "music", "audio": "music-theme", "volume": 0.15, "fade_in": 1}},
    {"slug": f"{S}-sound-not-made", "dataJson": {"story": S, "kind": "effect"}},
    {"slug": "other-story-line-01-1", "dataJson": {"story": "other-story", "beat": "x", "speaker": "keeper", "audio": "take-01-4"}},
]  # fmt: skip

# The asset field that names a file on each kind of row: a Recording ref goes beside it.
_FILE_FIELDS = ("audio", "clip")


def _recording(asset: str, *, stale: bool) -> dict:
    """A Recording entry (Media package) for an asset: its facts as a describe job writes them, or (stale) facts that are wrong."""
    meta = ASSETS[asset].get("metadataJson") or {}
    words = meta.get("words") or []
    if stale:
        words = [{"text": "nothing", "start": 9.0, "end": 9.5}]
    video = meta.get("video") or {}
    data = {
        "asset": asset, "kind": "video" if ASSETS[asset]["mimeType"].startswith("video/") else "audio", "source": "uploaded", "status": "described",
        "duration_seconds": 99.0 if stale else float(video.get("duration_seconds") or 2.0), "has_audio": True, "words": words,
        "text": " ".join(str(w.get("text")) for w in words if w.get("text")), "level_db": -60.0 if stale else -18.0,
        **({"width": 640, "height": 480} if video else {}),
    }  # no `story`: a Recording belongs to no story
    return {"slug": f"rec-{asset}", "title": asset, "dataJson": data}


def shaped(shape: str) -> list[dict]:
    """The rows as Marvin holds them in one shape (see the module's docstring)."""
    rows = copy.deepcopy(ROWS)
    if shape == "legacy":
        return rows
    named = sorted({str(d[f]) for r in rows for d in [r["dataJson"]] for f in _FILE_FIELDS if d.get(f)})
    for row in rows:
        d = row["dataJson"]
        held = next((str(d[f]) for f in _FILE_FIELDS if d.get(f)), None)
        if held:
            d["recording"] = f"rec-{held}"
    if shape == "stale":
        line = next(r for r in rows if r["slug"] == L["01-1"])
        line["dataJson"]["recording"] = "rec-take-07-1"  # a ref left pointing at another file's Recording
    return rows + [_recording(a, stale=shape == "stale") for a in named]


class _Marvin(BaseHTTPRequestHandler):
    rows: list[dict] = []
    fetched: list[str] = []  # the asset ids whose file was downloaded, in order

    def _send(self, status: int, body: bytes = b"") -> None:
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path != "/api/platform/entries/query":
            return self._send(404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        wanted = body["spec"]["entries"]
        wanted = [wanted] if isinstance(wanted, str) else list(wanted)  # one slug, or a list of them: never a substring
        hits = [r for r in _Marvin.rows if r["slug"] in wanted]
        self._send(200, json.dumps({"entries": hits, "total": len(hits)}).encode())

    def do_GET(self):  # noqa: N802
        path = self.path
        if path.startswith("/api/platform/entries?"):
            return self._send(200, json.dumps(_Marvin.rows).encode())
        if path.startswith("/api/platform/assets?q="):
            return self._send(200, b"[]")  # no asset is found by a name: every reference here is an id
        prefix = "/api/platform/assets/"
        if not path.startswith(prefix):
            return self._send(404)
        ref, _, tail = path[len(prefix) :].partition("/")
        if ref not in ASSETS:
            return self._send(404)
        if tail == "file":
            _Marvin.fetched.append(ref)
            return self._send(200, f"file:{ref}".encode())
        return self._send(200, json.dumps({"id": ref, "slug": ref, "name": ref, **ASSETS[ref]}).encode())

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def _no_ffmpeg(monkeypatch):
    """The title and end cards are drawn with ffmpeg: here each picture is only made empty, so the pull needs no ffmpeg (test_cards draws them)."""
    monkeypatch.setattr(ffmpeg, "run", lambda cmd, **_kw: Path(cmd[-1]).touch())


@pytest.fixture
def marvin():
    server = HTTPServer(("127.0.0.1", 0), _Marvin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _pulled(marvin: str, out: Path, shape: str) -> dict:
    _Marvin.rows, _Marvin.fetched = shaped(shape), []
    result = marvin_pull.pull(S, out, creds=(marvin, "tok"))
    manifest_bytes = (out / "manifest.json").read_bytes()
    assert result.pop("manifest") == str(out / "manifest.json")
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    downloaded = {f: (out / f).read_text() for f in files if (out / f).read_bytes().startswith(b"file:")}
    return {"manifest": json.loads(manifest_bytes), "result": result, "fetched": list(_Marvin.fetched), "files": files, "downloaded": downloaded, "_bytes": manifest_bytes}


def _check(got: dict) -> None:
    got = {k: v for k, v in got.items() if k != "_bytes"}
    if os.environ.get("STORYRENDER_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n")
    want = json.loads(GOLDEN.read_text())
    assert got["result"] == want["result"]
    assert got["fetched"] == want["fetched"]
    assert got["files"] == want["files"] and got["downloaded"] == want["downloaded"]
    film, was = got["manifest"], want["manifest"]
    assert {k: v for k, v in film.items() if k != "shots"} == {k: v for k, v in was.items() if k != "shots"}
    assert [s["id"] for s in film["shots"]] == [s["id"] for s in was["shots"]]
    for shot, before in zip(film["shots"], was["shots"], strict=True):
        assert shot == before, shot["id"]


def test_the_pull_writes_exactly_what_it_wrote_before(marvin, tmp_path):
    _check(_pulled(marvin, tmp_path / "legacy", "legacy"))


@pytest.mark.parametrize("shape", ["recordings", "stale"])
def test_recordings_and_refs_to_them_change_nothing_the_pull_writes(marvin, tmp_path, shape):
    legacy = _pulled(marvin, tmp_path / "legacy", "legacy")
    got = _pulled(marvin, tmp_path / shape, shape)
    assert got["_bytes"] == legacy["_bytes"]  # the manifest, byte for byte
    assert got["fetched"] == legacy["fetched"] and got["result"] == legacy["result"] and got["files"] == legacy["files"]


def test_the_fixture_reaches_what_it_is_meant_to(marvin, tmp_path):
    """The golden file is only a guard if the story uses what it should: a change to the fixture that drops one of these must say so."""
    got = _pulled(marvin, tmp_path, "legacy")
    shots = {s["id"]: s for s in got["manifest"]["shots"]}
    sfx = shots["b01"]["sfx"]
    assert any(fx["at"] < 0 for fx in sfx) and any(fx.get("ring") for fx in sfx)  # placed before the beat; rings over
    assert any("line_at" in fx for fx in sfx) and shots["b01"]["camera_cues"] and shots["b01"]["look_cues"]
    assert shots["b01"]["mix_cues"][0]["line_share"] and shots["b01"]["emphasis_cues"]  # cues on a take with no word timings are placed by share
    assert shots["b01"]["lines"][0]["words"] and "words" not in shots["b01"]["lines"][1]
    assert set(shots["b03"]["clip"]) == {"video", "id", "look", "corner", "size", "shape", "audio", "volume", "start", "end"}
    assert shots["b02"]["overlay"]["id"] == "overlay-sparks" and shots["b03"]["overlay"]["id"] == "overlay-rain-loop" and shots["b05"]["overlay"]["id"] == "info-b05"
    assert shots["b02"]["starts_during"] and shots["b02"]["beat_ambience"] and shots["b01"]["ambience"]["muffled"]
    film = got["manifest"]
    assert film["music"] and film["ambience"] and film["chapters"] and film["caption"]["speakers"] and shots["intro"] and shots["outro"]
    assert got["result"]["not_recorded"] and got["result"]["skipped"] == ["06"] and got["result"]["estimated"]
    assert "take-01-1-second" not in got["fetched"] and "poster-03" not in got["fetched"]  # a take not in use and a clip's poster are never fetched
