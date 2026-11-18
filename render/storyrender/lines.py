"""Which records are a story's spoken lines, and in what order they play: shared by the render's pull and the script export, so a beat's lines are
the same whichever reads them.

A line is a record of the story with a beat and a speaker. It used to be found by its slug (`<story>-line-3012-1`), which only the import makes; a
line added by hand (the Add a line step, or New) has a slug Marvin made from its title, and was never found. The slug still breaks ties.

Order: a line with an `order` number plays by it (1, 1.5, 2 ...); those with none play after the numbered ones, in slug order. A line with `leave_out`
ticked is set aside: not rendered, not timed, not counted, and not deleted, so a different way of saying a beat can be tried and put back."""


def _data(row: dict) -> dict:
    return row.get("dataJson") or row.get("data") or {}


def is_line(row: dict, story: str) -> bool:
    """A spoken line of `story`: it has a beat and a speaker, and is not a take (a take names its line, not a beat)."""
    d = _data(row)
    return d.get("story") == story and bool(d.get("beat")) and "speaker" in d and "line" not in d


def is_left_out(row: dict) -> bool:
    v = _data(row).get("leave_out")
    return v is True or str(v).strip().lower() in ("true", "yes")


def order_key(row: dict) -> tuple:
    """Numbered lines first by their number, then the rest; each by slug."""
    raw = _data(row).get("order")
    try:
        number = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        number = None
    return (number is None, number or 0.0, str(row.get("slug") or ""))


def of_story(rows: list[dict], story: str, *, include_left_out: bool = False) -> list[dict]:
    """The story's lines in playing order, those set aside left out (unless asked for)."""
    return sorted((r for r in rows if is_line(r, story) and (include_left_out or not is_left_out(r))), key=order_key)


def cues_by_beat(beats: list[dict], lines: list[dict]) -> tuple[dict[str, list], list[tuple[str, dict]]]:
    """Each beat's cue rows (its **Cues on words**) by where their line is *now* (v221): a row names its line, but is kept in the `cues` of the beat
    it was made on, so a line moved to another beat left its cues behind, placed on the wrong shot or lost. Every beat's rows are gathered and each
    is given to the beat that holds its line today; a row already on that beat stays where it is, in its order, and one moved in comes after them
    (unless the same row is there already). A row whose line is no line of the story keeps its stored beat, as before, and is also returned (with
    that beat's slug) so the caller can say so. `lines` should include the lines set aside: their cues stay with them."""
    home = {str(ln.get("slug")): str(_data(ln).get("beat")) for ln in lines if ln.get("slug")}
    known = {str(b.get("slug")) for b in beats}
    out: dict[str, list] = {str(b.get("slug")): [] for b in beats}
    moving: list[tuple[str, dict]] = []
    unknown: list[tuple[str, dict]] = []
    for beat in beats:
        slug = str(beat.get("slug"))
        rows = _data(beat).get("cues")
        for row in rows if isinstance(rows, list) else []:
            where = home.get(str(row.get("line"))) if isinstance(row, dict) else None
            if isinstance(row, dict) and where is None:
                unknown.append((slug, row))
            if where in known and where != slug:
                moving.append((where, row))
            else:
                out[slug].append(row)
    for where, row in moving:
        if row not in out[where]:
            out[where].append(row)
    return out, unknown
