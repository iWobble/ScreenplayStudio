"""Is a story ready to have pictures and voices made? Read from the records only (no AI, no spend, nothing changed), so a person learns what is
missing before an approval costs anything, not after a picture comes out wrong or ElevenLabs refuses a voice.

`check` takes the story's records as plain dicts (`dataJson` of each) and returns findings: `fix` is what stops a picture or a recording from being
made (or makes it plainly wrong), `look` is worth a glance. `report` writes them in words a person can act on."""

from collections import Counter, defaultdict

from . import numbering

SHOWN = 6  # names listed before "and N more"


def _text(row: dict, key: str) -> str:
    return str((row or {}).get(key) or "").strip()


def _names(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    return ", ".join(items[:SHOWN]) + (f" and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def _slugs(value) -> list[str]:
    return [s.strip() for s in str(value or "").split(",") if s.strip()]


def check(
    story: dict,
    *,
    worlds: set[str],
    characters: list[dict],
    actors: dict[str, dict],
    voices: dict[str, dict],
    beats: list[dict],
    lines: list[dict],
    scenes: list[dict],
    sounds: list[dict],
    plan: dict | None = None,
) -> list[tuple[str, str, str]]:
    """Findings as (level, area, sentence). Each record is its dataJson plus `slug` (so a name can be given)."""
    lines = [ln for ln in lines if str(ln.get("leave_out") or "").lower() not in ("true", "yes") and ln.get("leave_out") is not True]  # a line set aside is not needed
    out: list[tuple[str, str, str]] = []
    fix = lambda area, text: out.append(("fix", area, text))  # noqa: E731
    look = lambda area, text: out.append(("look", area, text))  # noqa: E731

    world = _text(story, "world")
    if not world:
        fix("Story", "no World: choose one, its rules and style decide how every picture looks")
    elif world not in worlds:
        fix("Story", f"the World “{world}” is not in this workspace")
    for key, label, why in (("setting", "Setting", "where and when it happens"), ("premise", "Premise", "what the story is about")):
        if not _text(story, key):
            fix("Story", f"no {label}: say {why} (a `{label}:` line on the title page, or the {label} field); the pictures read it")
    if not beats:
        fix("Story", "no beats yet: bring the Fountain in first")

    speakers = Counter(_text(ln, "speaker").lower() for ln in lines if _text(ln, "speaker"))
    by_speaker = {_text(c, "speaker").lower(): c for c in characters if _text(c, "speaker")}
    by_slug = {_text(c, "slug"): c for c in characters}

    def voice_problem(name: str, who: str) -> None:
        if name not in voices:
            fix("Voices", f"{who}: the voice “{name}” is not in this workspace (import the voices, or choose another)")
        elif not _text(voices[name], "elevenlabs_voice_id"):
            fix("Voices", f"{who}: the voice “{name}” has no ElevenLabs id, so it is never sent to ElevenLabs")

    # Characters: who can have a master picture, who can be recorded
    on_screen = [c for c in characters if _text(c, "presence") != "voice only"]
    for c in characters:
        who = _text(c, "title") or _text(c, "cast_id") or _text(c, "slug")
        spoken = speakers.get(_text(c, "speaker").lower(), 0)
        screen = c in on_screen
        if screen:
            if not _text(c, "actor"):
                fix("Characters", f"{who} has no actor: no master picture can be made")
            elif _text(c, "actor") not in actors:
                fix("Characters", f"{who}: the actor “{_text(c, 'actor')}” is not in this workspace")
            if not _text(c, "role"):
                look("Characters", f"{who} has no description (Role): the picture only has the actor to go by")
            if not _text(c, "costume"):
                look("Characters", f"{who} has no costume: the pictures use the actor's own clothes")
            if not _text(c, "master"):
                look("Characters", f"{who} has no master picture yet (make it before any still)")
        if spoken:
            if not _text(c, "voice"):
                fix("Voices", f"{who} speaks {spoken} line{'s' if spoken != 1 else ''} but has no voice: nothing can be recorded")
            else:
                voice_problem(_text(c, "voice"), who)
    # a speaker with no Character: each line needs a voice of its own
    for speaker, n in sorted(speakers.items()):
        if speaker in by_speaker:
            continue
        own = [ln for ln in lines if _text(ln, "speaker").lower() == speaker]
        if any(not _text(ln, "voice") for ln in own):
            fix("Voices", f"{speaker} speaks {n} line{'s' if n != 1 else ''} and has no Character and no voice on the lines")
    for ln in lines:
        if _text(ln, "voice") and _text(ln, "voice") not in voices:
            voice_problem(_text(ln, "voice"), f"a line by {_text(ln, 'speaker') or 'someone'}")
            break

    # Beats: the cast of each picture
    nobody = sorted((_text(b, "number") for b in beats if not _slugs(b.get("cast"))), key=numbering.order_key)
    if nobody:
        look("Beats", f"{len(nobody)} beat{'s' if len(nobody) != 1 else ''} with nobody in the cast (the picture shows no one): {_names(nobody)}")
    unknown = sorted({s for b in beats for s in _slugs(b.get("cast")) if s not in by_slug})
    if unknown:
        fix("Beats", f"the cast names {_names(unknown)}, who {'is' if len(unknown) == 1 else 'are'} not a Character of this story")
    for key, label in (("expression", "what the people are doing (expression)"), ("focus", "the one thing the picture is about (focus)")):
        n = sum(1 for b in beats if not _text(b, key))
        if n and n == len(beats):
            look("Beats", f"no beat says {label}: the picture is made from the beat's words alone")
        elif n:
            look("Beats", f"{n} of {len(beats)} beats do not say {label}")
    scene_slugs = {_text(s, "slug") for s in scenes}
    lost = sorted((_text(b, "number") for b in beats if _text(b, "scene") and _text(b, "scene") not in scene_slugs), key=numbering.order_key)
    if lost:
        look("Beats", f"{len(lost)} beat{'s' if len(lost) != 1 else ''} name a scene that is not there: {_names(lost)}")

    # Scenes
    bare = [_text(s, "place") or _text(s, "slug") for s in scenes if not _text(s, "set_dressing")]
    if bare:
        look("Scenes", f"{len(bare)} of {len(scenes)} scenes have no set dressing (what is in the place): {_names(bare)}")

    # Sounds
    empty = [_text(s, "title") or _text(s, "slug") for s in sounds if _text(s, "source") in ("", "generated") and not _text(s, "prompt")]
    if empty:
        fix("Sounds", f"{len(empty)} sound{'s' if len(empty) != 1 else ''} to generate with no prompt: {_names(empty)}")
    unsized = [_text(s, "title") or _text(s, "slug") for s in sounds if _text(s, "source") in ("", "generated") and not s.get("duration_seconds") and _text(s, "prompt")]
    if unsized:
        look("Sounds", f"{len(unsized)} sound{'s' if len(unsized) != 1 else ''} with no length (the generator then guesses): {_names(unsized)}")
    same: dict[str, list[str]] = defaultdict(list)
    for s in sounds:
        if _text(s, "prompt"):
            same[" ".join(_text(s, "prompt").lower().split())].append(_text(s, "title") or _text(s, "slug"))
    again = [f"“{names[0]}” ×{len(names)}" for names in same.values() if len(names) > 1]
    if again:
        look("Sounds", f"the same sound is described more than once ({_names(again)}): one sound can be used in several beats")
    if plan:
        _voice_plan(plan, characters, lines, voices, fix, look)
    return out


def _voice_plan(plan: dict, characters: list[dict], lines: list[dict], voices: dict[str, dict], fix, look) -> None:
    """What the ElevenLabs plan allows, from what its usage lookup said (`tier`, `characters_left`, `resets_at`): whether the lines still to record fit
    in what is left, and whether a library voice is used on a free plan, which refuses it only when a recording is asked for."""
    tier = str(plan.get("tier") or "").strip().lower()
    try:
        left = int(plan.get("characters_left"))
    except (TypeError, ValueError):
        left = None
    to_record = [ln for ln in lines if str(ln.get("source") or "generated") == "generated" and not str(ln.get("audio") or "").strip() and str(ln.get("text") or "").strip()]
    needed = sum(len(str(ln.get("text"))) for ln in to_record)
    resets = f", until it resets on {str(plan['resets_at'])[:10]}" if plan.get("resets_at") else ""
    if left is not None and needed:
        if needed > left:
            fix("Voices", f"the {len(to_record)} lines still to record need about {needed:,} characters and the {tier or 'ElevenLabs'} plan has {left:,} left{resets}: a recording would stop partway")
        else:
            look("Voices", f"the {len(to_record)} lines still to record need about {needed:,} of the {left:,} characters the {tier or 'ElevenLabs'} plan has left{resets}")
    if tier == "free":
        used = {str(c.get("voice")) for c in characters if str(c.get("voice") or "").strip()} | {str(ln.get("voice")) for ln in lines if str(ln.get("voice") or "").strip()}
        library = sorted(v for v in used if str((voices.get(v) or {}).get("category") or "").lower() == "professional")
        if library:
            fix("Voices", f"the free ElevenLabs plan refuses library voices when a recording is asked for: {', '.join(library[:SHOWN])}")


AREAS = ("Story", "Characters", "Voices", "Beats", "Scenes", "Sounds")


def report(findings: list[tuple[str, str, str]], counts: dict[str, int], when: str) -> tuple[str, int, int]:
    """The findings in words, and how many must be fixed and how many are worth a look."""
    fixes = [f for f in findings if f[0] == "fix"]
    looks = [f for f in findings if f[0] == "look"]
    head = ", ".join(f"{n} {name}" for name, n in counts.items() if n)
    lines = [f"Checked {when}: {head}."]
    if not fixes:
        lines.append("Nothing stops a picture or a recording from being made.")
    for title, group in (("Fix before making anything", fixes), ("Worth a look", looks)):
        if not group:
            continue
        lines += ["", f"{title} ({len(group)}):"]
        for area in AREAS:
            lines += [f"  {area}: {text}" for level, a, text in group if a == area]
    return "\n".join(lines), len(fixes), len(looks)
