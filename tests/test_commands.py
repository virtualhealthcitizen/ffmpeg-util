"""Unit tests for command-arg builders. No ffmpeg binary required."""

import pytest

from ffmpeg_util import commands as c
from ffmpeg_util.runner import FfmpegRunner


def test_convert_defaults_to_stream_copy():
    args = c.build_convert_args("in.mkv", "out.mp4")
    assert args == ["-i", "in.mkv", "-c:v", "copy", "-c:a", "copy", "out.mp4"]


def test_convert_extract_audio():
    args = c.build_convert_args("in.mp4", "out.mp3", extract_audio=True, acodec="libmp3lame")
    assert "-vn" in args
    assert args[args.index("-c:a") + 1] == "libmp3lame"
    assert args[-1] == "out.mp3"


def test_convert_custom_codecs():
    args = c.build_convert_args("in.mp4", "out.mkv", vcodec="libx265", acodec="aac")
    assert args[args.index("-c:v") + 1] == "libx265"
    assert args[args.index("-c:a") + 1] == "aac"


def test_trim_with_duration_seeks_before_input():
    args = c.build_trim_args("in.mp4", "out.mp4", start="10", duration="5")
    assert args[:2] == ["-ss", "10"]
    assert "-t" in args and args[args.index("-t") + 1] == "5"
    assert "-c" in args  # stream copy by default


def test_trim_with_end_uses_to():
    args = c.build_trim_args("in.mp4", "out.mp4", start="0", end="30")
    assert args[args.index("-to") + 1] == "30"


def test_trim_reencode_drops_copy():
    args = c.build_trim_args("in.mp4", "out.mp4", start="0", duration="5", reencode=True)
    assert "copy" not in args


def test_trim_rejects_end_and_duration_together():
    with pytest.raises(ValueError):
        c.build_trim_args("in.mp4", "out.mp4", end="30", duration="5")


def test_concat_requires_two_inputs():
    with pytest.raises(ValueError):
        c.build_concat_args(["only.mp4"], "out.mp4", "list.txt")


def test_concat_uses_demuxer():
    args = c.build_concat_args(["a.mp4", "b.mp4"], "out.mp4", "list.txt")
    assert args[:2] == ["-f", "concat"]
    assert args[-1] == "out.mp4"


def test_write_concat_list_escapes_quotes(tmp_path):
    list_file = tmp_path / "list.txt"
    c.write_concat_list(["o'brien.mp4", "plain.mp4"], str(list_file))
    content = list_file.read_text(encoding="utf-8")
    assert "o'\\''brien.mp4" in content
    assert content.count("file '") == 2


def test_probe_duration_dry_run_returns_none():
    # In dry-run, run_ffprobe returns None, so no duration is available.
    runner = FfmpegRunner(ffprobe="ffprobe-sentinel-not-on-path", dry_run=True)
    assert c.probe_duration(runner, "in.mp4") is None


def test_concat_orchestration_dry_run(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.concat(runner, ["a.mp4", "b.mp4"], "joined.mp4")
    out = capsys.readouterr().out
    assert "-f concat" in out
    assert "joined.mp4" in out


def test_thumbnail_single_frame():
    args = c.build_thumbnail_args("in.mp4", "out.png", time="00:00:05", width=320)
    assert args[:2] == ["-ss", "00:00:05"]
    assert "-frames:v" in args and args[args.index("-frames:v") + 1] == "1"
    assert "scale=320:-1" in args


def test_thumbnail_multiple_uses_filter():
    args = c.build_thumbnail_args("in.mp4", "out%d.png", count=4)
    assert "thumbnail" in args
    assert args[args.index("-frames:v") + 1] == "4"


def test_thumbnail_rejects_zero_count():
    with pytest.raises(ValueError):
        c.build_thumbnail_args("in.mp4", "out.png", count=0)


def test_compress_defaults_to_crf_23():
    args = c.build_compress_args("in.mp4", "out.mp4")
    assert args[args.index("-crf") + 1] == "23"
    assert args[args.index("-c:v") + 1] == "libx264"


def test_compress_bitrate_path():
    args = c.build_compress_args("in.mp4", "out.mp4", bitrate="2M")
    assert args[args.index("-b:v") + 1] == "2M"
    assert "-crf" not in args


def test_compress_rejects_crf_and_bitrate():
    with pytest.raises(ValueError):
        c.build_compress_args("in.mp4", "out.mp4", crf=20, bitrate="2M")


def test_compress_scale_filter():
    args = c.build_compress_args("in.mp4", "out.mp4", width=1280)
    assert "scale=1280:-1" in args
