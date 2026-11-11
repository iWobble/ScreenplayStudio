"""storyrender — `pull`, `listen`, `render`, `plan`, `demo`, `youtube`."""

import argparse
import json
import sys
from pathlib import Path

from . import build, demo, ffmpeg, manifest, marvin_pull, youtube


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


def cmd_listen(a) -> int:
    m = manifest.load(Path(a.manifest), probe=ffmpeg.duration, need_stills=False)
    out = Path(a.output) if a.output else Path(a.manifest).with_name("rough-cut.mp3")
    result = build.listen(m, out, keep=Path(a.keep) if a.keep else None)
    (out.with_suffix(".timeline.json")).write_text(json.dumps(result["timeline"], indent=2, ensure_ascii=False))
    print(f"{out}  ({build.timecode(result['seconds'])})\n")
    for shot in result["timeline"]:
        for fx in shot.get("sounds", []):
            print(f"{build.timecode(fx['start'])}  {shot['shot']:<5} {'(sound)':<9} until {build.timecode(fx['end'])}   [{fx['id'] or ''}]")
        for line in shot["lines"]:
            who = (line["speaker"] or "").ljust(9)
            print(f"{build.timecode(line['start'])}  {shot['shot']:<5} {who} {line['text'][:60]}   [{line['id'] or ''}]")
    return 0


def cmd_pull(a) -> int:
    result = marvin_pull.pull(a.story, Path(a.out))
    print(json.dumps(result, indent=2))
    if result["not_recorded"]:
        print(f"note: {len(result['not_recorded'])} lines have no recording yet and are left out", file=sys.stderr)
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
    pl = sub.add_parser("pull", help="Marvin story → manifest.json + the recorded takes (reads with the CLI's token; changes nothing in Marvin)")
    pl.add_argument("story", help="the story entry's slug, e.g. the-last-onion")
    pl.add_argument("--out", required=True)
    pl.set_defaults(fn=cmd_pull)
    li = sub.add_parser("listen", help="manifest → one rough-cut mp3 of the sound alone, and a timeline naming each line")
    li.add_argument("manifest")
    li.add_argument("-o", "--output")
    li.add_argument("--keep", help="keep the intermediate files in this folder")
    li.set_defaults(fn=cmd_listen)
    s = sub.add_parser("plan", help="print the timeline a manifest implies (measures audio, renders nothing)")
    s.add_argument("manifest")
    s.set_defaults(fn=cmd_plan)
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
    except (manifest.ManifestError, ffmpeg.FfmpegError, youtube.YouTubeError, marvin_pull.PullError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
