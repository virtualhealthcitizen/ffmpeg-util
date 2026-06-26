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


def test_file_missing_404(client, media, auth):
    d, _ = media
    r = client.get("/file", params={"path": str(d / "does-not-exist.png")}, headers=auth)
    assert r.status_code == 404


def test_file_requires_token(client, media):
    _, src = media
    r = client.get("/file", params={"path": str(src)})
    assert r.status_code == 401
