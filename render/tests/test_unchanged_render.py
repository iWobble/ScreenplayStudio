"""A film with none of the v218+ cue keys (look, mix, emphasis, whip-pan, sway) renders exactly as before: every ffmpeg command the render runs, and
the captions it burns in, are the same to the character as Studio v217 made them. (A shake is left out on purpose: v218 gives it room to show.)

The commands are recorded with ffmpeg itself stubbed out, so nothing is encoded. To refresh the golden file after a change that is *meant* to alter
every render: STORYRENDER_GOLDEN=1 pytest tests/test_unchanged_render.py."""

import json
import os
from pathlib import Path

from storyrender import build, ffmpeg, manifest

GOLDEN = Path(__file__).parent / "data" / "unchanged_render.json"


def _manifest(tmp: Path) -> Path:
    for name in ("a.png", "b.png", "c.png", "rain.png", "l1.wav", "l2.wav", "l3.wav", "clang.wav", "thud.wav", "sea.wav", "cheer.wav", "wind.wav", "music.mp3"):
        (tmp / name).write_bytes(b"")
    words = [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate("The hammer strikes the wheel.".split())]
    raw = {
        "title": "Unchanged",
        "size": [1080, 1920],
        "fps": 30,
        "caption": {"style": "highlight", "speakers": {"Smith": "#ff8800"}},
        "music": {"audio": "music.mp3", "volume": 0.12, "duck": "light"},
        "ambience": {"audio": "wind.wav", "volume": 0.3},
        "ambience_duck": "strong",
        "start_fade": 1.0,
        "end_fade": 2.0,
        "end_transition": "fade",
        "end_transition_seconds": 1.0,
        "shots": [
            {
                "id": "a", "still": "a.png", "hold": 3,
                "move": {"from": {"x": 0.5, "y": 0.5, "zoom": 1.0}, "to": {"x": 0.55, "y": 0.45, "zoom": 1.12}, "rock": {"degrees": 2.5, "seconds": 6, "heave": 0.012}},
                "lines": [
                    {"id": "l1", "speaker": "Smith", "text": "The hammer strikes the wheel.", "audio": "l1.wav", "words": words},
                    {"id": "l2", "speaker": "Jo", "text": "Again!", "audio": "l2.wav", "nudge": -0.3},
                ],
                "sfx": [{"audio": "thud.wav", "at": 0.2, "volume": 0.5, "fade_in": 0.1}, {"audio": "clang.wav", "line": "l1", "line_at": 1.15, "nudge": 0.1}],
                "camera_cues": [{"kind": "punch", "line": "l1", "line_at": 1.15}, {"kind": "nudge", "x": 0.7, "y": 0.4, "line": "l2", "line_share": 0.5, "nudge": 0.2}],
                "ambience": {"audio": "sea.wav", "volume": 0.4},
                "beat_ambience": {"audio": "cheer.wav", "volume": 0.6, "fade_in": 0.5},
                "transition": "fade", "transition_seconds": 0.8,
            },
            {
                "id": "b", "still": "b.png", "transition": "dissolve", "transition_seconds": 0.6,
                "lines": [{"id": "l3", "speaker": "Smith", "text": "And the sea answers.", "audio": "l3.wav", "muffled": True, "volume": 0.8}],
                "overlay": {"video": "rain.png", "blend": "screen", "opacity": 0.6, "fade": 0.5},
                "ambience": {"audio": "sea.wav", "volume": 0.2, "muffled": True},
                "music_volume": 0.05, "bed_volume": 0.1, "bed_muffled": True, "picture_lead": 0.4,
            },
            {"id": "c", "still": "c.png", "hold": 2.5, "after": 1.0},
        ],
    }  # fmt: skip
    path = tmp / "manifest.json"
    path.write_text(json.dumps(raw))
    return path


def _recorded(tmp_path: Path, monkeypatch) -> dict:
    ran: list[dict] = []

    def run(cmd, *, cwd=None):
        ran.append({"cmd": [str(c) for c in cmd], "cwd": str(cwd) if cwd else None})
        out = Path(cmd[-1])
        (out if out.is_absolute() or cwd is None else Path(cwd) / out).touch()  # the render moves and reads what each step made

    monkeypatch.setattr(ffmpeg, "run", run)
    monkeypatch.setattr(ffmpeg, "probe", lambda _p: {"format": {"duration": "12.0"}})
    film = manifest.load(_manifest(tmp_path), probe=lambda _p: 2.0)
    work = tmp_path / "work"
    build.render(film, tmp_path / "out" / "film.mp4", keep=work)
    text = json.dumps({"ran": ran, "captions": (work / "captions.ass").read_text()}, indent=1)
    return json.loads(text.replace(str(tmp_path), "<tmp>"))


def test_a_film_without_the_new_cue_keys_renders_exactly_as_before(tmp_path, monkeypatch):
    got = _recorded(tmp_path, monkeypatch)
    if os.environ.get("STORYRENDER_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1) + "\n")
    want = json.loads(GOLDEN.read_text())
    assert got["captions"] == want["captions"]
    assert len(got["ran"]) == len(want["ran"])
    for g, w in zip(got["ran"], want["ran"], strict=True):
        assert g == w


def test_a_camera_cue_no_longer_hides_the_films_own_settings(tmp_path):
    """v212 to v216 read the film's music, captions, size, beds… from the last camera cue's row instead of the manifest (a loop reused the name), so a
    film with a camera cue lost them all (put right in v217). The golden file above is v217's."""
    film = manifest.load(_manifest(tmp_path), probe=lambda _p: 2.0)
    assert film.title == "Unchanged" and film.caption["style"] == "highlight" and film.music and film.ambience and film.ambience_duck == "strong"
    assert film.end_transition == "fade" and film.start_fade == 1.0
