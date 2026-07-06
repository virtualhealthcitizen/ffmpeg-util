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


def test_compress_target_size_dry_run(capsys):
    # Dry-run never probes duration, so compress_to_size used to always raise
    # here instead of printing the two would-be encode passes.
    rc = main(["compress", "in.mp4", "out.mp4", "--target-size", "5",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-pass 1" in out and "-pass 2" in out and "out.mp4" in out


def test_fade_dry_run(capsys):
    # Same dry-run-never-probes gap as crop-aspect/target-size, hit via fade's
    # own duration probe.
    rc = main(["fade", "in.mp4", "out.mp4", "--duration", "1",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fade=t=in" in out and "out.mp4" in out


def test_contact_sheet_dry_run(capsys):
    rc = main(["contact-sheet", "in.mp4", "out.jpg",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tile=" in out and "out.jpg" in out


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


def test_crop_aspect_dry_run(capsys):
    # Dry-run never calls ffprobe, so probe_dimensions always returns None here;
    # crop_to_aspect must fall back to a placeholder instead of raising.
    rc = main(["crop-aspect", "in.mp4", "out.mp4", "--aspect", "16:9",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "crop=" in out and "out.mp4" in out


def test_trim_pct_dry_run(capsys):
    # Dry-run never calls ffprobe, so probe_duration always returns None here;
    # trim-pct crashed with "error: duration_s must be positive" on every
    # --dry-run invocation because the CLI fed a bare `dur or 0.0` straight
    # into build_trim_pct_args instead of falling back to a placeholder like
    # crop-aspect/contact-sheet/poster-frame do.
    rc = main(["trim-pct", "in.mp4", "out.mp4", "--start-pct", "10", "--end-pct", "50",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-ss" in out and "-to" in out and "out.mp4" in out


def test_poster_frame_dry_run(capsys):
    # Same dry-run-never-probes gap as crop-aspect/fade, but here it used to
    # reach real ffmpeg unfixed: without a probed duration, build_poster_frame_args
    # falls back to a raw "<pct>%" -ss value that real ffmpeg rejects outright
    # ("Invalid duration for option ss"), so the CLI command crashed on every run.
    rc = main(["poster-frame", "in.mp4", "out.png", "--percent", "25",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "-ss" in out and "%" not in out and "out.png" in out


def test_concat_reencode_dry_run(capsys):
    # Same dry-run-never-probes gap as crop-aspect, but hit via the CLI's own
    # dims-is-None check rather than a commands.py helper.
    rc = main(["concat", "in1.mp4", "in2.mp4", "-o", "out.mp4", "--reencode",
               "--ffmpeg", "ffmpeg", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "filter_complex" in out and "out.mp4" in out
    # probe_has_audio() must assume audio is present in dry-run (ffprobe is
    # never actually invoked), so the printed command uses the real aformat
    # audio path -- not the anullsrc/-shortest silent-track fallback, which
    # would misrepresent what a real run against audio-bearing inputs does.
    assert "anullsrc" not in out and "-shortest" not in out
    assert "aformat" in out


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
