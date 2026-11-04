"""Pull a story's recorded lines out of Marvin and lay them out the way `listen` and `render` read them.

Marvin keeps the story (its beats, its speech lines, the audio of each take). This reads those records with the signed-in
CLI's token (`~/.marvin/credentials.json`, from `marvin auth login`), downloads each recorded take, and writes
`manifest.json` + `audio/<line>.<ext>` (and `stills/<beat>.<ext>` for any beat that has a still). Nothing is written back.
The Marvin calls are `marvin_worker.marvin_api`'s (it names itself to Marvin's edge, which refuses Python's default user agent).
"""

import json
from pathlib import Path

from marvin_worker import marvin_api

CREDENTIALS = Path.home() / ".marvin" / "credentials.json"


class PullError(RuntimeError):
    pass


def credentials(path: Path = CREDENTIALS) -> tuple[str, str]:
    try:
        raw = json.loads(path.read_text())
        return str(raw["apiUrl"]).rstrip("/"), str(raw["userToken"])
    except (OSError, KeyError, json.JSONDecodeError) as e:
        raise PullError(f"can't read Marvin credentials from {path} ({e}); run `marvin auth login`") from e


def _extension(mime: str | None, fallback: str) -> str:
    return {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
        (mime or "").split(";")[0].lower(), fallback
    )


def _fetch_asset(creds: tuple[str, str], asset_id: str, dest_stem: Path, fallback_ext: str) -> Path:
    dest = dest_stem.with_suffix("." + _extension(marvin_api.asset(creds, asset_id).get("mimeType"), fallback_ext))
    marvin_api.download_asset(creds, asset_id, dest)
    return dest


def pull(story: str, out: Path, *, creds: tuple[str, str] | None = None) -> dict:
    """Write `out/manifest.json` for the story's recorded lines. Returns what was found: the shots, and the lines still to record."""
    creds = creds or credentials()
    try:
        return _pull(story, out, creds)
    except marvin_api.MarvinError as e:
        raise PullError(str(e)) from e


def _pull(story: str, out: Path, creds: tuple[str, str]) -> dict:
    rows = marvin_api.entries(creds)
    data = lambda e: e.get("dataJson") or e.get("data") or {}  # noqa: E731
    story_row = next((e for e in rows if e.get("slug") == story), None)
    if story_row is None:
        raise PullError(f"no story “{story}” in the workspace the CLI is signed in to")
    beats = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-beat-") and data(e).get("story") == story), key=lambda e: str(data(e).get("number")))
    lines = sorted((e for e in rows if e.get("slug", "").startswith(f"{story}-line-") and data(e).get("story") == story), key=lambda e: e["slug"])
    by_beat: dict[str, list[dict]] = {}
    for line in lines:
        by_beat.setdefault(str(data(line).get("beat")), []).append(line)

    shots, missing = [], []
    for beat in beats:
        number = str(data(beat).get("number"))
        spoken = []
        for line in by_beat.get(beat["slug"], []):
            d = data(line)
            if not d.get("audio"):
                missing.append(line["slug"])
                continue
            file = _fetch_asset(creds, str(d["audio"]), out / "audio" / line["slug"], "mp3")
            spoken.append({"id": line["slug"], "audio": str(file.relative_to(out)), "text": d.get("caption") or d.get("text") or "", "speaker": d.get("speaker")})
        if not spoken:
            continue
        shot: dict = {"id": f"b{number}", "lines": spoken}
        if data(beat).get("still"):
            still = _fetch_asset(creds, str(data(beat)["still"]), out / "stills" / f"b{number}", "png")
            shot["still"] = str(still.relative_to(out))
        shots.append(shot)
    if not shots:
        raise PullError(f"“{story}” has no recorded lines yet: record some with the storyworld-record-lines workflow")
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({"title": story_row.get("title") or story, "shots": shots}, indent=2, ensure_ascii=False))
    return {"manifest": str(out / "manifest.json"), "shots": len(shots), "lines": sum(len(s["lines"]) for s in shots), "not_recorded": missing}
