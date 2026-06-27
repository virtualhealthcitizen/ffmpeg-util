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


def test_fade_args_with_audio():
    args = c.build_fade_args("in.mp4", "out.mp4", 1.0, 5.0, audio=True)
    vf = args[args.index("-vf") + 1]
    assert "fade=t=in:st=0:d=1.0" in vf
    assert "fade=t=out:st=4.000:d=1.0" in vf
    af = args[args.index("-af") + 1]
    assert "afade=t=in" in af and "afade=t=out" in af


def test_fade_args_without_audio_and_validation():
    args = c.build_fade_args("in.mp4", "out.mp4", 1.0, 5.0, audio=False)
    assert "-af" not in args
    with pytest.raises(ValueError):
        c.build_fade_args("in.mp4", "out.mp4", 0, 5.0)
    with pytest.raises(ValueError):
        c.build_fade_args("in.mp4", "out.mp4", 1.0, 0)


def test_volume_args_build_filter():
    args = c.build_volume_args("in.mp4", "out.mp4", -6.0)
    assert args[args.index("-af") + 1] == "volume=-6.0dB"
    assert args[args.index("-c:v") + 1] == "copy"


def test_reverse_args_with_audio():
    args = c.build_reverse_args("in.mp4", "out.mp4", audio=True)
    fc = args[args.index("-filter_complex") + 1]
    assert "reverse" in fc and "areverse" in fc
    assert args.count("-map") == 2


def test_reverse_args_without_audio():
    args = c.build_reverse_args("in.mp4", "out.mp4", audio=False)
    assert args[args.index("-vf") + 1] == "reverse"
    assert "-an" in args and "-filter_complex" not in args


def test_extract_frames_args_build_select():
    args = c.build_extract_frames_args("in.mp4", "f_%04d.png", every=30)
    vf = args[args.index("-vf") + 1]
    assert vf == "select=not(mod(n\\,30))"
    assert args[args.index("-fps_mode") + 1] == "vfr"
    assert args[-1] == "f_%04d.png"


def test_extract_frames_args_reject_zero():
    with pytest.raises(ValueError):
        c.build_extract_frames_args("in.mp4", "f_%04d.png", every=0)


def test_loop_args_use_stream_loop_count_minus_one():
    args = c.build_loop_args("in.mp4", "out.mp4", 3)
    assert args[args.index("-stream_loop") + 1] == "2"  # 3 plays = 2 extra loops
    assert "-c" in args and args[args.index("-c") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_loop_args_reject_zero():
    with pytest.raises(ValueError):
        c.build_loop_args("in.mp4", "out.mp4", 0)


def test_pad_args_build_filter():
    args = c.build_pad_args("in.mp4", "o.mp4", 640, 480)
    vf = args[args.index("-vf") + 1]
    assert "scale=640:480:force_original_aspect_ratio=decrease" in vf
    assert "pad=640:480:(ow-iw)/2:(oh-ih)/2" in vf


def test_pad_args_reject_bad_values():
    with pytest.raises(ValueError):
        c.build_pad_args("in.mp4", "o.mp4", 0, 480)


def test_mute_args_strip_audio():
    args = c.build_mute_args("in.mp4", "out.mp4")
    assert "-an" in args
    assert args[args.index("-c") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_crop_args_build_filter():
    args = c.build_crop_args("in.mp4", "o.mp4", 160, 120, 10, 20)
    assert args[args.index("-vf") + 1] == "crop=160:120:10:20"
    assert args[-1] == "o.mp4"


def test_crop_args_reject_bad_values():
    with pytest.raises(ValueError):
        c.build_crop_args("in.mp4", "o.mp4", 0, 100)
    with pytest.raises(ValueError):
        c.build_crop_args("in.mp4", "o.mp4", 100, 100, x=-1)


def test_transform_args_map_to_filters():
    assert c.build_transform_args("in.mp4", "o.mp4", "rotate-cw")[3] == "transpose=1"
    assert c.build_transform_args("in.mp4", "o.mp4", "rotate-ccw")[3] == "transpose=2"
    assert c.build_transform_args("in.mp4", "o.mp4", "rotate-180")[3] == "transpose=2,transpose=2"
    assert c.build_transform_args("in.mp4", "o.mp4", "hflip")[3] == "hflip"
    assert c.build_transform_args("in.mp4", "o.mp4", "vflip")[3] == "vflip"


def test_transform_args_rejects_unknown_op():
    with pytest.raises(ValueError):
        c.build_transform_args("in.mp4", "o.mp4", "barrel-roll")


def test_atempo_chain_decomposes_out_of_range_factors():
    assert c.atempo_chain(1.5) == "atempo=1.500000"
    assert c.atempo_chain(4) == "atempo=2.000000,atempo=2.000000"
    assert c.atempo_chain(0.25) == "atempo=0.500000,atempo=0.500000"


def test_atempo_chain_rejects_nonpositive():
    with pytest.raises(ValueError):
        c.atempo_chain(0)


def test_build_speed_args_with_audio():
    args = c.build_speed_args("in.mp4", "out.mp4", 2.0, audio=True)
    fc = args[args.index("-filter_complex") + 1]
    assert "setpts=0.500000*PTS" in fc
    assert "atempo=2.000000" in fc
    assert args.count("-map") == 2


def test_build_speed_args_without_audio():
    args = c.build_speed_args("in.mp4", "out.mp4", 0.5, audio=False)
    assert "-an" in args
    assert "-filter_complex" not in args
    assert args[args.index("-vf") + 1] == "setpts=2.000000*PTS"


def test_change_speed_rejects_bad_factor():
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError):
        c.change_speed(runner, "in.mp4", "out.mp4", 0)


def test_gif_filter_string():
    assert c.gif_filter(12, 480) == "fps=12,scale=480:-1:flags=lanczos"


def test_make_gif_two_pass_dry_run(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.make_gif(runner, "in.mp4", "out.gif", fps=15, width=320, start="1", duration="2")
    out = capsys.readouterr().out
    assert "palettegen" in out and "paletteuse" in out
    assert "out.gif" in out
    assert "-ss 1" in out and "-t 2" in out


def test_make_gif_rejects_bad_inputs():
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", fps=0)
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", width=0)


def test_contact_sheet_args_builds_tile_filter():
    # 6 tiles over a 5s clip -> fps = 6/5 = 1.2
    args = c.build_contact_sheet_args("in.mp4", "sheet.png", duration_s=5, cols=3, rows=2, width=160)
    vf = args[args.index("-vf") + 1]
    assert "fps=1.200000" in vf
    assert "scale=160:-1" in vf
    assert "tile=3x2" in vf
    assert args[-1] == "sheet.png"
    assert args[args.index("-frames:v") + 1] == "1"


def test_contact_sheet_args_rejects_bad_inputs():
    with pytest.raises(ValueError):
        c.build_contact_sheet_args("in.mp4", "s.png", duration_s=5, cols=0, rows=2)
    with pytest.raises(ValueError):
        c.build_contact_sheet_args("in.mp4", "s.png", duration_s=0, cols=2, rows=2)


def test_target_video_bitrate_math():
    # 0.5 MB over 5s with 128 kbps audio -> 800 - 128 = 672 kbps video
    assert c.target_video_bitrate_kbps(0.5, 5, 128) == 672
    assert c.target_video_bitrate_kbps(10, 60, 0) == int(10 * 8000 / 60)


def test_target_video_bitrate_rejects_bad_inputs():
    with pytest.raises(ValueError):
        c.target_video_bitrate_kbps(1, 0)  # zero duration
    with pytest.raises(ValueError):
        c.target_video_bitrate_kbps(0.01, 100, 128)  # target too small


def test_compress_to_size_runs_two_passes_dry_run(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    vkbps = c.compress_to_size(runner, "in.mp4", "out.mp4", 0.5, duration_s=5)
    assert vkbps == 672
    out = capsys.readouterr().out
    assert "-pass 1" in out and "-pass 2" in out
    assert "out.mp4" in out
