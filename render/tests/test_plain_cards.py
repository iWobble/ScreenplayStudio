"""A beat that shows a plain card: the story's card colour with the beat's card words on it (none: a blank hold), in place of a picture. It is a
beat like any other (a number, a length, lines, sounds, a chapter, a transition in), no still is ever made for it, and centred Fountain text
(`> THE END <`) is how a screenplay writes one."""

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from storyrender import beat_import, build, cards, chapters, ffmpeg, fountain, manifest, marvin_pull, numbering, ready, script
from tests.test_fountain import casting, run  # noqa: F401  (the fake workspace and the import runner)
from tests.test_listen_pull import _ROWS, S, _FakeMarvin, marvin  # noqa: F401  (the fake Marvin the pull reads)

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
PACKAGE = Path(__file__).resolve().parents[2] / "docs" / "screenplay-studio.marvin-package.json"


def _inked(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Every colour (with its opacity) the picture holds."""
    return [colour for _count, colour in image.getcolors(image.width * image.height)]


# ── the card itself ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_beat_shows_a_plain_card_only_when_it_says_so():
    assert cards.is_plain({"shows": "Plain card"}) and cards.is_plain({"shows": " plain card "})
    assert not cards.is_plain({}) and not cards.is_plain({"shows": "Picture"}) and not cards.is_plain({"shows": ""})


def test_a_plain_card_is_one_colour_the_size_of_the_frame_and_a_bad_colour_is_the_default(tmp_path):
    image = Image.open(cards.make_plain("#2b1b12", tmp_path / "a" / "card.png", (360, 640))).convert("RGB")
    assert image.size == (360, 640) and image.getcolors() == [(360 * 640, (0x2B, 0x1B, 0x12))]
    assert Image.open(cards.make_plain("blue-ish", tmp_path / "b.png", (64, 36))).convert("RGB").getcolors() == [(64 * 36, (0x11, 0x11, 0x11))]


def test_the_words_of_a_plain_card_are_in_the_storys_text_colour_on_a_clear_backdrop(tmp_path):
    card = {**cards.info_of({"info_label": "Later", "info_title": "THREE YEARS LATER", "info_text": "The lamp still burns."}), "dim": 0.0, "text_colour": (10, 200, 30)}
    image = Image.open(cards.make_info(card, tmp_path / "words.png", (360, 640)))
    assert {pixel[:3] for pixel in _inked(image) if pixel[3] == 255} == {(10, 200, 30)}  # label, title and sentence all in the one colour
    assert not [pixel for pixel in _inked(image) if pixel[3] >= 100 and pixel[1] < 50]  # and no dark shadow under them: there is no picture to stand out from
    assert image.getpixel((2, 2))[3] == 0  # nothing is dimmed: the card's own colour shows


# ── what the pull hands the renderer ──────────────────────────────────────────────────────────────────────────────────────────
def _pulled(marvin, tmp_path, story: dict, *more: dict, **options) -> tuple[dict, dict]:
    rows = [dict(r) for r in _ROWS]
    rows[0] = {**rows[0], "dataJson": story}
    rows += [{"slug": f"{S}-beat-{d['number']}", "dataJson": {"story": S, **d}} for d in more]
    _FakeMarvin.rows = rows
    try:
        result = marvin_pull.pull(S, tmp_path, creds=(marvin, "tok"), **options)
    finally:
        _FakeMarvin.rows = _ROWS
    return result, {s["id"]: s for s in json.loads((tmp_path / "manifest.json").read_text())["shots"]}


def test_a_plain_card_with_no_still_and_no_lines_is_a_shot_of_the_storys_colour_and_size_with_its_words_over_it(marvin, tmp_path):
    story = {"format": "square-1x1", "card_color": "#2b1b12", "card_text_color": "#ffeedd"}
    card = {"number": "04", "shows": "Plain card", "info_title": "THREE YEARS LATER", "chapter": f"{S}-chapter-2"}
    result, shots = _pulled(marvin, tmp_path, story, card, {"number": "05", "shows": "Plain card", "hold_seconds": 2.5})
    shot = shots["b04"]
    assert "04" not in result["skipped"] and result["placeholders"] == []  # it has its picture: nothing to stand in for, nothing left out
    still = Image.open(tmp_path / shot["still"]).convert("RGB")
    assert shot["still"] == "stills/b04-card.png" and still.size == (1080, 1080) and still.getcolors() == [(1080 * 1080, (0x2B, 0x1B, 0x12))]
    assert shot["hold"] == marvin_pull.DEFAULT_HOLD == 4.0 and shot["lines"] == [] and shot["chapter"] == f"{S}-chapter-2"
    assert shot["overlay"] == {"video": "video/info/b04.png", "blend": "normal", "opacity": 1.0, "id": "info-b04", "fade": cards.INFO_FADE, "delay": cards.INFO_DELAY}
    words = Image.open(tmp_path / shot["overlay"]["video"])
    assert {p[:3] for p in _inked(words) if p[3] == 255} == {(0xFF, 0xEE, 0xDD)} and words.getpixel((2, 2))[3] == 0
    blank = shots["b05"]
    assert blank["hold"] == 2.5 and "overlay" not in blank and blank["still"] == "stills/b05-card.png"  # no words: a blank hold, as long as it says
    _pulled(marvin, tmp_path / "cards", story, card, {"number": "05", "shows": "Plain card"}, beats="4-5")
    assert [s.id for s in manifest.load(tmp_path / "cards" / "manifest.json", probe=lambda _p: 1.0).shots] == ["b04", "b05"]  # the render has the still it needs for each


def test_a_plain_card_takes_no_overlay_camera_or_placeholder_from_anywhere_and_never_the_still_it_once_had(marvin, tmp_path):
    story = {"overlay": "rain-video", "camera": "Push in"}  # the story lays rain over every beat and pushes in on it
    card = {"number": "04", "shows": "Plain card", "still": "old-still", "camera": "Rocking"}  # it had a picture before it became a card
    result, shots = _pulled(marvin, tmp_path, story, card, beats="4", placeholders=True)
    assert set(shots["b04"]) == {"id", "lines", "hold", "still"} and shots["b04"]["still"] == "stills/b04-card.png"  # nothing was fetched: neither asset exists
    assert result["placeholders"] == []
    assert Image.open(tmp_path / "stills" / "b04-card.png").convert("RGB").getcolors() == [(1080 * 1920, (0x11, 0x11, 0x11))]  # no colour set: near black


def _card_manifest(tmp_path: Path, card: dict, **top) -> manifest.Manifest:
    cards.make_plain("#203040", tmp_path / "card.png", (360, 640))
    cards.make_plain("#a0a0a0", tmp_path / "grey.png", (360, 640))
    shots = [{"id": "b01", "still": "grey.png", "hold": 1, "lines": []}, {"id": "b02", "still": "card.png", "lines": [], **card}, {"id": "b03", "still": "grey.png", "hold": 1, "lines": [], "chapter": "c2"}]
    (tmp_path / "manifest.json").write_text(json.dumps({"size": [360, 640], "fps": 24, "shots": shots, **top}))
    return manifest.load(tmp_path / "manifest.json", probe=ffmpeg.duration)


def test_a_card_someone_reads_lasts_as_long_as_the_line_and_everything_after_it_starts_that_much_later(tmp_path):
    silent = manifest.plan(_card_manifest(tmp_path / "a", {"hold": 4}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "line.wav").write_bytes(b"x")
    cards.make_plain("#203040", tmp_path / "b" / "card.png", (360, 640))
    cards.make_plain("#a0a0a0", tmp_path / "b" / "grey.png", (360, 640))
    read = {"hold": 4, "lines": [{"id": "l1", "audio": "line.wav", "text": "Three years later.", "speaker": "narrator"}]}
    shots = [{"id": "b01", "still": "grey.png", "hold": 1, "lines": []}, {"id": "b02", "still": "card.png", **read}, {"id": "b03", "still": "grey.png", "hold": 1, "lines": []}]
    (tmp_path / "b" / "manifest.json").write_text(json.dumps({"shots": shots}))
    spoken = manifest.plan(manifest.load(tmp_path / "b" / "manifest.json", probe=lambda _p: 6.0))
    assert silent.shots[1].duration == 4.0 and spoken.shots[1].duration == pytest.approx(manifest.LEAD + 6.0 + manifest.TAIL)
    longer = spoken.shots[1].duration - 4.0
    assert spoken.shots[2].start - silent.shots[2].start == pytest.approx(longer) and spoken.duration - silent.duration == pytest.approx(longer)


def test_a_card_that_starts_a_chapter_is_where_the_chapters_mark_is(tmp_path):
    m = _card_manifest(tmp_path, {"hold": 4, "chapter": "c2"}, chapters=[{"id": "c2", "title": "Three years later"}])
    marks = chapters.markers(m)
    assert [(x.id, x.start) for x in marks] == [("c2", 1.0)]  # the card, not the first picture after it
    assert chapters.youtube(marks)[0].splitlines() == ["0:00 Intro", "0:01 Three years later"]


@needs_ffmpeg
def test_a_card_with_no_words_is_one_plain_colour_for_as_long_as_it_lasts(tmp_path):
    m = _card_manifest(tmp_path, {"hold": 2})
    build.render(m, tmp_path / "out.mp4", draft=True, keep=tmp_path / "work")

    def frame(at: float) -> bytes:
        import subprocess

        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(tmp_path / "work" / "video.mp4"), "-frames:v", "1", "-vf", "scale=4:4:flags=neighbor", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        return subprocess.run(cmd, capture_output=True, check=True).stdout

    for at in (1.2, 2.0, 2.8):
        pixels = {tuple(frame(at)[i : i + 3]) for i in range(0, 48, 3)}
        assert all(max(abs(got - want) for got, want in zip(p, (0x20, 0x30, 0x40), strict=True)) < 12 for p in pixels), (at, pixels)  # the card's colour everywhere, nothing like the grey around it
    assert float(ffmpeg.probe(tmp_path / "work" / "video.mp4")["format"]["duration"]) == pytest.approx(4.0, abs=1.5 / 24)


# ── the Fountain: centred text alone is a card ────────────────────────────────────────────────────────────────────────────────
ENDING = """Title: Tide

EXT. SHORE - DAY

Waves roll in. A deafening CRUNCH of timber.

MARA
Home.

> THREE YEARS LATER <

INT. HUT - NIGHT

> THE HUT <
> Where it began. <

NARRATOR (V.O.)
She never left.

A lamp burns low.

> THE END <
"""


def _plan(text: str):
    return fountain.cut(fountain.parse(text, lines=True), text=text)


def test_centred_text_standing_alone_is_a_card_beat_with_no_picture_and_inside_action_it_stays_action():
    beats = [b for _c, _n, b in _plan(ENDING).rows()]
    assert [(b["picture"], b.get("card")) for b in beats] == [
        ("Exterior: Shore, day. Waves roll in. A deafening CRUNCH of timber.", None),
        ("", {"title": "THREE YEARS LATER", "text": ""}),  # it ends the picture before it and is not part of it
        ("", {"title": "THE HUT", "text": "Where it began."}),  # right under a heading it is that scene's first beat; a second centred line is its sentence
        ("A lamp burns low.", None),  # action after a card is a new picture
        ("", {"title": "THE END", "text": ""}),
    ]
    assert [len(b["lines"]) for b in beats] == [1, 0, 1, 0, 0]  # a line after a card is read over the card
    assert [b.get("place") for b in beats] == ["EXT. SHORE - DAY", "EXT. SHORE - DAY", "INT. HUT - NIGHT", "INT. HUT - NIGHT", "INT. HUT - NIGHT"]
    assert all(not b["sounds"] for b in beats[1:])  # no sound is asked for from a card's capitals
    assert fountain.check(_plan(ENDING)) == []  # nothing is lost: the words are on the cards
    mixed = [b for _c, _n, b in _plan("INT. HUT - NIGHT\n\nA sign on the door.\n> KEEP OUT <\nIt creaks.\n").rows()]
    assert len(mixed) == 1 and "card" not in mixed[0] and "KEEP OUT" in mixed[0]["picture"] and "It creaks." in mixed[0]["picture"]  # a centred line inside a paragraph of action is action
    two = [b.get("card") for _c, _n, b in _plan("INT. HUT - NIGHT\n\n> ONE <\n\n===\n\n> TWO <\n").rows()]
    assert two == [{"title": "ONE", "text": ""}, {"title": "TWO", "text": ""}]  # a page break sets a second card off, as it does a picture
    assert [b.get("card") for _c, _n, b in _plan("INT. HUT - NIGHT\n\n> **THE END** <\n").rows()] == [{"title": "THE END", "text": ""}]  # emphasis marks come off


def test_the_import_makes_a_card_beat_that_asks_for_no_picture_no_sound_and_no_cast(casting):
    fake, ctx = casting(ENDING)
    done = run(ctx)
    beats = {m["dataJson"]["number"]: m for m in fake.made if m["entryTypeId"] == "T-beat"}
    assert [(n, m["dataJson"].get("shows"), m["dataJson"].get("info_title"), m["dataJson"].get("info_text")) for n, m in beats.items()] == [
        ("01", None, None, None), ("02", "Plain card", "THREE YEARS LATER", None), ("03", "Plain card", "THE HUT", "Where it began."), ("04", None, None, None), ("05", "Plain card", "THE END", None),
    ]  # fmt: skip
    for number in ("02", "03", "05"):
        data = beats[number]["dataJson"]
        assert not {"picture", "sounds", "cast", "references"} & set(data) and data["status"] == "draft"  # nothing a still or a sound is made from
    assert beats["05"]["title"] == "Beat 05: THE END" and beats["03"]["title"] == "Beat 03: Narrator: She never left."
    assert beats["02"]["dataJson"]["scene"] == "s-shore" and beats["05"]["dataJson"]["scene"] == "s-hut"  # a card is in the scene it is written in
    assert "> THE END <" in beats["05"]["dataJson"]["fountain"]
    lines = [m["dataJson"] for m in fake.made if m["entryTypeId"] == "T-line"]
    assert [(ln["beat"], ln["speaker"], ln.get("extension")) for ln in lines] == [("s-beat-01", "mara", None), ("s-beat-03", "narrator", "V.O.")]  # only what is spoken is a line
    assert not [m["slug"] for m in fake.made if m["entryTypeId"] == "T-sound" and any(f"-sound-{n}-" in m["slug"] for n in ("02", "03", "05"))]
    assert done["result"]["beats_made"] == 5


def test_bringing_the_same_fountain_in_again_changes_no_card(casting):
    fake, ctx = casting(ENDING)
    run(ctx)
    for m in fake.made:
        if m["entryTypeId"] in ("T-beat", "T-line"):
            fake.records[m["slug"]] = {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]}
    fake.made.clear(), fake.patched.clear()
    done = run(ctx, mode="refresh")
    assert not [m for m in fake.made if m["entryTypeId"] in ("T-beat", "T-line")] and not [slug for slug, _ in fake.patched if "-beat-" in slug]
    assert done["result"]["updated"] == [] and done["result"]["trashed"] == []


def test_a_sheet_row_marked_as_a_card_is_planned_with_its_words_and_no_picture():
    _, rows = beat_import.parse_any("| 01 | — | No speech. | A wide shot. |\n| 02 | — | No speech. |  |\n")
    rows[1]["card"] = {"title": "THE END", "text": "A Storyworld film"}
    made = {slug: (title, data) for slug, title, data in beat_import.import_plan("s", rows, set())["beats"]}
    title, data = made["s-beat-02"]
    assert title == "Beat 02: THE END" and {k: v for k, v in data.items() if k != "audio_notes"} == {"story": "s", "number": "02", "status": "draft", "shows": "Plain card", "info_title": "THE END", "info_text": "A Storyworld film"}
    assert "shows" not in made["s-beat-01"][1] and made["s-beat-01"][1]["picture"] == "A wide shot."


def _records(fake) -> dict:
    made = lambda t: [{"slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]} for m in fake.made if m["entryTypeId"] == t]  # noqa: E731
    lines: dict = {}
    for m in made("T-line"):
        lines.setdefault(m["dataJson"].get("beat"), []).append(m)
    beats = sorted(made("T-beat"), key=lambda m: numbering.order_key(m["dataJson"].get("number")))
    return {"story": {"slug": "s", "title": "Tide", "dataJson": {}}, "beats": beats, "lines": lines, "scenes": {m["slug"]: m for m in made("T-scene")}, "sounds": {m["slug"]: m for m in made("T-sound")}, "chapters": {}, "characters": [], "revisions": []}


def test_the_complete_script_writes_a_card_as_centred_text_and_reads_it_back_as_the_same_beat(casting):
    fake, ctx = casting(ENDING)
    run(ctx)
    records = _records(fake)
    records["beats"].append({"slug": "s-beat-06", "title": "Beat 06", "dataJson": {"story": "s", "number": "06", "shows": "Plain card", "scene": "s-hut", "hold_seconds": 3}})  # a blank hold, made by hand
    text = script.fountain_complete(records)
    blocks = text.split("\n\n")
    assert "> THREE YEARS LATER <" in blocks and "> THE HUT <\n> Where it began. <" in blocks and "> THE END <" in blocks
    assert "Beat 06.\n\n[[Beat 06. Shows: Plain card. Hold: 3s.]]" in text  # no words to centre: the note says what it shows
    again, ctx2 = casting(text)
    run(ctx2)
    want = [(d.get("shows"), d.get("info_title"), d.get("info_text"), "picture" in d) for d in (b["dataJson"] for b in records["beats"])]
    got = [m["dataJson"] for m in again.made if m["entryTypeId"] == "T-beat"]
    assert [(d.get("shows"), d.get("info_title"), d.get("info_text"), "picture" in d) for d in got] == want
    assert got[-1]["hold_seconds"] == 3.0 and [d.get("shows") for d in got].count("Plain card") == 4


# ── no spend: the package never sends a card to be drawn ──────────────────────────────────────────────────────────────────────
def _blueprint(kind: str, slug: str) -> dict:
    return next(b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == kind and b["slug"] == slug)["payload"]


def _marvin_where(data: dict, where: list[dict]) -> bool:
    """A record against a query's `where`, as Marvin reads it (services/entries/query.py `_matches`): a field that is absent, empty text or an empty
    list is missing; `neq` is true of a missing field."""
    def one(cond: dict) -> bool:
        actual, op, expected = data.get(cond["field"]), cond.get("op") or "eq", cond.get("value")
        missing = actual is None or actual == "" or actual == []
        return {"exists": not missing, "missing": missing, "in": actual in (expected if isinstance(expected, list) else [expected]), "neq": actual != expected, "eq": actual == expected}[op]

    return all(one(cond) for cond in where)


def test_the_beat_form_has_the_choice_as_plain_text_options_and_the_worker_reads_the_same_words():
    fields = {f["key"]: f for f in _blueprint("entry_type", "beat")["schema_json"]["fields"]}
    shows = fields["shows"]
    assert shows["type"] == "select" and shows["options"] == ["Picture", cards.PLAIN_CARD] and all(isinstance(o, str) for o in shows["options"])
    assert "defaultValue" not in shows and not shows.get("required")  # empty is a picture: no beat that exists changes
    assert {fields[k]["group"] for k in ("info_label", "info_title", "info_text", "info_icon", "info_dim")} == {"Card words"}


def test_the_stills_batch_never_picks_a_plain_card_and_still_picks_every_other_waiting_beat():
    collect = next(a for a in _blueprint("workflow", "screenplay-make-stills")["definition"]["actions"] if a.get("kind") == "collect")
    where = collect["query"]["where"]
    assert {"field": "shows", "op": "neq", "value": cards.PLAIN_CARD} in where
    waiting = {"status": "draft", "picture": "A wide shot."}
    assert _marvin_where(waiting, where) and _marvin_where({**waiting, "shows": "Picture"}, where) and _marvin_where({**waiting, "shows": ""}, where)
    assert not _marvin_where({**waiting, "shows": cards.PLAIN_CARD}, where)  # a card that still holds the words of the picture it was
    assert not _marvin_where({"status": "draft", "shows": cards.PLAIN_CARD, "info_title": "THE END"}, where)  # and one the Fountain made
    details = next(a for a in _blueprint("workflow", "screenplay-write-beat-details")["definition"]["actions"] if a.get("kind") == "collect")
    assert {"field": "shows", "op": "neq", "value": cards.PLAIN_CARD} in details["query"]["where"]  # nor is the AI asked to describe one


def test_the_stills_batch_says_in_whole_sentences_that_it_leaves_a_plain_card_out():
    blueprint = next(b for b in json.loads(PACKAGE.read_text(encoding="utf-8"))["blueprints"] if b["kind"] == "workflow" and b["slug"] == "screenplay-make-stills")
    said = blueprint["payload"]["description"]
    assert said == blueprint["description"] and said.endswith(".") and "plain card" in said  # the list and the workflow's own page say the same


def test_a_plain_card_set_to_queued_starts_no_still_and_the_one_beat_workflow_does_not_queue_it():
    take = _blueprint("workflow", "screenplay-take-still")["definition"]
    assert {"field": "entry.data.shows", "op": "neq", "value": cards.PLAIN_CARD} in take["conditions"]  # the workflow that spends does not start for it
    assert take["trigger"] == {"type": "event", "event": "entry_updated"} and any(a.get("integration") == "openai_images" for a in take["actions"])
    one = _blueprint("workflow", "screenplay-make-still")["definition"]["actions"]
    assert [a.get("when") for a in one if a.get("data") == {"status": "queued"}] == [{"field": "entry.data.shows", "op": "neq", "value": cards.PLAIN_CARD}]


# ── readiness and the AI's beat details leave a card alone ────────────────────────────────────────────────────────────────────
def test_readiness_does_not_ask_a_plain_card_for_a_cast_an_expression_or_a_focus():
    from tests.test_ready import GOOD

    card = {"slug": "s-beat-1002", "number": "1002", "shows": "Plain card", "info_title": "THE END", "scene": "sc1"}
    assert ready.check(**{**GOOD, "beats": [*GOOD["beats"], card]}) == []


def test_the_ai_is_not_asked_to_describe_a_plain_card(monkeypatch, tmp_path):
    from tests.test_beat_details import beat, go

    fake, done = go(monkeypatch, tmp_path, [beat(1, shows="Plain card", info_title="THE END")], "[]")
    assert fake.asked == [] and done["result"]["written"] == 0


def test_a_refresh_makes_a_beat_whose_words_were_centred_since_a_card_and_keeps_that_with_its_new_piece_of_the_text(casting):
    before = "INT. HUT - NIGHT\n\nA lamp burns low.\n\nMARA\nStill here.\n\nThe end of the road.\n"
    fake, ctx = casting(before)
    run(ctx)
    for m in fake.made:
        if m["entryTypeId"] in ("T-beat", "T-line"):
            fake.records[m["slug"]] = {"id": f"id-{m['slug']}", "slug": m["slug"], "title": m["title"], "dataJson": m["dataJson"]}
    fake.made.clear(), fake.patched.clear()
    fake.story["dataJson"]["fountain"] = before.replace("The end of the road.", "> The end of the road. <")
    run(ctx, mode="refresh")
    last = [body for slug, body in fake.patched if slug == "id-s-beat-02"][-1]  # what the record holds once every change is in
    assert last["dataJson"]["shows"] == "Plain card" and last["dataJson"]["info_title"] == "The end of the road." and last["title"] == "Beat 02: The end of the road."
    assert "> The end of the road. <" in last["dataJson"]["fountain"]  # and its own piece of the text is the new one
