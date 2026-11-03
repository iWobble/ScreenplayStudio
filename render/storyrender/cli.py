"""storyrender — `render`, `plan`, `from-beats`, `demo`, `youtube`."""

import argparse
import json
import sys
from pathlib import Path

from . import beats, build, demo, ffmpeg, manifest, youtube


def _load(path: str) -> manifest.Manifest:
    return manifest.load(Path(path), probe=ffmpeg.duration)


def cmd_render(a) -> int:
    m = _load(a.manifest)
    out = Path(a.output) if a.output else Path(a.manifest).with_suffix(".mp4")
    result = build.render(m, out, draft=a.draft, keep=Path(a.keep) if a.keep else None)
    print(json.dumps(result, indent=2))
    if not result["short_ok"]:
        print(f"warning: {result['measured_seconds']}s is over the {manifest.MAX_SHORT_SECONDS}s a Short may run", file=sys.stderr)
    return 0


def cmd_plan(a) -> int:
    m = _load(a.manifest)
    t = manifest.plan(m)
    print(
        json.dumps(
            {
                "seconds": round(t.duration, 3),
                "shots": [
                    {"id": s.shot.id, "start": round(s.start, 3), "seconds": round(s.duration, 3), "lines": [round(p.start, 3) for p in s.lines]}
                    for s in t.shots
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_from_beats(a) -> int:
    rows = beats.load(Path(a.beat_sheet))
    if not rows:
        print("no shot rows found in that beat sheet", file=sys.stderr)
        return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.skeleton.json").write_text(json.dumps(beats.skeleton_manifest(rows, a.title, ext=a.ext), indent=2, ensure_ascii=False))
    (out / "lines.json").write_text(json.dumps(beats.speech_lines(rows), indent=2, ensure_ascii=False))
    (out / "beats.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    lines = beats.speech_lines(rows)
    chars = sum(ln["characters"] for ln in lines)
    print(f"{len(rows)} beats, {len(lines)} lines, {chars} characters to record → {out}/ (manifest.skeleton.json, lines.json, beats.json)")
    return 0


def cmd_demo(a) -> int:
    path = demo.make(Path(a.folder))
    print(path)
    return 0


def cmd_youtube(a) -> int:
    creds = youtube.credentials()
    if a.action == "check":
        print(json.dumps(youtube.check(creds), indent=2))
        return 0
    meta = youtube.metadata(a.title, a.description, a.tag or [])
    print(json.dumps(youtube.upload(Path(a.video), meta, creds), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="storyrender", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="manifest → mp4")
    r.add_argument("manifest")
    r.add_argument("-o", "--output")
    r.add_argument("--draft", action="store_true", help="half size, fast encode, to check timing")
    r.add_argument("--keep", help="keep the intermediate files in this folder")
    r.set_defaults(fn=cmd_render)
    s = sub.add_parser("plan", help="print the timeline a manifest implies (measures audio, renders nothing)")
    s.add_argument("manifest")
    s.set_defaults(fn=cmd_plan)
    b = sub.add_parser("from-beats", help="beat sheet → skeleton manifest + the lines to record")
    b.add_argument("beat_sheet")
    b.add_argument("--out", required=True)
    b.add_argument("--title", default="Untitled")
    b.add_argument("--ext", default="mp3", help="extension the recorded lines will have")
    b.set_defaults(fn=cmd_from_beats)
    d = sub.add_parser("demo", help="make a 3-beat placeholder project (stills + tones) to test the pipeline")
    d.add_argument("folder")
    d.set_defaults(fn=cmd_demo)
    y = sub.add_parser("youtube", help="try the credentials (check) or upload a PRIVATE video (upload); needs YOUTUBE_* in the environment")
    y.add_argument("action", choices=["check", "upload"])
    y.add_argument("video", nargs="?")
    y.add_argument("--title", default="")
    y.add_argument("--description", default="")
    y.add_argument("--tag", action="append")
    y.set_defaults(fn=cmd_youtube)
    args = p.parse_args(argv)
    if args.cmd == "youtube" and args.action == "upload" and not (args.video and args.title):
        p.error("youtube upload needs a video file and --title")
    try:
        return args.fn(args)
    except (manifest.ManifestError, ffmpeg.FfmpegError, youtube.YouTubeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
