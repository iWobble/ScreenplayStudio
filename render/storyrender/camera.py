"""Camera moves as presets: a name a beat, a scene or the story can pick, which the render turns into the still's move (where the camera looks at the
start and at the end, and how close). A still has no depth and no time, so only the moves a still can show are here: the ones that move the frame
across the picture or in on it. A dolly zoom, a rack focus or an orbit needs more than a picture and is asked for in the picture's own prompt instead.

x and y are where the frame's centre sits in the picture (0 to 1, left to right, top to bottom) and zoom is how close (1 is the whole picture). The frame
never leaves the picture, so a move at zoom 1 has nowhere to go: a pan or a tilt is at 1.3 and more."""

import re
from typing import NamedTuple


class Preset(NamedTuple):
    label: str
    start: tuple[float, float, float]  # x, y, zoom
    end: tuple[float, float, float]
    what: str
    rock: tuple[float, float, float] | None = None  # roll in degrees, seconds for one sway, heave as a share of the picture's height


PRESETS: dict[str, Preset] = {
    "still": Preset("Still", (0.5, 0.5, 1.0), (0.5, 0.5, 1.0), "the camera does not move"),
    "push-in": Preset("Push in", (0.5, 0.5, 1.0), (0.5, 0.5, 1.22), "moves in toward the middle: tension, closeness"),
    "pull-out": Preset("Pull out", (0.5, 0.5, 1.22), (0.5, 0.5, 1.0), "moves back to show the surroundings, or isolate"),
    "zoom-in": Preset("Zoom in", (0.5, 0.5, 1.0), (0.5, 0.5, 1.6), "a long close in on the middle"),
    "zoom-out": Preset("Zoom out", (0.5, 0.5, 1.6), (0.5, 0.5, 1.0), "a long reveal out from the middle"),
    "pan-left": Preset("Pan left", (0.64, 0.5, 1.3), (0.36, 0.5, 1.3), "swings left across the picture"),
    "pan-right": Preset("Pan right", (0.36, 0.5, 1.3), (0.64, 0.5, 1.3), "swings right across the picture"),
    "tilt-up": Preset("Tilt up", (0.5, 0.64, 1.3), (0.5, 0.36, 1.3), "pivots up to reveal height"),
    "tilt-down": Preset("Tilt down", (0.5, 0.36, 1.3), (0.5, 0.64, 1.3), "pivots down"),
    "pedestal-up": Preset("Pedestal up", (0.5, 0.6, 1.1), (0.5, 0.4, 1.1), "rises straight up, without tilting"),
    "pedestal-down": Preset("Pedestal down", (0.5, 0.4, 1.1), (0.5, 0.6, 1.1), "sinks straight down"),
    "truck-left": Preset("Truck left", (0.6, 0.5, 1.15), (0.4, 0.5, 1.15), "slides left alongside the action"),
    "truck-right": Preset("Truck right", (0.4, 0.5, 1.15), (0.6, 0.5, 1.15), "slides right alongside the action"),
    "rocking": Preset("Rocking", (0.5, 0.5, 1.12), (0.5, 0.5, 1.12), "rolls gently from side to side, like a ship at sea", rock=(2.5, 6.0, 0.012)),
    "heavy-rocking": Preset("Heavy rocking", (0.5, 0.5, 1.16), (0.5, 0.5, 1.16), "rolls hard and heaves, like a ship in a storm", rock=(6.0, 4.0, 0.03)),
    "drift": Preset("Drift", (0.46, 0.52, 1.08), (0.54, 0.48, 1.12), "a slow, small float that gives the picture life"),
}


def _point(value: tuple[float, float, float]) -> dict:
    return {"x": value[0], "y": value[1], "zoom": value[2]}


def key_of(name: object) -> str:
    """A preset's key from however it is written: the form's choice reads "Push in", the table's key is "push-in"."""
    return re.sub(r"[\s_-]+", "-", str(name or "").strip().lower())


def move_of(name: object) -> dict | None:
    """The manifest `move` ({from, to}) for a preset's name, or None for a name that is not one (a typo keeps the render's own default move)."""
    preset = PRESETS.get(key_of(name))
    if not preset:
        return None
    move = {"from": _point(preset.start), "to": _point(preset.end)}
    if preset.rock:
        move["rock"] = {"degrees": preset.rock[0], "seconds": preset.rock[1], "heave": preset.rock[2]}
    return move


def pick(beat: dict, scene: dict | None, story: dict) -> str | None:
    """The preset a beat uses: its own, else its scene's, else the story's. A name that is not a preset is skipped for the next, so a typo on a
    beat does not hide the scene's choice."""
    for row in (beat, scene or {}, story):
        name = key_of(row.get("camera"))
        if name in PRESETS:
            return name
    return None


# --- a camera cue on a word (v212) ------------------------------------------------------------------------------------------------------------
# `[[Camera: punch]]` among a line's words moves the camera at that word (the end of the word before the note), on top of the beat's own move:

CUES = {
    "punch": "a quick zoom in that settles back: punch (6% in), punch 1.1 (10% in)",
    "shake": "a short shake that dies away: shake (1.2% of the frame), shake 2 (2%)",
    "nudge": "a short drift toward a point of the picture, which it then stays near: nudge 0.7,0.4 (x, y from 0 to 1)",
    "whip-pan": "a fast sweep sideways that eases back to where it was: whip-pan left, whip-pan right 0.5 (a share of the frame, 0.35 unless given)",
    "sway": "a handheld sway that dies away: sway (0.8% of the frame over 1.5 s), sway 1.5 (1.5%), sway 1.5 3 (over 3 s), sway 3s",
}
PUNCH = 1.06  # how close a punch goes: 6% in
PUNCH_ATTACK, PUNCH_RELEASE = 0.2, 0.3  # seconds in, and back
SHAKE = 1.2  # percent of the frame a shake moves at first
SHAKE_SECONDS, SHAKE_DECAY = 0.3, 0.12  # how long it lasts, and how fast it dies away
SHAKE_HZ = (7.0, 5.5)  # side to side and up and down, out of step: well under half a draft's 24 frames a second, so no frame rate hides it
NUDGE_SECONDS, NUDGE_ZOOM, NUDGE_SHARE = 0.4, 1.04, 0.35  # the drift's length, the room it makes, and how far toward the point it goes
ROOM_ATTACK = 0.03  # seconds a shake, a sway or a whip-pan takes to zoom in just far enough to have room to move (v218), released as it dies away
WHIP, MAX_WHIP = 0.35, 0.5  # how far a whip-pan sweeps, as a share of the frame
WHIP_OUT, WHIP_BACK = 0.12, 0.45  # seconds out (fast, with a streak of motion blur), and back
SWAY, SWAY_SECONDS = 0.8, 1.5  # percent of the frame a sway moves at first, and how long it takes to die away
SWAY_HZ = (1.1, 0.8)  # slow, side to side and up and down out of step


def cue_of(raw: object) -> dict | None:
    """A cue's camera ({kind, amount?, x?, y?, seconds?}) checked: None for a kind that is not one of CUES, or a number that is not one; numbers out
    of range are held in it. A whip-pan's x is its direction (-1 left, 1 right); a sway's seconds how long it lasts."""
    if not isinstance(raw, dict) or str(raw.get("kind") or "").lower() not in CUES:
        return None
    kind = str(raw["kind"]).lower()
    out: dict = {"kind": kind}
    try:
        if kind == "nudge":
            out["x"], out["y"] = min(max(float(raw.get("x", 0.5)), 0.0), 1.0), min(max(float(raw.get("y", 0.5)), 0.0), 1.0)
            return out
        if kind == "whip-pan" and raw.get("x") not in (None, ""):
            out["x"] = -1 if float(raw["x"]) < 0 else 1
        if raw.get("amount") is not None:
            amount = float(raw["amount"])
            out["amount"] = {"punch": (1.0, 1.5), "whip-pan": (0.05, MAX_WHIP), "sway": (0.0, 5.0)}.get(kind, (0.0, 10.0))
            out["amount"] = min(max(amount, out["amount"][0]), out["amount"][1])
        if kind == "sway" and raw.get("seconds") not in (None, ""):
            out["seconds"] = min(max(float(raw["seconds"]), 0.2), 10.0)
    except (TypeError, ValueError):
        return None
    return out


# --- a look on a word (v218) ------------------------------------------------------------------------------------------------------------------
# `[[Look: flash]]` among a line's words changes how the picture looks at that word (the end of the word before the note), for a moment, laid over
# the shot's own picture and never changing its length or its sound. Each kind's words after it, in this order: a colour word, then the amount,
# then the seconds; any may be left out, and a number written `2s` is always the seconds (`blur 2s`: the default strength, for two seconds).

LOOKS = {
    "flash": "a quick flash of white over the picture: flash, flash 0.6 (how bright, 0-1), flash orange 0.6 0.4 (a colour, and seconds)",
    "burn": "a flash in orange, like a film burn: burn, burn 0.7 0.5",
    "dip": "a dip to black and back: dip, dip white, dip white 1.2 (seconds, down over half and up over half)",
    "freeze": "the camera's move (and a shake, a punch) holds still, then carries on: freeze, freeze 1 (seconds)",
    "tint": "a colour from the word to the end of the beat: tint sepia, tint mono, tint cold 0.5 (how much, 0-1), tint warm 1 2 (for 2 seconds)",
    "blur": "starts out of focus and sharpens: blur, blur 0.6 (how strong, 0-1), blur 0.6 1.2 (over 1.2 s)",
    "vignette": "the edges darken and release: vignette, vignette 0.8 (how dark, 0-1), vignette 0.8 2 (over 2 s)",
    "glitch": "a short burst of split colour and jitter: glitch, glitch 0.4 (seconds)",
}
LOOK_SLOTS = {  # the words each kind takes after its name, in order (see above)
    "flash": ("color", "amount", "seconds"), "burn": ("amount", "seconds"), "dip": ("color", "seconds"), "freeze": ("seconds",),
    "tint": ("color", "amount", "seconds"), "blur": ("amount", "seconds"), "vignette": ("amount", "seconds"), "glitch": ("seconds",),
}  # fmt: skip
LOOK_DEFAULTS = {  # (amount, seconds, colour): None where a kind has none (a tint without seconds lasts to the end of its beat)
    "flash": (0.9, 0.25, "white"), "burn": (0.9, 0.35, "orange"), "dip": (1.0, 0.8, "black"), "freeze": (None, 0.6, None),
    "tint": (1.0, None, "sepia"), "blur": (0.6, 0.8, None), "vignette": (0.7, 1.0, None), "glitch": (None, 0.2, None),
}  # fmt: skip
FLASHES = {"white": "white", "black": "black", "orange": "0xff8a1e", "red": "0xe0201c", "gold": "0xffd25a", "blue": "0x5aa0ff"}  # a flash's or a dip's colour
TINTS = {  # a tint's colour, as an RGB matrix (each row: how much of R, G, B makes the new R, G, B)
    "sepia": ((0.393, 0.769, 0.189), (0.349, 0.686, 0.168), (0.272, 0.534, 0.131)),
    "mono": ((0.299, 0.587, 0.114),) * 3,
    "cold": ((0.85, 0.0, 0.0), (0.0, 0.97, 0.05), (0.05, 0.1, 1.15)),
    "warm": ((1.12, 0.05, 0.0), (0.02, 1.0, 0.0), (0.0, 0.0, 0.8)),
}
MAX_LOOK_SECONDS = 30.0
FLASH_RISE = 0.04  # seconds a flash takes to come up: it falls away over the rest of its seconds


def _seconds_in(value: object, low: float = 0.05, high: float = MAX_LOOK_SECONDS) -> float:
    return min(max(float(value), low), high)  # type: ignore[arg-type]


def look_of(raw: object) -> dict | None:
    """A cue's look ({kind, amount?, seconds?, color?}) checked: None for a kind that is not one of LOOKS, a colour it does not know or a number that
    is not one; numbers out of range are held in it (amount 0-1, seconds 0.05-30)."""
    if not isinstance(raw, dict) or str(raw.get("kind") or "").lower() not in LOOKS:
        return None
    kind = str(raw["kind"]).lower()
    slots = LOOK_SLOTS[kind]
    out: dict = {"kind": kind}
    try:
        if "color" in slots and raw.get("color") not in (None, ""):
            color = str(raw["color"]).strip().lower()
            if color not in (TINTS if kind == "tint" else FLASHES if kind == "flash" else ("black", "white")):
                return None
            out["color"] = color
        if "amount" in slots and raw.get("amount") not in (None, ""):
            out["amount"] = min(max(float(raw["amount"]), 0.0), 1.0)
        if raw.get("seconds") not in (None, ""):
            out["seconds"] = _seconds_in(raw["seconds"])
    except (TypeError, ValueError):
        return None
    return out


# --- the mix at a word (v219) -----------------------------------------------------------------------------------------------------------------
# `[[Mix: dead-air 2]]` among a line's words changes the beds under the voice at that word for a while; the voice itself is never touched.

MIXES = {
    "dead-air": "the beds, the music and the sounds already playing drop to silence, and come back: dead-air, dead-air 2 (seconds)",
    "duck": "the music and the beds dip under for a while: duck, duck 0.3 (the level they dip to, 0-1), duck 0.3 2 (for 2 seconds), duck 2s",
}
MIX_SLOTS = {"dead-air": ("seconds",), "duck": ("amount", "seconds")}
MIX_DEFAULTS = {"dead-air": (0.0, 1.5), "duck": (0.3, 1.5)}  # (the level they go to, seconds)
MIX_RAMPS = {"dead-air": (0.1, 0.1), "duck": (0.25, 0.5)}  # seconds down, and back up


def mix_of(raw: object) -> dict | None:
    """A cue's mix ({kind, amount?, seconds?}) checked: None for a kind that is not one of MIXES or a number that is not one; numbers out of range
    are held in it (amount 0-1, seconds 0.05-30)."""
    if not isinstance(raw, dict) or str(raw.get("kind") or "").lower() not in MIXES:
        return None
    kind = str(raw["kind"]).lower()
    out: dict = {"kind": kind}
    try:
        if kind == "duck" and raw.get("amount") not in (None, ""):
            out["amount"] = min(max(float(raw["amount"]), 0.0), 1.0)
        if raw.get("seconds") not in (None, ""):
            out["seconds"] = _seconds_in(raw["seconds"])
    except (TypeError, ValueError):
        return None
    return out


EMPHASIS, MAX_EMPHASIS = 1.3, 2.0  # how much bigger an emphasised word is in the captions


def emphasis_of(raw: object) -> dict | None:
    """A cue's emphasis (true, or {scale?}) checked: {} or {"scale": 1-2}; None for false or anything else."""
    if raw is True:
        return {}
    if not isinstance(raw, dict):
        return None
    if raw.get("scale") in (None, ""):
        return {}
    try:
        return {"scale": min(max(float(raw["scale"]), 1.0), MAX_EMPHASIS)}
    except (TypeError, ValueError):
        return None

