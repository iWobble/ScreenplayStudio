"""Fitting what was heard onto what was written. Whisper's words are the right *times* but sometimes the wrong *spelling* (a name, a number, a made-up
word), and a caption should show the author's words. So the written words are matched to the heard ones, and each written word takes the time of
the heard word it matched; a written word nothing matched is placed in the gap between its neighbours, by its length."""

import re
from difflib import SequenceMatcher


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", str(word).lower())


def script_times(script: str, heard: list[dict]) -> list[dict]:
    """[{text, start, end}] for each word of `script`, with times from `heard` ([{text, start, end}] in seconds, as the model gave them).
    Empty when nothing was heard. With no script, the heard words themselves."""
    heard = [h for h in heard if _norm(h["text"])]
    if not heard:
        return []
    words = script.split()
    if not words:
        return [{"text": str(h["text"]).strip(), "start": round(float(h["start"]), 3), "end": round(float(h["end"]), 3)} for h in heard]
    a, b = [_norm(w) for w in words], [_norm(h["text"]) for h in heard]
    known: list[tuple[float, float] | None] = [None] * len(words)
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            known[block.a + k] = (float(heard[block.b + k]["start"]), float(heard[block.b + k]["end"]))
    start, end = float(heard[0]["start"]), float(heard[-1]["end"])
    i = 0
    while i < len(words):  # a run of written words nothing matched: share the gap between the matched neighbours out by length
        if known[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and known[j] is None:
            j += 1
        left = known[i - 1][1] if i > 0 else start  # type: ignore[index]
        right = known[j][0] if j < len(words) else end  # type: ignore[index]
        right = max(right, left)
        weights = [max(1, len(a[k]) or len(words[k])) for k in range(i, j)]
        clock = left
        for k, weight in zip(range(i, j), weights, strict=True):
            span = (right - left) * weight / sum(weights)
            known[k] = (clock, clock + span)
            clock += span
        i = j
    return [{"text": w, "start": round(known[n][0], 3), "end": round(known[n][1], 3)} for n, w in enumerate(words)]  # type: ignore[index]
