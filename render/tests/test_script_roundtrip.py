"""The most detailed screenplay the importer understands goes in, the records it made come out as a Fountain, and that Fountain goes in again as the
same thing: chapters, beats, lines (speaker, words, how they are said), places (inside or outside, times of day), sounds, lyrics, holds, transitions,
characters and the title page. Offline: the import runs against the fake workspace of the import tests."""

import re

from storyrender import fountain, numbering, script
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)

MAX_TEXT = """Title: THE LAST LIGHT
Credit: Written by
Author: A Writer
Source: Original story
Draft date: November 2026
Setting: A lighthouse on a storm coast, one winter night.
Premise: A keeper and her apprentice keep the light burning through a storm.
Contact:
    Agent: Someone
    someone@example.com
Copyright: (c) 2026 A Writer.

# ACT I: THE STORM
= A keeper trims the wick as the storm builds.

## SCENE 1: THE LAMP ROOM

INT. LAMP ROOM - NIGHT #1#

MARA (50s), a lighthouse keeper in a salt-stained oilskin, carries a brass lantern. She has a scar across one eyebrow.

[[Sound: wind howling around the glass at 0.5s.]]

[[Hold: 2s.]]

===

JONAH (20s), her apprentice, drags a coil of rope up the stairs. His boots are soaked.

MARA
(without looking up)
You're late.

JONAH
The path is gone, Mara.

NARRATOR (V.O.)
By midnight the sea had taken the path.

CUT TO:

# ACT II: THE LIGHT

EXT. COAST - CONTINUOUS #2#

Waves climb the rocks. A deafening CRUNCH of timber.

~ O sailor, sail home before the dark

===

SUPER: THE LAST LIGHT

DISSOLVE TO:

INT. LAMP ROOM - DAWN #3#

The lamp turns slowly. Mara smiles.

MARA
We kept it burning.

FADE OUT.
"""


def _row(m):
    return {"slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]}


def _records_from(fake):
    made = lambda t: [m for m in fake.made if m["entryTypeId"] == t]  # noqa: E731
    lines: dict = {}
    for m in made("T-line"):
        lines.setdefault(m["dataJson"].get("beat"), []).append(_row(m))
    beats = sorted(made("T-beat"), key=lambda m: numbering.order_key(m["dataJson"].get("number")))
    return {
        "story": {"slug": "s", "title": "THE LAST LIGHT", "dataJson": fake.story["dataJson"]},
        "beats": [_row(m) for m in beats], "lines": lines,
        "scenes": {m["slug"]: _row(m) for m in made("T-scene")}, "sounds": {m["slug"]: _row(m) for m in made("T-sound")},
        "chapters": {m["slug"]: _row(m) for m in made("T-chapter")}, "characters": [_row(m) for m in made("T-cast")], "revisions": [],
    }  # fmt: skip


def _facts(text):
    plan = fountain.cut(fountain.parse(text))
    rows = [(n, b) for _c, n, b in plan.rows()]
    return {
        "chapters": [(c.number, c.title, c.summary, len(c.beats)) for c in plan.chapters],
        "lines": [[(x["speaker"], x["text"]) for x in b["lines"]] for _n, b in rows],
        "pictures": [re.sub(r"\s+", " ", b["picture"]) for _n, b in rows],
        "holds": [b.get("hold") for _n, b in rows],
        "transitions": [b.get("transition_text") for _n, b in rows],
        "headings": [fountain.place_of(b.get("place", "")) for _n, b in rows],
        "sounds": [[(s.get("title"), s.get("at")) for s in b.get("sounds") or []] for _n, b in rows],
        "sung": [[w.rstrip(" ~").strip() for w in b.get("sung") or []] for _n, b in rows],
        "characters": [(c["handle"], c["name"], c["age"], c["sex"], c["description"]) for c in plan.characters],
        "places": plan.places,
    }


def test_the_most_detailed_screenplay_comes_back_out_as_itself(casting):
    fake, ctx = casting(MAX_TEXT)
    run(ctx)
    fake.story["dataJson"].update(fountain.title_page(MAX_TEXT))  # what the import fills the story's credits with
    exported = script.stamp_revision(script.fountain_complete(_records_from(fake)), fake.story)
    before, after = _facts(MAX_TEXT), _facts(exported)
    for key in before:
        if key == "chapters":  # the first synopsis of each chapter is its summary
            assert [(n, t, len(s) > 0, c) for n, t, s, c in before[key]] == [(n, t, len(s) > 0, c) for n, t, s, c in after[key]], key
        elif key == "headings":  # the scene number is the scene's, not the heading's: the same place keeps one
            assert [(h["name"], h["kind"], h["time"]) for h in before[key]] == [(h["name"], h["kind"], h["time"]) for h in after[key]], key
        else:
            assert before[key] == after[key], key
    page = fountain.title_page(MAX_TEXT)
    assert {k: page[k] for k in ("credit", "author", "source", "draft_date", "setting", "premise", "copyright")} == {k: fountain.title_page(exported)[k] for k in ("credit", "author", "source", "draft_date", "setting", "premise", "copyright")}
    assert "Agent: Someone" in fountain.title_page(exported)["contact"]
