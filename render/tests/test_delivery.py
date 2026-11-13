"""How a line is said lives on the line, so the script comes out of the records as it went in: the parenthetical under a cue is the line's direction,
an extension on the cue is its extension, and a tag inside the speech ([sighs]) is delivery, kept apart from the words the caption shows."""

from storyrender import delivery, fountain, script
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_script_roundtrip import _facts, _records_from

TEXT = """Title: THE LAST LIGHT
Setting: A lighthouse on a storm coast.
Premise: A keeper and her apprentice keep the light burning.

# ACT I: THE STORM

INT. LAMP ROOM - NIGHT #1#

MARA (50s), a lighthouse keeper in a salt-stained oilskin, carries a brass lantern. She has a scar across one eyebrow.

JONAH (20s), her apprentice, drags a coil of rope up the stairs. His boots are soaked.

MARA
(without looking up)
You're late.

JONAH
Fine. [sighs] The path is gone, Mara.

NARRATOR (V.O.)
(slowly)
By midnight the sea had taken the path.

MARA (O.S.)
[whispers] Come in out of the rain.
"""


def test_tags_extensions_and_parentheticals_split_into_a_line_s_own_fields():
    assert delivery.split_tags("Fine. [sighs] Go on.") == ("Fine. Go on.", "Fine. [sighs] Go on.")
    assert delivery.split_tags("[whispers] Quiet now.") == ("Quiet now.", "[whispers] Quiet now.")
    assert delivery.split_tags("x [pause] y [laughs].") == ("x y.", "x [pause] y [laughs].")  # no space is left in front of a full stop
    assert delivery.split_tags("My uncle (he was eighty) laughed.") == ("My uncle (he was eighty) laughed.", "")  # an aside is spoken words
    assert delivery.split_tags("a [[note]] b") == ("a [[note]] b", "")  # a note is not a tag
    assert delivery.split_tokens(["O.S.", "softly"]) == ("O.S.", "softly")
    assert delivery.split_tokens(["CONT'D"]) == ("CONT'D", "")  # one that arrives in a note; the Fountain reader drops a (CONT'D) on the cue itself, as a formatter adds it
    note = "The deck. Delivery: Mara (without looking up); Narrator (V.O.); Mara (O.S., softly)."
    assert delivery.for_lines(note, ["mara", "narrator", "mara", "cook"]) == [("", "without looking up"), ("V.O.", ""), ("O.S.", "softly"), ("", "")]


def test_the_import_puts_how_a_line_is_said_on_the_line(casting):
    fake, ctx = casting(TEXT)
    run(ctx)
    lines = [m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-line"]
    by_text = {d["text"]: d for d in lines}
    late = by_text["You're late."]
    assert late["direction"] == "without looking up" and "extension" not in late and "delivery_text" not in late
    path = by_text["Fine. The path is gone, Mara."]  # the caption's words carry no tag
    assert path["delivery_text"] == "Fine. [sighs] The path is gone, Mara."
    narrator = by_text["By midnight the sea had taken the path."]
    assert narrator["extension"] == "V.O." and narrator["direction"] == "slowly"
    come_in = by_text["Come in out of the rain."]
    assert come_in["extension"] == "O.S." and come_in["delivery_text"] == "[whispers] Come in out of the rain."


def test_the_script_made_from_the_records_says_it_the_same_way(casting):
    fake, ctx = casting(TEXT)
    run(ctx)
    fake.story["dataJson"].update(fountain.title_page(TEXT))
    exported = script.stamp_revision(script.fountain_complete(_records_from(fake)), fake.story)
    assert "(without looking up)" in exported and "(slowly)" in exported
    assert "Fine. [sighs] The path is gone, Mara." in exported  # the tag is back inside the speech
    assert "MARA (O.S.)" in exported and "NARRATOR (V.O.)" in exported
    assert "Delivery:" not in exported.split("\n\n# ")[-1] or "[sighs]" in exported  # a tag in the speech is not also written as a note
    assert _facts(TEXT)["lines"] == _facts(exported)["lines"]  # the same speakers and the same words, tags included


def test_a_speech_line_has_an_extension_to_pick_and_the_fountain_reader_accepts_each_choice():
    import json
    from pathlib import Path

    package = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"
    line = {b["slug"]: b for b in json.loads(package.read_text(encoding="utf-8"))["blueprints"]}["speech-line"]
    fields = {f["key"]: f for f in line["payload"]["schema_json"]["fields"]}
    assert fields["extension"]["type"] == "select" and fields["extension"]["group"] == fields["direction"]["group"] == "How it is said"
    for choice in fields["extension"]["options"]:
        assert delivery.EXTENSION.match(choice), choice  # the reader takes what the form offers
