"""Beat numbers: digits, then letters for a beat inserted later (1002a ... 1002z, then 1002aa, 1002ab ... as spreadsheet columns run).

The letters sort by length first and then alphabetically, so 1002z comes before 1002aa: a plain text sort would put 1002aa before 1002b.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"^0*(\d+)([a-z]*)$")
LAST_LETTER = "z"


def parts(number: object) -> "tuple[int, str] | None":
    """`04a` -> (4, "a"); None for anything that is not a beat number."""
    m = _NUMBER.match(str(number if number is not None else "").strip().lower())
    return (int(m.group(1)), m.group(2)) if m else None


def order_key(number: object) -> tuple:
    """A key that puts beat numbers in the order they play: 4, 4a, 4b ... 4z, 4aa, 4ab ..., 5. What is not a number sorts after, by its text."""
    p = parts(number)
    return (0, p[0], len(p[1]), p[1], "") if p else (1, 0, 0, "", str(number if number is not None else ""))


def after(number: str) -> str:
    """The number a beat inserted after `number` takes: 1002 -> 1002a, 1002a -> 1002b, 1002z -> 1002aa, 1002az -> 1002ba."""
    m = re.fullmatch(r"(\d+)([a-z]*)", number)
    if not m:
        raise ValueError(f"beat number “{number}” cannot be followed by an inserted beat")
    digits, letters = m.groups()
    chars = list(letters) or ["`"]  # one step before "a", so a bare number takes "a"
    i = len(chars) - 1
    while i >= 0 and chars[i] == LAST_LETTER:
        chars[i] = "a"
        i -= 1
    if i < 0:
        chars.insert(0, "a")
    else:
        chars[i] = chr(ord(chars[i]) + 1)
    return digits + "".join(chars)
