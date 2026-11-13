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
ASPECTS = ((9, 16), (1, 1), (4, 5), (16, 9))  # the shapes a film may have (formats.SHAPES)
DEFAULT_FPS = 30
TRIM_SLACK = 0.05  # an `end` a hair past the file's length (rounded timings) is read as its end
LEAD = 0.3  # silence before a shot's first line
GAP = 0.25  # between lines in a shot
TAIL = 0.35  # after the last line, before the cut
MAX_SHORT_SECONDS = 180


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Rock:
    """A ship's rocking over the still: the frame rolls from side to side and rises and falls a little, in a steady rhythm that carries on across cuts
    (it runs on the film's clock), so a deck rocks through every beat, not afresh at each one."""

    degrees: float = 0.0
    """The most the frame tilts either way."""
    seconds: float = 6.0
    """One whole sway: over and back."""
    heave: float = 0.0
    """How far it rises and falls, as a share of the picture's height."""


MAX_ROCK_DEGREES = 15.0
MAX_ROCK_HEAVE = 0.1


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
    volume: float = 1.0  # how loud the line is in the mix, whichever take is used: 1 is as recorded
    muffled: bool = False  # heard through a wall: the highs are cut (the same low-pass as a muffled bed)


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
    fade_in_set: bool = False  # set by the story or the beat (not the sound): the film's start fade does not replace it
    fade_out_set: bool = False


TRANSITIONS = ("cut", "fade", "dissolve")
MAX_TRANSITION = 5.0
DEFAULT_TRANSITION_SECONDS = 0.5
PLAYS = ("", "loop", "once")
MAX_OVERLAY_FADE = 10.0
MAX_MUSIC_FADE = 30.0  # seconds: the longest a beat or the story may take to ease the music
MAX_OVERLAY_DELAY = 60.0
BLENDS = ("normal", "screen", "multiply", "overlay", "lighten", "addition")
MAX_END_FADE = 30.0
DUCKS = ("light", "strong")


@dataclass
class Overlay:
    """A video laid over a shot's still, looped to the shot's length: rain, smoke, film grain. `normal` uses the video's own transparency (a WebM
    or MOV with an alpha channel) and `opacity`; the other blends make an ordinary mp4 shot on black work (`screen` drops the black)."""

    video: Path
    blend: str = "normal"
    opacity: float = 1.0
    ref: str | None = None
    play: str = ""
    """loop, or once (play through, then hold the last frame). Empty: an animated picture (GIF, APNG) plays once, a video loops."""
    fade: float = 0.0
    """Seconds it fades in over at its start and out over at the end of the shot."""
    delay: float = 0.0
    """Seconds into the shot before it appears (a typed-out text starts a moment after the picture)."""


@dataclass
class Shot:
    id: str
    still: Path
    hold: float = 0.0
    move_from: Move = Move()
    move_to: Move = Move(zoom=1.08)
    rock: Rock | None = None
    """A rocking (a ship's roll and heave) added to the move, or None for a steady frame."""
    lines: list[Line] = field(default_factory=list)
    sfx: list[Sfx] = field(default_factory=list)
    lead: float = LEAD
    gap: float = GAP
    tail: float = TAIL
    ambience: Ambience | None = None
    overlay: Overlay | None = None
    music_volume: float | None = None
    music_fade_in: float | None = None
    """Seconds the music takes to ease to this shot's level as it starts (when that differs from the shot before); None leaves the default half second."""
    music_fade_out: float | None = None
    """Seconds the music takes to ease away from this shot's level as it ends; None leaves the default half second."""
    bed_volume: float | None = None
    """The level of the story's own ambience bed while this shot plays (a scene or a beat turns it down: 0 = silence); None keeps the story's level."""
    bed_muffled: bool = False
    """The story's own bed heard from inside while this shot plays (low-passed, eased in and out at the cut): the same sound, through a wall."""
    after: float = 0.0
    """Seconds of quiet added after the shot (the picture held, no sound): the pause where a scene ends. It is part of the shot's length."""
    transition: str = "cut"
    """How the film gets into this shot from the one before: cut, fade (down to black and up) or dissolve (a cross-fade). Never changes a length."""
    transition_seconds: float = 0.0
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
    loudness: float = -16.0
    """The integrated loudness (LUFS) the sound is normalised to when `loudnorm` is on: -14 is what the big platforms aim for."""
    end_hold: float = 0.0
    ambience: Ambience | None = None
    """The story's own ambience: one bed under the whole film, layered with whatever a beat or its scene asks for."""
    start_fade: float | None = None
    """Seconds every bed that starts the film (the music, the story's ambience) fades in over; None leaves each sound's own."""
    end_fade: float | None = None
    """Seconds every bed (the ambience that runs to the end and the music) fades out over at the end of the film; None leaves each sound's own."""
    ambience_duck: str = ""
    """light or strong: every ambience bed goes down under each spoken line, as the music's duck does; empty leaves the beds where they are."""
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


def _rock(raw: dict | None, where: str) -> Rock | None:
    if not raw:
        return None
    rock = Rock(float(raw.get("degrees", 0)), float(raw.get("seconds", 6)), float(raw.get("heave", 0)))
    if not (0 <= rock.degrees <= MAX_ROCK_DEGREES and 1 <= rock.seconds <= 30 and 0 <= rock.heave <= MAX_ROCK_HEAVE):
        raise ManifestError(f"{where}: rock is degrees 0–{MAX_ROCK_DEGREES:g}, seconds 1–30 and heave 0–{MAX_ROCK_HEAVE:g} (got {raw})")
    return rock if (rock.degrees or rock.heave) else None


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



def _line_volume(value, where: str) -> float:
    """A line's level in the mix: 0 to 1 (empty is 1, as recorded)."""
    if value in (None, ""):
        return 1.0
    try:
        level = float(value)
    except (TypeError, ValueError):
        raise ManifestError(f"{where}: volume is a number from 0 to 1 (got {value!r})") from None
    if not 0 <= level <= 1:
        raise ManifestError(f"{where}: volume is 0–1 (got {level})")
    return level

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
            raise ManifestError(f"{where}: no still (make one for that beat, or render a draft, which shows a plain card in its place)")
        still = audio_path(s["still"], f"{where} still") if (s.get("still") and (need_stills or (base / s["still"]).is_file())) else Path()
        move = s.get("move") or {}
        shot = Shot(
            id=sid,
            still=still,
            hold=float(s.get("hold") or 0),
            move_from=_move(move.get("from"), Move(), f"{where} move.from"),
            move_to=_move(move.get("to"), Move(zoom=1.08), f"{where} move.to"),
            rock=_rock(move.get("rock"), f"{where} move.rock"),
            lead=float(s.get("lead", LEAD)),
            gap=float(s.get("gap", GAP)),
            tail=float(s.get("tail", TAIL)),
            chapter=str(s["chapter"]) if s.get("chapter") else None,
        )
        if s.get("after") not in (None, "", 0):
            shot.after = float(s["after"])
            if not 0 < shot.after <= MAX_TRANSITION * 2:
                raise ManifestError(f"{where}: after is more than 0 and at most {MAX_TRANSITION * 2:g} seconds (got {shot.after:g})")
        kind = str(s.get("transition") or "cut")
        if kind not in TRANSITIONS:
            raise ManifestError(f"{where}: transition is {', '.join(TRANSITIONS)} (got {kind})")
        if kind != "cut":
            seconds = float(s.get("transition_seconds") or DEFAULT_TRANSITION_SECONDS)
            if not 0 < seconds <= MAX_TRANSITION:
                raise ManifestError(f"{where}: transition_seconds is more than 0 and at most {MAX_TRANSITION:g} (got {seconds:g})")
            shot.transition, shot.transition_seconds = kind, seconds
        if s.get("ambience"):
            amb = s["ambience"]
            shot.ambience = Ambience(
                audio_path(amb.get("audio") or "", f"{where} ambience"), float(amb.get("volume", 0.5)), bool(amb.get("muffled", False)), amb.get("id"),
                fade_in=float(amb.get("fade_in") or 0), fade_out=float(amb.get("fade_out") or 0),
                fade_in_set=bool(amb.get("fade_in_set")), fade_out_set=bool(amb.get("fade_out_set")),
            )
        if s.get("overlay"):
            ov = s["overlay"]
            blend = str(ov.get("blend") or "normal")
            opacity = float(ov.get("opacity", 1.0))
            if blend not in BLENDS or not 0 <= opacity <= 1:
                raise ManifestError(f"{where} overlay: blend is one of {', '.join(BLENDS)} and opacity 0–1 (got {blend}, {opacity})")
            play = str(ov.get("play") or "")
            fade, delay = float(ov.get("fade") or 0), float(ov.get("delay") or 0)
            if play not in PLAYS or not 0 <= fade <= MAX_OVERLAY_FADE or not 0 <= delay <= MAX_OVERLAY_DELAY:
                raise ManifestError(f"{where} overlay: play is loop or once, fade 0–{MAX_OVERLAY_FADE:g} and delay 0–{MAX_OVERLAY_DELAY:g} seconds (got {play or 'empty'}, {fade:g}, {delay:g})")
            shot.overlay = Overlay(audio_path(ov.get("video") or "", f"{where} overlay"), blend, opacity, ov.get("id"), play, fade, delay)
        if s.get("music_volume") not in (None, ""):
            shot.music_volume = float(s["music_volume"])
            if not 0 <= shot.music_volume <= 1:
                raise ManifestError(f"{where}: music_volume is 0–1 (got {shot.music_volume})")
        for key in ("music_fade_in", "music_fade_out"):
            if s.get(key) not in (None, ""):
                seconds = float(s[key])
                if not 0 <= seconds <= MAX_MUSIC_FADE:
                    raise ManifestError(f"{where}: {key} is 0–{MAX_MUSIC_FADE:g} seconds (got {seconds:g})")
                setattr(shot, key, seconds)
        if s.get("bed_volume") not in (None, ""):
            shot.bed_volume = float(s["bed_volume"])
            if not 0 <= shot.bed_volume <= 1:
                raise ManifestError(f"{where}: bed_volume is 0–1 (got {shot.bed_volume})")
        shot.bed_muffled = bool(s.get("bed_muffled", False))
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
                    volume=_line_volume(ln.get("volume"), lw),
                    muffled=bool(ln.get("muffled", False)),
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
        for key in ("story_fade_in", "story_fade_out"):
            if music.get(key) not in (None, "") and not 0 <= float(music[key]) <= MAX_MUSIC_FADE:
                raise ManifestError(f"music: {key} is 0–{MAX_MUSIC_FADE:g} seconds (got {music[key]})")
        if music.get("duck") not in (None, "") and music["duck"] not in DUCKS:
            raise ManifestError(f"music: duck is {' or '.join(DUCKS)} (got {music['duck']})")
    size = tuple(raw.get("size") or DEFAULT_SIZE)
    if len(size) != 2 or not any(size[0] * h == size[1] * w for w, h in ASPECTS):
        raise ManifestError(f"size must be 9:16, 1:1, 4:5 or 16:9 (got {size})")
    loudness = raw.get("loudness")
    if loudness not in (None, "") and not -30 <= float(loudness) <= -5:
        raise ManifestError(f"loudness is a target between -30 and -5 LUFS (got {loudness})")
    story_bed = None
    if raw.get("ambience"):
        amb = raw["ambience"]
        story_bed = Ambience(
            audio_path(amb.get("audio") or "", "ambience"), float(amb.get("volume", 0.5)), False, amb.get("id"),
            fade_in=float(amb.get("fade_in") or 0), fade_out=float(amb.get("fade_out") or 0),
            fade_in_set=bool(amb.get("fade_in_set")), fade_out_set=bool(amb.get("fade_out_set")),
        )  # fmt: skip
    start_fade = raw.get("start_fade")
    if start_fade not in (None, ""):
        start_fade = float(start_fade)
        if not 0 < start_fade <= MAX_END_FADE:
            raise ManifestError(f"start_fade is more than 0 and at most {MAX_END_FADE:g} seconds (got {start_fade:g})")
    end_fade = raw.get("end_fade")
    if end_fade not in (None, ""):
        end_fade = float(end_fade)
        if not 0 < end_fade <= MAX_END_FADE:
            raise ManifestError(f"end_fade is more than 0 and at most {MAX_END_FADE:g} seconds (got {end_fade:g})")
    ambience_duck = str(raw.get("ambience_duck") or "")
    if ambience_duck and ambience_duck not in DUCKS:
        raise ManifestError(f"ambience_duck is {' or '.join(DUCKS)} (got {ambience_duck})")
    return Manifest(
        title=str(raw.get("title") or path.stem),
        size=(int(size[0]), int(size[1])),
        fps=int(raw.get("fps") or DEFAULT_FPS),
        shots=shots,
        music=music,
        ambience=story_bed,
        ambience_duck=ambience_duck,
        caption=dict(raw.get("caption") or {}),
        loudnorm=bool(raw.get("loudnorm", True)),
        loudness=float(loudness) if loudness not in (None, "") else -16.0,
        end_hold=float(raw.get("end_hold") or 0),
        start_fade=start_fade if isinstance(start_fade, float) else None,
        end_fade=end_fade if isinstance(end_fade, float) else None,
        chapters=[Chapter(str(c["id"]), str(c.get("title") or c["id"])) for c in raw.get("chapters") or [] if isinstance(c, dict) and c.get("id")],
    )


def plan(manifest: Manifest) -> Timeline:
    """Lay the shots end to end: each lasts as long as its lines need (with the silences around them), or its hold when that is longer: a beat that is
    too quick to take in is given its hold, the picture staying up after the last line."""
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
        duration = max(shot.hold, spoken, sfx_end) + shot.after
        if index == len(manifest.shots) - 1:
            duration += manifest.end_hold
        shots.append(PlannedShot(shot, clock, duration, lines))
        clock += duration
    return Timeline(shots)
