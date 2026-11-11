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

import html
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


def fountain_as_written(records: dict) -> "str | None":
    """The Fountain the writer wrote, made again from what the records kept of it: the story's front matter (the title page), then each beat's own
    piece in order. The same words in the same order, with one blank line between pieces. None when the story was not made from Fountain (a beat
    holds no text of its own), and then the production script below is the one to make."""
    beats = records.get("beats", [])
    pieces = [str(_data(b).get("fountain") or "") for b in beats]
    if not beats or not all(piece.strip() for piece in pieces):
        return None
    front = str(_data(records["story"]).get("fountain_front") or "")
    return "\n".join(p for p in [front, *pieces] if p.strip()).rstrip("\n") + "\n"


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
        "characters": [e for e in rows if _data(e).get("story") == story and "profile" in _data(e) and _data(e).get("cast_id")],  # a character has a profile; a casting (also story + cast_id) does not
    }


def _ids(value: object) -> list[str]:
    """The ids in a beat's `cast` text ("pirate-captain, old-ship-cook")."""
    return [part for part in re.split(r"[,;\s]+", str(value or "")) if part]


def breakdown(records: dict) -> dict:
    """What the script needs, read from the records (the "script breakdown" film crews make): who appears and speaks, where, which sounds.

    {"story", "beats", "seconds_spoken", "target_seconds", "characters": [{"id", "role", "actor", "speaks", "words", "seconds", "beats"}], "locations": [...], "sounds": [...]}
    A character is anyone named as a speaker or on screen (a beat's `cast`); beat numbers are the story's own, so they stay stable when beats are added.
    """
    scenes, sounds = records.get("scenes", {}), records.get("sounds", {})
    lines_by_beat = records.get("lines", {})
    people: dict[str, dict] = {}
    places: dict[str, dict] = {}
    heard: dict[str, dict] = {}
    # One person is one row, however a record names them: a character is named by its id on a beat (`cast`) and by its `speaker` on a speech line.
    named: dict[str, dict] = {}
    for character in records.get("characters", []):
        cd = _data(character)
        cast_id = str(cd.get("cast_id") or character.get("slug") or "").strip()
        if not cast_id:
            continue
        for alias in (cast_id, str(cd.get("speaker") or "").strip().lower()):
            if alias:
                named[alias] = {"id": cast_id, "role": _clean(cd.get("role")), "actor": _clean(cd.get("actor"))}

    def person(name: str) -> dict:
        who = named.get(name) or named.get(name.lower()) or {"id": name, "role": "", "actor": ""}
        return people.setdefault(who["id"], {**who, "speaks": 0, "words": 0, "seconds": 0.0, "beats": []})

    for who in {w["id"]: w for w in named.values()}.values():  # everyone cast in the story is listed, spoken or not
        person(who["id"])

    def mark(item: dict, number: str) -> None:
        if number and number not in item["beats"]:
            item["beats"].append(number)

    total = 0.0
    for beat in records.get("beats", []):
        d = _data(beat)
        number = str(d.get("number") or "").strip()
        for who in _ids(d.get("cast")):
            mark(person(who), number)
        scene_slug = str(d.get("scene") or "")
        if scene_slug:
            scene = scenes.get(scene_slug, {})
            sd = _data(scene)
            where = places.setdefault(scene_slug, {"id": scene_slug, "title": _clean(scene.get("title") or _slug_words(scene_slug)), "place": _clean(sd.get("place")), "look": _clean(sd.get("look")), "ambience": str(sd.get("ambience") or ""), "beats": []})
            mark(where, number)
        for placed in d.get("sounds") if isinstance(d.get("sounds"), list) else []:
            if isinstance(placed, dict) and placed.get("sound"):
                key = str(placed["sound"])
                heard.setdefault(key, {"id": key, "title": _clean(sounds.get(key, {}).get("title") or _slug_words(key)), "beats": []})
                mark(heard[key], number)
        for line in lines_by_beat.get(beat.get("slug", ""), []):
            ld = _data(line)
            if not _clean(ld.get("text")):
                continue
            who = person(str(ld.get("speaker") or "voice").strip().lower())
            who["speaks"] += 1
            who["words"] += len(_clean(ld.get("text")).split())
            try:
                seconds = float(ld.get("duration_seconds") or 0)
            except (TypeError, ValueError):
                seconds = 0.0
            who["seconds"] = round(who["seconds"] + seconds, 2)
            total += seconds
            mark(who, number)
    for place in places.values():
        bed = place["ambience"]
        place["ambience"] = _clean(sounds.get(bed, {}).get("title") or _slug_words(bed)) if bed else ""
    story = records["story"]
    return {
        "story": _clean(story.get("title") or story.get("slug")),
        "beats": len(records.get("beats", [])),
        "seconds_spoken": round(total, 2),
        "target_seconds": _data(story).get("target_seconds"),
        "characters": sorted(people.values(), key=lambda p: (-p["speaks"], p["id"])),
        "locations": list(places.values()),
        "sounds": list(heard.values()),
    }


def _range(beats: list[str]) -> str:
    return ", ".join(beats) if len(beats) <= 6 else f"{beats[0]}–{beats[-1]} ({len(beats)} beats)"


def breakdown_html(info: dict) -> str:
    """The breakdown as one self-contained page (it previews on the asset's page and prints)."""
    e = html.escape

    def table(heads: list[str], rows: list[list[str]]) -> str:
        if not rows:
            return "<p class='none'>None.</p>"
        head = "".join(f"<th>{e(h)}</th>" for h in heads)
        body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table><tr>{head}</tr>{body}</table>"

    target = _seconds(info.get("target_seconds"))
    summary = f"{info['beats']} beats · {info['seconds_spoken']:g}s of recorded speech" + (f" · aimed at {target}" if target else "")
    characters = table(["Character", "Role", "Actor", "Lines", "Words", "Spoken", "Beats"], [[c["id"], c["role"], c["actor"], c["speaks"], c["words"], f"{c['seconds']:g}s", _range(c["beats"])] for c in info["characters"]])
    locations = table(["Scene", "Place and look", "Ambience", "Beats"], [[p["title"], " ".join(x for x in (p["place"], p["look"]) if x), p["ambience"], _range(p["beats"])] for p in info["locations"]])
    sound_rows = table(["Sound", "Beats"], [[x["title"], _range(x["beats"])] for x in info["sounds"]])
    style = "body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#222}h1{margin-bottom:0}.sub{color:#666;margin-top:.25rem}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}th,td{text-align:left;border-bottom:1px solid #ddd;padding:.4rem .6rem;vertical-align:top}th{background:#f4f4f4}@media print{body{margin:0}}"
    title = e(info["story"])
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}: script breakdown</title><style>{style}</style></head><body>"
        f"<h1>{title}: script breakdown</h1><p class='sub'>{e(summary)}</p>"
        f"<h2>Characters</h2>{characters}<h2>Locations</h2>{locations}<h2>Sounds</h2>{sound_rows}</body></html>\n"
    )


def title_page(text: str) -> dict[str, str]:
    """The `Title:` / `Credit:` / `Notes:` lines at the top of Fountain `text`, by lower-cased key."""
    found: dict[str, str] = {}
    for line in text.split("\n"):
        key, colon, value = line.partition(":")
        if not colon or key.strip().lower() not in ("title", "credit", "notes"):
            break
        found[key.strip().lower()] = value.strip()
    return found


def with_title_page(page: str, text: str) -> str:
    """screenplain's HTML leaves out the title page (the PDF has one) and calls the tab "Screenplay": name the page after the
    story and put the title page first, then the script on its own page when printed."""
    info = title_page(text)
    title = info.get("title")
    if not title:
        return page
    safe = html.escape(title)
    extra = "".join(f'<p class="{k}">{html.escape(info[k])}</p>' for k in ("credit", "notes") if info.get(k))
    cover = (
        '<style>.titlepage{text-align:center;margin:0 auto;padding:180pt 0 120pt;font-family:\'Courier Final Draft\',\'Courier Screenplay\',Courier;font-size:12pt}'
        ".titlepage .title{text-transform:uppercase;text-decoration:underline;margin-bottom:24pt}"
        ".titlepage p{margin:0 0 12pt}@media print{.titlepage{page-break-after:always}}</style>"
        f'<div class="titlepage"><p class="title">{safe}</p>{extra}</div>'
    )
    page = page.replace("<title>Screenplay</title>", f"<title>{safe}: script</title>", 1)
    return page.replace("<body>", f"<body>{cover}", 1)


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
        if fmt == "html":
            target.write_text(with_title_page(target.read_text(encoding="utf-8"), text), encoding="utf-8")
        made[fmt] = target
    return made
