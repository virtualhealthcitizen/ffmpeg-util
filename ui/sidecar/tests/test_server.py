"""End-to-end integration tests for the sidecar against real ffmpeg."""

import json


def _sse_events(text: str) -> list:
    return [
        json.loads(line[len("data:"):].strip())
        for line in text.splitlines()
        if line.startswith("data:")
    ]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_probe_requires_token(client, media):
    _, src = media
    r = client.post("/probe", json={"input": str(src)})
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
