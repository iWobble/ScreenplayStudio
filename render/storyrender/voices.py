"""ElevenLabs' voice list → Marvin `voice` records. The pure parts: what a listed voice becomes (its slug, one-line summary and tags),
and which listed voices are new. The job (`import-voices` in jobs.py) does the calling, downloading and writing."""

import re

LABELS = ("gender", "age", "accent", "descriptive", "use_case")  # ElevenLabs' labels, which become tags


def short_name(name: str) -> str:
    """"Roger - Laid-Back, Casual, Resonant" → "Roger"."""
    return re.split(r"\s[-–]\s", name or "")[0].strip() or "voice"


def slug_for(name: str, taken: set[str]) -> str:
    """`voice-roger`; a second Roger is `voice-roger-2`."""
    base = "voice-" + (re.sub(r"[^a-z0-9]+", "-", short_name(name).lower()).strip("-") or "voice")
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    return slug


def tag_name(value: str) -> str:
    return re.sub(r"[_\s]+", "-", str(value).strip().lower())


def tags_for(labels: dict | None) -> list[str]:
    """The voice's labels as tags, without repeats, in a stable order: male, middle-aged, american, deep, narrative-story."""
    labels = labels or {}
    return list(dict.fromkeys(tag_name(labels[k]) for k in LABELS if labels.get(k)))


def summary_for(labels: dict | None) -> str:
    """"Male, middle-aged, american; conversational, classy": who it sounds like, then what it suits."""
    labels = labels or {}
    who = ", ".join(str(labels[k]).replace("_", "-") for k in ("gender", "age", "accent") if labels.get(k))
    suits = ", ".join(str(labels[k]).replace("_", " ") for k in ("use_case", "descriptive") if labels.get(k))
    if not who:
        return suits.capitalize()
    return who[:1].upper() + who[1:] + (f"; {suits}" if suits else "")


def new_voices(listed: list[dict], known_ids: set[str]) -> list[dict]:
    """The listed voices Marvin has no record of yet (matched by ElevenLabs voice id), in the order listed."""
    return [v for v in listed if v.get("voice_id") and v["voice_id"] not in known_ids]


def search_term(raw: object) -> str:
    """The optional search from a job's args: blank, missing, or a template left unfilled ("${inputs.search}") is no search."""
    text = str(raw or "").strip()
    return "" if text.startswith("${") else text
