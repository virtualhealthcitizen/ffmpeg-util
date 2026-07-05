"""CLI smoke tests, mostly driven through --dry-run so no ffmpeg is required;
one real sample-encode test is skipped cleanly when ffmpeg isn't on PATH."""

import shutil

import pytest

from ffmpeg_util.cli import main


def test_convert_dry_run(capsys):
    rc = main(["convert", "in.mkv", "out.mp4", "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "in.mkv" in out and "out.mp4" in out


def test_trim_dry_run(capsys):
    rc = main(["trim", "in.mp4", "out.mp4", "--start", "5", "--duration", "10",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    assert "-ss" in capsys.readouterr().out


def test_trim_conflicting_options_errors(capsys):
    rc = main(["trim", "in.mp4", "out.mp4", "--end", "30", "--duration", "5",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_compress_dry_run(capsys):
    rc = main(["compress", "in.mp4", "out.mp4", "--crf", "20", "--width", "1280",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-crf" in out and "scale=1280" in out


def test_compress_hwaccel_dry_run(capsys):
    rc = main(["compress", "in.mp4", "out.mp4", "--crf", "20", "--hwaccel", "nvenc",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "h264_nvenc" in out and "-cq" in out and "-crf" not in out


def test_compress_hwaccel_rejects_target_size(capsys):
    rc = main(["compress", "in.mp4", "out.mp4", "--target-size", "5", "--hwaccel", "nvenc",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


def test_thumbnail_dry_run(capsys):
    rc = main(["thumbnail", "in.mp4", "out.png", "--time", "00:00:03",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    assert "out.png" in capsys.readouterr().out


def test_autocrop_dry_run(capsys):
    # Dry-run only emits the cropdetect analysis pass (the crop pass depends on
    # its result); it must exit 0 without treating "no crop detected" as failure.
    rc = main(["autocrop", "in.mp4", "out.mp4", "--limit", "16",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    assert "cropdetect=limit=16" in capsys.readouterr().out


def test_watermark_dry_run(capsys):
    rc = main(["watermark", "in.mp4", "out.mp4", "--text", "© 2024",
               "--position", "bottom-right", "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "drawtext" in out and "out.mp4" in out


def test_hardsub_dry_run(capsys):
    rc = main(["hardsub", "in.mp4", "out.mp4", "--subtitle", "subs.srt",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "subtitles=" in out and "out.mp4" in out


def test_pip_dry_run(capsys):
    rc = main(["pip", "base.mp4", "out.mp4", "--overlay", "overlay.mp4",
               "--size", "30", "--position", "top-right",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "filter_complex" in out and "overlay" in out and "out.mp4" in out


def test_chapters_dry_run(capsys):
    rc = main(["chapters", "in.mp4", "out.mp4",
               "--chapters", "0:00 Intro\n0:30 Chapter 2",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ffmetadata" in out and "out.mp4" in out


def test_trim_segments_dry_run(capsys):
    rc = main(["trim-segments", "in.mp4", "out.mp4",
               "--segments", "0 5\n10 15",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "filter_complex" in out and "concat=n=2" in out and "out.mp4" in out


def test_compress_estimate_size_rejects_dry_run(capsys):
    rc = main(["compress", "in.mp4", "out.mp4", "--crf", "28", "--estimate-size",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 1
    assert "dry-run" in capsys.readouterr().err.lower()


def test_compress_estimate_size_rejects_target_size(capsys):
    rc = main(["compress", "in.mp4", "out.mp4", "--target-size", "5", "--estimate-size",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_compress_estimate_size_real(tmp_path, capsys):
    src = tmp_path / "in.mp4"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True,
    )
    out_path = tmp_path / "out.mp4"
    rc = main(["compress", str(src), str(out_path), "--crf", "30", "--estimate-size"])
    assert rc == 0
    assert not out_path.exists()  # estimate-only: OUTPUT is never written
    out = capsys.readouterr().out
    assert "Estimated output size:" in out
