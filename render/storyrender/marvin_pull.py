"""Pull a story's recorded lines out of Marvin and lay them out the way `listen` and `render` read them.

Marvin keeps the story (its beats, its speech lines, the audio of each take). This reads those records with the signed-in
CLI's token (`~/.marvin/credentials.json`, from `marvin auth login`), downloads each recorded take, and writes
`manifest.json` + `audio/<line>.<ext>` (and `stills/<beat>.<ext>` for any beat that has a still). Nothing is written back.
The Marvin calls are `marvin_worker.marvin_api`'s (it names itself to Marvin's edge, which refuses Python's default user agent).
"""

import json
from pathlib import Path

from marvin_worker import marvin_api

CREDENTIALS = Path.home() / ".marvin" / "credentials.json"


class PullError(RuntimeError):
    pass


def credentials(path: Path = CREDENTIALS) -> tuple[str, str]:
    try:
        raw = json.loads(path.read_text())
        return str(raw["apiUrl"]).rstrip("/"), str(raw["userToken"])
    except (OSError, KeyError, json.JSONDecodeError) as e:
        raise PullError(f"can't read Marvin credentials from {path} ({e}); run `marvin auth login`") from e


def _extension(mime: str | None, fallback: str) -> str:
    return {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
        (mime or "").split(";")[0].lower(), fallback
    )


def _fetch_asset(creds: tuple[str, str], asset_id: str, dest_stem: Path, fallback_ext: str) -> Path:
    return _fetch_asset_with_record(creds, asset_id, dest_stem, fallback_ext)[0]


def _fetch_asset_with_record(creds: tuple[str, str], asset_id: str, dest_stem: Path, fallback_ext: str) -> tuple[Path, dict]:
    """The asset's file, and its record (its metadata holds what the recording knows about itself)."""
    record = marvin_api.asset(creds, asset_id)
    dest = dest_stem.with_suffix("." + _extension(record.get("mimeType"), fallback_ext))
    marvin_api.download_asset(creds, asset_id, dest)
    return dest, record


def pull(story: str, out: Path, *, creds: tuple[str, str] | None = None) -> dict:
    """Write `out/manifest.json` for the story's recorded lines. Returns what was found: the shots, and the lines still to record."""
    creds = creds or credentials()
    try:
        return _pull(story, out, creds)
    except marvin_api.MarvinError as e:
        raise PullError(str(e)) from e


def _pull(story: str, out: Path, creds: tuple[str, str]) -> dict:
    rows = marvin_api.entries(creds)
    data = lambda e: e.get("dataJson") or e.get("data") or {}  # noqa: E731
    story_row = next((e for e in rows if e.get("slug") == story), None)
    if story_row is None:
        raise PullError(f"no story “{story}” in the workspace the CLI is signed in to")
    beats = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-beat-") and data(e).get("story") == story), key=lambda e: str(data(e).get("number")))
    lines = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-line-") and data(e).get("story") == story), key=lambda e: e["slug"])
    by_beat: dict[str, list[dict]] = {}
    for line in lines:
        by_beat.setdefault(str(data(line).get("beat")), []).append(line)

    scenes = {e["slug"]: e for e in rows if data(e).get("story") == story and "ambience" in data(e)}  # scenes that name an ambience
    # Sounds belong to the library, not to a story: each is found by the slug a beat or scene names, whichever story made it.
    wanted = {str(item.get("sound")) for b in beats for item in (data(b).get("sounds") if isinstance(data(b).get("sounds"), list) else []) if isinstance(item, dict)}
    wanted |= {str(data(sc).get("ambience")) for sc in scenes.values() if data(sc).get("ambience")}
    sounds = {e["slug"]: e for e in marvin_api.query(creds, {"entries": sorted(wanted)}, limit=max(len(wanted), 1))} if wanted else {}
    taken: dict[str, Path] = {}  # an ambience's take is downloaded once, however many beats use it
    shots, missing = [], []
    for beat in beats:
        number = str(data(beat).get("number"))
        spoken = []
        for line in by_beat.get(beat["slug"], []):
            d = data(line)
            if not d.get("audio"):
                missing.append(line["slug"])
                continue
            file, record = _fetch_asset_with_record(creds, str(d["audio"]), out / "audio" / line["slug"], "mp3")
            entry = {"id": line["slug"], "audio": str(file.relative_to(out)), "text": d.get("caption") or d.get("text") or "", "speaker": d.get("speaker")}
            if words := spoken_words(d, record.get("metadataJson")):
                entry["words"] = words
            spoken.append(entry)
        effects = _sound_effects(creds, out, data(beat).get("sounds"), sounds, data, missing)
        if not spoken and not effects and not data(beat).get("hold_seconds"):
            continue  # nothing to hear and no time asked for; a held beat (the closing smile) is a silent shot, and stays
        shot: dict = {"id": f"b{number}", "lines": spoken}
        for key, field in (("lead", "lead_seconds"), ("gap", "gap_seconds"), ("tail", "tail_seconds")):
            if data(beat).get(field) is not None:  # empty keeps the renderer's default
                shot[key] = float(data(beat)[field])
        if effects:
            shot["sfx"] = effects
        bed = _ambience(creds, out, data(beat), scenes, sounds, data, taken, missing)
        if bed:
            shot["ambience"] = bed
        if not spoken and data(beat).get("hold_seconds"):
            shot["hold"] = float(data(beat)["hold_seconds"])  # a sound-only beat lasts as long as its beat sheet window (a spoken one, as long as its audio)
        if isinstance(data(beat).get("move"), dict):
            shot["move"] = data(beat)["move"]  # where the camera looks: {"from": {x, y, zoom}, "to": {...}}, so one still can serve several beats
        if data(beat).get("still"):
            still = _fetch_asset(creds, str(data(beat)["still"]), out / "stills" / f"b{number}", "png")
            shot["still"] = str(still.relative_to(out))
        shots.append(shot)
    if not shots:
        raise PullError(f"“{story}” has no recorded lines yet: record some with the screenplay-record-lines workflow")
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({"title": story_row.get("title") or story, "shots": shots}, indent=2, ensure_ascii=False))
    return {"manifest": str(out / "manifest.json"), "shots": len(shots), "lines": sum(len(s["lines"]) for s in shots), "not_recorded": missing}


def spoken_words(d: dict, metadata: dict | None) -> list[dict]:
    """The word timings for captions: [{text, start, end}] in seconds, from the *recording's own* metadata (the voice service's answer
    is kept on the asset), so a line that keeps several takes gets the timings of the one it uses, whichever that is.

    Left out when the caption is not the spoken text (a caption override cannot be aligned to the words), and a v3 delivery tag such as
    "[sighs]" is dropped, since it is direction and not something said or shown.
    """
    if d.get("caption") and d.get("caption") != d.get("text"):
        return []
    raw = (metadata or {}).get("words")
    words = [w for w in raw if isinstance(w, dict) and w.get("text") is not None] if isinstance(raw, list) else []
    return [w for w in words if not (str(w["text"]).startswith("[") and str(w["text"]).endswith("]"))]


def _sound_effects(creds, out: Path, placed, sounds: dict, data, missing: list) -> list[dict]:
    """A beat's `sounds` ([{sound, at, volume}]) as manifest `sfx`: each sound's take downloaded. A sound with no take yet is
    named in `not_recorded`, like a line with none, and left out."""
    effects = []
    for item in placed if isinstance(placed, list) else []:
        row = sounds.get(str(item.get("sound"))) if isinstance(item, dict) else None
        if row is None:
            missing.append(str(item.get("sound") if isinstance(item, dict) else item))
            continue
        d = data(row)
        if not d.get("audio"):
            missing.append(row["slug"])
            continue
        file = _fetch_asset(creds, str(d["audio"]), out / "audio" / "sounds" / row["slug"], "mp3")
        volume = item.get("volume") if item.get("volume") is not None else d.get("volume")
        effects.append({"id": row["slug"], "audio": str(file.relative_to(out)), "at": float(item.get("at") or 0), "volume": float(volume if volume is not None else 0.6)})
    return effects


def _ambience(creds, out: Path, beat: dict, scenes: dict, sounds: dict, data, taken: dict, missing: list) -> dict | None:
    """The bed under a beat: its scene's ambience (a sound's take), at the scene's level unless the beat sets its own, muffled when the
    scene is heard from inside. A scene with no ambience, or a sound with no take yet, gives none (the sound is named in `not_recorded`)."""
    scene = scenes.get(str(beat.get("scene")))
    name = str(data(scene).get("ambience") or "") if scene else ""
    if not name:
        return None
    sound = sounds.get(name)
    if sound is None or not data(sound).get("audio"):
        if name not in missing:
            missing.append(name)
        return None
    if name not in taken:
        taken[name] = _fetch_asset(creds, str(data(sound)["audio"]), out / "audio" / "sounds" / name, "mp3")
    level = next((v for v in (beat.get("ambience_volume"), data(scene).get("ambience_volume"), data(sound).get("volume")) if v is not None), 0.5)
    return {"id": name, "audio": str(taken[name].relative_to(out)), "volume": float(level), "muffled": bool(data(scene).get("ambience_muffled"))}
