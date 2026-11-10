"""The manifest: what a story needs to be assembled, and the timeline it implies.

    {"title": "The Last Onion", "size": [1080, 1920], "fps": 30,
     "music": {"audio": "audio/bed.mp3", "volume": 0.12},
     "shots": [{"id": "b04", "still": "stills/b04.png", "hold": 4,
                "move": {"from": {"x": 0.5, "y": 0.5, "zoom": 1.0}, "to": {"x": 0.55, "y": 0.45, "zoom": 1.12}},
                "lines": [{"speaker": "Cook", "text": "Your feast.", "audio": "audio/b04-1.mp3", "words": [{"text": "Your", "start": 0, "end": 0.2}]}],
                "sfx": [{"audio": "audio/chop.mp3", "at": 0.5, "volume": 0.6}]}]}

A shot lasts max(hold, lead + its lines + gaps + tail): the audio decides, as the edit plan says. Paths are relative to the manifest.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

DEFAULT_SIZE = (1080, 1920)
DEFAULT_FPS = 30
TRIM_SLACK = 0.05  # an `end` a hair past the file's length (rounded timings) is read as its end
LEAD = 0.3  # silence before a shot's first line
GAP = 0.25  # between lines in a shot
TAIL = 0.35  # after the last line, before the cut
MAX_SHORT_SECONDS = 180


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Move:
    """A camera position over the still: the centre (0–1 of the picture) and a zoom of 1 or more (1 = the whole frame)."""

    x: float = 0.5
    y: float = 0.5
    zoom: float = 1.0


@dataclass
class Line:
    text: str
    audio: Path | None = None
    duration: float = 0.0
    speaker: str | None = None
    words: list[dict] = field(default_factory=list)
    caption: bool = True
    ref: str | None = None  # what the line is called outside the manifest (its Marvin speech-line slug), so a timeline can name it
    start: float = 0.0  # seconds into the audio file where the line begins (a line cut from a longer take)
    end: float | None = None  # …and where it ends; None = the file's end. Word times are from `start`.


@dataclass
class Sfx:
    audio: Path
    at: float = 0.0
    volume: float = 1.0
    duration: float = 0.0
    ref: str | None = None  # what the sound is called outside the manifest (its Marvin sound slug), so a timeline can name it
    fade_in: float = 0.0  # seconds to rise from silence at the start / fall to silence at the end, so a sound does not click on or off
    fade_out: float = 0.0


@dataclass
class Ambience:
    """A bed of sound under a shot (the sea outside, the same sea heard through a hull). Consecutive shots with the same bed
    share one continuous track, so there is no seam at each shot's edge."""

    audio: Path
    volume: float = 0.5
    muffled: bool = False  # heard from inside: low-passed, as through a wall
    ref: str | None = None
    fade_in: float = 0.0  # 0: the renderer's own crossfade (BED_FADE)
    fade_out: float = 0.0


BLENDS = ("normal", "screen", "multiply", "overlay", "lighten", "addition")
DUCKS = ("light", "strong")


@dataclass
class Overlay:
    """A video laid over a shot's still, looped to the shot's length: rain, smoke, film grain. `normal` uses the video's own transparency (a WebM
    or MOV with an alpha channel) and `opacity`; the other blends make an ordinary mp4 shot on black work (`screen` drops the black)."""

    video: Path
    blend: str = "normal"
    opacity: float = 1.0
    ref: str | None = None


@dataclass
class Shot:
    id: str
    still: Path
    hold: float = 0.0
    move_from: Move = Move()
    move_to: Move = Move(zoom=1.08)
    lines: list[Line] = field(default_factory=list)
    sfx: list[Sfx] = field(default_factory=list)
    lead: float = LEAD
    gap: float = GAP
    tail: float = TAIL
    ambience: Ambience | None = None
    overlay: Overlay | None = None
    music_volume: float | None = None
    """The music's level while this shot plays (0 = silence), when it differs from the story's; None keeps the story's."""
    chapter: str | None = None
    """The id of the chapter this shot belongs to (a story is cut into chapters; see `chapters.py`)."""


@dataclass
class Chapter:
    id: str
    title: str


@dataclass
class Manifest:
    title: str
    size: tuple[int, int]
    fps: int
    shots: list[Shot]
    music: dict | None = None
    caption: dict = field(default_factory=dict)
    loudnorm: bool = True
    end_hold: float = 0.0
    chapters: list[Chapter] = field(default_factory=list)
    """The story's chapters in order; a shot names one by id. Empty for a story that is not cut into chapters."""


@dataclass
class PlannedLine:
    line: Line
    start: float  # on the whole timeline


@dataclass
class PlannedShot:
    shot: Shot
    start: float
    duration: float
    lines: list[PlannedLine]


@dataclass
class Timeline:
    shots: list[PlannedShot]

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.shots)


def _move(raw: dict | None, default: Move, where: str) -> Move:
    if raw is None:
        return default
    move = Move(float(raw.get("x", 0.5)), float(raw.get("y", 0.5)), float(raw.get("zoom", 1.0)))
    if not (0 <= move.x <= 1 and 0 <= move.y <= 1) or move.zoom < 1:
        raise ManifestError(f"{where}: x and y are 0–1 and zoom is 1 or more (got {raw})")
    return move


def _trim(ln: dict, total: float, where: str) -> tuple[float, float | None]:
    """A line's `start` and `end` (seconds into its audio file), checked against the file's length."""
    start = float(ln.get("start") or 0)
    end = float(ln["end"]) if ln.get("end") is not None else None
    if start < 0 or start >= total:
        raise ManifestError(f"{where}: start {start:g}s is outside the {total:.2f}s audio")
    if end is not None and not start < end <= total + TRIM_SLACK:
        raise ManifestError(f"{where}: end {end:g}s must come after start {start:g}s and within the {total:.2f}s audio")
    return start, end


def load(path: Path, *, probe: Callable[[Path], float], need_stills: bool = True) -> Manifest:
    """Read and check a manifest. `probe` measures an audio file's seconds (ffprobe in real use). `need_stills=False` is for
    listening: a shot's still may be missing then, because only the sound is made."""
    base = path.parent
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"can't read {path}: {e}") from e
    shots_raw = raw.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise ManifestError("the manifest has no shots")

    def audio_path(value, where: str) -> Path:
        file = (base / value).resolve()
        if not file.is_file():
            raise ManifestError(f"{where}: no such file {value}")
        return file

    shots: list[Shot] = []
    for i, s in enumerate(shots_raw, 1):
        sid = str(s.get("id") or f"shot{i}")
        where = f"shot {sid}"
        if not s.get("still") and need_stills:
            raise ManifestError(f"{where}: no still")
        still = audio_path(s["still"], f"{where} still") if (s.get("still") and (need_stills or (base / s["still"]).is_file())) else Path()
        move = s.get("move") or {}
        shot = Shot(
            id=sid,
            still=still,
            hold=float(s.get("hold") or 0),
            move_from=_move(move.get("from"), Move(), f"{where} move.from"),
            move_to=_move(move.get("to"), Move(zoom=1.08), f"{where} move.to"),
            lead=float(s.get("lead", LEAD)),
            gap=float(s.get("gap", GAP)),
            tail=float(s.get("tail", TAIL)),
            chapter=str(s["chapter"]) if s.get("chapter") else None,
        )
        if s.get("ambience"):
            amb = s["ambience"]
            shot.ambience = Ambience(
                audio_path(amb.get("audio") or "", f"{where} ambience"), float(amb.get("volume", 0.5)), bool(amb.get("muffled", False)), amb.get("id"),
                fade_in=float(amb.get("fade_in") or 0), fade_out=float(amb.get("fade_out") or 0),
            )
        if s.get("overlay"):
            ov = s["overlay"]
            blend = str(ov.get("blend") or "normal")
            opacity = float(ov.get("opacity", 1.0))
            if blend not in BLENDS or not 0 <= opacity <= 1:
                raise ManifestError(f"{where} overlay: blend is one of {', '.join(BLENDS)} and opacity 0–1 (got {blend}, {opacity})")
            shot.overlay = Overlay(audio_path(ov.get("video") or "", f"{where} overlay"), blend, opacity, ov.get("id"))
        if s.get("music_volume") not in (None, ""):
            shot.music_volume = float(s["music_volume"])
            if not 0 <= shot.music_volume <= 1:
                raise ManifestError(f"{where}: music_volume is 0–1 (got {shot.music_volume})")
        for j, ln in enumerate(s.get("lines") or [], 1):
            lw = f"{where} line {j}"
            start, end = 0.0, None
            if ln.get("audio"):
                file = audio_path(ln["audio"], lw)
                total = probe(file)
                start, end = _trim(ln, total, lw)
                seconds = (end if end is not None else total) - start
            elif ln.get("duration"):
                file, seconds = None, float(ln["duration"])
            else:
                raise ManifestError(f"{lw}: needs audio, or a duration for a silent line")
            shot.lines.append(
                Line(
                    text=str(ln.get("text") or ""),
                    audio=file,
                    duration=seconds,
                    speaker=ln.get("speaker"),
                    words=[w for w in ln.get("words") or [] if isinstance(w, dict)],
                    caption=bool(ln.get("caption", file is not None)),
                    ref=ln.get("id"),
                    start=start,
                    end=end,
                )
            )
        for j, fx in enumerate(s.get("sfx") or [], 1):
            file = audio_path(fx.get("audio") or "", f"{where} sfx {j}")
            shot.sfx.append(
                Sfx(file, float(fx.get("at", 0)), float(fx.get("volume", 1)), probe(file), ref=fx.get("id"), fade_in=float(fx.get("fade_in") or 0), fade_out=float(fx.get("fade_out") or 0))
            )
        shots.append(shot)

    music = raw.get("music")
    if music:
        music = {**music, "audio": str(audio_path(music.get("audio") or "", "music")), "volume": float(music.get("volume", 0.12))}
        if music.get("duck") not in (None, "") and music["duck"] not in DUCKS:
            raise ManifestError(f"music: duck is {' or '.join(DUCKS)} (got {music['duck']})")
    size = tuple(raw.get("size") or DEFAULT_SIZE)
    if len(size) != 2 or size[0] * 16 != size[1] * 9:
        raise ManifestError(f"size must be 9:16 (got {size}); a Short is vertical")
    return Manifest(
        title=str(raw.get("title") or path.stem),
        size=(int(size[0]), int(size[1])),
        fps=int(raw.get("fps") or DEFAULT_FPS),
        shots=shots,
        music=music,
        caption=dict(raw.get("caption") or {}),
        loudnorm=bool(raw.get("loudnorm", True)),
        end_hold=float(raw.get("end_hold") or 0),
        chapters=[Chapter(str(c["id"]), str(c.get("title") or c["id"])) for c in raw.get("chapters") or [] if isinstance(c, dict) and c.get("id")],
    )


def plan(manifest: Manifest) -> Timeline:
    """Lay the shots end to end: each lasts as long as its lines need (or its hold, if longer)."""
    shots: list[PlannedShot] = []
    clock = 0.0
    for index, shot in enumerate(manifest.shots):
        cursor = shot.lead
        lines: list[PlannedLine] = []
        for line in shot.lines:
            lines.append(PlannedLine(line, clock + cursor))
            cursor += line.duration + shot.gap
        spoken = cursor - shot.gap + shot.tail if shot.lines else 0.0
        sfx_end = max((fx.at + fx.duration for fx in shot.sfx), default=0.0)
        duration = max(shot.hold, spoken, sfx_end)
        if index == len(manifest.shots) - 1:
            duration += manifest.end_hold
        shots.append(PlannedShot(shot, clock, duration, lines))
        clock += duration
    return Timeline(shots)
