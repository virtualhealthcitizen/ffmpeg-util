"""CLI smoke tests driven through --dry-run so no ffmpeg is required."""

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
