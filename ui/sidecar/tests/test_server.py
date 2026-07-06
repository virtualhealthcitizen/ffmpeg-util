"""End-to-end integration tests for the sidecar against real ffmpeg."""

import glob
import json
import os
import tempfile

import pytest


def _sse_events(text: str) -> list:
    return [
        json.loads(line[len("data:"):].strip())
        for line in text.splitlines()
        if line.startswith("data:")
    ]


def test_expected_output_duration():
    import server
    assert server._expected_output_duration("convert", 10) == 10
    assert server._expected_output_duration("speed", 10, factor=2) == 5
    assert server._expected_output_duration("loop", 10, count=3) == 30
    assert server._expected_output_duration("boomerang", 10) == 20
    assert server._expected_output_duration("convert", None) is None
    # trim: output length comes from duration / end-start / remaining-after-start
    assert server._expected_output_duration("trim", 30, duration="5") == 5
    assert server._expected_output_duration("trim", 30, start="10", end="00:00:25") == 15
    assert server._expected_output_duration("trim", 30, start="20") == 10
    # trim_segments: joined output length is the sum of each segment's own
    # span, not the original (pre-trim) input duration `total` holds.
    assert server._expected_output_duration(
        "trim_segments", 600, segments_text="0 15\n100 115",
    ) == 30
    # Bad/empty segments text falls back to `total` rather than raising.
    assert server._expected_output_duration("trim_segments", 600, segments_text="") == 600


def test_parse_time():
    import server
    assert server._parse_time("5") == 5
    assert server._parse_time("01:30") == 90
    assert server._parse_time("01:00:00") == 3600


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_probe_requires_token(client, media):
    _, src = media
    r = client.post("/probe", json={"input": str(src)})
    assert r.status_code == 401


def test_exists_reports_presence(client, media, auth):
    d, src = media
    r = client.get("/exists", params={"path": str(src)}, headers=auth)
    assert r.status_code == 200
    assert r.json()["exists"] is True
    r = client.get("/exists", params={"path": str(d / "nope.mp4")}, headers=auth)
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_exists_reports_directory(client, media, auth):
    d, _ = media
    r = client.get("/exists", params={"path": str(d)}, headers=auth)
    assert r.status_code == 200
    assert r.json()["exists"] is True


def test_exists_requires_token(client, media):
    _, src = media
    r = client.get("/exists", params={"path": str(src)})
    assert r.status_code == 401


def test_probe(client, media, auth):
    _, src = media
    r = client.post("/probe", json={"input": str(src)}, headers=auth)
    assert r.status_code == 200
    out = r.json()["result"]
    assert "duration" in out and "video" in out


def test_probe_json(client, media, auth):
    _, src = media
    r = client.post("/probe", json={"input": str(src), "as_json": True}, headers=auth)
    assert r.status_code == 200
    data = json.loads(r.json()["result"])
    assert "streams" in data and "format" in data


def test_convert(client, media, auth):
    d, src = media
    out = d / "out.mkv"
    r = client.post(
        "/convert",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_convert_extract_audio(client, media, auth):
    d, src = media
    out = d / "audio.m4a"
    r = client.post(
        "/convert",
        json={"input": str(src), "output": str(out), "extract_audio": True,
              "acodec": "aac", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_trim(client, media, auth):
    d, src = media
    out = d / "clip.mp4"
    r = client.post(
        "/trim",
        json={"input": str(src), "output": str(out), "start": "1",
              "duration": "1", "reencode": True, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()


def test_trim_conflicting_options_400(client, media, auth):
    d, src = media
    r = client.post(
        "/trim",
        json={"input": str(src), "output": str(d / "x.mp4"),
              "end": "2", "duration": "1"},
        headers=auth,
    )
    assert r.status_code == 400


def test_concat(client, media, auth):
    d, src = media
    out = d / "joined.mp4"
    r = client.post(
        "/concat",
        json={"inputs": [str(src), str(src)], "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()


def test_concat_too_few_inputs_400(client, media, auth):
    d, src = media
    r = client.post(
        "/concat",
        json={"inputs": [str(src)], "output": str(d / "x.mp4")},
        headers=auth,
    )
    assert r.status_code == 400


def test_concat_reencode_produces_output(client, media, auth):
    d, src = media
    out = d / "joined_reenc.mp4"
    r = client.post(
        "/concat",
        json={"inputs": [str(src), str(src)], "output": str(out), "reencode": True, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert out.exists()


def test_thumbnail(client, media, auth):
    d, src = media
    out = d / "thumb.png"
    r = client.post(
        "/thumbnail",
        json={"input": str(src), "output": str(out), "time": "1",
              "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_compress(client, media, auth):
    d, src = media
    out = d / "small.mp4"
    r = client.post(
        "/compress",
        json={"input": str(src), "output": str(out), "crf": 30,
              "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()


def test_compress_estimate_size(client, media, auth):
    d, src = media
    r = client.post(
        "/compress/estimate-size",
        json={"input": str(src), "crf": 30, "width": 160, "sample_seconds": 1},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["estimated_bytes"] > 0
    assert body["sample_bytes"] > 0
    assert body["duration_s"] == pytest.approx(3, abs=0.5)  # `media` is a 3s clip
    assert 0 < body["sample_seconds"] <= 3


def test_compress_estimate_size_missing_input_400(client, auth, tmp_path):
    r = client.post(
        "/compress/estimate-size",
        json={"input": str(tmp_path / "does-not-exist.mp4"), "crf": 30},
        headers=auth,
    )
    assert r.status_code == 400


def _duration(path):
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _dims(path):
    import json as _json
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    s = _json.loads(out.stdout)["streams"][0]
    return s["width"], s["height"]


def _audio_stream_count(path):
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return len([ln for ln in out.stdout.splitlines() if ln.strip()])


def _mean_volume(path):
    import re
    import subprocess
    from conftest import FFMPEG
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out.stderr)
    assert m, out.stderr
    return float(m.group(1))


def _first_frame_yavg(path):
    import re
    import subprocess
    from conftest import FFMPEG
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path),
         "-vf", r"select=eq(n\,0),signalstats,metadata=print",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", out.stdout + out.stderr)
    return float(m.group(1)) if m else None


def _first_frame_satavg(path):
    import re
    import subprocess
    from conftest import FFMPEG
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path),
         "-vf", r"select=eq(n\,0),signalstats,metadata=print",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"lavfi\.signalstats\.SATAVG=([\d.]+)", out.stdout + out.stderr)
    return float(m.group(1)) if m else None


def _avg_frame_rate(path):
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    num, den = out.stdout.strip().split("/")
    return float(num) / float(den)


def test_waveform_produces_image_of_size(client, media, auth):
    d, src = media
    out = d / "wave.png"
    r = client.post(
        "/waveform",
        json={"input": str(src), "output": str(out), "width": 640, "height": 120, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (640, 120)


def test_waveform_no_audio_input_rejected(client, media_no_audio, auth):
    # Regression: showwavespic (an audio-only filter) was sent straight to
    # ffmpeg with no has_audio() guard, unlike the sibling audio-only ops
    # (loudnorm/volume/mono/sample-rate/trim-silence) — a video-only input hit
    # a raw ffmpeg filtergraph crash instead of a clear 400.
    d, src = media_no_audio
    out = d / "wave_no_audio_out.png"
    r = client.post(
        "/waveform",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_run_stream_waveform_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "wave_stream_no_audio_out.png"
    r = client.post(
        "/run/stream",
        json={"op": "waveform", "input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "error" for e in events), r.text
    assert not out.exists()


def test_crop_aspect_produces_target_ratio(client, media, auth):
    d, src = media  # 320x240 (4:3)
    out = d / "wide.mp4"
    r = client.post(
        "/crop-aspect",
        json={"input": str(src), "output": str(out), "aspect": "16:9", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 180)  # 16:9 crop of 320x240


def test_autocrop_removes_black_bars(client, media, auth):
    import subprocess
    from conftest import FFMPEG
    d, src = media  # 320x240
    # Letterbox it: 320x180 content centered in a 320x240 black frame.
    boxed = d / "letterboxed.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-vf", "scale=320:180,pad=320:240:0:30:black", "-pix_fmt", "yuv420p",
         str(boxed)],
        check=True,
    )
    assert _dims(boxed) == (320, 240)
    out = d / "autocropped.mp4"
    r = client.post(
        "/autocrop",
        json={"input": str(boxed), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 180)  # black bars detected and cropped off


def test_fps_resamples_frame_rate(client, media, auth):
    d, src = media  # 30 fps source
    out = d / "fps15.mp4"
    r = client.post(
        "/fps",
        json={"input": str(src), "output": str(out), "fps": 15, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert abs(_avg_frame_rate(out) - 15) < 0.5


def test_eq_brightness_raises_luma(client, media, auth):
    d, src = media
    base = _first_frame_yavg(src)
    out = d / "bright.mp4"
    r = client.post(
        "/eq",
        json={"input": str(src), "output": str(out), "brightness": 0.3, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    brightened = _first_frame_yavg(out)
    assert base is not None and brightened is not None
    assert brightened > base + 15, f"base={base} brightened={brightened}"


def test_grayscale_removes_saturation(client, media, auth):
    d, src = media
    base = _first_frame_satavg(src)
    out = d / "gray.mp4"
    r = client.post(
        "/grayscale",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    after = _first_frame_satavg(out)
    assert base is not None and after is not None, f"base={base} after={after}"
    assert base > 10, f"source should be colorful, SATAVG={base}"
    assert after < 3, f"grayscale should be ~0 saturation, got {after}"


def test_invert_negates_luma(client, media, auth):
    d, src = media
    base = _first_frame_yavg(src)
    out = d / "inverted.mp4"
    r = client.post(
        "/invert",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    inverted = _first_frame_yavg(out)
    assert base is not None and inverted is not None, f"base={base} inverted={inverted}"
    # negate maps each 8-bit sample x -> 255-x, so YAVG_out ≈ 255 - YAVG_in.
    assert abs((base + inverted) - 255) < 25, f"base={base} inverted={inverted}"


def test_autorotate_produces_output(client, media, auth):
    d, src = media
    out = d / "oriented.mp4"
    r = client.post(
        "/autorotate",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "autorotate should produce an output file"


def test_deinterlace_produces_output(client, media, auth):
    d, src = media
    out = d / "deinterlaced.mp4"
    r = client.post(
        "/deinterlace",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "deinterlace should produce an output file"


def test_sharpen_produces_output(client, media, auth):
    d, src = media
    out = d / "sharpened.mp4"
    r = client.post(
        "/sharpen",
        json={"input": str(src), "output": str(out), "amount": 2.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "sharpen should produce an output file"


def test_denoise_produces_output(client, media, auth):
    d, src = media
    out = d / "denoised.mp4"
    r = client.post(
        "/denoise",
        json={"input": str(src), "output": str(out), "strength": 4.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "denoise should produce an output file"


def test_stabilize_produces_output(client, media, auth):
    d, src = media
    out = d / "stabilized.mp4"
    r = client.post(
        "/stabilize",
        json={"input": str(src), "output": str(out),
              "shakiness": 5, "smoothing": 10, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "stabilize should produce an output file"


def test_timecode_produces_output(client, media, auth):
    d, src = media
    out = d / "timecoded.mp4"
    r = client.post(
        "/timecode",
        json={"input": str(src), "output": str(out), "font_size": 24,
              "position": "top-left", "color": "white", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "timecode should produce an output file"


def test_fade_makes_first_frame_dark(client, media, auth):
    d, src = media
    base = _first_frame_yavg(src)
    out = d / "faded.mp4"
    r = client.post(
        "/fade",
        json={"input": str(src), "output": str(out), "duration": 1.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    faded = _first_frame_yavg(out)
    assert base is not None and faded is not None, f"base={base} faded={faded}"
    # Fade-in => the first frame is (near) black, far darker than the source's.
    assert faded < base - 20, f"base={base} faded={faded}"
    assert faded < 40, f"faded first-frame YAVG should be dark, got {faded}"


def _integrated_loudness(path):
    import re
    import subprocess
    from conftest import FFMPEG
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    matches = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", out.stderr)
    return float(matches[-1]) if matches else None


def test_loudnorm_hits_target(client, media, auth):
    d, src = media
    out = d / "normalized.mp4"
    r = client.post(
        "/loudnorm",
        json={"input": str(src), "output": str(out), "target_i": -16.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    measured = _integrated_loudness(out)
    assert measured is not None, "no ebur128 reading"
    assert abs(measured - (-16.0)) < 1.5, f"target -16, measured {measured}"


def test_volume_attenuates_by_gain(client, media, auth):
    d, src = media
    out = d / "quieter.mp4"
    r = client.post(
        "/volume",
        json={"input": str(src), "output": str(out), "gain": -6.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    before, after = _mean_volume(src), _mean_volume(out)
    # -6 dB gain should drop the measured mean volume by ~6 dB.
    assert abs((before - 6.0) - after) < 1.5, f"before={before} after={after}"


def test_loudnorm_no_audio_input_rejected(client, media_no_audio, auth):
    # Regression: loudnorm/volume/mono/sample-rate/trim-silence are audio-only
    # ops that used to be sent straight to ffmpeg with no audio-stream check,
    # crashing with a cryptic ffmpeg stream-specifier error on a video-only
    # input instead of a clear 400.
    d, src = media_no_audio
    out = d / "loudnorm_no_audio_out.mp4"
    r = client.post(
        "/loudnorm",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_volume_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "volume_no_audio_out.mp4"
    r = client.post(
        "/volume",
        json={"input": str(src), "output": str(out), "gain": -6.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_run_stream_volume_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "volume_stream_no_audio_out.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "volume", "input": str(src), "output": str(out), "gain": -6.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "error" for e in events), r.text
    assert not out.exists()


def test_vstack_doubles_height(client, media, auth):
    d, src = media  # 320x240
    out = d / "stacked.mp4"
    r = client.post(
        "/vstack",
        json={"inputs": [str(src), str(src)], "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 480)  # two 240-tall videos stacked


def test_hstack_doubles_width(client, media, auth):
    d, src = media  # 320x240
    out = d / "sbs.mp4"
    r = client.post(
        "/hstack",
        json={"inputs": [str(src), str(src)], "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (640, 240)  # two 320-wide videos side by side


def test_hstack_requires_two_400(client, media, auth):
    d, src = media
    r = client.post(
        "/hstack",
        json={"inputs": [str(src)], "output": str(d / "x.mp4")},
        headers=auth,
    )
    assert r.status_code == 400


def test_xfade_concat_produces_output(client, media, auth):
    d, src = media  # 3s 320x240 clip
    out = d / "xfade.mp4"
    # offset 2.0: transition starts 2s into the 3s first clip (3 - 1 = 2)
    r = client.post(
        "/xfade-concat",
        json={
            "inputs": [str(src), str(src)],
            "output": str(out),
            "transition": "fade",
            "duration": 1.0,
            "offset": 2.0,
            "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert out.exists()
    assert _dims(out) == (320, 240)


def test_xfade_concat_auto_offset(client, media, auth):
    d, src = media  # 3s 320x240 clip
    out = d / "xfade_auto.mp4"
    # omit offset — sidecar probes clip 1 and computes it
    r = client.post(
        "/xfade-concat",
        json={
            "inputs": [str(src), str(src)],
            "output": str(out),
            "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert out.exists()


def test_xfade_concat_requires_two_400(client, media, auth):
    d, src = media
    r = client.post(
        "/xfade-concat",
        json={"inputs": [str(src)], "output": str(d / "x.mp4"), "offset": 2.0},
        headers=auth,
    )
    assert r.status_code == 400


def test_expected_output_duration_xfade_concat(media):
    # Regression: `_expected_output_duration` had no case for xfade_concat, so
    # it fell through to `total` — clip 1's own duration alone, since only the
    # first input is probed for `total` in run_stream. The real xfade output
    # plays clip 1 up to the transition offset then all of clip 2, so it runs
    # past clip 1's end; the progress bar used to hit 100% and stall while
    # ffmpeg kept encoding into clip 2.
    import server
    _, src = media  # 3s clip
    s = str(src)
    total = server.commands.probe_duration(server.FfmpegRunner(), s)
    result = server._expected_output_duration(
        "xfade_concat", total, inputs=[s, s], xfade_duration=1.0,
    )
    assert abs(result - 5.0) < 0.2  # auto offset (3 - 1 = 2) + clip 2's 3s
    # Explicit offset is honoured over the auto-computed one.
    assert abs(
        server._expected_output_duration(
            "xfade_concat", total, inputs=[s, s], xfade_offset=1.0,
        ) - 4.0
    ) < 0.2
    # Fewer than two inputs, or no probed `total` — safe fallback.
    assert server._expected_output_duration("xfade_concat", total, inputs=[s]) == total
    assert server._expected_output_duration("xfade_concat", None, inputs=[s, s]) is None


def test_run_stream_xfade_concat_progress_total(client, media, auth):
    d, src = media  # 3s 320x240 clip
    out = d / "xfade_stream.mp4"
    r = client.post(
        "/run/stream",
        json={
            "op": "xfade_concat", "inputs": [str(src), str(src)], "output": str(out),
            "transition": "fade", "xfade_duration": 1.0, "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream xfade_concat should produce output"
    progress = [e for e in events if e.get("type") == "progress" and e.get("total")]
    assert progress, "expected at least one progress event with a total"
    assert abs(progress[-1]["total"] - 5.0) < 0.2


def test_expected_output_duration_concat(media):
    # Regression: `_expected_output_duration` had no case for concat, so it
    # fell through to `total` — the FIRST input's duration alone, since only
    # the first input is probed for `total` in run_stream. The concat
    # demuxer/filter joins every input sequentially, so the real output spans
    # the sum of all their durations.
    import server
    d, src = media  # 3s clip
    total = server.commands.probe_duration(server.FfmpegRunner(), str(src))
    result = server._expected_output_duration("concat", total, inputs=[str(src), str(src), str(src)])
    assert abs(result - 9.0) < 0.3  # 3 * 3s
    # Fewer than two inputs, or no probed `total` — safe fallback.
    assert server._expected_output_duration("concat", total, inputs=[str(src)]) == total
    assert server._expected_output_duration("concat", None, inputs=[str(src), str(src)]) is None


def test_run_stream_concat_progress_total(client, media, auth):
    d, src = media  # 3s 320x240 clip
    out = d / "concat_stream.mp4"
    r = client.post(
        "/run/stream",
        json={
            "op": "concat", "inputs": [str(src), str(src)], "output": str(out),
            "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream concat should produce output"
    progress = [e for e in events if e.get("type") == "progress" and e.get("total")]
    assert progress, "expected at least one progress event with a total"
    assert abs(progress[-1]["total"] - 6.0) < 0.3  # 2 * 3s, not just 3s


def test_boomerang_doubles_duration(client, media, auth):
    d, src = media
    out = d / "boomerang.mp4"
    r = client.post(
        "/boomerang",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    assert abs(_duration(out) - 2 * _duration(src)) < 0.4


def test_reverse_preserves_duration(client, media, auth):
    d, src = media
    out = d / "reversed.mp4"
    r = client.post(
        "/reverse",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    # Integrity check: a reversed clip has the same length (content reversal isn't
    # asserted here — that's covered by the filter-string unit tests).
    assert abs(_duration(out) - _duration(src)) < 0.3


def test_frames_extracts_expected_count(client, media, auth):
    # media is testsrc duration=3 @30fps -> 90 frames; every 30 -> frames 0,30,60 -> 3 files.
    d, src = media
    outdir = d / "frames"
    outdir.mkdir()
    r = client.post(
        "/frames",
        json={"input": str(src), "output": str(outdir / "f_%04d.png"), "every": 30, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    pngs = list(outdir.glob("f_*.png"))
    assert len(pngs) == 3, [p.name for p in pngs]


def test_scene_thumbs_finds_cuts(client, tmp_path, auth):
    import subprocess
    from conftest import FFMPEG
    # Build a 2-second clip with a hard cut at the 1-second mark (red → blue).
    src = tmp_path / "cuts.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=160x120:d=1",
         "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", str(src)],
        check=True,
    )
    outdir = tmp_path / "scene"
    outdir.mkdir()
    r = client.post(
        "/scene-thumbs",
        json={"input": str(src), "output": str(outdir / "s_%04d.png"),
              "threshold": 0.1, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    pngs = list(outdir.glob("s_*.png"))
    assert len(pngs) >= 1, "expected at least one scene-change thumbnail"


def test_run_stream_scene_thumbs(client, tmp_path, auth):
    import subprocess
    from conftest import FFMPEG
    # Hard cut red → blue (high luma contrast); threshold 0.05 is very sensitive.
    src = tmp_path / "cuts2.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=160x120:d=1",
         "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", str(src)],
        check=True,
    )
    outdir = tmp_path / "scene2"
    outdir.mkdir()
    r = client.post(
        "/run/stream",
        json={"op": "scene_thumbs", "input": str(src),
              "output": str(outdir / "t_%04d.png"),
              "threshold": 0.05, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _sse_events(r.text)[-1]["type"] == "done"
    assert list(outdir.glob("t_*.png")), "expected at least one scene thumbnail from stream"


def test_loop_multiplies_duration(client, media, auth):
    d, src = media  # ~3s clip
    out = d / "looped.mp4"
    r = client.post(
        "/loop",
        json={"input": str(src), "output": str(out), "count": 3, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    ratio = _duration(out) / _duration(src)
    assert 2.6 <= ratio <= 3.4, f"ratio={ratio:.2f}"  # ~3x, generous tolerance


def test_blur_region_produces_same_dimensions(client, media, auth):
    d, src = media  # 320x240
    out = d / "blurred_region.mp4"
    r = client.post(
        "/blur-region",
        json={"input": str(src), "output": str(out),
              "x": 40, "y": 20, "width": 80, "height": 60, "sigma": 10, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 240)  # output frame unchanged


def test_blur_pad_produces_target_frame(client, media, auth):
    d, src = media  # 320x240
    out = d / "blurpad.mp4"
    r = client.post(
        "/blur-pad",
        json={"input": str(src), "output": str(out), "width": 480, "height": 480, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (480, 480)


def test_run_stream_blur_region_default_sigma():
    # Regression: RunReq's `sigma` field is shared between blur_region and
    # blur_pad but defaulted to 20 (blur-pad's value) unconditionally, so
    # calling /run/stream op=blur_region without an explicit sigma used
    # blur-pad's default instead of blur-region's own default (10, matching
    # the CLI and the dedicated /blur-region endpoint).
    import server
    req = server.RunReq(op="blur_region", output="out.mp4", input="in.mp4", width=80, height=60)
    args, _ = server._build_op_args(req)
    fc = args[args.index("-filter_complex") + 1]
    assert "gblur=sigma=10" in fc


def test_run_stream_blur_pad_default_sigma():
    import server
    req = server.RunReq(op="blur_pad", output="out.mp4", input="in.mp4", width=480, height=480)
    args, _ = server._build_op_args(req)
    fc = args[args.index("-filter_complex") + 1]
    assert "gblur=sigma=20" in fc


def test_image_to_video_makes_clip(client, media, auth):
    import subprocess
    from conftest import FFMPEG
    d, _ = media
    img = d / "still.png"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=320x240", "-frames:v", "1", str(img)],
        check=True,
    )
    out = d / "fromimage.mp4"
    r = client.post(
        "/image-to-video",
        json={"input": str(img), "output": str(out), "seconds": 2, "fps": 24, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert abs(_duration(out) - 2) < 0.3  # ~2s clip
    assert _dims(out) == (320, 240)  # has a video stream at the image size


def test_image_to_video_with_audio_muxes_track(client, media, auth):
    import subprocess
    from conftest import FFMPEG
    d, _ = media
    img = d / "still2.png"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1", str(img)],
        check=True,
    )
    track = d / "voiceover.wav"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2",
         str(track)],
        check=True,
    )
    out = d / "fromimage_with_audio.mp4"
    r = client.post(
        "/image-to-video",
        json={"input": str(img), "output": str(out), "seconds": 2, "fps": 24,
              "audio": str(track), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert abs(_duration(out) - 2) < 0.3
    assert _audio_stream_count(out) == 1


def test_pad_produces_target_frame(client, media, auth):
    d, src = media  # 320x240
    out = d / "padded.mp4"
    r = client.post(
        "/pad",
        json={"input": str(src), "output": str(out), "width": 640, "height": 640, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (640, 640)  # exact target frame, with bars


def _audio_channels(path):
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip())


def test_title_sets_metadata(client, media, auth):
    import subprocess
    from conftest import FFPROBE
    d, src = media
    out = d / "titled.mp4"
    r = client.post(
        "/title",
        json={"input": str(src), "output": str(out), "title": "Hello Clip", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format_tags=title",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "Hello Clip"


def _sample_rate(path):
    import subprocess
    from conftest import FFPROBE
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip())


def test_sample_rate_resamples_audio(client, media, auth):
    d, src = media  # 44100 Hz source
    out = d / "sr.mp4"
    r = client.post(
        "/sample-rate",
        json={"input": str(src), "output": str(out), "rate": 22050, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _sample_rate(out) == 22050


def test_mono_downmixes_to_one_channel(client, media, auth):
    import subprocess
    from conftest import FFMPEG
    d, src = media
    # The fixture clip is mono; make a stereo source so the downmix is meaningful.
    stereo = d / "stereo.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-ac", "2", "-c:v", "copy", str(stereo)],
        check=True,
    )
    assert _audio_channels(stereo) == 2
    out = d / "mono.mp4"
    r = client.post(
        "/mono",
        json={"input": str(stereo), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _audio_channels(out) == 1


def test_sample_rate_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "sr_no_audio_out.mp4"
    r = client.post(
        "/sample-rate",
        json={"input": str(src), "output": str(out), "rate": 22050, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_run_stream_sample_rate_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "sr_stream_no_audio_out.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "sample_rate", "input": str(src), "output": str(out), "rate": 22050, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "error" for e in events), r.text
    assert not out.exists()


def test_mono_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "mono_no_audio_out.mp4"
    r = client.post(
        "/mono",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_mute_removes_audio(client, media, auth):
    d, src = media  # has an audio track
    assert _audio_stream_count(src) >= 1
    out = d / "muted.mp4"
    r = client.post(
        "/mute",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _audio_stream_count(out) == 0


def test_replace_audio_swaps_track(client, media, auth):
    import subprocess
    from conftest import FFMPEG
    d, src = media  # 320x240 video, 44100 Hz audio
    # A distinct new audio track at 22050 Hz so we can prove the swap happened.
    new_audio = d / "newtrack.wav"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=22050:duration=2",
         str(new_audio)],
        check=True,
    )
    out = d / "redubbed.mp4"
    r = client.post(
        "/replace-audio",
        json={"input": str(src), "audio": str(new_audio), "output": str(out),
              "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _audio_stream_count(out) == 1
    assert _sample_rate(out) == 22050  # the new track (source was 44100)
    assert _dims(out) == _dims(src)    # video stream-copied unchanged


def test_dedicated_endpoint_rejects_missing_extension(client, media, auth):
    d, src = media
    r = client.post(
        "/mute",
        json={"input": str(src), "output": str(d / "noext"), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "extension" in r.json()["detail"].lower()


def test_dedicated_endpoint_rejects_missing_dir(client, media, auth):
    d, src = media
    r = client.post(
        "/mute",
        json={"input": str(src), "output": str(d / "nope" / "out.mp4"), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "does not exist" in r.json()["detail"].lower()


def test_crop_produces_requested_dimensions(client, media, auth):
    d, src = media  # 320x240
    out = d / "cropped.mp4"
    r = client.post(
        "/crop",
        json={"input": str(src), "output": str(out), "width": 160, "height": 120,
              "x": 10, "y": 20, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (160, 120)


def test_crop_bad_values_400(client, media, auth):
    d, src = media
    r = client.post(
        "/crop",
        json={"input": str(src), "output": str(d / "x.mp4"), "width": 0, "height": 120},
        headers=auth,
    )
    assert r.status_code == 400


def test_transform_rotate_swaps_dimensions(client, media, auth):
    d, src = media  # 320x240
    out = d / "rot.mp4"
    r = client.post(
        "/transform",
        json={"input": str(src), "output": str(out), "op": "rotate-cw", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (240, 320)  # swapped


def test_transform_hflip_keeps_dimensions(client, media, auth):
    d, src = media
    out = d / "flip.mp4"
    r = client.post(
        "/transform",
        json={"input": str(src), "output": str(out), "op": "hflip", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 240)


def test_transform_unknown_op_400(client, media, auth):
    d, src = media
    r = client.post(
        "/transform",
        json={"input": str(src), "output": str(d / "x.mp4"), "op": "nope"},
        headers=auth,
    )
    assert r.status_code == 400


def test_speed_2x_halves_duration(client, media, auth):
    d, src = media  # ~3s clip
    out = d / "fast.mp4"
    r = client.post(
        "/speed",
        json={"input": str(src), "output": str(out), "factor": 2.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    src_dur, out_dur = _duration(src), _duration(out)
    assert abs(out_dur - src_dur / 2) < 0.3, f"src={src_dur:.2f} out={out_dur:.2f}"


def test_run_stream_speed(client, media, auth):
    d, src = media
    out = d / "slow.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "speed", "input": str(src), "output": str(out),
              "factor": 0.5, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _sse_events(r.text)[-1]["type"] == "done"
    assert _duration(out) > _duration(src)  # slower -> longer


def test_run_stream_progress_carries_eta_fields(client, media, auth):
    # Progress events must expose out_time (output position) + total (expected
    # output duration) so the renderer can compute a live ETA from the speed.
    d, src = media
    out = d / "eta.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "compress", "input": str(src), "output": str(out),
              "crf": 30, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    progress = [e for e in _sse_events(r.text) if e["type"] == "progress"]
    assert progress, "expected at least one progress event"
    # `total` is the expected output duration (~3s source, compress keeps length).
    assert all(e["total"] is not None for e in progress)
    assert abs(progress[-1]["total"] - 3.0) < 0.5
    # at least one event reports a concrete output position
    assert any(e.get("out_time") is not None for e in progress)
    for e in progress:
        if e["out_time"] is not None:
            assert 0 <= e["out_time"] <= e["total"] + 0.5


def test_gif_export(client, media, auth):
    import json as _json
    import subprocess
    from conftest import FFPROBE

    d, src = media
    out = d / "clip.gif"
    r = client.post(
        "/gif",
        json={"input": str(src), "output": str(out), "fps": 10, "width": 240,
              "duration": "1", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0
    # Confirm it's actually a GIF, 240 wide.
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    s = _json.loads(probe.stdout)["streams"][0]
    assert s["codec_name"] == "gif"
    assert s["width"] == 240


def test_run_stream_gif(client, media, auth):
    d, src = media
    out = d / "stream.gif"
    r = client.post(
        "/run/stream",
        json={"op": "gif", "input": str(src), "output": str(out),
              "fps": 10, "width": 200, "duration": "1", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1]["type"] == "done"
    assert out.exists() and out.stat().st_size > 0
    # Stronger feedback: the GIF run now streams console log lines, a phase
    # marker per pass, and progress over the encode (it used to emit only done).
    logs = [e["line"] for e in events if e["type"] == "log"]
    assert logs, "expected streamed ffmpeg console log lines"
    assert any("Pass 1/2" in ln for ln in logs)
    assert any("Pass 2/2" in ln for ln in logs)
    assert any(e["type"] == "progress" for e in events)


def test_gif_dither_param(client, media, auth):
    d, src = media
    out = d / "dither.gif"
    r = client.post(
        "/gif",
        json={"input": str(src), "output": str(out), "fps": 10, "width": 240,
              "duration": "1", "dither": "bayer", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_gif_loop_param(client, media, auth):
    d, src = media
    out = d / "noloop.gif"
    r = client.post(
        "/gif",
        json={"input": str(src), "output": str(out), "fps": 10, "width": 240,
              "duration": "1", "loop": -1, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_run_stream_emits_console_log(client, media, auth):
    # Every streamed op surfaces ffmpeg's console output as `log` events so the
    # UI console panel isn't empty during a run.
    d, src = media
    out = d / "logged.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "compress", "input": str(src), "output": str(out),
              "crf": 30, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    logs = [e["line"] for e in _sse_events(r.text) if e["type"] == "log"]
    assert logs, "expected at least one ffmpeg console log line"
    assert any(ln.strip() for ln in logs)
    # The live -stats readout must stream too (not just the startup info block),
    # so the console keeps updating during a long encode instead of going silent.
    assert any("time=" in ln or "frame=" in ln for ln in logs), \
        "expected live ffmpeg stats lines (frame=/time=) in the console stream"


def test_contact_sheet_dimensions(client, media, auth):
    import json as _json
    import subprocess
    from conftest import FFPROBE

    d, src = media
    out = d / "sheet.png"
    cols, rows, tile_w = 3, 2, 160  # source is 320x240 -> tile 160x120 -> sheet 480x240
    r = client.post(
        "/contact-sheet",
        json={"input": str(src), "output": str(out), "cols": cols, "rows": rows,
              "width": tile_w, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    dims = _json.loads(probe.stdout)["streams"][0]
    assert dims["width"] == cols * tile_w   # 480
    assert dims["height"] == rows * 120     # 240


def test_compress_target_size_hits_budget(client, media, auth):
    d, src = media
    out = d / "sized.mp4"
    target_mb = 0.4
    r = client.post(
        "/compress",
        json={"input": str(src), "output": str(out), "target_size": target_mb, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists()
    size_mb = out.stat().st_size / 1_000_000
    # Two-pass should land in the ballpark of the target (generous tolerance for a short clip).
    assert 0.4 * target_mb <= size_mb <= 1.8 * target_mb, f"got {size_mb:.3f} MB"


def test_compress_target_size_conflict_400(client, media, auth):
    d, src = media
    r = client.post(
        "/compress",
        json={"input": str(src), "output": str(d / "x.mp4"), "target_size": 0.5, "crf": 23},
        headers=auth,
    )
    assert r.status_code == 400


def test_compress_hwaccel_rejects_target_size_400(client, media, auth):
    d, src = media
    r = client.post(
        "/compress",
        json={"input": str(src), "output": str(d / "x.mp4"), "target_size": 0.5, "hwaccel": "nvenc"},
        headers=auth,
    )
    assert r.status_code == 400


def test_compress_hwaccel_nvenc(client, media, auth, nvenc_available):
    if not nvenc_available:
        pytest.skip("h264_nvenc not usable on this machine (no NVIDIA GPU/driver)")
    d, src = media
    out = d / "nvenc.mp4"
    r = client.post(
        "/compress",
        json={"input": str(src), "output": str(out), "crf": 30, "width": 160,
              "hwaccel": "nvenc", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0
    import json as _json2, subprocess as _sp
    from conftest import FFPROBE
    probe = _sp.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert _json2.loads(probe.stdout)["streams"][0]["codec_name"] == "h264"


def test_run_stream_hwaccel_nvenc(client, media, auth, nvenc_available):
    if not nvenc_available:
        pytest.skip("h264_nvenc not usable on this machine (no NVIDIA GPU/driver)")
    d, src = media
    out = d / "stream_nvenc.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "compress", "input": str(src), "output": str(out),
              "crf": 30, "hwaccel": "nvenc", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1]["type"] == "done"
    assert out.exists() and out.stat().st_size > 0


def test_run_stream_emits_progress_and_done(client, media, auth):
    d, src = media
    out = d / "stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "compress", "input": str(src), "output": str(out),
              "crf": 30, "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    types = [e["type"] for e in events]
    assert "progress" in types
    assert types[-1] == "done"
    assert events[-1]["output"] == str(out)
    assert out.exists()


def test_run_stream_target_size_two_pass(client, media, auth):
    d, src = media
    out = d / "stream_sized.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "compress", "input": str(src), "output": str(out),
              "target_size": 0.4, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1]["type"] == "done"
    assert out.exists()
    size_mb = out.stat().st_size / 1_000_000
    assert 0.4 * 0.4 <= size_mb <= 1.8 * 0.4, f"got {size_mb:.3f} MB"


def test_run_stream_missing_extension_error(client, media, auth):
    d, src = media
    r = client.post(
        "/run/stream",
        json={"op": "gif", "input": str(src), "output": str(d / "output"),  # no extension
              "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    last = _sse_events(r.text)[-1]
    assert last["type"] == "error"
    assert "extension" in last["detail"].lower()


def test_run_stream_error_event(client, media, auth):
    d, _ = media
    r = client.post(
        "/run/stream",
        json={"op": "convert", "input": str(d / "nope.mp4"),
              "output": str(d / "x.mp4"), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200  # stream opens, error arrives as an event
    events = _sse_events(r.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["detail"]


def test_run_stream_concat_too_few_inputs_cleans_up_manifest(client, media, auth):
    d, src = media
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "ffconcat_*.txt")))
    r = client.post(
        "/run/stream",
        json={"op": "concat", "inputs": [str(src)], "output": str(d / "joined.mp4"),
              "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    last = _sse_events(r.text)[-1]
    assert last["type"] == "error"
    assert "two input" in last["detail"].lower()
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "ffconcat_*.txt")))
    # The concat-list manifest written before validation failed must not leak.
    assert after - before == set()


def test_run_stream_requires_token(client, media):
    _, src = media
    r = client.post(
        "/run/stream",
        json={"op": "convert", "input": str(src), "output": "x.mp4"},
    )
    assert r.status_code == 401


def test_file_serves_generated_thumbnail(client, media, auth):
    d, src = media
    thumb = d / "preview.png"
    client.post(
        "/thumbnail",
        json={"input": str(src), "output": str(thumb), "time": "1", "overwrite": True},
        headers=auth,
    )
    r = client.get("/file", params={"path": str(thumb)}, headers=auth)
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_file_serves_video_with_range(client, media, auth):
    _, src = media  # the generated clip is an mp4
    r = client.get("/file", params={"path": str(src)},
                   headers={**auth, "Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers.get("content-type", "").startswith("video/")
    assert "bytes" in r.headers.get("content-range", "")


def test_file_missing_404(client, media, auth):
    d, _ = media
    r = client.get("/file", params={"path": str(d / "does-not-exist.png")}, headers=auth)
    assert r.status_code == 404


def test_file_requires_token(client, media):
    _, src = media
    r = client.get("/file", params={"path": str(src)})
    assert r.status_code == 401


def test_trim_silence_produces_output(client, media, auth):
    d, src = media
    out = d / "trimmed.mp4"
    r = client.post(
        "/trim-silence",
        json={"input": str(src), "output": str(out),
              "threshold_db": -50.0, "min_duration": 0.5, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_trim_silence_requires_token(client, media):
    d, src = media
    r = client.post(
        "/trim-silence",
        json={"input": str(src), "output": str(d / "x.mp4"), "overwrite": True},
    )
    assert r.status_code == 401


def test_trim_silence_via_run_stream(client, media, auth):
    d, src = media
    out = d / "trimmed_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_silence", "input": str(src), "output": str(out),
              "threshold_db": -50.0, "min_duration": 0.5, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0].get("output") == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_trim_silence_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "trim_silence_no_audio_out.mp4"
    r = client.post(
        "/trim-silence",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()
    assert not out.exists()


def test_run_stream_trim_silence_no_audio_input_rejected(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "trim_silence_stream_no_audio_out.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_silence", "input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "error" for e in events), r.text
    assert not out.exists()


def test_run_stream_image_to_video_defaults_30fps(client, media, auth):
    # Regression: RunReq.fps defaulted to 12 (GIF's value), so calling
    # /run/stream op=image_to_video without an explicit fps used 12fps instead
    # of the expected 30fps default (matching the CLI + /image-to-video endpoint).
    import json as _json
    import subprocess
    from conftest import FFMPEG, FFPROBE

    d, _ = media
    img = d / "still_fps.png"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=160x120", "-frames:v", "1", str(img)],
        check=True,
    )
    out = d / "fromimage_fps.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "image_to_video", "input": str(img), "output": str(out),
              "seconds": 1.0, "overwrite": True},  # no fps field — tests the default
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1]["type"] == "done"
    assert out.exists()
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    fps_str = _json.loads(probe.stdout)["streams"][0]["r_frame_rate"]
    num, den = map(int, fps_str.split("/"))
    assert 28 <= num / den <= 32, f"expected ~30 fps default, got {fps_str}"


def test_remux(client, media, auth):
    d, src = media
    out = d / "remuxed.mkv"
    r = client.post(
        "/remux",
        json={"input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_run_stream_remux(client, media, auth):
    d, src = media
    out = d / "remuxed_stream.mkv"
    r = client.post(
        "/run/stream",
        json={"op": "remux", "input": str(src), "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["output"] == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_preview_clip(client, media, auth):
    d, src = media
    out = d / "preview.mp4"
    r = client.post(
        "/preview-clip",
        json={"input": str(src), "output": str(out), "seconds": 1.0, "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_preview_clip_rejects_bad_seconds(client, media, auth):
    d, src = media
    out = d / "bad_preview.mp4"
    r = client.post(
        "/preview-clip",
        json={"input": str(src), "output": str(out), "seconds": 0, "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400


def test_run_stream_preview_clip(client, media, auth):
    d, src = media
    out = d / "preview_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "preview_clip", "input": str(src), "output": str(out),
              "seconds": 1.0, "width": 160, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["output"] == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_poster_frame(client, media, auth):
    d, src = media
    out = d / "poster.png"
    r = client.post(
        "/poster-frame",
        json={"input": str(src), "output": str(out), "percent": 50.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_poster_frame_reports_clear_error_when_duration_unprobeable(client, media, auth, monkeypatch):
    # The endpoint must go through commands.poster_frame() (which raises a clear
    # ValueError -> 400 when duration probing fails on a real run) rather than
    # calling build_poster_frame_args() directly with duration_s=None, which
    # would emit an unusable "<pct>%" -ss value and crash inside ffmpeg instead.
    import server
    monkeypatch.setattr(server.commands, "probe_duration", lambda runner, path: None)
    d, src = media
    out = d / "poster_unprobeable.png"
    r = client.post(
        "/poster-frame",
        json={"input": str(src), "output": str(out), "percent": 50.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400
    assert "could not determine input duration" in r.json()["detail"]
    assert not out.exists()


def test_poster_frame_rejects_bad_percent(client, media, auth):
    d, src = media
    out = d / "bad_poster.png"
    r = client.post(
        "/poster-frame",
        json={"input": str(src), "output": str(out), "percent": 150.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400


def test_run_stream_poster_frame(client, media, auth):
    d, src = media
    out = d / "poster_stream.png"
    r = client.post(
        "/run/stream",
        json={"op": "poster_frame", "input": str(src), "output": str(out),
              "percent": 25.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["output"] == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_trim_pct(client, media, auth):
    d, src = media
    out = d / "trim_pct.mp4"
    r = client.post(
        "/trim-pct",
        json={"input": str(src), "output": str(out), "start_pct": 25.0, "end_pct": 75.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists() and out.stat().st_size > 0


def test_trim_pct_rejects_bad_pct(client, media, auth):
    d, src = media
    out = d / "trim_pct_bad.mp4"
    r = client.post(
        "/trim-pct",
        json={"input": str(src), "output": str(out), "start_pct": 75.0, "end_pct": 25.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 400


def test_run_stream_trim_pct(client, media, auth):
    d, src = media
    out = d / "trim_pct_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_pct", "input": str(src), "output": str(out),
              "start_pct": 25.0, "end_pct": 75.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["output"] == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_run_stream_trim_pct_reencode(client, media, auth):
    # reencode=True must be forwarded by _build_op_args, not silently dropped.
    d, src = media
    out = d / "trim_pct_reencode.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_pct", "input": str(src), "output": str(out),
              "start_pct": 25.0, "end_pct": 75.0, "reencode": True, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["output"] == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_run_stream_trim_pct_reencode_duration(client, media, auth):
    # Regression: build_trim_pct_args used -to end_s with reencode=True. Since
    # input-seeking (-ss before -i) resets output PTS to 0 during re-encode,
    # -to end_s produced end_s seconds instead of (end_s - start_s).
    # Fix: use -t (end_s - start_s) for the reencode path.
    import shutil
    import subprocess
    d, src = media
    out = d / "trim_pct_reencode_dur.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_pct", "input": str(src), "output": str(out),
              "start_pct": 25.0, "end_pct": 75.0, "reencode": True, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    ffprobe = shutil.which("ffprobe")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    dur = float(probe.stdout.strip())
    # 25%–75% of 3s = 1.5s; with the bug the output was ~2.25s (75% of 3s)
    assert dur <= 2.0, f"trim-pct reencode output was {dur:.2f}s; expected ~1.5s (used -to instead of -t)"


def test_watermark_produces_output(client, media, auth):
    d, src = media
    out = d / "watermarked.mp4"
    r = client.post(
        "/watermark",
        json={"input": str(src), "output": str(out), "text": "© Test",
              "font_size": 24, "position": "bottom-right",
              "color": "white", "opacity": 1.0, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "watermark should produce an output file"


def test_watermark_requires_auth(client, media):
    d, src = media
    out = d / "wm_noauth.mp4"
    r = client.post(
        "/watermark",
        json={"input": str(src), "output": str(out), "text": "hi"},
    )
    assert r.status_code == 401


def test_run_stream_watermark(client, media, auth):
    d, src = media
    out = d / "wm_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "watermark", "input": str(src), "output": str(out),
              "text": "© Stream", "font_size": 20, "position": "top-left",
              "color": "yellow", "opacity": 0.8, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream watermark should produce output"


def _make_srt(path):
    """Write a minimal valid SRT subtitle file."""
    path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nTest subtitle\n\n",
        encoding="utf-8",
    )
    return path


def test_hardsub_produces_output(client, media, auth, tmp_path):
    d, src = media
    srt = _make_srt(tmp_path / "subs.srt")
    out = tmp_path / "hardsub.mp4"
    r = client.post(
        "/hardsub",
        json={"input": str(src), "subtitle": str(srt), "output": str(out),
              "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "/hardsub should produce an output file"


def test_hardsub_requires_auth(client, media, tmp_path):
    d, src = media
    srt = _make_srt(tmp_path / "subs_noauth.srt")
    out = tmp_path / "hardsub_noauth.mp4"
    r = client.post(
        "/hardsub",
        json={"input": str(src), "subtitle": str(srt), "output": str(out)},
    )
    assert r.status_code == 401


def test_run_stream_hardsub(client, media, auth, tmp_path):
    d, src = media
    srt = _make_srt(tmp_path / "subs_stream.srt")
    out = tmp_path / "hardsub_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "hardsub", "input": str(src), "subtitle": str(srt),
              "output": str(out), "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream hardsub should produce output"


def test_pip_produces_output(client, media, auth):
    d, src = media  # 320x240 clip
    out = d / "pip.mp4"
    r = client.post(
        "/pip",
        json={"input": str(src), "overlay": str(src), "output": str(out),
              "size_pct": 25, "position": "bottom-right", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "/pip should produce an output file"


def test_pip_preserves_base_dims(client, media, auth):
    d, src = media  # 320x240
    out = d / "pip_dims.mp4"
    r = client.post(
        "/pip",
        json={"input": str(src), "overlay": str(src), "output": str(out),
              "size_pct": 25, "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert _dims(out) == (320, 240)


def test_pip_requires_auth(client, media):
    d, src = media
    r = client.post(
        "/pip",
        json={"input": str(src), "overlay": str(src), "output": str(d / "pip_noauth.mp4")},
    )
    assert r.status_code == 401


def test_run_stream_pip_produces_output(client, media, auth):
    d, src = media
    out = d / "pip_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "pip", "input": str(src), "overlay": str(src),
              "output": str(out), "pip_size": 25, "position": "top-left",
              "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream pip should produce output"


def test_run_stream_pip_defaults_bottom_right(client, auth, tmp_path):
    # Regression: RunReq.position defaulted to "top-left" (timecode's value,
    # shared across the timecode/watermark/pip fields), so calling /run/stream
    # op=pip without an explicit position landed the overlay in the top-left
    # corner instead of the bottom-right default (matching the CLI + /pip
    # endpoint + build_pip_args default).
    import re
    import subprocess
    from conftest import FFMPEG

    base = tmp_path / "pip_base.mp4"
    overlay = tmp_path / "pip_overlay.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1:r=10",
         "-c:v", "libx264", str(base)],
        check=True,
    )
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=white:s=320x240:d=1:r=10",
         "-c:v", "libx264", str(overlay)],
        check=True,
    )
    out = tmp_path / "pip_default_position.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "pip", "input": str(base), "overlay": str(overlay),
              "output": str(out), "pip_size": 25, "overwrite": True},
        # no "position" field — exercises the RunReq default
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[-1]["type"] == "done"
    assert out.exists()

    def _corner_yavg(crop_expr):
        p = subprocess.run(
            [FFMPEG, "-hide_banner", "-i", str(out),
             "-vf", rf"select=eq(n\,0),crop={crop_expr},signalstats,metadata=print",
             "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        m = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", p.stdout + p.stderr)
        assert m, p.stdout + p.stderr
        return float(m.group(1))

    # Overlay is 80x60 (25% of 320 wide, -2 aspect) placed at x=230,y=170 for
    # bottom-right (W-w-10, H-h-10); sample a box fully inside that rect.
    top_left = _corner_yavg("40:40:0:0")
    bottom_right = _corner_yavg("30:30:250:180")
    assert bottom_right > 150, f"expected white overlay near bottom-right, YAVG={bottom_right}"
    assert top_left < 50, f"expected untouched black base at top-left, YAVG={top_left}"


def test_pixfmt_converts_format(client, media, auth):
    d, src = media
    out = d / "pixfmt_out.mp4"
    r = client.post(
        "/pixfmt",
        json={"input": str(src), "output": str(out), "pix_fmt": "yuv420p", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert out.exists(), "/pixfmt should produce an output file"


def test_pixfmt_requires_auth(client, media):
    d, src = media
    r = client.post(
        "/pixfmt",
        json={"input": str(src), "output": str(d / "pixfmt_noauth.mp4")},
    )
    assert r.status_code == 401


def test_run_stream_pixfmt_produces_output(client, media, auth):
    d, src = media
    out = d / "pixfmt_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "pixfmt", "input": str(src), "output": str(out),
              "pix_fmt": "yuv420p", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream pixfmt should produce output"


def test_trim_segments_joins_two_segments(client, media, auth):
    d, src = media  # 3s 320x240 clip
    out = d / "trim_segments_out.mp4"
    r = client.post(
        "/trim-segments",
        json={
            "input": str(src), "output": str(out),
            "segments_text": "0 1\n2 3",
            "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert out.exists()
    assert abs(_duration(out) - 2.0) < 0.2
    assert _dims(out) == (320, 240)


def test_trim_segments_bad_segments_400(client, media, auth):
    d, src = media
    r = client.post(
        "/trim-segments",
        json={"input": str(src), "output": str(d / "bad.mp4"), "segments_text": "not a segment"},
        headers=auth,
    )
    assert r.status_code == 400


def test_trim_segments_requires_auth(client, media):
    d, src = media
    r = client.post(
        "/trim-segments",
        json={"input": str(src), "output": str(d / "noauth.mp4"), "segments_text": "0 1"},
    )
    assert r.status_code == 401


def test_run_stream_trim_segments_produces_output(client, media, auth):
    d, src = media
    out = d / "trim_segments_stream.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_segments", "input": str(src), "output": str(out),
              "segments_text": "0 1\n2 3", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events)
    assert out.exists(), "/run/stream trim_segments should produce output"
    # Regression: the progress "total" (expected output duration) used to
    # fall through to the original 3s input clip's duration instead of the
    # joined 2s (1-0 + 3-2) segment sum, making the progress bar read ~66% at
    # completion instead of 100%.
    progress = [e for e in events if e.get("type") == "progress" and e.get("total")]
    assert progress, "expected at least one progress event with a total"
    assert abs(progress[-1]["total"] - 2.0) < 0.2


def test_trim_segments_no_audio_input(client, media_no_audio, auth):
    # Regression: build_trim_segments_args used to always emit an [0:a]atrim
    # filter, which errors out on a video-only input ("Stream specifier 'a'
    # in filter ... matches no streams"). /trim-segments must detect the
    # missing audio stream and skip the audio filter chain.
    d, src = media_no_audio
    out = d / "trim_segments_no_audio_out.mp4"
    r = client.post(
        "/trim-segments",
        json={
            "input": str(src), "output": str(out),
            "segments_text": "0 1\n2 3",
            "overwrite": True,
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert out.exists()
    assert abs(_duration(out) - 2.0) < 0.2


def test_run_stream_trim_segments_no_audio_input(client, media_no_audio, auth):
    d, src = media_no_audio
    out = d / "trim_segments_stream_no_audio.mp4"
    r = client.post(
        "/run/stream",
        json={"op": "trim_segments", "input": str(src), "output": str(out),
              "segments_text": "0 1\n2 3", "overwrite": True},
        headers=auth,
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert any(e.get("type") == "done" for e in events), r.text
    assert out.exists(), "/run/stream trim_segments should produce output for a video-only input"
