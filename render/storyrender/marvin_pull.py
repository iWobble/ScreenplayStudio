"""Pull a story's recorded lines out of Marvin and lay them out the way `listen` and `render` read them.

Marvin keeps the story (its beats, its speech lines, the audio of each take). This reads those records with the signed-in
CLI's token (`~/.marvin/credentials.json`, from `marvin auth login`), downloads each recorded take, and writes
`manifest.json` + `audio/<line>.<ext>` (and `stills/<beat>.<ext>` for any beat that has a still). Nothing is written back.
The Marvin calls are `marvin_worker.marvin_api`'s (it names itself to Marvin's edge, which refuses Python's default user agent).
"""

import json
import re
from pathlib import Path

from marvin_worker import marvin_api

from . import camera, captions, cards, ffmpeg, formats, numbering

CREDENTIALS = Path.home() / ".marvin" / "credentials.json"


class PullError(RuntimeError):
    pass

DEFAULT_HOLD = 4.0  # seconds a beat with a picture and no words or sound plays, the default the Timeline draws it at


def credentials(path: Path = CREDENTIALS) -> tuple[str, str]:
    try:
        raw = json.loads(path.read_text())
        return str(raw["apiUrl"]).rstrip("/"), str(raw["userToken"])
    except (OSError, KeyError, json.JSONDecodeError) as e:
        raise PullError(f"can't read Marvin credentials from {path} ({e}); run `marvin auth login`") from e


def _extension(mime: str | None, fallback: str) -> str:
    return {
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
        "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov", "image/gif": "gif", "image/apng": "apng", "image/vnd.mozilla.apng": "apng",
    }.get(
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


def chapter_rows(rows: list[dict], story: str, data) -> list[dict]:
    """The story's chapters, in order: `{"id": slug, "title"}` for each `chapter` entry that names this story (chapter 2 before chapter 10)."""
    own = [e for e in rows if data(e).get("story") == story and e.get("slug", "").startswith(f"{story}-chapter-")]
    own.sort(key=lambda e: (float(data(e).get("number")) if str(data(e).get("number") or "").replace(".", "", 1).isdigit() else float("inf"), e["slug"]))
    return [{"id": e["slug"], "title": e.get("title") or e["slug"]} for e in own]


_BEAT_NUMBER = re.compile(r"^0*(\d+)([a-z]*)$")
_BEAT_RANGE = re.compile(r"^0*(\d+)\s*-\s*0*(\d+)$")


def beat_chooser(spec: str | None):
    """Which beats a draft is for, from a person's words: `3`, `2-4`, `1,3,5` or `4a` (an inserted beat). A number with no letter takes the
    beat and the ones inserted after it (`4` is 04 and 04a); a range is by number. Returns a test on a beat's number, or None for every beat."""
    tokens = [t for t in re.split(r"[,\s]+", (spec or "").strip().lower()) if t]
    if not tokens:
        return None
    singles: set[tuple[int, str]] = set()
    whole: set[int] = set()
    spans: list[tuple[int, int]] = []
    for token in tokens:
        if m := _BEAT_RANGE.match(token):
            spans.append((int(m.group(1)), int(m.group(2))))
        elif m := _BEAT_NUMBER.match(token):
            (singles.add((int(m.group(1)), m.group(2))) if m.group(2) else whole.add(int(m.group(1))))
        else:
            raise PullError(f"“{token}” is not a beat: use a number (3), a range (2-4), a list (1,3,5) or an inserted beat (4a)")

    def wants(number: object) -> bool:
        m = _BEAT_NUMBER.match(str(number or "").strip().lower())
        if not m:
            return False
        n, suffix = int(m.group(1)), m.group(2)
        return n in whole or (n, suffix) in singles or any(low <= n <= high for low, high in spans)

    return wants


PLACEHOLDER_SIZE = (1080, 1920)


def _placeholder(path: Path, number: str, size: tuple[int, int] = PLACEHOLDER_SIZE) -> Path:
    """A plain card standing in for a beat that has no still yet, so a draft can still be watched for timing, sound and overlays."""
    label = f"Beat {number}".replace("'", "").replace(":", "").replace("\\", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x2b2b2b:s={size[0]}x{size[1]}",
            "-vf", f"drawtext=text='{label}':fontcolor=white@0.85:fontsize=110:x=(w-text_w)/2:y=(h-text_h)/2-60,"
            "drawtext=text='no still yet':fontcolor=white@0.55:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2+90",
            "-frames:v", "1", str(path),
        ]
    )  # fmt: skip
    return path


def pull(story: str, out: Path, *, creds: tuple[str, str] | None = None, beats: str | None = None, placeholders: bool = False) -> dict:
    """Write `out/manifest.json` for the story's recorded lines. Returns what was found: the shots, and the lines still to record. `beats`
    limits it to some beats (a quick look at one beat without the rest of the film): see beat_chooser. `placeholders` gives a beat with no
    still a plain card (a draft): the beats that got one are named in `placeholders` of the result."""
    creds = creds or credentials()
    try:
        return _pull(story, out, creds, beat_chooser(beats), placeholders)
    except marvin_api.MarvinError as e:
        raise PullError(str(e)) from e


def _pull(story: str, out: Path, creds: tuple[str, str], chosen=None, placeholders: bool = False) -> dict:
    rows = marvin_api.entries(creds)
    data = lambda e: e.get("dataJson") or e.get("data") or {}  # noqa: E731
    story_row = next((e for e in rows if e.get("slug") == story), None)
    if story_row is None:
        raise PullError(f"no story “{story}” in the workspace the CLI is signed in to")
    beats = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-beat-") and data(e).get("story") == story), key=lambda e: numbering.order_key(data(e).get("number")))
    if chosen is not None:
        beats = [b for b in beats if chosen(data(b).get("number"))]
        if not beats:
            raise PullError("none of the beats you chose exist in this story")
    lines = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-line-") and data(e).get("story") == story), key=lambda e: e["slug"])
    by_beat: dict[str, list[dict]] = {}
    for line in lines:
        by_beat.setdefault(str(data(line).get("beat")), []).append(line)

    chapters = chapter_rows(rows, story, data)
    scenes = {e["slug"]: e for e in rows if data(e).get("story") == story and ("ambience" in data(e) or "overlay" in data(e) or "story_ambience_volume" in data(e) or "story_ambience_muffled" in data(e) or "music_volume" in data(e) or "camera" in data(e))}  # scenes that name an ambience or an overlay, or say how the story's own bed is heard in them
    # Sounds belong to the library, not to a story: each is found by the slug a beat or scene names, whichever story made it.
    wanted = {str(item.get("sound")) for b in beats for item in (data(b).get("sounds") if isinstance(data(b).get("sounds"), list) else []) if isinstance(item, dict)}
    wanted |= {str(data(sc).get("ambience")) for sc in scenes.values() if data(sc).get("ambience")}
    wanted |= {str(data(b).get("ambience")) for b in beats if data(b).get("ambience")}  # a beat's own bed, and the story's default
    if data(story_row).get("ambience"):
        wanted.add(str(data(story_row)["ambience"]))
    sounds = {e["slug"]: e for e in marvin_api.query(creds, {"entries": sorted(wanted)}, limit=max(len(wanted), 1))} if wanted else {}
    taken: dict[str, Path] = {}  # an ambience's take is downloaded once, however many beats use it
    videos: dict[str, Path] = {}  # …and so is an overlay video
    size = formats.size_of(data(story_row)) or PLACEHOLDER_SIZE  # the picture shape the story asked for: the cards and placeholder cards are made to fit it
    shots, missing, carded, skipped = [], [], [], []
    scenes_of: list[str] = []  # the scene of each shot made, for the pause where a scene ends
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
            if d.get("volume") not in (None, ""):  # the line's own level and muffle: whichever take plays, the line is mixed this way
                entry["volume"] = d["volume"]
            if d.get("muffled"):
                entry["muffled"] = True
            if words := spoken_words(d, record.get("metadataJson")):
                entry["words"] = words
            spoken.append(entry)
        effects = _sound_effects(creds, out, data(beat).get("sounds"), sounds, data, missing)
        has_still = bool(data(beat).get("still"))
        if not spoken and not effects and not data(beat).get("hold_seconds") and not has_still:
            skipped.append(number)
            continue  # nothing to hear, no time asked for and no picture: there is nothing to show. A beat with a picture always plays (below), a held one too
        shot: dict = {"id": f"b{number}", "lines": spoken}
        for key, field in (("lead", "lead_seconds"), ("gap", "gap_seconds"), ("tail", "tail_seconds")):
            if data(beat).get(field) is not None:  # empty keeps the renderer's default
                shot[key] = float(data(beat)[field])
        shot.update(transition_of(data(beat), data(story_row)))
        if effects:
            shot["sfx"] = effects
        bed = _ambience(creds, out, data(beat), scenes, sounds, data, taken, missing, data(story_row))
        if bed:
            shot["ambience"] = bed
        shot.update(story_bed_in(data(beat), scenes.get(str(data(beat).get("scene")))))
        cover = _info_overlay(creds, out, data(beat), number, size) or _overlay(creds, out, data(beat), scenes, data(story_row), data, videos)
        if cover:
            shot["overlay"] = cover
        scene_row = scenes.get(str(data(beat).get("scene")))
        shot.update(music_in(data(beat), data(scene_row) if scene_row else {}))
        own_hold = _positive(data(beat).get("hold_seconds"))
        if own_hold is not None:
            shot["hold"] = own_hold  # the least this beat lasts: a silent one holds that long, a spoken one at least that long (the picture stays up after the last line)
        elif not spoken and has_still:
            shot["hold"] = DEFAULT_HOLD  # a silent beat with a picture and no time set lasts the default the Timeline also draws it at
        if data(beat).get("chapter"):
            shot["chapter"] = str(data(beat)["chapter"])  # the chapter's slug, as the chapter list below names it
        if chosen := camera.move_of(camera.pick(data(beat), None, {})):
            shot["move"] = chosen  # the beat chose a camera by name: that, even when numbers are also written out
        elif isinstance(data(beat).get("move"), dict):
            shot["move"] = data(beat)["move"]  # where the camera looks: {"from": {x, y, zoom}, "to": {...}}, so one still can serve several beats
        elif preset := camera.move_of(camera.pick({}, data(scene_row) if scene_row else None, data(story_row))):
            shot["move"] = preset  # nothing of its own: the camera preset of its scene, else the story
        if data(beat).get("still"):
            still = _fetch_asset(creds, str(data(beat)["still"]), out / "stills" / f"b{number}", "png")
            shot["still"] = str(still.relative_to(out))
        elif placeholders:
            shot["still"] = str(_placeholder(out / "stills" / f"b{number}-placeholder.png", number, size).relative_to(out))
            carded.append(number)
        shots.append(shot)
        scenes_of.append(str(data(beat).get("scene") or "").strip())
    for shot, pause in zip(shots, scene_breaks(scenes_of, data(story_row).get("scene_break_seconds")), strict=True):
        if pause:
            shot["after"] = pause
    if not shots:
        raise PullError(f"“{story}” has no recorded lines yet: record some with the screenplay-record-lines workflow")
    out.mkdir(parents=True, exist_ok=True)
    if chosen is None:  # a title card before the beats and an end card after them: real shots, so everything after them starts when the render starts it
        intro, outro = cards.shots(data(story_row), out, size)
        shots = [s for s in (intro, *shots, outro) if s is not None]
    music = music_of(creds, out, data(story_row), data)
    story_bed = story_ambience(creds, out, data(story_row), sounds, data, taken, missing)
    start_fade = _positive(data(story_row).get("start_fade_seconds"))  # every bed that starts the film fades in over this long
    end_fade = _positive(data(story_row).get("end_fade_seconds"))  # every bed fades out over this long at the end of the film
    (out / "manifest.json").write_text(
        json.dumps({"title": story_row.get("title") or story, "shots": shots, **({"chapters": chapters} if chapters else {}), **({"size": list(size)} if formats.size_of(data(story_row)) else {}), **({"loudness": level} if (level := formats.loudness_of(data(story_row))) else {}), **({"caption": caption} if (caption := caption_of(data(story_row), speaker_colours(rows, story, data))) else {}), **({"music": music} if music else {}), **({"ambience": story_bed} if story_bed else {}), **({"start_fade": start_fade} if start_fade else {}), **({"end_fade": end_fade} if end_fade else {}), **({"ambience_duck": duck} if (duck := str(data(story_row).get("ambience_ducking") or "").strip()) in ("light", "strong") else {})}, indent=2, ensure_ascii=False)
    )
    return {"manifest": str(out / "manifest.json"), "shots": len(shots), "lines": sum(len(s["lines"]) for s in shots), "not_recorded": missing, "placeholders": carded, "skipped": skipped}


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


def cascaded_fades(sound: dict, *levels: dict) -> dict:
    """An ambience bed's fades, each setting overriding the one before: the sound's own, then the story's `ambience_fade_in` / `_out`, then the
    beat's. Those that came from the story or the beat are flagged (`fade_in_set`, `fade_out_set`), so the film's start and end fades, which only
    cover what nothing more specific set, leave them alone."""
    fades = fades_of(sound)
    for source in levels:
        for key in ("fade_in", "fade_out"):
            if (value := _positive(source.get(f"ambience_{key}"))) is not None:
                fades[key] = value
                fades[f"{key}_set"] = True
    return fades


def fades_of(d: dict) -> dict:
    """A sound record's `fade_in` / `fade_out` (seconds), as manifest keys, only for the ones that are set."""
    return {k: float(d[k]) for k in ("fade_in", "fade_out") if d.get(k) not in (None, "", 0)}


def music_of(creds, out: Path, story_data: dict, data) -> dict | None:
    """The story's music bed: the sound its `music` field names (a record of kind music), played under the whole film at that sound's volume
    (0.12 if it has none), faded out at the end (and in, if the sound says so). None when the story names none, or its take is not made."""
    name = str(story_data.get("music") or "").strip()
    if not name:
        return None
    row = next(iter(marvin_api.query(creds, {"entries": name}, limit=1)), None)
    if row is None or not data(row).get("audio"):
        return None
    file = _fetch_asset(creds, str(data(row)["audio"]), out / "audio" / "sounds" / name, "mp3")
    volume = _unit(story_data.get("music_volume"))  # the story's own level, else the sound's, else 0.12
    if volume is None:
        volume = data(row).get("volume")
    duck = str(story_data.get("music_ducking") or "").strip()  # lower the bed while someone speaks: light or strong
    return {
        "audio": str(file.relative_to(out)),
        "volume": float(volume if volume not in (None, "") else 0.12),
        "id": name,
        **fades_of(data(row)),
        **{f"story_{k}": v for k, v in fades_of({"fade_in": story_data.get("music_fade_in"), "fade_out": story_data.get("music_fade_out")}).items()},
        **({"duck": duck} if duck in ("light", "strong") else {}),
    }


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
        effects.append({"id": row["slug"], "audio": str(file.relative_to(out)), "at": float(item.get("at") or 0), "volume": float(volume if volume is not None else 0.6), **fades_of(d)})
    return effects


def scene_breaks(scenes: list[str], seconds: object) -> list[float]:
    """The quiet to add after each shot where its scene ends: the story's `scene_break_seconds` (when that is above 0) after a shot whose next shot
    is in a different scene. A shot or its neighbour with no scene has none, and neither has the last. Must match the timeline view's
    `spine.scene_break` (Marvin: timeline.ts)."""
    pause = _positive(seconds)
    if pause is None:
        return [0.0] * len(scenes)
    following = [*scenes[1:], ""] if scenes else []
    return [pause if (here and there and here != there) else 0.0 for here, there in zip(scenes, following, strict=True)]


def caption_of(story: dict, speakers: dict[str, str]) -> dict:
    """The caption look the story asks for, as the manifest's `caption` (only what is set and valid): `caption_style`, `caption_position`,
    `caption_size`, `caption_color`, `caption_highlight_color`, and a colour for each speaker whose cast member has a `caption_color`."""
    out: dict = {}
    for key, options in (("style", captions.STYLES), ("position", captions.POSITIONS), ("size", captions.SIZES)):
        value = str(story.get(f"caption_{key}") or "").strip().lower()
        if value in options:
            out[key] = value
    for key, field in (("color", "caption_color"), ("highlight", "caption_highlight_color")):
        value = str(story.get(field) or "").strip()
        if captions._HEX.match(value):
            out[key] = "#" + value.lstrip("#").lower()
    if speakers:
        out["speakers"] = speakers
    return out


def speaker_colours(rows: list[dict], story: str, data) -> dict[str, str]:
    """{speaker: #RRGGBB} from the story's cast members that have a `caption_color`: the word a line's speaker is written as, lower case."""
    out: dict[str, str] = {}
    for row in rows:
        d = data(row)
        value = str(d.get("caption_color") or "").strip()
        if d.get("story") == story and str(d.get("speaker") or "").strip() and captions._HEX.match(value):
            out[str(d["speaker"]).strip().lower()] = "#" + value.lstrip("#").lower()
    return out


TRANSITION_KINDS = ("cut", "fade", "dissolve")


def transition_of(beat: dict, story: dict) -> dict:
    """How the film gets into a beat from the one before: the beat's own `transition` / `transition_seconds`, else the story's, else a cut. Only a
    real transition is returned (a cut is the default and needs no key); an unknown name is a cut."""
    kind = str(beat.get("transition") or story.get("transition") or "cut").strip().lower()
    if kind not in TRANSITION_KINDS or kind == "cut":
        return {}
    seconds = _positive(beat.get("transition_seconds")) or _positive(story.get("transition_seconds"))
    return {"transition": kind, **({"transition_seconds": seconds} if seconds else {})}


def music_in(beat: dict, scene: dict) -> dict:
    """How the music is heard in this beat: its level (the beat's own, else its scene's; the story's level and the sound's are the bed's, see `music_of`)
    and how long it takes to ease to and from that level. Nothing when none is set, so the bed stays where the story put it."""
    out: dict = {}
    level = _unit(beat.get("music_volume"))
    if level is None:
        level = _unit(scene.get("music_volume"))
    if level is not None:
        out["music_volume"] = level  # 0 is silence
    for key in ("music_fade_in", "music_fade_out"):
        if (seconds := _positive(beat.get(key))) is not None:
            out[key] = seconds
    return out


def story_bed_in(beat: dict, scene: dict | None) -> dict:
    """How the story's own ambience bed is heard in this beat: its level (the beat's own, else its scene's) and whether it is heard from inside (the
    scene's). It is the same bed, running on without a seam: only its level and its muffling change, eased at the cut. Nothing when neither is set."""
    here = (scene or {}).get("dataJson") or (scene or {}).get("data") or {}
    level = _unit(beat.get("story_ambience_volume"))
    if level is None:
        level = _unit(here.get("story_ambience_volume"))
    out: dict = {}
    if level is not None:
        out["bed_volume"] = level
    if here.get("story_ambience_muffled"):
        out["bed_muffled"] = True
    return out


def story_ambience(creds, out: Path, story_data: dict, sounds: dict, data, taken: dict, missing: list) -> dict | None:
    """The story's own ambience: one bed under the whole film at the story's level, else the sound's own, else 0.5. It layers with the beds of
    beats and scenes instead of giving way to them. None when the story names none or its sound has no take yet (named in `not_recorded`)."""
    name = str(story_data.get("ambience") or "").strip()
    if not name:
        return None
    sound = sounds.get(name)
    if sound is None or not data(sound).get("audio"):
        if name not in missing:
            missing.append(name)
        return None
    if name not in taken:
        taken[name] = _fetch_asset(creds, str(data(sound)["audio"]), out / "audio" / "sounds" / name, "mp3")
    level = next((v for v in (story_data.get("ambience_volume"), data(sound).get("volume")) if v not in (None, "")), 0.5)
    return {"id": name, "audio": str(taken[name].relative_to(out)), "volume": float(level), **cascaded_fades(data(sound), story_data)}


def _positive(value) -> float | None:
    """A length of time from a form field: a number above 0, or None when it is empty, not a number or not above 0."""
    try:
        seconds = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return seconds if seconds is not None and seconds > 0 else None


def _unit(value) -> float | None:
    """A level from a form field: a number from 0 to 1, or None when it is empty, not a number or out of range."""
    try:
        level = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return level if level is not None and 0 <= level <= 1 else None


def _info_overlay(creds, out: Path, beat: dict, number, size: tuple[int, int]) -> dict | None:
    """The beat's info card (see cards.info_of), drawn as a picture and handed on as the beat's overlay: it replaces any overlay the beat, its scene
    or the story has for this beat. It starts after `overlay_delay` (default 0.6 s) and fades with `overlay_fade` (default 0.35 s)."""
    card = cards.info_of(beat)
    if card is None:
        return None
    icon = _fetch_asset(creds, card["icon"], out / "video" / "info" / f"b{number}-icon", "png") if card["icon"] else None
    picture = cards.make_info(card, out / "video" / "info" / f"b{number}.png", size, icon)
    fade, delay = _positive(beat.get("overlay_fade")), _positive(beat.get("overlay_delay"))
    return {"video": str(picture.relative_to(out)), "blend": "normal", "opacity": 1.0, "id": f"info-b{number}", "fade": min(fade or cards.INFO_FADE, 10.0), "delay": min(delay if delay is not None else cards.INFO_DELAY, 60.0)}


def _overlay(creds, out: Path, beat: dict, scenes: dict, story_data: dict, data, taken: dict) -> dict | None:
    """The video or picture over a beat's still (a video, an animated GIF or a PNG with transparency): the beat's own, else its scene's, else the story's. A level that sets its blend to "none" says no overlay
    here, and the levels above it are not consulted (a quiet beat in a rainy scene)."""
    scene = scenes.get(str(beat.get("scene")))
    for owner in (beat, data(scene) if scene else {}, story_data):
        blend = str(owner.get("overlay_blend") or "")
        if blend == "none":
            return None
        asset = owner.get("overlay")
        if not asset:
            continue
        key = str(asset)
        if key not in taken:
            taken[key] = _fetch_asset(creds, key, out / "video" / "overlays" / key[:12], "mp4")
        opacity = _unit(owner.get("overlay_opacity"))
        play = str(owner.get("overlay_play") or "").strip().lower()
        fade, delay = _positive(owner.get("overlay_fade")), _positive(owner.get("overlay_delay"))  # from the same level that named the picture
        return {
            "video": str(taken[key].relative_to(out)), "blend": blend or "normal", "opacity": 1.0 if opacity is None else opacity, "id": key,
            **({"play": play} if play in ("loop", "once") else {}), **({"fade": min(fade, 10.0)} if fade else {}), **({"delay": min(delay, 60.0)} if delay else {}),
        }  # fmt: skip
    return None


def _ambience(creds, out: Path, beat: dict, scenes: dict, sounds: dict, data, taken: dict, missing: list, story_data: dict | None = None) -> dict | None:
    """The bed under a beat: its own ambience, else its scene's. At the level the beat sets, else the scene's, else the sound's own; muffled when
    the scene is heard from inside. It plays together with the story's own bed (see story_ambience), which runs under everything. A beat with
    none, or a sound with no take yet, gives no bed (the sound is named in `not_recorded`)."""
    scene = scenes.get(str(beat.get("scene")))
    own = str(beat.get("ambience") or "")
    from_scene = str(data(scene).get("ambience") or "") if scene else ""
    name = own or from_scene
    if not name:
        return None
    sound = sounds.get(name)
    if sound is None or not data(sound).get("audio"):
        if name not in missing:
            missing.append(name)
        return None
    if name not in taken:
        taken[name] = _fetch_asset(creds, str(data(sound)["audio"]), out / "audio" / "sounds" / name, "mp3")
    if own:
        named_level, muffled = None, False
    else:
        named_level, muffled = data(scene).get("ambience_volume"), bool(data(scene).get("ambience_muffled"))
    level = next((v for v in (beat.get("ambience_volume"), named_level, data(sound).get("volume")) if v not in (None, "")), 0.5)
    return {"id": name, "audio": str(taken[name].relative_to(out)), "volume": float(level), "muffled": muffled, **cascaded_fades(data(sound), story_data or {}, beat)}
