"""Quick looks at some beats (a render with `beats`) are kept as their own video files, never as the story's `video`, so nothing replaces
them and they pile up. After a new look is uploaded, the story's older looks beyond the newest few go to Marvin's Trash (restorable there
for 30 days). Only a video asset whose metadata names this story and has `beats` is ever touched: never the story's current video, never a
whole-story render, never another story's look. Nothing here fails the render: what could not be trashed is said in the job's log."""

import json
import urllib.parse

from marvin_worker import marvin_api
from marvin_worker.jobs import Context

KEEP_PARTIAL_DRAFTS = 3  # the new look and the two before it
LOOK_NAME = "draft of beat"  # a look's name is "<Title>: video (draft of beat 12,13,14)": narrows the listing, the metadata decides
LOOKS_URL = "/api/platform/assets?" + urllib.parse.urlencode({"q": LOOK_NAME, "asset_type": "video", "sort": "newest"})


def keep_count(story_data: dict) -> int:
    """How many looks a story keeps: its `keep_partial_drafts` field when it has one (a whole number, at least 1: the new look always
    stays), else KEEP_PARTIAL_DRAFTS."""
    try:
        return max(1, int(str(story_data.get("keep_partial_drafts")).strip()))
    except (TypeError, ValueError):
        return KEEP_PARTIAL_DRAFTS


def is_look_of(asset: dict, story: str) -> bool:
    meta = asset.get("metadataJson") or asset.get("metadata_json") or {}
    return isinstance(meta, dict) and meta.get("kind") == "video" and meta.get("story") == story and bool(str(meta.get("beats") or "").strip())


def trash_old_looks(ctx: Context, story: str, new_id: str) -> int:
    """Put the story's looks beyond the newest `keep_count` in the Trash (the new one counts as the newest) and say how many in the job's
    log. Returns how many went. The library lists newest first (Marvin sorts by when each was uploaded)."""
    try:
        record = next(iter(marvin_api.query(ctx.creds, {"entries": story}, limit=1)), None) or {}
        data = record.get("dataJson") or {}
        rows = json.loads(marvin_api.request(ctx.creds, LOOKS_URL) or b"[]")
    except Exception as e:  # noqa: BLE001 — tidying up must never fail a video that was made
        ctx.note(f"could not look for older looks at some beats to put in the Trash ({e})")
        return 0
    if not isinstance(rows, list):
        return 0
    keep = keep_count(data)
    spare = {str(new_id), str(data.get("video") or "")}  # the new look, and whatever the story's video is now
    older = [str(a.get("id")) for a in rows if isinstance(a, dict) and is_look_of(a, story) and str(a.get("id")) not in spare]
    gone, failed = 0, []
    for asset_id in older[keep - 1 :]:
        try:
            marvin_api.request(ctx.creds, f"/api/platform/assets/{asset_id}", method="DELETE")
            gone += 1
        except Exception as e:  # noqa: BLE001 — one that cannot be trashed is left where it is
            failed.append(f"{asset_id} ({e})")
    if gone:
        ctx.note(f"put {gone} older look{'s' if gone != 1 else ''} at some beats in the Trash (the newest {keep} are kept; restore from the Trash within 30 days)")
    if failed:
        ctx.note(f"could not put {len(failed)} older look{'s' if len(failed) != 1 else ''} in the Trash: {', '.join(failed)}")
    return gone
