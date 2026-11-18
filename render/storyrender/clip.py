"""A beat's clip (v223): a short video of the author (a webcam take) played over the beat's still, picture-in-picture, with its own sound.

    "clip": {"video": "video/clips/b04.webm", "look": "pip", "corner": "bottom-right", "size": 0.28, "shape": "circle",
             "audio": true, "volume": 1.0, "start": 0, "end": null}

The still (with its camera move, its overlay) is the background; the clip is cropped to a square from its centre, masked to a circle, a rounded
square or a square, scaled to `size` of the frame's width and set in a corner with a 3% margin and a thin soft border. It plays from the
shot's picture start and is gone when it ends. Its sound is mixed in from that same point, like a spoken line (the music ducks under it). The shot
lasts at least as long as the (trimmed) clip. A clip file that is missing or cannot be read is left out, and said so; a bad setting is refused.
`full` (the clip filling the frame) is reserved: it is not built yet, so it plays as `pip` and says so.

Everything the renderer needs is here: the shape of the settings, how they are checked, the filter graph that lays the clip over a shot, and the
clip's sound as a piece of the mix. `manifest`, `build` and `marvin_pull` call in at one place each.
"""

import functools
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LOOKS = ("pip", "full")
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
SHAPES = ("circle", "rounded", "square")
MIN_SIZE, MAX_SIZE = 0.15, 0.5
DEFAULT_SIZE = 0.28
MARGIN = 0.03  # of the frame's width, between the clip's border and the frame's edges
BORDER = 0.006  # the border's width, of the frame's width (6 px on a 1080 frame), at least 2 px
BORDER_COLOUR = "white"
BORDER_OPACITY = 0.85
ROUNDING = 0.18  # a rounded square's corner radius, of its side
FADE_OUT = 0.25  # seconds the clip fades away over as it ends, so it does not blink off
FALLBACK_HOLD = 4.0  # seconds a beat whose clip was all it had is held when the clip cannot be read (the pull's default hold for a silent picture)
TRIM_SLACK = 0.05  # an `end` a hair past the file's length (rounded timings) is read as its end


class ClipError(ValueError):
    pass


@dataclass
class Clip:
    video: Path
    duration: float
    """Seconds the clip plays: from `start` to `end` (or the file's end)."""
    look: str = "pip"
    corner: str = "bottom-right"
    size: float = DEFAULT_SIZE
    """The clip's width (without its border) as a share of the frame's width."""
    shape: str = "circle"
    audio: bool = True
    """Its own sound plays (when the file has any)."""
    volume: float = 1.0
    start: float = 0.0
    end: float | None = None
    ref: str | None = None


def _number(raw: dict, key: str, default: float | None, where: str) -> float | None:
    value = raw.get(key)
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ClipError(f"{where}: {key} is a number (got {value!r})")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ClipError(f"{where}: {key} is a number (got {value!r})") from None


def _choice(raw: dict, key: str, options: tuple[str, ...], default: str, where: str) -> str:
    value = str(raw.get(key) or default).strip().lower()
    if value not in options:
        raise ClipError(f"{where}: {key} is {', '.join(options)} (got {raw.get(key)!r})")
    return value


def _flag(value, default: bool = True) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "off", "0")
    return bool(value)


def check(raw: dict, where: str) -> dict:
    """The clip's settings from the manifest, checked (everything but the file and its length): a ClipError naming `where` for a bad one."""
    if not isinstance(raw, dict):
        raise ClipError(f"{where}: clip is an object with a video (got {raw!r})")
    size = _number(raw, "size", DEFAULT_SIZE, where)
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ClipError(f"{where}: size is {MIN_SIZE:g}–{MAX_SIZE:g} of the frame's width (got {size:g})")
    volume = _number(raw, "volume", 1.0, where)
    if not 0 <= volume <= 1:
        raise ClipError(f"{where}: volume is 0–1 (got {volume:g})")
    start = _number(raw, "start", 0.0, where)
    end = _number(raw, "end", None, where)
    if start < 0:
        raise ClipError(f"{where}: start is 0 or more seconds (got {start:g})")
    if end is not None and end <= start:
        raise ClipError(f"{where}: end {end:g}s must come after start {start:g}s")
    return {
        "look": _choice(raw, "look", LOOKS, "pip", where),
        "corner": _choice(raw, "corner", CORNERS, "bottom-right", where),
        "shape": _choice(raw, "shape", SHAPES, "circle", where),
        "size": size,
        "volume": volume,
        "audio": _flag(raw.get("audio")),
        "start": start,
        "end": end,
    }


def load(raw: dict, find: Callable[[str], Path], probe: Callable[[Path], float], where: str, notes: list[str]) -> Clip | None:
    """A shot's clip from the manifest. A bad setting raises ClipError naming `where`; a file that is missing or cannot be measured gives None and
    a line in `notes` (the beat renders without it). `find` turns the manifest's path into a file (None-safe: it may raise OSError); `probe`
    measures it (the same probe the lines use)."""
    settings = check(raw, where)
    name = str(raw.get("video") or "")
    try:
        file = find(name)
        if not name or not file.is_file():
            raise FileNotFoundError(name or "no file named")
        try:
            total = float(probe(file))
        except Exception as unheard:  # noqa: BLE001
            try:  # a browser's webm with no sound (the microphone was refused) and no length in its header: the probe listens, so watch it instead
                total = _picture_seconds(file)
            except Exception:  # noqa: BLE001
                raise unheard from None  # what the probe said is the reason worth giving
    except Exception as e:  # noqa: BLE001  (a clip that cannot be read must never stop the film: it is left out, and said)
        notes.append(f"{where}: the clip {name or '(none)'} could not be read ({str(e).splitlines()[0][:200] if str(e) else type(e).__name__}), so the beat plays without it")
        return None
    if settings["start"] >= total:
        raise ClipError(f"{where}: start {settings['start']:g}s is past the end of the {total:.2f}s clip")
    if settings["end"] is not None and settings["end"] > total + TRIM_SLACK:
        raise ClipError(f"{where}: end {settings['end']:g}s is past the end of the {total:.2f}s clip")
    end = min(settings["end"], total) if settings["end"] is not None else None
    if settings["look"] == "full":
        notes.append(f"{where}: the clip's full-frame look is not built yet, so it plays in a corner (pip)")
        settings["look"] = "pip"
    return Clip(
        video=file, duration=(end if end is not None else total) - settings["start"], look=settings["look"], corner=settings["corner"],
        size=settings["size"], shape=settings["shape"], audio=settings["audio"], volume=settings["volume"], start=settings["start"], end=end,
        ref=str(raw["id"]) if raw.get("id") else None,
    )  # fmt: skip


def _picture_seconds(path: Path) -> float:
    """How long a video's picture runs, by decoding it to nowhere (for a file whose header has no length and which has no sound to measure)."""
    done = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-an", "-f", "null", "-progress", "pipe:1", "-"], capture_output=True, text=True)
    micro = max((int(v) for k, _, v in (line.partition("=") for line in done.stdout.splitlines()) if k == "out_time_us" and v.strip().isdigit()), default=0)
    if done.returncode != 0 or micro <= 0:
        raise ValueError(f"ffmpeg can't read {path.name} as a video: {done.stderr.strip()[-200:]}")
    return micro / 1_000_000


# ── the picture ──────────────────────────────────────────────────────────────
def _even(n: float) -> int:
    return max(2, 2 * round(n / 2))


@dataclass(frozen=True)
class Box:
    """Where a clip sits, in pixels of the frame: `side` the clip's own square, `border` around it, `x`/`y` the top left of the bordered square."""

    side: int
    border: int
    x: int
    y: int

    @property
    def outer(self) -> int:
        return self.side + 2 * self.border


def box(clip: Clip, size: tuple[int, int]) -> Box:
    width, height = size
    side = _even(clip.size * width)
    border = max(2, round(BORDER * width))
    margin = round(MARGIN * width)
    outer = side + 2 * border
    x = margin if clip.corner.endswith("left") else width - margin - outer
    y = margin if clip.corner.startswith("top") else height - margin - outer
    return Box(side, border, x, y)


def _alpha(side: float, centre: float, radius: float, soft: float) -> str:
    """A geq expression, 0–255: inside the shape (a square of `side` centred at `centre`, corners rounded by `radius`) 255, outside 0, with an
    edge `soft` pixels wide. It is the signed distance to a rounded square: a circle is one rounded all the way, a square one not rounded at all."""
    half = side / 2
    qx, qy = f"(abs(X+0.5-{centre:g})-{half - radius:g})", f"(abs(Y+0.5-{centre:g})-{half - radius:g})"
    distance = f"(hypot(max({qx},0),max({qy},0))+min(max({qx},{qy}),0)-{radius:g})"
    return f"255*clip(0.5-{distance}/{soft:g},0,1)"


def _radius(shape: str, side: float) -> float:
    return side / 2 if shape == "circle" else side * ROUNDING if shape == "rounded" else 0.0


def trim(clip: Clip) -> str:
    """The part of the clip that plays, from 0 (its timestamps reset first: a browser's webm may not start at 0). Empty when it is the whole file."""
    if not clip.start and clip.end is None:
        return ""
    end = f":end={clip.end:.4f}" if clip.end is not None else ""
    return f"trim=start={clip.start:.4f}{end},"


def video_filter(clip: Clip, index: int, size: tuple[int, int], fps: int, shown: float, into: str, out: str) -> str:
    """The filter graph part that lays the clip (input `index`) over the shot's picture (label `into`) and leaves it as `out`. The clip is cut to its
    part, cropped square from its centre, scaled, framed by a soft border, masked to its shape, faded away over its last moments and laid in its
    corner from the picture's first frame; once it ends the picture shows alone. `shown` is how long the picture is up (a clip that outlasts its
    picture is cut with it)."""
    b = box(clip, size)
    side, outer, border = b.side, b.outer, b.border
    centre = outer / 2
    inner_r = _radius(clip.shape, side)
    outer_r = inner_r + border if clip.shape != "square" else 0.0
    plays = min(clip.duration, shown) if shown > 0 else clip.duration
    fade = min(FADE_OUT, plays / 2)
    still = f"r={fps}:d={1 / fps:.6f}"  # one frame: a mask or a plate is the same for every frame, and is held after its one frame
    return ";".join([
        f"[{index}:v]setpts=PTS-STARTPTS,{trim(clip)}setpts=PTS-STARTPTS,fps={fps},crop='min(iw,ih)':'min(iw,ih)',scale={side}:{side},setsar=1,"
        f"pad={outer}:{outer}:{border}:{border}:color={BORDER_COLOUR},format=gbrp[clipv]",
        f"color=c={BORDER_COLOUR}:s={outer}x{outer}:{still},format=gbrp[clipw]",
        f"color=c=black:s={outer}x{outer}:{still},format=gray,geq=lum='{_alpha(side, centre, inner_r, 1)}',format=gbrp[clipm]",
        "[clipw][clipv][clipm]maskedmerge[clipf]",  # the clip inside its shape, the border colour around it
        f"color=c=black:s={outer}x{outer}:{still},format=gray,"  # the clip solid, its border a little see-through and soft at its edge
        f"geq=lum='max({_alpha(side, centre, inner_r, 1)},{BORDER_OPACITY:g}*{_alpha(outer, centre, outer_r, max(1.5, border * 0.6))})'[clipa]",
        f"[clipf]format=gbrap[clipg];[clipg][clipa]alphamerge,"
        f"fade=t=out:st={max(plays - fade, 0):.3f}:d={fade:.3f}:alpha=1[clipp]",
        f"{into}format=rgba[clipb];[clipb][clipp]overlay=x={b.x}:y={b.y}:eof_action=pass:format=auto,format=yuv420p{out}",
    ])  # fmt: skip


# ── the sound ────────────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=None)
def _has_sound(path: Path) -> bool:
    from . import ffmpeg

    try:
        return any(s.get("codec_type") == "audio" for s in ffmpeg.probe(path).get("streams") or [])
    except Exception:  # noqa: BLE001  (unreadable: nothing to hear)
        return False


def heard(clip: Clip | None) -> bool:
    """Whether the clip's sound is in the mix: it asks for it, at a level above 0, and the file has a sound at all."""
    return clip is not None and clip.audio and clip.volume > 0 and clip.duration > 0 and _has_sound(clip.video)


def audio_cut(clip: Clip) -> str:
    """The audio filter (with a trailing comma) that takes the clip's part of its sound, from 0 like the picture."""
    if not clip.start and clip.end is None:
        return "asetpts=PTS-STARTPTS,"
    end = f":end={clip.end:.4f}" if clip.end is not None else ""
    return f"asetpts=PTS-STARTPTS,atrim=start={clip.start:.4f}{end},asetpts=PTS-STARTPTS,"


# ── from a beat in Marvin ────────────────────────────────────────────────────
FIELDS = (("look", "clip_look"), ("corner", "clip_corner"), ("size", "clip_size"), ("shape", "clip_shape"), ("audio", "clip_audio"),
          ("volume", "clip_volume"), ("start", "clip_start"), ("end", "clip_end"))  # fmt: skip


def from_beat(beat: dict, fetch: Callable[[str], Path], out: Path, where: str, notes: list[str]) -> dict | None:
    """A beat's `clip` (a video asset) and its `clip_*` settings as the manifest's shot `clip`, the file fetched with `fetch` (asset id → the file
    under `out`). The settings are handed on as they are written, so a bad one is refused by the render with the beat's name; an empty one is left
    out (the default). None for a beat with no clip, and for one whose file cannot be fetched (said in `notes`: the beat plays without it)."""
    asset = str(beat.get("clip") or "").strip()
    if not asset:
        return None
    try:
        file = fetch(asset)
    except Exception as e:  # noqa: BLE001  (a clip that cannot be fetched must not stop the film)
        notes.append(f"{where}: its clip could not be fetched ({str(e).splitlines()[0][:200] if str(e) else type(e).__name__}), so it plays without it")
        return None
    settings = {key: beat[field] for key, field in FIELDS if beat.get(field) not in (None, "")}
    for key in ("look", "corner", "shape"):
        if key in settings:
            settings[key] = str(settings[key]).strip().lower()
    return {"video": str(file.relative_to(out)), "id": asset, **settings}
