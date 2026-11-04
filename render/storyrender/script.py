"""A story's records → a screenplay: Fountain (plain text, the standard screenplay markup), then a PDF and an HTML page.

The records are the source of truth, so the script is made from them, not written by hand:

    scene            →  a scene heading            .THE MESS #5#     (the number is its first beat's)
    scene place/look →  the first action line      The mess: twin long tables… Lantern-lit evening.
    scene ambience   →  a sound line               SFX: harbour ambience, under the scene
    beat picture     →  an action line             05 — Medium close-up of the captain, seated.
    beat sounds      →  a sound line               SFX 1.6s: spoon on bowl
    speech line      →  a character cue + text     CAPTAIN / (tired, a little amused) / Make do.
    narrator         →  NARRATOR (V.O.)

`direction` on a line becomes its parenthetical, so what is written for the voice is what a person reads when they record it.
`fountain()` is pure (records in, text out); `pull_records()` reads Marvin; `render()` runs `screenplain` for the PDF and HTML.
"""

import re
import shutil
import subprocess
from pathlib import Path

NARRATOR = "narrator"


def _data(row: dict) -> dict:
    return row.get("dataJson") or row.get("data") or {}


def _clean(text: object) -> str:
    """One line of plain text: Fountain reads leading symbols and blank lines as markup, so a stray one is made harmless."""
    return " ".join(str(text or "").split())


def _cue(speaker: str) -> str:
    name = _clean(speaker).upper() or "VOICE"
    return f"{name} (V.O.)" if _clean(speaker).lower() == NARRATOR else name


def _slug_words(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug or "").strip()


def _seconds(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return f"{number:g}s"


def _sound_line(placed: dict, sounds: dict) -> str:
    sound = sounds.get(str(placed.get("sound")), {})
    name = _clean(sound.get("title") or _slug_words(str(placed.get("sound") or ""))) or "sound"
    when = _seconds(placed.get("at"))
    return f"SFX {when}: {name.lower()}" if when else f"SFX: {name.lower()}"


def fountain(records: dict) -> str:
    """The Fountain text for `records`: {"story": row, "scenes": {slug: row}, "beats": [row], "lines": {beat slug: [row]}, "sounds": {slug: row}}."""
    story = records["story"]
    scenes, sounds = records.get("scenes", {}), records.get("sounds", {})
    lines_by_beat = records.get("lines", {})
    out: list[str] = [f"Title: {_clean(story.get('title') or story.get('slug'))}", "Credit: A Storyworld film"]
    seconds = _seconds(_data(story).get("target_seconds"))
    if seconds:
        out.append(f"Notes: about {seconds} long")
    out.append("")  # screenplain starts the script on a new page after the title page by itself (a `===` here would leave a blank one)

    scene_now, bed_now = None, None
    for beat in records.get("beats", []):
        d = _data(beat)
        number = str(d.get("number") or "").strip()
        scene_slug = d.get("scene")
        if scene_slug and scene_slug != scene_now:
            scene_now = scene_slug
            scene = scenes.get(str(scene_slug), {})
            heading = _clean(scene.get("title") or _slug_words(str(scene_slug))).upper()
            tag = f" #{int(number)}#" if number.isdigit() else ""
            out += [f".{heading}{tag}", ""]
            sd = _data(scene)
            setting = " ".join(x for x in (_clean(sd.get("place")), _clean(sd.get("look"))) if x)
            if setting:
                out += [setting, ""]
            if sd.get("ambience") != bed_now:  # said when the ambience changes, not at every scene that shares it
                bed_now = sd.get("ambience")
                if bed_now:
                    bed = sounds.get(str(bed_now), {})
                    out += [f"SFX: {_clean(bed.get('title') or _slug_words(str(bed_now))).lower()}, under the scene", ""]
        picture = _clean(d.get("picture"))
        out += [f"{number} — {picture}" if picture else f"{number} —", ""]
        for placed in d.get("sounds") if isinstance(d.get("sounds"), list) else []:
            if isinstance(placed, dict) and placed.get("sound"):
                out += [_sound_line(placed, sounds), ""]
        for line in lines_by_beat.get(beat.get("slug", ""), []):
            ld = _data(line)
            spoken = _clean(ld.get("text"))
            if not spoken:
                continue
            out.append(_cue(ld.get("speaker") or ""))
            if _clean(ld.get("direction")):
                out.append(f"({_clean(ld['direction']).rstrip('.').lower()})")
            out += [spoken, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def pull_records(story: str, creds: tuple[str, str]) -> dict:
    """The story's records from Marvin, in the shape `fountain()` reads."""
    from marvin_worker import marvin_api

    rows = marvin_api.entries(creds)
    story_row = next((e for e in rows if e.get("slug") == story), None)
    if story_row is None:
        raise LookupError(f"no story “{story}” in this workspace")
    beats = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-beat-") and _data(e).get("story") == story), key=lambda e: str(_data(e).get("number")))
    lines: dict[str, list[dict]] = {}
    for line in sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-line-") and _data(e).get("story") == story), key=lambda e: e["slug"]):
        lines.setdefault(str(_data(line).get("beat")), []).append(line)
    return {
        "story": story_row,
        "beats": beats,
        "lines": lines,
        "scenes": {e["slug"]: e for e in rows if _data(e).get("story") == story and "ambience" in _data(e)},
        "sounds": {e["slug"]: e for e in rows if e.get("slug", "").find("-sound-") >= 0},
    }


def render(text: str, out: Path, stem: str) -> dict[str, Path]:
    """Write `<stem>.fountain`, and a PDF and an HTML page made from it with screenplain (Courier 12, the standard screenplay layout)."""
    out.mkdir(parents=True, exist_ok=True)
    source = out / f"{stem}.fountain"
    source.write_text(text, encoding="utf-8")
    exe = shutil.which("screenplain")
    if exe is None:
        raise RuntimeError("screenplain is not installed (pip install screenplain)")
    made = {"fountain": source}
    for fmt, extension in (("pdf", "pdf"), ("html", "html")):
        target = out / f"{stem}.{extension}"
        done = subprocess.run([exe, "-f", fmt, str(source), str(target)], capture_output=True, text=True, timeout=120)  # noqa: S603
        if done.returncode != 0:
            raise RuntimeError(f"screenplain {fmt} failed: {(done.stderr or done.stdout).strip()[:300]}")
        made[fmt] = target
    return made
