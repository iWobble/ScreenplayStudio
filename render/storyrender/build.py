"""Assemble: a still per shot moved by its focal path, the shots' audio mixed on one timeline, captions burned in, one mp4 out.

Per shot a silent clip (zoompan over the still, eased); one narration wav per shot (lines and sound effects delayed into
place, padded to the shot's length), joined without re-encoding so there are no seams; then a single final encode that burns
the captions, adds the music bed under everything, normalises loudness and muxes. ffmpeg runs in a temp folder so the
caption file needs no path escaping.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import captions, ffmpeg
from .manifest import MAX_SHORT_SECONDS, Ambience, Manifest, Move, PlannedShot, Timeline, plan

SUPERSAMPLE = 2  # zoompan on a larger picture moves smoothly instead of in whole-pixel steps
SAMPLE_RATE = 48000


def zoompan_filter(planned: PlannedShot, size: tuple[int, int], fps: int) -> str:
    """cover-fit the still to the frame, then ease the camera from the shot's first position to its second."""
    width, height = size
    frames = max(2, round(planned.duration * fps))
    a, b = planned.shot.move_from, planned.shot.move_to
    p = f"(0.5-0.5*cos(PI*on/{frames - 1}))"  # eased 0 → 1 over the shot

    def mix(x: float, y: float) -> str:
        return f"({x}+({y}-{x})*{p})"

    zoom = mix(a.zoom, b.zoom)
    cx, cy = mix(a.x, b.x), mix(a.y, b.y)
    x = f"max(0,min(iw-iw/({zoom}),{cx}*iw-iw/(2*{zoom})))"
    y = f"max(0,min(ih-ih/({zoom}),{cy}*ih-ih/(2*{zoom})))"
    big = (width * SUPERSAMPLE, height * SUPERSAMPLE)
    return (
        f"scale={big[0]}:{big[1]}:force_original_aspect_ratio=increase,crop={big[0]}:{big[1]},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},format=yuv420p"
    )


def _clip(planned: PlannedShot, size, fps, out: Path, *, draft: bool) -> None:
    ffmpeg.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-t", f"{planned.duration:.3f}",
            "-i", str(planned.shot.still), "-vf", zoompan_filter(planned, size, fps), "-frames:v", str(max(2, round(planned.duration * fps))),
            "-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast", "-crf", "20" if draft else "12", "-an", str(out),
        ]
    )  # fmt: skip


def _cut(line) -> str:
    """The filter that takes a line out of a longer take (empty when it is the whole file)."""
    if not line.start and line.end is None:
        return ""
    end = f":end={line.end:.4f}" if line.end is not None else ""
    return f"atrim=start={line.start:.4f}{end},asetpts=PTS-STARTPTS,"


def fades(length: float, fade_in: float = 0.0, fade_out: float = 0.0) -> str:
    """ffmpeg filters (with a trailing comma, or nothing) that fade a sound in over `fade_in` seconds and out over `fade_out`, each held to at most
    half the sound so the two never overlap. A sound with no fades gets none."""
    half = max(length, 0.0) / 2
    parts = []
    if fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={min(fade_in, half):.3f}")
    if fade_out > 0:
        d = min(fade_out, half)
        parts.append(f"afade=t=out:st={max(length, 0.0) - d:.3f}:d={d:.3f}")
    return ",".join(parts) + "," if parts else ""


def _narration(planned: PlannedShot, out: Path) -> None:
    """One wav, exactly the shot's length: its lines and sound effects delayed into place."""
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    pieces = [(p.line.audio, p.start - planned.start, 1.0, _cut(p.line), "") for p in planned.lines if p.line.audio] + [
        (fx.audio, fx.at, fx.volume, "", fades(fx.duration, fx.fade_in, fx.fade_out)) for fx in planned.shot.sfx
    ]
    for n, (file, at, volume, cut, fade) in enumerate(pieces):
        inputs += ["-i", str(file)]
        chains.append(
            f"[{n}:a]{cut}aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,{fade}adelay={round(max(at, 0) * 1000)}:all=1,volume={volume}[a{n}]"
        )
        labels.append(f"[a{n}]")
    if not pieces:
        ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", f"{planned.duration:.3f}", str(out)])
        return
    mix = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,apad,atrim=0:{planned.duration:.3f}[out]"
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join([*chains, mix]), "-map", "[out]", "-ar", str(SAMPLE_RATE), str(out)])


MUFFLE_HZ = 700  # heard through a wall: the highs go, the low wash of the sea stays
BED_FADE = 0.6  # seconds a bed fades in or out where the place changes (neighbouring beds overlap by half of it: a crossfade)


@dataclass
class Bed:
    """One continuous run of an ambience under consecutive shots, with the level each shot asks for."""

    ambience: Ambience
    start: float
    end: float
    levels: list[tuple[float, float, float]] = field(default_factory=list)  # (from, to, volume) in timeline seconds


def beds(timeline: Timeline) -> list[Bed]:
    """Group consecutive shots that share an ambience (same sound, same muffling) into one bed each. The level can change shot to shot
    inside a bed (the cabin goes quiet for the letters) without the sound restarting."""
    runs: list[Bed] = []
    for planned in timeline.shots:
        amb = planned.shot.ambience
        if amb is None:
            continue
        key = (amb.audio, amb.muffled)
        last = runs[-1] if runs else None
        if last is not None and (last.ambience.audio, last.ambience.muffled) == key and abs(last.end - planned.start) < 1e-6:
            last.end = planned.start + planned.duration
            last.levels.append((planned.start, last.end, amb.volume))
        else:
            runs.append(Bed(amb, planned.start, planned.start + planned.duration, [(planned.start, planned.start + planned.duration, amb.volume)]))
    return runs


def _level(bed: Bed) -> str:
    """The bed's volume over time as one ffmpeg expression (a step per shot), in the bed's own clock."""
    expr = f"{bed.levels[-1][2]:.4f}"
    for begin, end, volume in reversed(bed.levels[:-1]):
        expr = f"if(lt(t,{end - bed.start:.4f}),{volume:.4f},{expr})"
    return expr


def _mix_beds(narration: Path, runs: list[Bed], total: float, out: Path) -> None:
    """Lay each bed under the narration: looped to length, muffled if heard from inside, at the level each shot asks for, faded in and
    out so a change of place is a crossfade. The narration is the base: nothing here makes the cut longer."""
    inputs, chains, labels = [], [], []
    for n, bed in enumerate(runs, 1):
        begin, end = max(0.0, bed.start - BED_FADE / 2), min(total, bed.end + BED_FADE / 2)
        length = end - begin
        fade_in = min(bed.ambience.fade_in or BED_FADE, length / 2)  # the sound's own fades, else the crossfade
        fade_out = min(bed.ambience.fade_out or BED_FADE, length / 2)
        shifted = Bed(bed.ambience, begin, end, [(max(b, begin), e, v) for b, e, v in bed.levels])
        shifted.levels[0] = (begin, shifted.levels[0][1], shifted.levels[0][2])
        inputs += ["-stream_loop", "-1", "-i", str(bed.ambience.audio)]
        muffle = f",lowpass=f={MUFFLE_HZ}" if bed.ambience.muffled else ""
        chains.append(
            f"[{n}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo{muffle},atrim=0:{length:.3f},asetpts=PTS-STARTPTS,"
            f"volume='{_level(shifted)}':eval=frame,afade=t=in:st=0:d={fade_in:.3f},afade=t=out:st={length - fade_out:.3f}:d={fade_out:.3f},"
            f"adelay={round(begin * 1000)}:all=1[b{n}]"
        )
        labels.append(f"[b{n}]")
    mix = f"[0:a]{''.join(labels)}amix=inputs={len(labels) + 1}:normalize=0:duration=first[out]"
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(narration), *inputs, "-filter_complex", ";".join([*chains, mix]), "-map", "[out]", "-ar", str(SAMPLE_RATE), str(out)])


def _with_ambience(timeline: Timeline, narration: Path) -> Path:
    """The narration with its ambience beds under it (the same file when no shot has one)."""
    runs = beds(timeline)
    if not runs:
        return narration
    mixed = narration.with_name("narration-mixed.wav")
    _mix_beds(narration, runs, timeline.duration, mixed)
    return mixed


def _join(files: list[Path], out: Path, work: Path, *, kind: str) -> None:
    listing = work / f"{kind}.txt"
    listing.write_text("".join(f"file '{f}'\n" for f in files))
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])


def render(manifest: Manifest, out: Path, *, draft: bool = False, keep: Path | None = None) -> dict:
    """Render the manifest to `out`. Returns what was made: duration and the measured result."""
    timeline: Timeline = plan(manifest)
    size = (manifest.size[0] // 2, manifest.size[1] // 2) if draft else manifest.size
    fps = 24 if draft else manifest.fps
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="storyrender-") as tmp:
        work = Path(keep) if keep else Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        clips, wavs = [], []
        for i, planned in enumerate(timeline.shots):
            clip, wav = work / f"clip{i:03d}.mp4", work / f"narration{i:03d}.wav"
            _clip(planned, size, fps, clip, draft=draft)
            _narration(planned, wav)
            clips.append(clip)
            wavs.append(wav)
        _join(clips, work / "video.mp4", work, kind="video")
        _join(wavs, work / "narration.wav", work, kind="audio")
        mixed = _with_ambience(timeline, work / "narration.wav")
        if mixed != work / "narration.wav":
            mixed.replace(work / "narration.wav")  # the final encode reads narration.wav
        (work / "captions.ass").write_text(captions.ass(timeline, size, manifest.caption))
        _final(manifest, timeline, work, out, size, fps, draft=draft)
    result = ffmpeg.probe(out)
    seconds = float(result["format"]["duration"])
    return {
        "output": str(out),
        "planned_seconds": round(timeline.duration, 3),
        "measured_seconds": round(seconds, 3),
        "shots": len(timeline.shots),
        "captions": len(captions.cues(timeline)),
        "short_ok": seconds <= MAX_SHORT_SECONDS,
    }


def _final(manifest: Manifest, timeline: Timeline, work: Path, out: Path, size, fps, *, draft: bool) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", "video.mp4", "-i", "narration.wav"]
    audio = "[1:a]"
    chain: list[str] = []
    if manifest.music:
        cmd += ["-stream_loop", "-1", "-i", manifest.music["audio"]]
        fade_out = float(manifest.music.get("fade_out") or 2.0)  # a bed fades out at the end, by default over the last 2 s
        fade_in = float(manifest.music.get("fade_in") or 0)
        fade_at = max(0.0, timeline.duration - fade_out)
        rise = f"afade=t=in:st=0:d={min(fade_in, timeline.duration / 2):.3f}," if fade_in > 0 else ""
        chain.append(
            f"[2:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,volume={manifest.music['volume']},{rise}afade=t=out:st={fade_at:.3f}:d={fade_out:g},atrim=0:{timeline.duration:.3f}[bed]"
        )
        chain.append("[1:a][bed]amix=inputs=2:normalize=0:duration=first[mix]")
        audio = "[mix]"
    if manifest.loudnorm:
        chain.append(f"{audio}loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        audio = "[aout]"
    cmd += ["-filter_complex", ";".join(chain)] if chain else []
    cmd += [
        "-vf", "subtitles=captions.ass", "-map", "0:v", "-map", audio if chain else "1:a",
        "-c:v", "libx264", "-preset", "ultrafast" if draft else "medium", "-crf", "28" if draft else "18", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-t", f"{timeline.duration:.3f}", "-movflags", "+faststart",
        "-metadata", f"title={manifest.title}", str(out.resolve()),
    ]  # fmt: skip
    ffmpeg.run(cmd, cwd=work)





def listen(manifest: Manifest, out: Path, *, keep: Path | None = None) -> dict:
    """Stitch the story's sound alone into one mp3, with the same timing a render would have, and say where each line sits.
    Returns the length and the `timeline`: every shot and line with its start and end in seconds, so "at 0:41 it needs to
    say something else" can be turned into the line to change."""
    timeline: Timeline = plan(manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="storyrender-") as tmp:
        work = Path(keep) if keep else Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        wavs = []
        for i, planned in enumerate(timeline.shots):
            wav = work / f"narration{i:03d}.wav"
            _narration(planned, wav)
            wavs.append(wav)
        _join(wavs, work / "narration.wav", work, kind="audio")
        heard = _with_ambience(timeline, work / "narration.wav")
        ffmpeg.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(heard), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-q:a", "2", str(out)]
        )
    return {
        "output": str(out),
        "seconds": round(float(ffmpeg.probe(out)["format"]["duration"]), 3),
        "ambience": [
            {"id": b.ambience.ref, "start": round(b.start, 3), "end": round(b.end, 3), "muffled": b.ambience.muffled, "levels": [[round(x, 3), round(y, 3), v] for x, y, v in b.levels]}
            for b in beds(timeline)
        ],
        "timeline": [
            {
                "shot": planned.shot.id,
                "start": round(planned.start, 3),
                "sounds": [
                    {"id": fx.ref, "start": round(planned.start + fx.at, 3), "end": round(planned.start + fx.at + fx.duration, 3), "volume": fx.volume}
                    for fx in planned.shot.sfx
                ],
                "lines": [
                    {
                        "id": p.line.ref,
                        "speaker": p.line.speaker,
                        "text": p.line.text,
                        "start": round(p.start, 3),
                        "end": round(p.start + p.line.duration, 3),
                    }
                    for p in planned.lines
                ],
            }
            for planned in timeline.shots
            if planned.lines or planned.shot.sfx
        ],
    }


def timecode(seconds: float) -> str:
    """m:ss.s, as a player shows it, so a note like "at 0:41" matches the timeline."""
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"
