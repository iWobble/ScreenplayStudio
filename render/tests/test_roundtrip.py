"""Import, then export: the Fountain that comes back should say the same things as the Fountain that went in.

The rule (Jared, 2026-11-11): everything the importer reads, the exporter can write, so the file before the cut and after the export are
essentially the same. `script.fountain` was built to make a production script from records, not to mirror a source, so it does not yet:
each gap below is an expected failure with its reason, strict, so the moment one is closed the test says so and the mark comes off.
"""

import collections
import re
from pathlib import Path

import pytest

from storyrender import beat_import, fountain, script
from tests.test_fountain import ALL_ELEMENTS

DEVILS_SHOALS = (Path(__file__).parent / "data" / "devils_shoals.fountain").read_text(encoding="utf-8")


def _exported(text: str) -> list[dict]:
    """The elements of the Fountain the records of `text` make: import it as the job does, then export it as the script job does."""
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    ip = beat_import.import_plan("s", beat_import.parse_any(plan.sheet())[1], {})
    fountain.attach_source(ip, plan, "s")
    lines: dict[str, list[dict]] = collections.defaultdict(list)
    for slug, title, data in ip["lines"]:
        lines[data["beat"]].append({"slug": slug, "title": title, "dataJson": data})
    records = {
        "story": {"slug": "s", "title": "Story", "dataJson": {"fountain_front": plan.front}},
        "scenes": {},
        "chapters": [{"slug": s, "title": t, "dataJson": d} for s, t, d in ip["chapters"]],
        "beats": [{"slug": s, "title": t, "dataJson": d} for s, t, d in ip["beats"]],
        "lines": dict(lines),
        "sounds": {},
    }
    return fountain.parse(script.fountain_as_written(records) or script.fountain(records))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


CATEGORIES = {
    "speeches": lambda els: [(e["name"].upper(), _words(e["text"])) for e in els if e["t"] == "dialogue"],
    "sections": lambda els: [e["title"] for e in els if e["t"] == "section"],
    "scene headings": lambda els: [e["text"].upper() for e in els if e["t"] == "scene"],
    "transitions": lambda els: [e["text"] for e in els if e["t"] == "transition"],
    "action": lambda els: _words(" ".join(e["text"] for e in els if e["t"] == "action")),
}
GAPS: dict[str, str] = {}  # category -> why the export does not yet say what the import read (none: each beat keeps its own text as written)
FIXTURES = {"every element": ALL_ELEMENTS, "devil's shoals": DEVILS_SHOALS}


def _cases() -> list:
    return [
        pytest.param(name, text, category, marks=[pytest.mark.xfail(strict=True, reason=GAPS[category])] if category in GAPS else [], id=f"{name}-{category}")
        for name, text in FIXTURES.items()
        for category in CATEGORIES
    ]


@pytest.mark.parametrize(("name", "text", "category"), _cases())
def test_the_export_says_what_the_import_read(name, text, category):
    pick = CATEGORIES[category]
    assert pick(_exported(text)) == pick(fountain.parse(text))


def test_every_gap_is_a_category_the_test_knows():
    assert set(GAPS) <= set(CATEGORIES)


@pytest.mark.parametrize(("name", "text"), list(FIXTURES.items()))
def test_the_export_has_every_word_of_the_import_in_order(name, text):
    """Not only the elements the reader knows: the whole text, notes, boneyards, synopses, title page and all (only blank lines may differ)."""
    plan = fountain.cut(fountain.parse(text, lines=True), text=text)
    ip = beat_import.import_plan("s", beat_import.parse_any(plan.sheet())[1], {})
    fountain.attach_source(ip, plan, "s")
    records = {"story": {"slug": "s", "title": "S", "dataJson": {"fountain_front": plan.front}}, "beats": [{"slug": s, "title": t, "dataJson": d} for s, t, d in ip["beats"]]}
    assert script.fountain_as_written(records).split() == text.replace("\r\n", "\n").split()


def test_a_story_not_made_from_fountain_has_no_as_written_script():
    assert script.fountain_as_written({"story": {"dataJson": {}}, "beats": [{"dataJson": {"number": "01", "picture": "x"}}]}) is None
