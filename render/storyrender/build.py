"""Assemble: a still per shot moved by its focal path, the shots' audio mixed on one timeline, captions burned in, one mp4 out.

Per shot a silent clip (zoompan over the still, eased); one narration wav per shot (lines and sound effects delayed into
place, padded to the shot's length), joined without re-encoding so there are no seams; then a single final encode that burns
the captions, adds the music bed under everything, normalises loudness and muxes. ffmpeg runs in a temp folder so the
caption file needs no path escaping.
"""

import functools
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import captions, ffmpeg
from .manifest import MAX_SHORT_SECONDS, Ambience, Manifest, Move, Overlay, PlannedShot, Timeline, plan

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


BLEND_FILTERS = {"screen": "screen", "multiply": "multiply", "overlay": "overlay", "lighten": "lighten", "addition": "addition"}


def overlay_filter(overlay: Overlay, size: tuple[int, int], fps: int) -> str:
    """The filter graph part that lays the overlay video ([1:v]) over the still's clip ([base]) and leaves the result as [v]. The overlay is
    cover-fitted to the frame. `normal` keeps its own transparency (and fades it by `opacity`); the other blends need no alpha at all."""
    width, height = size
    prepared = f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}"
    if overlay.blend == "normal":
        fade = f",colorchannelmixer=aa={overlay.opacity:.3f}" if overlay.opacity < 1 else ""
        return f"{prepared},format=rgba{fade}[ov];[base]format=rgba[b];[b][ov]overlay=shortest=1:format=auto,format=yuv420p[v]"
    mode = BLEND_FILTERS[overlay.blend]
    return f"{prepared},format=gbrp[ov];[base]format=gbrp[b];[b][ov]blend=all_mode={mode}:all_opacity={overlay.opacity:.3f}:shortest=1,format=yuv420p[v]"


@functools.lru_cache(maxsize=None)
def _has_decoder(name: str) -> bool:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in done.stdout.splitlines())


def _overlay_input(overlay: Overlay) -> list[str]:
    """Input arguments for the overlay: looped without end (the clip's length decides), and a WebM read with the VP9 decoder that keeps its
    transparency (ffmpeg's built-in one drops it)."""
    keep_alpha = ["-c:v", "libvpx-vp9"] if overlay.video.suffix.lower() == ".webm" and _has_decoder("libvpx-vp9") else []
    return ["-stream_loop", "-1", *keep_alpha, "-i", str(overlay.video)]


def clip_frames(planned: PlannedShot, fps: int) -> int:
    """How many frames a shot's clip has: what the clip, its trims and its transitions are all counted in, so a film's length never drifts."""
    return max(2, round(planned.duration * fps))


@dataclass
class Edges:
    """What a shot's two ends do, in frames: `dip_in` / `dip_out` frames of fade from and to black inside the clip; `blend_in` / `blend_out` frames
    that a dissolve takes from this shot's two ends (the dissolve itself is a short segment of its own, see `_dissolve`)."""

    dip_in: int = 0
    dip_out: int = 0
    blend_in: int = 0
    blend_out: int = 0


def edges_of(timeline: Timeline, fps: int) -> list[Edges]:
    """Per shot, the effect of the transitions around it. A transition is *into* a shot, from the one before, so the first shot's is ignored, and
    one never takes more than half of either shot. Cuts do nothing; a fade splits its time over the two shots; a dissolve takes half from each."""
    shots = timeline.shots
    edges = [Edges() for _ in shots]
    for k in range(1, len(shots)):
        shot = shots[k].shot
        if shot.transition == "cut" or shot.transition_seconds <= 0:
            continue
        half = round(shot.transition_seconds * fps / 2)
        half = min(half, (clip_frames(shots[k - 1], fps) - 1) // 2, (clip_frames(shots[k], fps) - 1) // 2)  # both sides of a shot may take at most all but one of its frames
        if half < 1:
            continue
        if shot.transition == "fade":
            edges[k - 1].dip_out, edges[k].dip_in = half, half
        else:
            edges[k - 1].blend_out, edges[k].blend_in = half, half
    return edges


def _dips(edge: Edges, frames: int, fps: int) -> str:
    """The fade filters for a clip whose ends dip to black, or nothing."""
    parts = []
    if edge.dip_in:
        parts.append(f"fade=t=in:st=0:d={edge.dip_in / fps:.4f}")
    if edge.dip_out:
        parts.append(f"fade=t=out:st={(frames - edge.dip_out) / fps:.4f}:d={edge.dip_out / fps:.4f}")
    return ",".join(parts)


def _clip(planned: PlannedShot, size, fps, out: Path, *, draft: bool, edge: Edges | None = None) -> None:
    frames = str(max(2, round(planned.duration * fps)))
    dips = _dips(edge, int(frames), fps) if edge else ""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-t", f"{planned.duration:.3f}", "-i", str(planned.shot.still)]
    if planned.shot.overlay is not None:
        cmd += _overlay_input(planned.shot.overlay)
        graph = f"[0:v]{zoompan_filter(planned, size, fps)}[base];{overlay_filter(planned.shot.overlay, size, fps)}"
        if dips:
            graph += f";[v]{dips}[vd]"
        cmd += ["-filter_complex", graph, "-map", "[vd]" if dips else "[v]"]
    else:
        cmd += ["-vf", zoompan_filter(planned, size, fps) + (f",{dips}" if dips else "")]
    cmd += ["-frames:v", frames, "-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast", "-crf", "20" if draft else "12", "-an", str(out)]
    ffmpeg.run(cmd)


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


def _mix_beds(narration: Path, runs: list[Bed], total: float, out: Path, end_fade: float | None = None, start_fade: float | None = None) -> None:
    """Lay each bed under the narration: looped to length, muffled if heard from inside, at the level each shot asks for, faded in and
    out so a change of place is a crossfade. The narration is the base: nothing here makes the cut longer."""
    inputs, chains, labels = [], [], []
    for n, bed in enumerate(runs, 1):
        begin, end = max(0.0, bed.start - BED_FADE / 2), min(total, bed.end + BED_FADE / 2)
        length = end - begin
        fade_in = min(bed.ambience.fade_in or BED_FADE, length / 2)  # the sound's own fades, else the crossfade
        if start_fade and bed.start <= 1e-6 and not bed.ambience.fade_in_set:  # the bed that starts the film fades in over the story's setting, unless more specific
            fade_in = min(start_fade, length / 2)
        fade_out = min(bed.ambience.fade_out or BED_FADE, length / 2)
        if end_fade and bed.end >= total - 1e-6 and not bed.ambience.fade_out_set:  # the bed that runs to the end of the film fades out over the story's setting, unless the story's ambience or the beat set its own
            fade_out = min(end_fade, length / 2)
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


def _with_ambience(timeline: Timeline, narration: Path, end_fade: float | None = None, story_bed: Ambience | None = None, start_fade: float | None = None) -> Path:
    """The narration with its ambience beds under it (the same file when there are none). The story's own bed runs under the whole film and
    plays together with the beds of the beats and scenes, which layer over it."""
    runs = beds(timeline)
    if story_bed is not None and timeline.duration > 0:
        runs.insert(0, Bed(story_bed, 0.0, timeline.duration, [(0.0, timeline.duration, story_bed.volume)]))
    if not runs:
        return narration
    mixed = narration.with_name("narration-mixed.wav")
    _mix_beds(narration, runs, timeline.duration, mixed, end_fade, start_fade)
    return mixed


def _encode(draft: bool) -> list[str]:
    return ["-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast", "-crf", "20" if draft else "12", "-pix_fmt", "yuv420p", "-an"]


def _dissolve(before: Path, after: Path, before_frames: int, half: int, fps: int, out: Path, *, draft: bool) -> None:
    """The cross-fade at a boundary, `2 × half` frames long: the last `half` frames of the shot before, held on its last frame for `half` more, mixed
    into the first `half` frames of the shot after, preceded by `half` held on its first. It stands in for exactly those frames, so the film is no
    longer or shorter. (A camera move eases to rest at both ends, so holding an end frame does not show.)"""
    d = 2 * half / fps
    graph = (
        # fps= on both: xfade stops at an input whose frame rate is unknown ("rate of 1/0"), which a trimmed and padded stream can end up with.
        f"[0:v]trim=start_frame={before_frames - half},setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop={half + 1},fps={fps}[a];"  # one frame over: xfade drops its last
        f"[1:v]trim=end_frame={half},setpts=PTS-STARTPTS,fps={fps},tpad=start_mode=clone:start={half}:stop_mode=clone:stop=1,fps={fps}[b];"
        f"[a][b]xfade=transition=fade:duration={d:.4f}:offset=0,fps={fps}[v]"
    )
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(before), "-i", str(after), "-filter_complex", graph, "-map", "[v]", "-frames:v", str(2 * half), *_encode(draft), str(out)])


def _body(clip: Path, frames: int, edge: Edges, out: Path, *, draft: bool) -> Path:
    """A clip without the frames its dissolves took from its two ends (the clip itself when it lost none)."""
    if not (edge.blend_in or edge.blend_out):
        return clip
    keep = f"trim=start_frame={edge.blend_in}:end_frame={frames - edge.blend_out},setpts=PTS-STARTPTS"
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-vf", keep, "-frames:v", str(frames - edge.blend_in - edge.blend_out), *_encode(draft), str(out)])
    return out


def _video_parts(clips: list[Path], timeline: Timeline, edges: list[Edges], work: Path, fps: int, *, draft: bool) -> list[Path]:
    """The clips to join: as they are for cuts and dips, and with the dissolves cut in where there are any (their bodies, and a short segment of
    cross-fade between each pair)."""
    if not any(e.blend_in or e.blend_out for e in edges):
        return clips
    parts: list[Path] = []
    for i, clip in enumerate(clips):
        frames = clip_frames(timeline.shots[i], fps)
        if i > 0 and edges[i].blend_in:
            seg = work / f"dissolve{i:03d}.mp4"
            _dissolve(clips[i - 1], clip, clip_frames(timeline.shots[i - 1], fps), edges[i].blend_in, fps, seg, draft=draft)
            parts.append(seg)
        parts.append(_body(clip, frames, edges[i], work / f"body{i:03d}.mp4", draft=draft))
    return parts


def _join(files: list[Path], out: Path, work: Path, *, kind: str) -> None:
    listing = work / f"{kind}.txt"
    listing.write_text("".join(f"file '{f}'\n" for f in files))
    ffmpeg.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])


def render(manifest: Manifest, out: Path, *, draft: bool = False, keep: Path | None = None) -> dict:
    """Render the manifest to `out`. Returns what was made: duration and the measured result."""
    timeline: Timeline = plan(manifest)
    size = (manifest.size[0] // 2 // 2 * 2, manifest.size[1] // 2 // 2 * 2) if draft else manifest.size  # half, and even: the encoder takes no odd side (4:5's 1350 halves to 675)
    fps = 24 if draft else manifest.fps
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="storyrender-") as tmp:
        work = Path(keep) if keep else Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        clips, wavs = [], []
        edges = edges_of(timeline, fps)  # how the transitions treat each shot's ends (all cuts: nothing)
        for i, planned in enumerate(timeline.shots):
            clip, wav = work / f"clip{i:03d}.mp4", work / f"narration{i:03d}.wav"
            _clip(planned, size, fps, clip, draft=draft, edge=edges[i])
            _narration(planned, wav)
            clips.append(clip)
            wavs.append(wav)
        _join(_video_parts(clips, timeline, edges, work, fps, draft=draft), work / "video.mp4", work, kind="video")
        _join(wavs, work / "narration.wav", work, kind="audio")
        mixed = _with_ambience(timeline, work / "narration.wav", manifest.end_fade, manifest.ambience, manifest.start_fade)
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


MUSIC_RAMP = 0.5  # seconds a change of the music's level takes, so it eases rather than clicks
DUCK_DEPTH = {"light": 0.35, "strong": 0.12}  # the music's gain while someone speaks: about -9 dB and -18 dB, however loud the voice is
DUCK_ATTACK = 0.2  # seconds the music takes to go down, finished as the line starts
DUCK_RELEASE = 0.5  # and to come back after the line ends


def speech_windows(timeline: Timeline) -> list[tuple[float, float]]:
    """When someone is speaking, as (start, end) seconds on the film: each line's span, with lines closer than one attack plus one release
    joined, so the music does not pump up in a short pause between two lines and the ramps never overlap."""
    spans = sorted((pl.start, pl.start + pl.line.duration) for p in timeline.shots for pl in p.lines if pl.line.duration > 0)
    joined: list[tuple[float, float]] = []
    for begin, end in spans:
        if joined and begin - joined[-1][1] < DUCK_ATTACK + DUCK_RELEASE:
            joined[-1] = (joined[-1][0], max(joined[-1][1], end))
        else:
            joined.append((begin, end))
    return joined


def duck_gain(windows: list[tuple[float, float]], depth: float) -> str | None:
    """The music's gain over the film as one ffmpeg expression: 1, falling to `depth` over each speech window and back after it. None when
    nobody speaks. The windows do not overlap (speech_windows), so the ramps simply add."""
    if not windows:
        return None
    ramps = "+".join(
        f"min(clip((t-{begin - DUCK_ATTACK:.3f})/{DUCK_ATTACK},0,1),clip(({end + DUCK_RELEASE:.3f}-t)/{DUCK_RELEASE},0,1))" for begin, end in windows
    )
    return f"1-{1 - depth:.3f}*({ramps})"


def music_level(timeline: Timeline, base: float, ramp: float = MUSIC_RAMP) -> str | None:
    """The music's volume over the film as one ffmpeg expression, or None when no shot asks for a level of its own. A shot's `music_volume`
    replaces the story's level while it plays (0 = silence); the level eases between shots over `ramp` seconds, centred on the cut, and a ramp
    never outlasts the shorter shot beside it."""
    spans = [(p.start, p.start + p.duration, p.shot.music_volume if p.shot.music_volume is not None else base) for p in timeline.shots]
    runs: list[tuple[float, float, float]] = []
    for begin, end, level in spans:  # neighbours at the same level are one run
        if runs and abs(runs[-1][2] - level) < 1e-9:
            runs[-1] = (runs[-1][0], end, level)
        else:
            runs.append((begin, end, level))
    if len(runs) == 1 and abs(runs[0][2] - base) < 1e-9:
        return None
    expr = f"{runs[0][2]:.4f}"
    for before, after in zip(runs, runs[1:], strict=False):
        r = max(0.05, min(ramp, before[1] - before[0], after[1] - after[0]))
        expr += f"+({after[2] - before[2]:.4f})*clip((t-{after[0] - r / 2:.4f})/{r:.4f},0,1)"
    return expr


def _final(manifest: Manifest, timeline: Timeline, work: Path, out: Path, size, fps, *, draft: bool) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", "video.mp4", "-i", "narration.wav"]
    audio = "[1:a]"
    chain: list[str] = []
    if manifest.music:
        cmd += ["-stream_loop", "-1", "-i", manifest.music["audio"]]
        fade_out = float(manifest.end_fade or manifest.music.get("fade_out") or 2.0)  # the music fades out at the end: the story's setting, else the sound's, else 2 s
        fade_in = float(manifest.start_fade or manifest.music.get("fade_in") or 0)  # the story's setting, else the sound's own, else none
        fade_at = max(0.0, timeline.duration - fade_out)
        rise = f"afade=t=in:st=0:d={min(fade_in, timeline.duration / 2):.3f}," if fade_in > 0 else ""
        level = music_level(timeline, float(manifest.music["volume"]))
        depth = DUCK_DEPTH.get(str(manifest.music.get("duck") or ""))
        duck = duck_gain(speech_windows(timeline), depth) if depth else None
        if level or duck:  # the level the beats ask for, times the dip under speech
            volume = f"volume='({level or manifest.music['volume']})*({duck or 1})':eval=frame"
        else:
            volume = f"volume={manifest.music['volume']}"
        chain.append(
            f"[2:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,{volume},{rise}afade=t=out:st={fade_at:.3f}:d={fade_out:g},atrim=0:{timeline.duration:.3f}[bed]"
        )
        chain.append("[1:a][bed]amix=inputs=2:normalize=0:duration=first[mix]")
        audio = "[mix]"
    if manifest.loudnorm:
        chain.append(f"{audio}loudnorm=I={manifest.loudness:g}:TP=-1.5:LRA=11[aout]")
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
        heard = _with_ambience(timeline, work / "narration.wav", manifest.end_fade, manifest.ambience, manifest.start_fade)
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
