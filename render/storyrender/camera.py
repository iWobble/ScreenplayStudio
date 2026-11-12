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
