"""A beat's own ambience is laid over its scene's: the scene's bed (the tavern) runs on under every beat of the scene without a seam, and the
beat's sound (a cheer) is a second bed over it for that beat. A manifest with only `ambience` per shot mixes exactly as it always did."""

import json
from pathlib import Path

import pytest

from storyrender import build, demo, ffmpeg, manifest, marvin_pull, script
from storyrender.manifest import Ambience, Shot
from tests.test_overlay_music import (
    DATA,
    _bed_db,
    _shot,
    _sounds,
    _timeline,
    _tone,
    needs_ffmpeg,
)

TAVERN, CHEER = Path("/x/tavern.mp3"), Path("/x/cheer.mp3")


def _graph(monkeypatch, timeline, **kw) -> list[str]:
    ran = []
    monkeypatch.setattr(build.ffmpeg, "run", lambda cmd, *a, **k: ran.append(cmd))
    build._with_ambience(timeline, Path("/x/narration.wav"), **kw)
    return ran[0] if ran else []


def _filters(cmd: list[str]) -> str:
    return cmd[cmd.index("-filter_complex") + 1]


# ── the beds over the film ─────────────────────────────────────────────────────
def test_a_beats_bed_is_laid_over_its_scenes_which_runs_on_unbroken_across_the_beats():
    tavern = Ambience(TAVERN, 0.5, ref="tavern")
    timeline = _timeline(_shot("a", 4, ambience=tavern), _shot("b", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.7, ref="cheer")), _shot("c", 4, ambience=tavern))
    scene, cheer = build.beds(timeline)
    assert (scene.ambience.ref, scene.start, scene.end, scene.over) == ("tavern", 0.0, 12.0, False)  # one run from the first beat to the last
    assert [v for _, _, v in scene.levels] == [0.5, 0.5, 0.5]  # at the scene's level in the cheering beat too
    assert (cheer.ambience.ref, cheer.start, cheer.end, cheer.over, cheer.levels) == ("cheer", 4.0, 8.0, True, [(4.0, 8.0, 0.7)])


def test_the_beats_bed_is_its_own_input_after_the_scenes_and_fades_in_and_out_around_the_beat(monkeypatch):
    tavern = Ambience(TAVERN, 0.5)
    cmd = _graph(monkeypatch, _timeline(_shot("a", 4, ambience=tavern), _shot("b", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.7)), _shot("c", 4, ambience=tavern)))
    assert cmd.count("/x/tavern.mp3") == 1 and cmd.index("/x/tavern.mp3") < cmd.index("/x/cheer.mp3")  # the tavern once, then the cheer
    graph = _filters(cmd)
    assert "atrim=0:12.000" in graph  # the tavern: the whole scene, to the end of the film, in one piece
    assert "[2:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:4.600" in graph and "adelay=3700:all=1[b2]" in graph  # the cheer: the beat and its crossfades
    assert "amix=inputs=3" in graph


def test_consecutive_beats_with_the_same_extra_sound_share_one_continuous_bed():
    tavern = Ambience(TAVERN, 0.5)
    timeline = _timeline(_shot("a", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.7)), _shot("b", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.3)), _shot("c", 4, ambience=tavern))
    runs = build.beds(timeline)
    assert [(r.over, r.start, r.end) for r in runs] == [(False, 0.0, 12.0), (True, 0.0, 8.0)]
    assert [v for _, _, v in runs[1].levels] == [0.7, 0.3]  # one bed, a quieter step for the second beat


def test_a_beats_bed_at_level_0_is_left_out_and_the_scenes_bed_plays_as_without_it(monkeypatch):
    tavern = Ambience(TAVERN, 0.5)
    silent = _timeline(_shot("a", 4, ambience=tavern), _shot("b", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.0)))
    plain = _timeline(_shot("a", 4, ambience=tavern), _shot("b", 4, ambience=tavern))
    assert [r.over for r in build.beds(silent)] == [False]
    assert _graph(monkeypatch, silent) == _graph(monkeypatch, plain)


def test_a_muffled_scene_bed_and_a_clear_beat_bed_each_keep_their_own_hearing(monkeypatch):
    tavern = Ambience(TAVERN, 0.5, muffled=True)
    graph = _filters(_graph(monkeypatch, _timeline(_shot("a", 4, ambience=tavern), _shot("b", 4, ambience=tavern, beat_ambience=Ambience(CHEER, 0.7)))))
    scene_chain, cheer_chain = graph.split(";")[:2]
    assert "lowpass=f=700" in scene_chain and "atrim=0:8.000" in scene_chain  # the storm through the wall, unbroken
    assert "lowpass" not in cheer_chain  # the cheer in the room, clear


def test_ducking_end_fade_and_the_story_bed_cover_the_beats_bed_too(monkeypatch):
    tavern = Ambience(TAVERN, 0.5)
    timeline = _timeline(_shot("a", 4, ambience=tavern), Shot("b", Path("b.png"), lines=[manifest.Line("x", None, 2.0)], ambience=tavern, beat_ambience=Ambience(CHEER, 0.7)))
    cmd = _graph(monkeypatch, timeline, story_bed=Ambience(Path("/x/wind.mp3"), 0.3), ambience_duck="strong", end_fade=3.0)
    chains = _filters(cmd).split(";")
    assert cmd.index("/x/wind.mp3") < cmd.index("/x/tavern.mp3") < cmd.index("/x/cheer.mp3")  # the story's, the scene's, the beat's
    cheer = next(c for c in chains if c.endswith("[b3]"))
    assert "*(1-0.880*" in cheer  # down under the line, as every bed is
    assert "afade=t=out" in cheer and ":d=" in cheer and "amix=inputs=4" in chains[-1]


def test_no_bed_anywhere_and_no_story_bed_leaves_the_narration_alone(monkeypatch):
    assert _graph(monkeypatch, _timeline(_shot("a", 4), _shot("b", 4))) == []  # nothing runs outside the scenes when the story names no bed


# ── a manifest from before: one `ambience` per shot ─────────────────────────────────────
def test_an_old_manifest_mixes_exactly_as_before(monkeypatch):
    sea = lambda **k: Ambience(Path("/x/sea.mp3"), **k)  # noqa: E731
    cmd = _graph(monkeypatch, _timeline(_shot("a", 4, ambience=sea(volume=0.5)), _shot("b", 4, ambience=sea(volume=0.3, muffled=True)), _shot("c", 4, ambience=sea(volume=0.1, muffled=True))))
    assert cmd == [  # the graph main made before beds could layer, word for word
        "ffmpeg", "-y", "-loglevel", "error", "-i", "/x/narration.wav", "-stream_loop", "-1", "-i", "/x/sea.mp3", "-stream_loop", "-1", "-i", "/x/sea.mp3", "-filter_complex",
        (
            "[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:4.300,asetpts=PTS-STARTPTS,volume='(0.5000)':eval=frame,afade=t=in:st=0:d=0.600,afade=t=out:st=3.700:d=0.600,adelay=0:all=1[b1];"
            "[2:a]aresample=48000,aformat=channel_layouts=stereo,lowpass=f=700,atrim=0:8.300,asetpts=PTS-STARTPTS,volume='(if(lt(t,4.3000),0.3000,0.1000))':eval=frame,afade=t=in:st=0:d=0.600,afade=t=out:st=7.700:d=0.600,adelay=3700:all=1[b2];"
            "[0:a][b1][b2]amix=inputs=3:normalize=0:duration=first[out]"
        ),
        "-map", "[out]", "-ar", "48000", "/x/narration-mixed.wav",
    ]  # fmt: skip


def test_the_manifest_reads_a_beats_bed_beside_its_scenes_and_an_old_one_has_none(tmp_path):
    (tmp_path / "b.png").write_bytes(b"x")
    for name in ("tavern.mp3", "cheer.mp3"):
        (tmp_path / name).write_bytes(b"x")
    shot = {"id": "b01", "still": "b.png", "hold": 2, "lines": [], "ambience": {"audio": "tavern.mp3", "id": "tavern"}}
    (tmp_path / "old.json").write_text(json.dumps({"shots": [shot]}))
    (tmp_path / "new.json").write_text(json.dumps({"shots": [{**shot, "beat_ambience": {"audio": "cheer.mp3", "id": "cheer", "volume": 0.7, "fade_in": 1.5, "fade_in_set": True}}]}))
    old = manifest.load(tmp_path / "old.json", probe=lambda _p: 1.0, need_stills=False).shots[0]
    new = manifest.load(tmp_path / "new.json", probe=lambda _p: 1.0, need_stills=False).shots[0]
    assert (old.ambience.ref, old.beat_ambience) == ("tavern", None)
    assert (new.ambience.ref, new.beat_ambience.ref, new.beat_ambience.volume, new.beat_ambience.fade_in, new.beat_ambience.fade_in_set) == ("tavern", "cheer", 0.7, 1.5, True)
    (tmp_path / "bad.json").write_text(json.dumps({"shots": [{**shot, "beat_ambience": {"audio": "gone.mp3"}}]}))
    with pytest.raises(manifest.ManifestError, match="beat_ambience: no such file gone.mp3"):
        manifest.load(tmp_path / "bad.json", probe=lambda _p: 1.0, need_stills=False)


# ── what the pull puts in the manifest ──────────────────────────────────────────────────
@pytest.fixture
def pull(tmp_path, monkeypatch):
    monkeypatch.setattr(marvin_pull, "_fetch_asset", lambda creds, asset, dest, ext: tmp_path / "audio" / "sounds" / f"{asset}.mp3")
    sounds = _sounds(tavern=0.6, cheer=0.4, storm=None)
    scenes = {
        "inn": {"dataJson": {"ambience": "tavern", "ambience_volume": 0.5, "ambience_fade_in": 9}},
        "cabin": {"dataJson": {"ambience": "storm", "ambience_volume": 0.3, "ambience_muffled": True}},
    }
    story = {"ambience_fade_out": 2}
    return lambda beat: marvin_pull._ambience(("u", "t"), tmp_path, beat, scenes, sounds, DATA, {}, [], story)


def test_the_pull_gives_the_scenes_bed_at_the_scenes_level_and_the_beats_over_it_with_the_beats_fades(pull):
    under, over = pull({"scene": "inn", "ambience": "cheer", "ambience_volume": 0.8, "ambience_fade_in": 0.3})
    assert (under["id"], under["volume"], under.get("fade_in"), under["fade_out"]) == ("tavern", 0.5, None, 2.0)  # the scene's own, the story's fade-out: not the beat's fade
    assert (over["id"], over["volume"], over["fade_in"], over["fade_out"], over["fade_in_set"]) == ("cheer", 0.8, 0.3, 2.0, True)


def test_a_beat_naming_its_scenes_own_sound_is_the_scenes_bed_at_the_beats_level_not_a_second_copy(pull):
    under, over = pull({"scene": "inn", "ambience": "tavern", "ambience_volume": 0.2})
    assert over is None and (under["id"], under["volume"]) == ("tavern", 0.2)
    assert pull({"scene": "inn", "ambience": "tavern", "ambience_volume": 0.2}) == pull({"scene": "inn", "ambience_volume": 0.2})  # the same as naming nothing


def test_a_beats_bed_at_level_0_keeps_the_scenes_bed_at_the_scenes_level(pull):
    under, over = pull({"scene": "inn", "ambience": "cheer", "ambience_volume": 0})
    assert (under["volume"], over["volume"]) == (0.5, 0.0)  # the 0 is the cheer's, the tavern plays on (and the render leaves a silent bed out)


def test_a_beats_bed_is_heard_as_its_scenes_unless_the_beat_says_clear_or_muffled(pull):
    assert pull({"scene": "cabin", "ambience": "cheer"})[1]["muffled"] is True  # through the wall, as the storm is
    under, over = pull({"scene": "cabin", "ambience": "cheer", "ambience_heard": "clear"})
    assert (under["muffled"], over["muffled"]) == (True, False)  # the storm outside, the cheer in the room
    assert pull({"scene": "inn", "ambience": "cheer", "ambience_heard": "muffled"})[1]["muffled"] is True
    assert pull({"scene": "inn", "ambience": "cheer", "ambience_heard": "loud"})[1]["muffled"] is False  # not a known word: as the scene's


# ── the script and the audio cut ─────────────────────────────────────────────────────────
def _row(slug, title="", **data):
    return {"slug": slug, "title": title or slug, "dataJson": data}


RECORDS = {
    "story": _row("s", "S", fountain_front=""),
    "scenes": {"s-inn": _row("s-inn", "The inn", story="s", ambience="s-tavern"), "s-road": _row("s-road", "The road", story="s")},
    "sounds": {"s-tavern": _row("s-tavern", "Tavern murmur"), "s-cheer": _row("s-cheer", "Crowd cheer")},
    "beats": [
        _row("s-beat-01", story="s", number="01", scene="s-inn", picture="The inn."),
        _row("s-beat-02", story="s", number="02", scene="s-inn", picture="A toast.", ambience="s-cheer", ambience_volume=0.7),
        _row("s-beat-03", story="s", number="03", scene="s-inn", picture="Quiet.", ambience="s-tavern"),
        _row("s-beat-04", story="s", number="04", scene="s-road", picture="Outside.", ambience="s-cheer"),
    ],
    "lines": {},
}


def test_the_script_says_a_beats_bed_is_over_its_scenes():
    text = script.fountain(RECORDS)
    assert "SFX: crowd cheer, over the scene's ambience" in text and "SFX: crowd cheer, under the beat" in text  # over the tavern; alone on the road
    assert text.count("SFX: tavern murmur") == 1  # the tavern once, under the scene: naming it again on beat 03 is the same bed
    complete = script.fountain_complete(RECORDS)
    assert "Ambience: Crowd cheer, level 0.7, over the scene's." in complete and "Ambience: Crowd cheer, under the beat." in complete


@needs_ffmpeg
def test_in_the_audio_cut_the_tavern_runs_on_through_the_cheer_which_is_heard_only_in_its_beat(tmp_path):
    project = demo.make(tmp_path / "demo", size=(360, 640))
    folder = project.parent
    _tone(folder / "tavern.mp3", 30.0, 1500)
    _tone(folder / "cheer.mp3", 30.0, 2500)
    raw = json.loads(project.read_text())
    for shot in raw["shots"]:
        shot["ambience"] = {"id": "tavern", "audio": "tavern.mp3", "volume": 0.8}
    raw["shots"][1]["beat_ambience"] = {"id": "cheer", "audio": "cheer.mp3", "volume": 0.8}
    project.write_text(json.dumps(raw))
    m = manifest.load(project, probe=ffmpeg.duration, need_stills=False)
    result = build.listen(m, tmp_path / "cut.mp3")
    assert [(b["id"], b.get("over")) for b in result["ambience"]] == [("tavern", None), ("cheer", "scene")]  # one tavern bed, the cheer over it
    plan = manifest.plan(m)
    window = lambda shot: (shot.start + 0.8, max(0.2, min(shot.duration - 1.4, 1.0)))  # noqa: E731 - clear of the crossfades at the cuts
    tavern = [_bed_db(tmp_path / "cut.mp3", *window(s), 1500) for s in plan.shots[:3]]
    assert max(tavern) - min(tavern) < 2.0  # the tavern is as loud in the cheering beat as either side of it: not replaced
    first, cheering = (_bed_db(tmp_path / "cut.mp3", *window(plan.shots[i]), 2500) for i in (0, 1))
    assert cheering > -45 and first < cheering - 12  # the cheer only in its beat
