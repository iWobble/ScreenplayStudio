"""A transition written in the Fountain reaches the film and comes back out: FADE IN: opens it, FADE OUT. ends it, a length is a note, a transition
set by hand on a beat is written to the complete export, and an edited transition line reaches a beat that still follows the script."""

import json

from storyrender import fountain, numbering, script
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)

TIDE = """Title: Tide

FADE IN:

EXT. SHORE - DAY

Waves roll in.

MARA
Home.

DISSOLVE TO:

INT. HUT - NIGHT

A lamp burns low on the table. [[Transition: 1.2s.]]

MARA
Still here.

CUT TO:

EXT. CLIFF - DAWN

Gulls wheel over the rocks.

MARA
Morning.

FADE OUT.
"""


def _beats(fake) -> dict[str, dict]:
    return {m["dataJson"]["number"]: m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-beat"}


def _settle(fake) -> None:
    """What the import made is now what the workspace holds, so a second import meets it."""
    homes = {"T-cast": "cast-member", "T-scene": "scene", "T-sound": "sound"}
    for m in fake.made:
        record = {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]}
        (fake.on_hand[homes[m["entryTypeId"]]] if m["entryTypeId"] in homes else fake.records)[m["slug"]] = record
    fake.made.clear()
    fake.patched.clear()


def _patched(fake) -> dict[str, dict]:
    return {slug.removeprefix("id-s-beat-"): body["dataJson"] for slug, body in fake.patched if slug.startswith("id-s-beat-")}


def _records(fake) -> dict:
    rows = sorted((r for slug, r in fake.records.items() if "-beat-" in slug), key=lambda r: numbering.order_key(r["dataJson"].get("number")))
    lines: dict = {}
    for slug, r in fake.records.items():
        if "-line-" in slug:
            lines.setdefault(r["dataJson"].get("beat"), []).append(r)
    return {"story": {"slug": "s", "title": "Tide", "dataJson": fake.story["dataJson"]}, "beats": rows, "lines": lines, "scenes": fake.on_hand["scene"], "sounds": fake.on_hand["sound"], "chapters": {}, "characters": [], "revisions": []}


def test_fade_in_is_the_first_beats_fade_and_a_fade_out_after_the_last_beat_is_how_the_film_ends():
    plan = fountain.cut(fountain.parse(TIDE))
    beats = [b for _c, _n, b in plan.rows()]
    assert [(b.get("transition"), b.get("transition_text")) for b in beats] == [("fade", "FADE IN:"), ("dissolve", "DISSOLVE TO:"), ("cut", "CUT TO:")]
    assert (plan.end_transition, plan.end_transition_text) == ("fade", "FADE OUT.")
    quiet = fountain.cut(fountain.parse(TIDE.replace("FADE OUT.\n", "").replace("FADE IN:\n\n", "")))
    assert (quiet.end_transition, quiet.end_transition_text) == ("", "") and "transition" not in next(iter(quiet.rows()))[2]
    assert fountain.cut(fountain.parse(TIDE.replace("FADE OUT.", "CUT TO BLACK."))).end_transition == ""  # a cut to black is a cut: the film just ends


def test_a_transition_the_video_has_no_word_for_plays_as_a_cut_and_the_split_report_names_it():
    plan = fountain.cut(fountain.parse(TIDE.replace("CUT TO:", "> BURN TO PINK.")))
    last = [b for _c, _n, b in plan.rows()][-1]
    assert last["transition_text"] == "BURN TO PINK." and "transition" not in last
    assert any("BURN TO PINK." in w and "plays as a cut" in w for w in plan.warnings)
    assert not any("plays as a cut" in w for w in fountain.cut(fountain.parse(TIDE)).warnings)


def test_the_import_gives_each_beat_its_transition_and_length_and_the_story_its_ending(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    beats = _beats(fake)
    assert [(b.get("transition"), b.get("transition_seconds")) for b in beats.values()] == [("fade", None), ("dissolve", 1.2), ("cut", None)]
    story = next(body["dataJson"] for slug, body in fake.patched if slug == "e0")
    assert story["end_transition"] == "fade"


def test_an_ending_the_person_chose_is_kept_and_a_script_with_no_fade_out_sets_none(casting):
    fake, ctx = casting(TIDE)
    fake.story["dataJson"]["end_transition"] = "cut"
    run(ctx)
    assert next(body["dataJson"] for slug, body in fake.patched if slug == "e0")["end_transition"] == "cut"
    fake, ctx = casting(TIDE.replace("FADE OUT.\n", ""))
    run(ctx)
    assert "end_transition" not in next(body["dataJson"] for slug, body in fake.patched if slug == "e0")


def test_an_edited_transition_line_reaches_a_beat_that_still_follows_the_script(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.story["dataJson"]["fountain"] = TIDE.replace("DISSOLVE TO:", "FADE TO:").replace("CUT TO:\n\n", "")
    done = run(ctx)
    changed = _patched(fake)
    assert (changed["02"]["transition"], changed["02"]["transition_text"]) == ("fade", "FADE TO:")  # it meant what its line said, so it follows the new line
    assert "transition" not in changed["03"] and "transition_text" not in changed["03"]  # the line was taken out: the beat has none again
    assert "01" not in changed  # FADE IN: is as it was
    assert "set by hand" not in done["log"]


def test_a_transition_set_by_hand_is_kept_and_said_when_the_script_says_another(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.records["s-beat-03"]["dataJson"]["transition"] = "dissolve"  # written CUT TO:, changed by hand
    fake.story["dataJson"]["fountain"] = TIDE.replace("CUT TO:", "FADE TO:")
    done = run(ctx)
    kept = _patched(fake)["03"]  # its piece of the text is the new one; how it plays is still the person's
    assert (kept["transition"], kept["transition_text"]) == ("dissolve", "CUT TO:") and "FADE TO:" in kept["fountain"]
    assert "beat 03 keeps its dissolve (set by hand); the script says FADE TO:" in done["log"]


def test_a_script_that_comes_to_say_what_the_hand_set_is_followed_again(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.records["s-beat-03"]["dataJson"]["transition"] = "dissolve"
    fake.story["dataJson"]["fountain"] = TIDE.replace("CUT TO:", "DISSOLVE TO:")
    done = run(ctx)
    assert (_patched(fake)["03"]["transition"], _patched(fake)["03"]["transition_text"]) == ("dissolve", "DISSOLVE TO:")
    assert "set by hand" not in done["log"]


def test_a_beat_made_before_its_first_transition_counted_gets_it_and_one_with_no_length_gets_the_notes(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    del fake.records["s-beat-01"]["dataJson"]["transition"]  # as the import left a first beat until now: the words, no kind
    del fake.records["s-beat-02"]["dataJson"]["transition_seconds"]
    run(ctx)
    assert _patched(fake)["01"]["transition"] == "fade" and _patched(fake)["02"]["transition_seconds"] == 1.2


def test_the_complete_script_writes_each_transition_as_it_plays_and_how_the_film_ends(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.story["dataJson"]["end_transition"] = "fade"
    fake.records["s-beat-03"]["dataJson"].update({"transition": "dissolve", "transition_seconds": 0.8})  # by hand: written CUT TO:
    text = script.fountain_complete(_records(fake))
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert lines.index("FADE IN:") < lines.index("EXT. SHORE - DAY #1#")  # before the first beat, where it was
    assert lines.count("DISSOLVE TO:") == 2 and "CUT TO:" not in lines  # the hand-set kind in the plain words for it, where CUT TO: was written
    assert "[[Beat 02. Cast: s-mara. Transition: 1.2s.]]" in lines and "[[Beat 03. Cast: s-mara. Transition: 0.8s.]]" in lines  # a length is a note on its beat
    assert lines[-1] == "FADE OUT."
    fake.story["dataJson"]["end_transition"] = "cut"
    assert "FADE OUT." not in script.fountain_complete(_records(fake))


def test_the_complete_script_comes_in_again_as_the_same_transitions_a_hand_set_one_included(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.story["dataJson"]["end_transition"] = "fade"
    fake.records["s-beat-03"]["dataJson"].update({"transition": "dissolve", "transition_seconds": 0.8})
    before = [(r["dataJson"].get("transition"), r["dataJson"].get("transition_seconds")) for r in _records(fake)["beats"]]
    again, ctx2 = casting(script.fountain_complete(_records(fake)))
    run(ctx2)
    assert [(b.get("transition"), b.get("transition_seconds")) for b in _beats(again).values()] == before == [("fade", None), ("dissolve", 1.2), ("dissolve", 0.8)]
    assert next(body["dataJson"] for slug, body in again.patched if slug == "e0")["end_transition"] == "fade"


def test_the_storys_cards_and_transition_go_out_on_the_title_page_and_come_back_into_empty_fields(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    settings = {"intro_title": "TIDE", "intro_subtitle": "A Storyworld film", "intro_seconds": 4, "outro_title": "The End", "card_color": "#2b1b12", "card_text_color": "#ffeedd", "transition": "dissolve", "transition_seconds": 0.8}
    fake.story["dataJson"].update(settings)
    text = script.fountain_complete(_records(fake))
    head = text.split("\n\n", 1)[0].split("\n")
    assert "Title card: TIDE — A Storyworld film (4s)" in head and "End card: The End" in head
    assert "Card colours: #2b1b12, text #ffeedd" in head and "Transition: dissolve (0.8s)" in head
    assert fountain.story_settings(fountain.title_page(text)) == settings
    again, ctx2 = casting(text)
    again.story["dataJson"]["intro_title"] = "My own title"  # a field already filled in is the person's
    run(ctx2)
    story = next(body["dataJson"] for slug, body in again.patched if slug == "e0")
    assert story["intro_title"] == "My own title" and {k: story[k] for k in settings if k != "intro_title"} == {k: v for k, v in settings.items() if k != "intro_title"}
    assert "card" not in json.dumps(story.get("title_page_other", "")).lower()  # they are fields now, not left-over title page lines


def test_a_story_with_no_cards_and_a_cut_between_beats_writes_no_such_lines(casting):
    fake, ctx = casting(TIDE)
    run(ctx)
    _settle(fake)
    fake.story["dataJson"]["transition"] = "cut"
    head = script.fountain_complete(_records(fake)).split("\n\n", 1)[0]
    assert "card" not in head.lower() and "Transition:" not in head
    assert fountain.story_settings({"title": "Tide", "transition": "wipe (9s)", "card_colours": "red"}) == {}  # what is not a setting is left out
