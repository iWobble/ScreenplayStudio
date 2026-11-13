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

from . import fountain as fountain_mod
from . import lines as lines_of
from . import numbering

NARRATOR = "narrator"


def _data(row: dict) -> dict:
    return row.get("dataJson") or row.get("data") or {}


def _clean(text: object) -> str:
    """One line of plain text: Fountain reads leading symbols and blank lines as markup, so a stray one is made harmless."""
    return " ".join(str(text or "").split())


_EXTENSION = re.compile(r"^(?:V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT[\u2019']?D)$", re.I)  # a speaker's extension (V.O.), not a parenthetical


def _cue(speaker: str, extension: str = "") -> str:
    name = _clean(speaker).upper() or "VOICE"
    if extension:
        return f"{name} ({extension})"
    return f"{name} (V.O.)" if _clean(speaker).lower() == NARRATOR else name


def _deliveries(picture: str) -> list[tuple[str, list[str]]]:
    """How the beat's lines are said, from the note its picture ends with (`... Delivery: Mara (without looking up); Narrator (V.O.).`): [(speaker,
    [what was written with them: parentheticals and an extension])], in the order of the lines they belong to."""
    tail = picture.split(" Delivery:", 1)[1] if " Delivery:" in picture else ""
    out: list[tuple[str, list[str]]] = []
    for item in [x.strip() for x in tail.strip().rstrip(".").split("; ") if x.strip()]:
        m = re.match(r"^(.*?) \((.*)\)$", item)
        if m:
            out.append((m.group(1).strip().lower(), [t.strip() for t in m.group(2).split(", ") if t.strip()]))
    return out


def _slug_words(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug or "").strip()


def _seconds(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return f"{number:g}s"


def _without_lead_heading(picture: str, name: str) -> str:
    """A scene's first picture without the scene's own heading it starts with (`INT. HOLD - NIGHT. Water…` or `Interior: Hold, night. Water…`, for the
    scene named Hold): the exported script writes the heading as a heading, so repeating it in the action would say it twice. A picture that only
    begins like a heading (`EXT. THE GALLEY, a wide shot`) is left as it is."""
    plain = lambda s: " ".join(str(s).replace("\u2019", "'").split())  # noqa: E731
    place = r"\s+".join(re.escape(w) for w in plain(name).split())
    if not place:
        return picture
    kind = r"(?:(?:INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?|EST\.?)\s+|(?:Interior and exterior|Interior|Exterior):\s+)"
    when = rf"(?:\s*[-\u2013\u2014,]\s*(?:{fountain_mod._TIME_WORDS.pattern})[A-Za-z' ]*?)?"  # a time of day or story time, not just any words
    m = re.match(rf"{kind}(?:THE\s+)?{place}{when}\s*\.\s*", plain(picture), re.I)
    return plain(picture)[m.end() :] if m else picture


def _heading_line(heading: str, tag: str, scene: dict, when: str = "") -> str:
    """A scene's heading line: `INT. CAPTAIN'S CABIN #2#` when the scene says whether it is inside or outside (its Inside or outside field: the
    other way from what the import reads), else a forced heading (`.CAPTAIN'S CABIN #2#`) as before."""
    prefix = fountain_mod.kind_prefix(_data(scene).get("inside_outside"))
    time = f" - {_clean(when).upper()}" if _clean(when) else ""  # the beat's time of day, as the heading had it
    return f"{prefix} {heading}{time}{tag}" if prefix else f".{heading}{time}{tag}"


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

    scene_now, bed_now, time_now = None, None, ""
    for beat in records.get("beats", []):
        d = _data(beat)
        number = str(d.get("number") or "").strip()
        scene_slug = d.get("scene")
        when = _clean(d.get("time_of_day"))
        if scene_slug and (scene_slug != scene_now or (when and when != time_now)):  # a new place, or the same place at another time of day
            scene_now, time_now = scene_slug, when
            scene = scenes.get(str(scene_slug), {})
            heading = _clean(scene.get("title") or _slug_words(str(scene_slug))).upper()
            tag = f" #{int(number)}#" if number.isdigit() else ""
            out += [_heading_line(heading, tag, scene, when), ""]
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


def _say(label: str, value: object) -> str:
    text = _clean(value)
    return f"{label}: {text.rstrip('.')}." if text else ""


def fountain_complete(records: dict) -> str:
    """Everything the records hold, as a Fountain a writer can read, edit and bring in again: the title page (credits, premise, setting, format,
    length, music), each character as a note with their role, costume, props and rules, each scene as a heading with its place, light, set dressing,
    continuity and ambience, each beat as the picture with a note of its hold, focus, expression, camera move, cast and sounds, each spoken line as
    dialogue with its direction and voice. A page break (`===`) keeps each beat its own picture when the Fountain is read again; notes (`[[ ]]`)
    keep what has no element of its own, so nothing a person put into the records is lost in the file."""
    story = records["story"]
    sd = _data(story)
    scenes, sounds, chapters = records.get("scenes", {}), records.get("sounds", {}), records.get("chapters", {})
    lines_by_beat = records.get("lines", {})
    out: list[str] = [f"Title: {_clean(story.get('title') or story.get('slug'))}", f"Credit: {_clean(sd.get('credit')) or 'A Storyworld film'}"]
    for key, label in (("author", "Author"), ("source", "Source"), ("draft_date", "Draft date"), ("contact", "Contact"), ("copyright", "Copyright")):
        raw = [ln.strip() for ln in str(sd.get(key) or "").splitlines() if ln.strip()]
        if len(raw) > 1:  # a value that runs over several lines continues on lines indented by four spaces (a contact's name and address)
            out += [f"{label}:"] + [f"    {ln}" for ln in raw]
        elif _clean(sd.get(key)):
            out.append(f"{label}: {_clean(sd[key])}")
    for key, label in (("premise", "Premise"), ("setting", "Setting"), ("world", "World"), ("format", "Format"), ("music", "Music"), ("platform", "Platform")):
        if _clean(sd.get(key)):
            out.append(f"{label}: {_clean(sd[key])}")
    seconds = _seconds(sd.get("target_seconds"))
    if seconds:
        out.append(f"Length: about {seconds}")
    out.append("")
    for ch in records.get("characters", []):  # who is in it, and what is said of each (the cast, costume and props belong to the story, not to a scene)
        cd = _data(ch)
        bits = [x for x in (_say("Role", cd.get("role")), _say("Costume", cd.get("costume")), _say("Props", cd.get("props")), _say("Rules", cd.get("rules")), _say("Played by", cd.get("actor"))) if x]
        out += [f"[[{_clean(cd.get('speaker') or ch.get('title') or '').upper()} is {_clean(ch.get('title'))}. " + " ".join(bits) + "]]", ""]

    scene_now, bed_now, chapter_now, first, time_now = None, None, None, True, ""
    scene_numbers: dict[str, int] = {}
    for beat in records.get("beats", []):
        d = _data(beat)
        number = str(d.get("number") or "").strip()
        chapter_slug = d.get("chapter")
        new_chapter = bool(chapter_slug) and chapter_slug != chapter_now
        scene_slug = d.get("scene")
        when = _clean(d.get("time_of_day"))
        new_scene = bool(scene_slug) and (scene_slug != scene_now or bool(when and when != time_now))  # a new place, or the same place at another time of day
        if not first:
            if not new_chapter:
                out += ["===", ""]  # each beat is its own picture (a chapter heading starts one itself)
            if _clean(d.get("transition_text")):
                out += [_clean(d["transition_text"]), ""]  # the transition written before this beat (CUT TO:), as it was: above a chapter heading, which a transition below it would not leave one
        if new_chapter:
            chapter_now = chapter_slug
            title = _clean((chapters.get(str(chapter_slug)) or {}).get("title") or _slug_words(str(chapter_slug)))
            out += [f"# {title}", ""]
            summary = _clean(_data(chapters.get(str(chapter_slug)) or {}).get("summary"))
            if summary:
                out += [f"= {summary}", ""]  # a section's synopsis, as the writer gave it
        if new_scene:
            scene_now, time_now = scene_slug, when
            scene = scenes.get(str(scene_slug), {})
            heading = _clean(scene.get("title") or _slug_words(str(scene_slug))).upper()
            scene_numbers[str(scene_slug)] = scene_numbers.get(str(scene_slug), len(scene_numbers) + 1)
            out += [_heading_line(heading, f" #{scene_numbers[str(scene_slug)]}#", scene, when), ""]
            sc = _data(scene)
            said = [x for x in (_say("Place", sc.get("place")), _say("Light", sc.get("look")), _say("Set dressing", sc.get("set_dressing")), _say("Continuity", sc.get("continuity"))) if x]
            if said:
                out += [f"[[Scene {_clean(scene.get('title') or _slug_words(str(scene_slug)))}. " + " ".join(said) + "]]", ""]  # a note: a synopsis would be read as the writer's own
            if sc.get("ambience") != bed_now:
                bed_now = sc.get("ambience")
            if sc.get("ambience"):
                bed = sounds.get(str(sc["ambience"]), {})
                level = f", level {sc['ambience_volume']}" if sc.get("ambience_volume") not in (None, "") else ""
                muffled = ", muffled (indoors)" if sc.get("ambience_muffled") else ""
                out += [f"[[Ambience: {_clean(bed.get('title') or _slug_words(str(sc['ambience'])))}{level}{muffled}. {_clean(_data(bed).get('prompt'))}]]", ""]
        deliveries = _deliveries(_clean(d.get("picture")))  # how each line is said: written again as its extension and parenthetical
        picture = _clean(d.get("picture")).split(" Delivery:")[0].strip()  # and not left in the action
        if new_scene:
            picture = _without_lead_heading(picture, _clean(scene.get("title") or _slug_words(str(scene_slug)))).strip()
        if picture and (fountain_mod._is_scene(picture) or fountain_mod._is_transition(picture) or picture.isupper() or picture[0] in "@#=~>!."):
            picture = "!" + picture  # forced action: a picture that begins like a heading, a cue or a transition is still only a picture
        out += [picture or f"Beat {number}.", ""]
        facts = [x for x in (_say("Hold", f"{_seconds(d.get('hold_seconds'))}" if _seconds(d.get("hold_seconds")) else ""), _say("Focus", d.get("focus")), _say("Expression", d.get("expression")), _say("Camera", d.get("move")), _say("Cast", d.get("cast")), _say("Transition", d.get("transition")), _say("Note", d.get("notes")), _say("Info card", " — ".join(x for x in (_clean(d.get("info_label")), _clean(d.get("info_title")), _clean(d.get("info_text"))) if x))) if x]
        out += [f"[[Beat {number}. " + " ".join(facts) + "]]" if facts else f"[[Beat {number}.]]", ""]
        for placed in d.get("sounds") if isinstance(d.get("sounds"), list) else []:
            if isinstance(placed, dict) and placed.get("sound"):
                snd = sounds.get(str(placed["sound"]), {})
                sung = re.search(r"Sung, as written:\s*(.+)$", str(_data(snd).get("prompt") or ""), re.S)
                if sung:  # the words that were sung go back as lyrics (a line that starts with ~), not as a sound note
                    out += [f"~ {_clean(sung.group(1)).rstrip(' ~').strip()}", ""]
                    continue
                at = f" at {_seconds(placed.get('at'))}" if _seconds(placed.get("at")) else ""
                name, prompt = _clean(snd.get("title") or _slug_words(str(placed["sound"]))), _clean(_data(snd).get("prompt"))
                words = prompt if prompt and prompt.lower().startswith(name.lower().rstrip(".")[:40]) else f"{name}. {prompt}".rstrip(". ") + "."
                out += [f"[[Sound: {words.rstrip('.')}{at}.]]", ""]
        for line in lines_by_beat.get(beat.get("slug", ""), []):
            ld = _data(line)
            spoken = _clean(ld.get("text"))
            if not spoken:
                continue
            who = _clean(ld.get("speaker")).lower()
            said = next((tokens for name, tokens in deliveries if name == who), [])
            if said:
                deliveries.remove(next(x for x in deliveries if x[0] == who))
            ext = next((tok for tok in said if _EXTENSION.match(tok)), "")
            paren = [tok for tok in said if not _EXTENSION.match(tok)]
            out.append(_cue(ld.get("speaker") or "", ext))
            if _clean(ld.get("direction")):
                out.append(f"({_clean(ld['direction']).rstrip('.').lower()})")
            elif paren:
                out.append(f"({', '.join(paren)})")  # as the writer had it
            out.append(spoken)
            extra = [x for x in (_say("Delivery", ld.get("delivery_text")), _say("Voice", ld.get("voice")), _say("Note", ld.get("take_notes"))) if x]
            out += ([f"[[{' '.join(extra)}]]"] if extra else []) + [""]
        first = False
    return "\n".join(out).rstrip("\n") + "\n"


_SCENE_ONLY = ("place", "set_dressing", "inside_outside", "continuity", "ambience_muffled", "story_ambience_muffled")


def _is_scene(row: dict, story: str) -> bool:
    """Whether an entry of the story is one of its scenes: it carries a field only a scene has (a beat also has an ambience, and a number). A scene
    with no ambience of its own is still a scene (it was left out, and then written as a bare `.HEADING` under its slug)."""
    d = _data(row)
    return d.get("story") == story and "number" not in d and ("ambience" in d or any(k in d for k in _SCENE_ONLY))


def pull_records(story: str, creds: tuple[str, str]) -> dict:
    """The story's records from Marvin, in the shape `fountain()` reads."""
    from marvin_worker import marvin_api

    rows = marvin_api.entries(creds)
    story_row = next((e for e in rows if e.get("slug") == story), None)
    if story_row is None:
        raise LookupError(f"no story “{story}” in this workspace")
    beats = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-beat-") and _data(e).get("story") == story), key=lambda e: numbering.order_key(_data(e).get("number")))
    lines: dict[str, list[dict]] = {}
    for line in lines_of.of_story(rows, story):
        lines.setdefault(str(_data(line).get("beat")), []).append(line)
    return {
        "story": story_row,
        "beats": beats,
        "lines": lines,
        "scenes": {e["slug"]: e for e in rows if _is_scene(e, story)},
        "sounds": {e["slug"]: e for e in rows if e.get("slug", "").find("-sound-") >= 0 or (_data(e).get("story") == story and "kind" in _data(e) and "source" in _data(e))},
        "chapters": {e["slug"]: e for e in rows if e.get("slug", "").startswith(f"{story}-chapter-") and _data(e).get("story") == story},
        "revisions": sorted((e for e in rows if _data(e).get("story") == story and _data(e).get("status") == "applied" and _data(e).get("applied_at")), key=lambda e: float(_data(e).get("number") or 0)),
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
        "revision": _data(story).get("revision"),
        "revision_date": _data(story).get("revision_date"),
        "revisions": [{"number": _data(r).get("number"), "date": _data(r).get("applied_at"), "note": _clean(_data(r).get("note") or r.get("title")), "same": _data(r).get("same"), "reworded": _data(r).get("reworded"), "new": _data(r).get("new_beats"), "removed": _data(r).get("removed")} for r in records.get("revisions", [])],
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
    summary = f"{info['beats']} beats · {info['seconds_spoken']:g}s of recorded speech" + (f" · aimed at {target}" if target else "") + (f" · {revision_text(info.get('revision'), info.get('revision_date'))}" if info.get("revision") else "")
    characters = table(["Character", "Role", "Actor", "Lines", "Words", "Spoken", "Beats"], [[c["id"], c["role"], c["actor"], c["speaks"], c["words"], f"{c['seconds']:g}s", _range(c["beats"])] for c in info["characters"]])
    locations = table(["Scene", "Place and look", "Ambience", "Beats"], [[p["title"], " ".join(x for x in (p["place"], p["look"]) if x), p["ambience"], _range(p["beats"])] for p in info["locations"]])
    sound_rows = table(["Sound", "Beats"], [[x["title"], _range(x["beats"])] for x in info["sounds"]])
    style = "body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#222}h1{margin-bottom:0}.sub{color:#666;margin-top:.25rem}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}th,td{text-align:left;border-bottom:1px solid #ddd;padding:.4rem .6rem;vertical-align:top}th{background:#f4f4f4}@media print{body{margin:0}}"
    title = e(info["story"])
    revisions = ""
    if info.get("revisions"):
        revisions = "<h2>Revisions</h2>" + table(["Revision", "Date", "What changed", "Beats unchanged", "Reworded", "New", "Gone"], [[r["number"], r["date"], r["note"], r["same"], r["reworded"], r["new"] or "", r["removed"]] for r in info["revisions"]])
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}: script breakdown</title><style>{style}</style></head><body>"
        f"<h1>{title}: script breakdown</h1><p class='sub'>{e(summary)}</p>"
        f"<h2>Characters</h2>{characters}<h2>Locations</h2>{locations}<h2>Sounds</h2>{sound_rows}{revisions}</body></html>\n"
    )


def title_page(text: str) -> dict[str, str]:
    """The title page at the top of Fountain `text` (`Title:`, `Credit:`, `Author:`, `Draft date:`, `Notes:` and any other key), by lower-cased key; a key's
    value may continue on indented lines. It ends at the first blank line."""
    found: dict[str, str] = {}
    key = ""
    for line in text.split("\n"):
        if not line.strip():
            break
        if line[:1] in (" ", "\t") and key:
            found[key] = (found[key] + " " + line.strip()).strip()
            continue
        name, colon, value = line.partition(":")
        if not colon:
            break
        key = name.strip().lower()
        found[key] = value.strip()
    return found


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def revision_text(number: object, date: object) -> str:
    """`Revision 3, 11 November 2026` (the date as the record keeps it: 2026-11-11)."""
    when = ""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:\b.*)?", str(date or "").strip())
    if m:
        when = f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    try:
        n = int(float(str(number)))
    except (TypeError, ValueError):
        return ""
    return f"Revision {n}" + (f", {when}" if when else "")


def stamp_revision(text: str, story: dict) -> str:
    """The Fountain with the story's revision on its title page, where screenplain prints the draft date (and the HTML cover does too): `Draft date: Revision 3,
    11 November 2026`, keeping an earlier draft date beside it. Nothing changes for a story with no revision."""
    d = _data(story)
    stamp = revision_text(d.get("revision"), d.get("revision_date"))
    if not stamp:
        return text
    lines = text.split("\n")
    end = next((i for i, ln in enumerate(lines) if not ln.strip()), len(lines))
    for i in range(end):
        name, colon, value = lines[i].partition(":")
        if colon and name.strip().lower() == "draft date":
            before = value.strip()
            lines[i] = f"Draft date: {stamp}" + (f" (first draft: {before})" if before and "revision" not in before.lower() else "")
            return "\n".join(lines)
    if not lines or not _TITLE_KEY_LINE.match(lines[0]):
        return text  # no title page to put it on
    lines.insert(end, f"Draft date: {stamp}")
    return "\n".join(lines)


_TITLE_KEY_LINE = re.compile(r"^[A-Za-z][A-Za-z ]*:")


def with_title_page(page: str, text: str) -> str:
    """screenplain's HTML leaves out the title page (the PDF has one) and calls the tab "Screenplay": name the page after the
    story and put the title page first, then the script on its own page when printed."""
    info = title_page(text)
    title = info.get("title")
    if not title:
        return page
    safe = html.escape(title)
    extra = "".join(f'<p class="{k.replace(" ", "-")}">{html.escape(info[k])}</p>' for k in ("credit", "author", "source", "draft date", "notes") if info.get(k))
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
