"""The manifest: what a story needs to be assembled, and the timeline it implies.

    {"title": "The Last Onion", "size": [1080, 1920], "fps": 30,
     "music": {"audio": "audio/bed.mp3", "volume": 0.12},
     "shots": [{"id": "b04", "still": "stills/b04.png", "hold": 4,
                "move": {"from": {"x": 0.5, "y": 0.5, "zoom": 1.0}, "to": {"x": 0.55, "y": 0.45, "zoom": 1.12}},
                "lines": [{"speaker": "Cook", "text": "Your feast.", "audio": "audio/b04-1.mp3", "words": [{"text": "Your", "start": 0, "end": 0.2}]}],
                "sfx": [{"audio": "audio/chop.mp3", "at": 0.5, "volume": 0.6}]}]}

A shot lasts max(hold, lead + its lines + gaps + tail): the audio decides, as the edit plan says. Paths are relative to the manifest.

The sound is laid out first, shot after shot (each line at its own place on the film's clock); the pictures are cut from it. With no `picture_lead`
a shot's picture starts where its sound starts, as it always did. A shot with `picture_lead` shows its picture that many seconds before its first
word (a silent one, before its own start), so the picture changes while the line before is still being spoken and the voice runs on across the cut.
A line's `nudge` moves it later (+) or earlier (-) than where it would start, so two voices may overlap.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import camera

DEFAULT_SIZE = (1080, 1920)
ASPECTS = ((9, 16), (1, 1), (4, 5), (16, 9))  # the shapes a film may have (formats.SHAPES)
DEFAULT_FPS = 30
TRIM_SLACK = 0.05  # an `end` a hair past the file's length (rounded timings) is read as its end
LEAD = 0.3  # silence before a shot's first line
GAP = 0.25  # between lines in a shot
TAIL = 0.35  # after the last line, before the cut
MAX_SHORT_SECONDS = 180
MIN_PICTURE = 0.5  # seconds a picture stays up at the least when the next one is brought forward by a picture lead
MAX_PICTURE_LEAD = 5.0
MAX_NUDGE = 10.0


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
    nudge: float = 0.0  # seconds later (+) or earlier (-) than where the line would start: a negative one overlaps the line before (an interruption)
    simultaneous: bool = False  # spoken at the same time as the line before in its shot (dual dialogue): it starts when that one starts


@dataclass
class Sfx:
    audio: Path
    at: float = 0.0
    volume: float = 1.0
    duration: float = 0.0
    ref: str | None = None  # what the sound is called outside the manifest (its Marvin sound slug), so a timeline can name it
    fade_in: float = 0.0  # seconds to rise from silence at the start / fall to silence at the end, so a sound does not click on or off
    fade_out: float = 0.0
    line: str | None = None  # placed on a word of a line (a cue, v211): the line's id; `at` is then ignored
    line_at: float | None = None  # seconds into that line (from its word timings)
    line_share: float | None = None  # …or how far into it, 0–1, when the take has no word timings (an estimate from the text)
    line_nudge: float = 0.0  # seconds later (or earlier, negative) than the word puts it, never before the film starts (v216)


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
END_TRANSITIONS = ("cut", "fade")
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
    """How long that fade or dissolve lasts, taken from the two shots around the cut (0 for a cut). On the first shot it is the fade up from black."""
    chapter: str | None = None
    """The id of the chapter this shot belongs to (a story is cut into chapters; see `chapters.py`)."""
    beat_ambience: Ambience | None = None
    """A beat's own bed, laid over `ambience` (its scene's), which runs on under it without a seam: a cheer over the tavern. None: only the scene's."""
    camera_cues: list[dict] = field(default_factory=list)
    """Camera moves on words of the shot's lines (v212): {kind: punch|shake|nudge, amount?, x?, y?, line, at|share}, on top of the shot's own move."""
    starts_during: dict | None = None
    """A picture that comes in at a word of a line of an earlier shot (a Pic note among the words, v211): {"line": its id, "at": seconds into it} or
    {"line", "share": 0–1}. It adds no time of its own; `hold` keeps it up at least that long from where it comes in."""
    picture_lead: float | None = None
    """Seconds before its first word that the shot's picture arrives (a silent shot's: before its own start), over the end of the shot before; the
    sound does not move. None: the picture starts where the shot's sound starts, as it always did. 0: at the first word."""


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
    end_transition: str = "cut"
    """How the picture leaves the last shot: cut, or fade (down to black inside that shot, `end_transition_seconds` long). Never changes a length."""
    end_transition_seconds: float = 0.0
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
    """Where the shot's picture starts on the film (the clip, its camera move, its beds and its chapter all go by the picture)."""
    duration: float
    """How long the picture is up: the shots' pictures follow one another without a gap, from 0 to the end of the film."""
    lines: list[PlannedLine]
    audio_start: float | None = None
    """Where the shot's sound starts: its lead-in, then its lines; its sound effects' `at` counts from here. None: the picture's start (the same
    unless a picture lead or a nudge moved the picture)."""
    audio_duration: float | None = None
    sfx_at: list[float] = field(default_factory=list)
    """Where each of the shot's sound effects starts, in seconds from `audio_start` (one placed on a word, there)."""
    camera: list[tuple[float, dict]] = field(default_factory=list)
    """The camera cues that fall while this shot's picture is up: (seconds into the picture, the cue)."""
    anchor: float | None = None
    """Where on the film the picture of a shot that `starts_during` a line comes in (None for any other shot)."""

    def __post_init__(self) -> None:
        if self.audio_start is None:
            self.audio_start = self.start
        if self.audio_duration is None:
            self.audio_duration = self.duration


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


def _on_a_line(raw: dict, where: str) -> dict:
    """A place on a word of a line: {"line": its id, "at": seconds into it} or {"line", "share": 0–1 of it}."""
    out: dict = {"line": str(raw["line"])}
    try:
        if raw.get("at") not in (None, ""):
            out["at"] = max(0.0, float(raw["at"]))
        elif raw.get("share") not in (None, ""):
            out["share"] = min(max(float(raw["share"]), 0.0), 1.0)
        else:
            out["at"] = 0.0
    except (TypeError, ValueError):
        raise ManifestError(f"{where}: at and share are numbers (got {raw})") from None
    return out


def _nudge(value, where: str) -> float:
    """A line's nudge: seconds later (+) or earlier (-) than its place; empty is 0."""
    if value in (None, ""):
        return 0.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ManifestError(f"{where}: nudge is a number of seconds (got {value!r})") from None
    if not -MAX_NUDGE <= seconds <= MAX_NUDGE:
        raise ManifestError(f"{where}: nudge is -{MAX_NUDGE:g} to {MAX_NUDGE:g} seconds (got {seconds:g})")
    return seconds


def _ambience(amb: dict, audio_path: Callable[[str, str], Path], where: str) -> Ambience:
    """A shot's bed (`ambience`, its scene's; `beat_ambience`, the beat's own over it) from the manifest."""
    return Ambience(
        audio_path(amb.get("audio") or "", where), float(amb.get("volume", 0.5)), bool(amb.get("muffled", False)), amb.get("id"),
        fade_in=float(amb.get("fade_in") or 0), fade_out=float(amb.get("fade_out") or 0),
        fade_in_set=bool(amb.get("fade_in_set")), fade_out_set=bool(amb.get("fade_out_set")),
    )


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
        for j, raw in enumerate(s.get("camera_cues") or [], 1):
            cue = camera.cue_of(raw)
            if cue is None:
                raise ManifestError(f"{where} camera cue {j}: kind is {', '.join(camera.CUES)} (got {raw})")
            placed = _on_a_line({"line": raw.get("line") or "", "at": raw.get("line_at"), "share": raw.get("line_share")}, f"{where} camera cue {j}") if raw.get("line") else {"at": float(raw.get("at") or 0)}
            shot.camera_cues.append({**cue, **placed, **({"nudge": _nudge(raw["nudge"], f"{where} camera cue {j}")} if raw.get("nudge") not in (None, "", 0) else {})})
        if isinstance(s.get("starts_during"), dict) and s["starts_during"].get("line"):
            shot.starts_during = _on_a_line(s["starts_during"], f"{where} starts_during")
        if s.get("picture_lead") not in (None, ""):
            shot.picture_lead = float(s["picture_lead"])
            if not 0 <= shot.picture_lead <= MAX_PICTURE_LEAD:
                raise ManifestError(f"{where}: picture_lead is 0–{MAX_PICTURE_LEAD:g} seconds (got {shot.picture_lead:g})")
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
            shot.ambience = _ambience(s["ambience"], audio_path, f"{where} ambience")
        if s.get("beat_ambience"):
            shot.beat_ambience = _ambience(s["beat_ambience"], audio_path, f"{where} beat_ambience")
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
                    nudge=_nudge(ln.get("nudge"), lw),
                    simultaneous=bool(ln.get("simultaneous", False)),
                )
            )
        for j, fx in enumerate(s.get("sfx") or [], 1):
            file = audio_path(fx.get("audio") or "", f"{where} sfx {j}")
            shot.sfx.append(
                Sfx(file, float(fx.get("at", 0)), float(fx.get("volume", 1)), probe(file), ref=fx.get("id"), fade_in=float(fx.get("fade_in") or 0), fade_out=float(fx.get("fade_out") or 0))
            )
            if fx.get("line"):
                placed = _on_a_line({"line": fx["line"], "at": fx.get("line_at"), "share": fx.get("line_share")}, f"{where} sfx {j}")
                shot.sfx[-1].line, shot.sfx[-1].line_at, shot.sfx[-1].line_share = placed["line"], placed.get("at"), placed.get("share")
                shot.sfx[-1].line_nudge = _nudge(fx.get("nudge"), f"{where} sfx {j}")
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
    end_transition, end_transition_seconds = str(raw.get("end_transition") or "cut"), 0.0
    if end_transition not in END_TRANSITIONS:
        raise ManifestError(f"end_transition is {' or '.join(END_TRANSITIONS)} (got {end_transition})")
    if end_transition != "cut":
        end_transition_seconds = float(raw.get("end_transition_seconds") or DEFAULT_TRANSITION_SECONDS)
        if not 0 < end_transition_seconds <= MAX_END_FADE:  # as long as the beds may fade: the picture goes with them
            raise ManifestError(f"end_transition_seconds is more than 0 and at most {MAX_END_FADE:g} (got {end_transition_seconds:g})")
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
        end_transition=end_transition,
        end_transition_seconds=end_transition_seconds,
        chapters=[Chapter(str(c["id"]), str(c.get("title") or c["id"])) for c in raw.get("chapters") or [] if isinstance(c, dict) and c.get("id")],
    )


def plan(manifest: Manifest) -> Timeline:
    """Lay the shots end to end: each lasts as long as its lines need (with the silences around them), or its hold when that is longer: a beat that is
    too quick to take in is given its hold, the picture staying up after the last line. That is the sound's layout; the pictures are cut from it
    (see `_pictures`), on the same clock, so the film is as long either way."""
    shots: list[PlannedShot] = []
    clock = 0.0
    said: dict[str, PlannedLine] = {}  # every line laid so far, by its id: a cue on one of its words is placed from it
    moves: list[tuple[float, dict]] = []  # the camera cues, where on the film each falls
    for index, shot in enumerate(manifest.shots):
        cursor = shot.lead
        lines: list[PlannedLine] = []
        last_end = 0.0  # where the latest line ends, in the shot's own seconds: with nudges an earlier line may end after the last
        for line in shot.lines:
            together = line.simultaneous and bool(lines)  # dual dialogue: it starts when the line before starts, and the next follows the later of the two
            if together:
                cursor = lines[-1].start - clock
            if line.nudge:
                cursor = max(cursor + line.nudge, -clock)  # never before the film starts; the next line follows this one where it now ends
            lines.append(PlannedLine(line, clock + cursor))
            if together:
                cursor = max(lines[-2].start - clock + lines[-2].line.duration, cursor + line.duration) + shot.gap
                last_end = max(last_end, cursor - shot.gap)
                continue
            last_end = max(last_end, cursor + line.duration)
            cursor += line.duration + shot.gap
        moved = any(line.nudge or line.simultaneous for line in shot.lines)
        spoken = (max(cursor - shot.gap, last_end) if moved else cursor - shot.gap) + shot.tail if shot.lines else 0.0
        said.update((p.line.ref, p) for p in lines if p.line.ref)
        sfx_at = [(max(_on_word(said, fx.line, fx.line_at, fx.line_share) + fx.line_nudge, 0.0) - clock) if fx.line in said else fx.at for fx in shot.sfx]  # on a word: nudged, never before 0
        sfx_end = max((at + fx.duration for at, fx in zip(sfx_at, shot.sfx, strict=True)), default=0.0)
        hold, anchor = shot.hold, None
        if shot.starts_during and shot.starts_during["line"] in said:  # it comes in at a word already spoken: its hold counts from there
            anchor = _on_word(said, shot.starts_during["line"], shot.starts_during.get("at"), shot.starts_during.get("share"))
            hold = max(0.0, anchor + shot.hold - clock) if shot.hold else 0.0
        duration = max(hold, spoken, sfx_end) + shot.after
        if index == len(manifest.shots) - 1:
            duration += manifest.end_hold
        placed = [at if fx.line in said else max(at, 0.0) for at, fx in zip(sfx_at, shot.sfx, strict=True)]  # (one on a word may start before its beat's sound)
        shots.append(PlannedShot(shot, clock, duration, lines, sfx_at=placed, anchor=anchor))
        for cue in shot.camera_cues:
            when = _on_word(said, cue["line"], cue.get("at"), cue.get("share")) if cue.get("line") in said else clock + cue.get("at", 0.0) if not cue.get("line") else None
            if when is not None:
                moves.append((when + cue.get("nudge", 0.0), len(shots) - 1, {k: v for k, v in cue.items() if k not in ("line", "at", "share", "nudge")}))
        clock += duration
    _pictures(shots, clock)
    for when, own, cue in moves:  # a camera cue moves the picture that is up when it falls (a picture that came in at an earlier word, perhaps)
        when = max(when, shots[own].start)  # a nudge never brings it before its own beat's picture is up
        planned = next((p for p in reversed(shots) if p.start <= when + 1e-9), shots[0]) if shots else None
        if planned is not None:
            planned.camera.append((when - planned.start, cue))
    return Timeline(shots)


def _on_word(said: dict[str, PlannedLine], ref: str | None, at: float | None, share: float | None) -> float:
    """Where on the film a place on a word of a line falls: the line's start, and the seconds into it (or its share of the line, for a take with no
    word timings), never past the line's end."""
    placed = said[str(ref)]
    into = at if at is not None else (share or 0.0) * placed.line.duration
    return placed.start + min(max(into, 0.0), placed.line.duration)


def _pictures(shots: list[PlannedShot], total: float) -> None:
    """Where each shot's picture starts and how long it is up. A shot with no picture lead starts its picture where its sound starts (or at its first
    word, when that comes earlier): as it always did. A line's own nudge never moves its picture (v217). One with a lead starts it that long before its first word (a silent one, before its own
    start). A picture brought forward never comes before 0, never leaves the one before it less than MIN_PICTURE, and never comes later than its sound
    starts unless its lead asks for that (a lead shorter than the lead-in). Nothing changes when no shot asks for a lead or a nudge."""
    starts: list[float] = []
    for k, planned in enumerate(shots):
        here = planned.audio_start
        # Where the first word would fall with no nudge of its own: a nudge moves the voice, never the picture cut from it.
        first_word = planned.lines[0].start - planned.lines[0].line.nudge if planned.lines else here
        lead = planned.shot.picture_lead
        wanted = first_word - lead if lead is not None else min(here, first_word)
        if planned.anchor is not None:
            wanted = planned.anchor  # a picture that comes in at a word of a line before it
        if k == 0:
            starts.append(0.0)
        elif wanted == here:
            starts.append(here)
        else:
            starts.append(max(starts[-1], min(max(wanted, starts[-1] + MIN_PICTURE), max(wanted, here), total)))
    if all(at == planned.audio_start for at, planned in zip(starts, shots, strict=True)):
        return  # the pictures are the sound's windows, to the last digit
    for k, planned in enumerate(shots):
        planned.start = starts[k]
        planned.duration = (starts[k + 1] if k + 1 < len(shots) else total) - starts[k]


def overlaps(timeline: Timeline) -> list[tuple[str, str, float]]:
    """Lines a nudge has laid wholly over another line, as (one, the other, seconds they overlap): two voices at once is an interruption, but one
    line hidden under another is more likely a nudge gone too far."""
    placed = sorted((p for s in timeline.shots for p in s.lines if p.line.duration > 0), key=lambda p: p.start)
    found = []
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            if b.start >= a.start + a.line.duration:
                break
            if b.line.simultaneous:
                continue  # dual dialogue: two at once on purpose
            both = min(a.start + a.line.duration, b.start + b.line.duration) - b.start
            if both >= min(a.line.duration, b.line.duration) - 1e-6:
                found.append((a.line.ref or a.line.text[:30], b.line.ref or b.line.text[:30], round(both, 3)))
    return found
