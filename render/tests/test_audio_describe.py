"""What a recording says about itself: silence at its ends, loudness, make, and where it came from. The parsers are tested on ffmpeg's real wording."""

from storyrender import audio_measure as am


def test_silence_at_the_start_and_the_end():
    out = "[silencedetect] silence_start: 0\n[silencedetect] silence_end: 0.52 | silence_duration: 0.52\n[silencedetect] silence_start: 3.1\n"
    assert am.parse_silence(out, 3.6) == (0.52, 0.5)  # 0.52 s before the first sound, the file ends in 0.5 s of it
    assert am.parse_silence("", 3.0) == (0.0, 0.0)  # no silence found anywhere
    mid = "silence_start: 1.2\nsilence_end: 1.9 | silence_duration: 0.7\n"
    assert am.parse_silence(mid, 4.0) == (0.0, 0.0)  # a pause inside is not an edge
    assert am.parse_silence("silence_start: 0\n", 2.0) == (2.0, 0.0)  # all silence: the whole of it is lead


def test_loudness_from_the_ebur128_summary_and_nothing_when_it_printed_none():
    out = "  Summary:\n\n  Integrated loudness:\n    I:         -23.4 LUFS\n    Threshold: -33.4 LUFS\n\n  Loudness range:\n    LRA:         5.2 LU\n\n  True peak:\n    Peak:       -1.3 dBFS\n"
    assert am.parse_loudness(out) == (-23.4, 5.2, -1.3)
    assert am.parse_loudness("[Parsed_ebur128] t: 0.1 M: -30") is None
    silent = out.replace("-23.4 LUFS", "-inf LUFS")
    assert am.parse_loudness(silent)[0] == -70.0


def test_the_make_of_a_recording_in_a_line():
    probed = {"streams": [{"codec_type": "audio", "codec_name": "opus", "sample_rate": "48000", "channels": 1, "bit_rate": "64000"}], "format": {}}
    assert am.format_summary(probed) == "opus · 48 kHz · mono · 64 kbit/s"
    assert am.format_summary({"streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100", "channels": 2}], "format": {"bit_rate": "128000"}}) == "mp3 · 44.1 kHz · stereo · 128 kbit/s"
    assert am.format_summary({"streams": [], "format": {}}) == ""


def test_where_a_recording_came_from_is_read_from_what_the_asset_keeps():
    assert am.source_of({"recording": {"source": "browser", "mime": "audio/webm"}}) == "recorded"
    assert am.source_of({"words": [{"text": "hi", "start": 0, "end": 0.2}]}) == "generated"  # a voice service's own timing
    assert am.source_of({"words": [{"text": "hi"}], "words_from": "faster-whisper"}) == "uploaded"  # timed here: not the service's
    assert am.source_of({}) == "uploaded" and am.source_of(None) == "uploaded"


def test_average_level_noise_floor_and_peak_from_the_astats_overall_block():
    out = "[Parsed_astats_0 @ 0x1] Channel: 1\n[Parsed_astats_0 @ 0x1] RMS level dB: -30.0\n[Parsed_astats_0 @ 0x1] Overall\n[Parsed_astats_0 @ 0x1] DC offset: 0.000000\n[Parsed_astats_0 @ 0x1] Peak level dB: -2.516000\n[Parsed_astats_0 @ 0x1] RMS level dB: -20.131000\n[Parsed_astats_0 @ 0x1] RMS trough dB: -64.222000\n"
    assert am.parse_stats(out) == {"rms_db": -20.1, "noise_floor_db": -64.2, "peak_db": -2.5}  # the Overall block, not one channel's
    assert am.parse_stats("nothing here") is None
    silent = out.replace("-20.131000", "-inf").replace("-64.222000", "-inf").replace("-2.516000", "-inf")
    assert am.parse_stats(silent) == {"rms_db": -60.0, "noise_floor_db": -90.0, "peak_db": -60.0}  # a silent file reads at the floors


def test_the_job_writes_what_the_take_says_about_itself_and_believes_a_source_it_already_has(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess

    from marvin_worker.jobs import Context

    from storyrender import jobs

    tone = tmp_path / "take.wav"  # a half-scale tone, then nothing: not clipped, quiet at the end
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1,volume=0.5,apad=pad_dur=1", "-t", "2", str(tone)], check=True)
    written: dict = {}
    entry = {"slug": "take-1", "dataJson": {"audio": "asset-1", "source": "uploaded"}}
    monkeypatch.setattr(jobs.marvin_api, "query", lambda creds, spec, limit=1: [entry])
    monkeypatch.setattr(jobs.marvin_api, "asset", lambda creds, ref: {"id": "asset-1", "name": "take.wav", "mimeType": "audio/wav", "metadataJson": {"recording": {"source": "browser"}}})
    monkeypatch.setattr(jobs.marvin_api, "download_asset", lambda creds, ref, dest: shutil.copy(tone, dest))
    monkeypatch.setattr(jobs.marvin_api, "update_entry", lambda creds, slug, data: written.update({"slug": slug, **data}))
    out = jobs.describe_audio({"job": "j", "args": {"entry": "take-1"}}, Context(creds=("http://m", "t"), work=tmp_path, name="d-1"))
    assert written["clipped"] == "no" and written["peak_db"] < -3 and written["noise_floor_db"] < -60 and written["rms_db"] > written["noise_floor_db"]
    assert written["tail_silence"] > 0.5 and "format" in written and "source" not in written  # the take already said where it came from
    assert "noise floor" in out["log"] and json.dumps(out["result"])


def test_a_silence_ffmpeg_closes_at_the_end_of_the_file_is_still_the_tail():
    both = "silence_start: 0\nsilence_end: 0.5 | silence_duration: 0.5\nsilence_start: 1.5\nsilence_end: 2 | silence_duration: 0.5"
    assert am.parse_silence(both, 2.0) == (0.5, 0.5)  # a newer ffmpeg
    assert am.parse_silence("silence_start: 0\nsilence_end: 0.5\nsilence_start: 1.5", 2.0) == (0.5, 0.5)  # an older one leaves it open
    assert am.parse_silence("silence_start: 0.8\nsilence_end: 1.1 | silence_duration: 0.3", 2.0) == (0.0, 0.0)  # a pause in the middle is neither
