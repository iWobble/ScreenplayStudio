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
