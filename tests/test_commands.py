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


def test_waveform_args_build_filter():
    args = c.build_waveform_args("in.mp4", "wave.png", 800, 120)
    assert args[args.index("-filter_complex") + 1] == "showwavespic=s=800x120"
    assert args[args.index("-frames:v") + 1] == "1"
    assert args[-1] == "wave.png"


def test_waveform_args_reject_bad_size():
    with pytest.raises(ValueError):
        c.build_waveform_args("in.mp4", "wave.png", 0, 100)


def test_parse_aspect():
    assert c.parse_aspect("16:9") == (16, 9)
    assert c.parse_aspect("1:1") == (1, 1)
    with pytest.raises(ValueError):
        c.parse_aspect("16-9")


def test_compute_aspect_crop_wide_from_4x3():
    # 320x240 (4:3) -> 16:9 keeps width, crops height to 180 (centered)
    assert c.compute_aspect_crop(320, 240, 16, 9) == (320, 180, 0, 30)


def test_compute_aspect_crop_square_and_even():
    cw, ch, x, y = c.compute_aspect_crop(320, 240, 1, 1)
    assert cw == 240 and ch == 240  # square = min side
    assert cw % 2 == 0 and ch % 2 == 0
    assert x == 40 and y == 0


def test_fps_args_build_filter():
    args = c.build_fps_args("in.mp4", "out.mp4", 15)
    assert args[args.index("-vf") + 1] == "fps=15"
    assert args[-1] == "out.mp4"


def test_fps_args_reject_nonpositive():
    with pytest.raises(ValueError):
        c.build_fps_args("in.mp4", "out.mp4", 0)


def test_eq_args_build_filter():
    args = c.build_eq_args("in.mp4", "out.mp4", brightness=0.3, contrast=1.2, saturation=0.5)
    vf = args[args.index("-vf") + 1]
    assert vf == "eq=brightness=0.3:contrast=1.2:saturation=0.5"


def test_eq_args_defaults_are_noop():
    args = c.build_eq_args("in.mp4", "out.mp4")
    assert args[args.index("-vf") + 1] == "eq=brightness=0.0:contrast=1.0:saturation=1.0"


def test_vstack_args_two_inputs():
    args = c.build_vstack_args(["a.mp4", "b.mp4"], "out.mp4")
    assert args.count("-i") == 2
    assert "[0:v][1:v]vstack=inputs=2[v]" in args
    assert args[-1] == "out.mp4"


def test_vstack_args_requires_two():
    with pytest.raises(ValueError):
        c.build_vstack_args(["only.mp4"], "out.mp4")


def test_hstack_args_two_inputs():
    args = c.build_hstack_args(["a.mp4", "b.mp4"], "out.mp4")
    assert args.count("-i") == 2
    assert "[0:v][1:v]hstack=inputs=2[v]" in args
    assert args[-1] == "out.mp4"


def test_hstack_args_requires_two():
    with pytest.raises(ValueError):
        c.build_hstack_args(["only.mp4"], "out.mp4")


def test_boomerang_args_forward_then_reverse():
    args = c.build_boomerang_args("in.mp4", "out.mp4")
    fc = args[args.index("-filter_complex") + 1]
    assert "reverse" in fc and "concat=n=2:v=1" in fc
    assert "-an" in args
    assert args[args.index("-map") + 1] == "[v]"


def test_require_output_extension():
    c.require_output_extension("out.mp4")  # ok, no raise
    c.require_output_extension("dir/clip.gif")
    with pytest.raises(ValueError):
        c.require_output_extension("output")  # no extension
    with pytest.raises(ValueError):
        c.require_output_extension("C:\\path\\to\\output")


def test_require_output_dir(tmp_path):
    c.require_output_dir("out.mp4")  # no dir component -> ok
    c.require_output_dir(str(tmp_path / "out.mp4"))  # existing dir -> ok
    with pytest.raises(ValueError):
        c.require_output_dir(str(tmp_path / "nope" / "out.mp4"))


def test_require_sequence_pattern():
    c.require_sequence_pattern("f_%04d.png")  # ok
    c.require_sequence_pattern("f_%d.png")
    with pytest.raises(ValueError):
        c.require_sequence_pattern("frame.png")  # no token


def test_extract_frames_requires_pattern():
    with pytest.raises(ValueError):
        c.build_extract_frames_args("in.mp4", "frames.png", every=10)  # no %d


def test_thumbnail_multi_requires_pattern():
    with pytest.raises(ValueError):
        c.build_thumbnail_args("in.mp4", "thumb.png", count=4)  # needs %d
    # single frame is fine without a pattern
    c.build_thumbnail_args("in.mp4", "thumb.png", count=1)


def test_grayscale_args_build_filter():
    args = c.build_grayscale_args("in.mp4", "out.mp4")
    assert args[args.index("-vf") + 1] == "hue=s=0"
    assert args[-1] == "out.mp4"


def test_invert_args_build_filter():
    args = c.build_invert_args("in.mp4", "out.mp4")
    assert args[args.index("-vf") + 1] == "negate"
    assert args[-1] == "out.mp4"


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


def test_loudnorm_args_build_filter():
    args = c.build_loudnorm_args("in.mp4", "out.mp4", -14.0)
    af = args[args.index("-af") + 1]
    assert af.startswith("loudnorm=I=-14.0:")
    assert "TP=-1.5" in af and "LRA=11" in af
    assert args[args.index("-c:v") + 1] == "copy"


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


def test_blur_pad_args_build_filter():
    args = c.build_blur_pad_args("in.mp4", "out.mp4", 1080, 1920, sigma=15)
    fc = args[args.index("-filter_complex") + 1]
    assert "split=2[bg][fg]" in fc
    assert "gblur=sigma=15" in fc
    assert "overlay=(W-w)/2:(H-h)/2[v]" in fc
    assert args[args.index("-map") + 1] == "[v]"


def test_blur_pad_args_reject_bad_size():
    with pytest.raises(ValueError):
        c.build_blur_pad_args("in.mp4", "out.mp4", 0, 100)


def test_image_to_video_args_build():
    args = c.build_image_to_video_args("photo.png", "out.mp4", 5.0, fps=24)
    assert args[:2] == ["-loop", "1"]
    assert args[args.index("-i") + 1] == "photo.png"
    assert args[args.index("-t") + 1] == "5.0"
    assert args[args.index("-r") + 1] == "24"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[-1] == "out.mp4"


def test_image_to_video_args_reject_bad_values():
    with pytest.raises(ValueError):
        c.build_image_to_video_args("photo.png", "out.mp4", 0)
    with pytest.raises(ValueError):
        c.build_image_to_video_args("photo.png", "out.mp4", 5.0, fps=0)


def test_pad_args_build_filter():
    args = c.build_pad_args("in.mp4", "o.mp4", 640, 480)
    vf = args[args.index("-vf") + 1]
    assert "scale=640:480:force_original_aspect_ratio=decrease" in vf
    assert "pad=640:480:(ow-iw)/2:(oh-ih)/2" in vf


def test_pad_args_reject_bad_values():
    with pytest.raises(ValueError):
        c.build_pad_args("in.mp4", "o.mp4", 0, 480)


def test_title_args_set_metadata():
    args = c.build_title_args("in.mp4", "out.mp4", "My Clip")
    assert args[args.index("-metadata") + 1] == "title=My Clip"
    assert args[args.index("-c") + 1] == "copy"


def test_sample_rate_args():
    args = c.build_sample_rate_args("in.mp4", "out.mp4", 22050)
    assert args[args.index("-ar") + 1] == "22050"
    assert args[args.index("-c:v") + 1] == "copy"


def test_sample_rate_args_reject_nonpositive():
    with pytest.raises(ValueError):
        c.build_sample_rate_args("in.mp4", "out.mp4", 0)


def test_mono_args_downmix():
    args = c.build_mono_args("in.mp4", "out.mp4")
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_mute_args_strip_audio():
    args = c.build_mute_args("in.mp4", "out.mp4")
    assert "-an" in args
    assert args[args.index("-c") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_replace_audio_args_map_and_copy():
    args = c.build_replace_audio_args("vid.mp4", "music.mp3", "out.mp4")
    # both inputs, in order
    first_i = args.index("-i")
    assert args[first_i + 1] == "vid.mp4"
    assert args[args.index("-i", first_i + 1) + 1] == "music.mp3"
    # video from input 0, audio from input 1
    maps = [args[i + 1] for i, a in enumerate(args) if a == "-map"]
    assert maps == ["0:v:0", "1:a:0"]
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-c:a") + 1] == "aac"
    assert "-shortest" in args
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


def test_parse_cropdetect_takes_last_suggestion():
    # cropdetect logs one crop= line per frame; the last is the most stable.
    text = (
        "[Parsed_cropdetect_0 @ 0x1] x1:0 y1:30 ... crop=320:160:0:40\n"
        "[Parsed_cropdetect_0 @ 0x1] x1:0 y1:30 ... crop=320:180:0:30\n"
    )
    assert c.parse_cropdetect(text) == (320, 180, 0, 30)


def test_parse_cropdetect_returns_none_when_absent():
    assert c.parse_cropdetect("") is None
    assert c.parse_cropdetect("no crop suggestions here") is None


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


def test_make_gif_duration_is_output_option_in_encode_pass(capsys):
    # Regression: when duration is set, -t must come AFTER both -i args in the
    # encode pass so ffmpeg treats it as an output option (limits the GIF length).
    # Placing -t between the two -i args makes it an input option for the palette,
    # which causes the GIF to run from start to EOF instead of for `duration` seconds.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.make_gif(runner, "in.mp4", "out.gif", fps=12, width=480, start="5", duration="3")
    lines = [l for l in capsys.readouterr().out.strip().split("\n") if l]
    assert len(lines) == 2, "expected two ffmpeg calls (palettegen + encode)"
    encode_tokens = lines[1].split()
    i_indices = [i for i, t in enumerate(encode_tokens) if t == "-i"]
    t_indices = [i for i, t in enumerate(encode_tokens) if t == "-t"]
    assert len(i_indices) == 2, "encode pass needs both input and palette -i"
    assert t_indices, "-t must appear in the encode pass"
    last_i = max(i_indices)
    for t_idx in t_indices:
        assert t_idx > last_i, "-t must come after both -i args (output option, not palette input option)"


def test_make_gif_rejects_bad_inputs():
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", fps=0)
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", width=0)
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", dither="bogus")


def test_make_gif_dither_in_encode_pass(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.make_gif(runner, "in.mp4", "out.gif", dither="bayer")
    lines = [l for l in capsys.readouterr().out.strip().split("\n") if l]
    assert len(lines) == 2
    assert "paletteuse=dither=bayer" in lines[1]
    assert "paletteuse=dither=bayer" not in lines[0]  # palettegen pass unchanged


def test_make_gif_loop_in_encode_pass(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.make_gif(runner, "in.mp4", "out.gif", loop=-1)
    lines = [l for l in capsys.readouterr().out.strip().split("\n") if l]
    assert len(lines) == 2
    encode_tokens = lines[1].split()
    assert "-loop" in encode_tokens
    assert encode_tokens[encode_tokens.index("-loop") + 1] == "-1"


def test_make_gif_defaults_dither_and_loop(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.make_gif(runner, "in.mp4", "out.gif")
    lines = [l for l in capsys.readouterr().out.strip().split("\n") if l]
    assert "paletteuse=dither=sierra2_4a" in lines[1]
    encode_tokens = lines[1].split()
    assert encode_tokens[encode_tokens.index("-loop") + 1] == "0"


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
