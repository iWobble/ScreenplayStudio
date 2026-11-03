# storyrender

Assembles a Storyworld story into a vertical narrated video with ffmpeg (no Python dependencies). It is the "renderer" the
Marvin workspace hands to: Marvin keeps the story, cast, lines and approvals; this does the binary work.

```
python3 -m storyrender demo /tmp/demo                     # 3 placeholder beats (stills + tones) to try it
python3 -m storyrender plan /tmp/demo/manifest.json       # the timeline the audio implies; renders nothing
python3 -m storyrender render /tmp/demo/manifest.json -o out.mp4   # 1080x1920 H.264 + AAC, captions burned in
python3 -m storyrender render m.json --draft              # half size, fast: check timing before the real render
python3 -m storyrender from-beats stories/the-last-onion/beat-sheet.md --out build/onion --title "The Last Onion"
uvx --from pytest pytest                                  # tests (real ffmpeg renders included)
```

## Manifest

See `storyrender/manifest.py`. Per shot: a `still`, a camera `move` (`from` / `to`, each `{x, y, zoom}`: the centre as 0–1 of the
picture and a zoom of 1 or more), `lines` (`audio` file, `text`, optional `words` timings for captions, `speaker`),
optional `sfx` (`audio`, `at`, `volume`) and a `hold`. A shot lasts `max(hold, lead 0.3 s + lines + 0.25 s gaps + 0.35 s tail)`:
**measured audio decides**, as the edit plan says. A line with no audio and a `duration` is silence (not captioned). `music` is a
bed under everything (`audio`, `volume`, faded out over the last 2 s); the result is normalised to -16 LUFS.

`from-beats` reads a beat-sheet table and writes `manifest.skeleton.json` (stills and line files named by convention:
`stills/b04.png`, `audio/b04-1.mp3`), `lines.json` (the spoken lines to record, in order: the Last Onion has 24 beats and 27 lines;
`Sound:` cues are not speech; each line carries its `characters`, and the command prints the total, which is what recording the script spends) and `beats.json`.

## Captions

Chunks of up to 4 words / 26 characters, broken at punctuation, timed to the word timings ElevenLabs returns (or spread over the
line by length without them). Placed above the bottom 20% so the Shorts interface doesn't cover them.

## Publishing

`python3 -m storyrender youtube check` / `youtube upload video.mp4 --title …` (`storyrender/youtube.py`). **Private only**: the module
refuses anything else; publish from YouTube Studio after watching. Needs `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
`YOUTUBE_REFRESH_TOKEN` in the environment (a Desktop OAuth client, scope `youtube.upload`; a service account can't upload).
Not run against real YouTube yet: it is tested against a fake Google.

Quota (checked against Google's docs 2026-11-03): `videos.insert` has its own bucket, 100 calls a day by default, 1 unit each.
Still unverified: whether a project that hasn't passed Google's API audit has its uploads locked to private. The first real upload
will show it (the module only uploads private, so this costs nothing to find out).
