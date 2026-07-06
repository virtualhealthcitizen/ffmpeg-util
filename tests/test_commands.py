"""Unit tests for command-arg builders (most need no ffmpeg binary; a few real
sample-encode tests are skipped cleanly when ffmpeg isn't on PATH)."""

import shutil

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


def test_concat_filter_requires_two_inputs():
    with pytest.raises(ValueError, match="at least two"):
        c.build_concat_filter_args(["only.mp4"], "out.mp4", 320, 240)


def test_concat_filter_requires_positive_dims():
    with pytest.raises(ValueError, match="dimensions"):
        c.build_concat_filter_args(["a.mp4", "b.mp4"], "out.mp4", 0, 240)


def test_concat_filter_structure():
    args = c.build_concat_filter_args(["a.mp4", "b.mp4"], "out.mp4", 320, 240)
    fc_idx = args.index("-filter_complex")
    fc = args[fc_idx + 1]
    assert "scale=320:240" in fc
    assert "concat=n=2:v=1:a=1" in fc
    assert "-map" in args
    assert "libx264" in args
    assert "aac" in args
    assert args[-1] == "out.mp4"


def test_concat_filter_anullsrc_for_silent_input():
    args = c.build_concat_filter_args(
        ["a.mp4", "b.mp4"], "out.mp4", 320, 240, has_audio=[True, False]
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "anullsrc" in fc


def test_concat_filter_shortest_bounds_silent_input():
    # anullsrc is an infinite source, so a silent input must be bounded by
    # -shortest or the re-encode never terminates.
    args = c.build_concat_filter_args(
        ["a.mp4", "b.mp4"], "out.mp4", 320, 240, has_audio=[True, False]
    )
    assert "-shortest" in args
    assert args[-1] == "out.mp4"


def test_concat_filter_no_shortest_when_all_have_audio():
    # Every input carries real audio -> [v] and [a] end together, so -shortest
    # (which could truncate a stream whose a/v lengths differ slightly) is omitted.
    args = c.build_concat_filter_args(
        ["a.mp4", "b.mp4"], "out.mp4", 320, 240, has_audio=[True, True]
    )
    assert "-shortest" not in args
    # Default has_audio (None -> all True) must likewise not add -shortest.
    default_args = c.build_concat_filter_args(["a.mp4", "b.mp4"], "out.mp4", 320, 240)
    assert "-shortest" not in default_args


def test_probe_has_audio_assumes_true_in_dry_run():
    # run_ffprobe never invokes ffprobe in dry-run mode (returns None), so
    # probe_has_audio must assume audio is present -- matching its sibling
    # has_audio() -- rather than silently reporting no audio. Otherwise the
    # CLI's `concat --reencode --dry-run` (the only caller that can hit
    # dry-run) prints the anullsrc/-shortest silent-track branch even for
    # real audio-bearing inputs, diverging from what the real run would do.
    runner = FfmpegRunner(ffprobe="ffprobe-sentinel-not-on-path", dry_run=True)
    assert c.probe_has_audio(runner, "in.mp4") is True


def test_concat_filter_three_inputs():
    args = c.build_concat_filter_args(["a.mp4", "b.mp4", "c.mp4"], "out.mp4", 640, 360)
    fc = args[args.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in fc
    assert args.count("-i") == 3


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


def test_compress_hwaccel_nvenc_remaps_crf_to_cq():
    args = c.build_compress_args("in.mp4", "out.mp4", crf=20, hwaccel="nvenc")
    assert args[args.index("-c:v") + 1] == "h264_nvenc"
    assert "-crf" not in args
    assert args[args.index("-cq") + 1] == "20"
    assert args[args.index("-rc") + 1] == "vbr"


def test_compress_hwaccel_qsv_remaps_crf_to_global_quality():
    args = c.build_compress_args("in.mp4", "out.mp4", hwaccel="qsv")
    assert args[args.index("-c:v") + 1] == "h264_qsv"
    assert "-crf" not in args
    assert args[args.index("-global_quality") + 1] == "23"


def test_compress_hwaccel_bitrate_path_keeps_bv_no_quality_flag():
    args = c.build_compress_args("in.mp4", "out.mp4", bitrate="2M", hwaccel="nvenc")
    assert args[args.index("-b:v") + 1] == "2M"
    assert "-cq" not in args and "-crf" not in args


def test_compress_rejects_bad_hwaccel():
    with pytest.raises(ValueError):
        c.build_compress_args("in.mp4", "out.mp4", hwaccel="cuda")


def test_estimate_compress_size_rejects_missing_duration(monkeypatch):
    # duration_s explicitly None and probe_duration unable to determine one.
    monkeypatch.setattr(c, "probe_duration", lambda runner, path: None)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-real")
    with pytest.raises(ValueError):
        c.estimate_compress_size(runner, "in.mp4", crf=28)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_estimate_compress_size_real_sample_encode(tmp_path):
    runner = FfmpegRunner(overwrite=True)
    src = tmp_path / "in.mp4"
    runner.run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src),
    ])
    result = c.estimate_compress_size(runner, str(src), crf=30, sample_seconds=2)
    assert result["estimated_bytes"] > 0
    assert result["sample_bytes"] > 0
    assert result["duration_s"] == pytest.approx(6, abs=0.5)
    assert 0 < result["sample_seconds"] <= 3  # sampled, not the full 6s


def test_waveform_args_build_filter():
    args = c.build_waveform_args("in.mp4", "wave.png", 800, 120)
    assert args[args.index("-filter_complex") + 1] == "showwavespic=s=800x120"
    assert args[args.index("-frames:v") + 1] == "1"
    assert args[-1] == "wave.png"


def test_waveform_args_reject_bad_size():
    with pytest.raises(ValueError):
        c.build_waveform_args("in.mp4", "wave.png", 0, 100)


def test_waveform_rejects_no_audio_input(monkeypatch):
    # Regression: build_waveform_args (showwavespic, an audio-only filter) was
    # called directly by the CLI/sidecar with no has_audio() guard, unlike its
    # sibling audio-only ops (loudnorm/volume/mono/sample-rate/trim-silence) —
    # a video-only input crashed ffmpeg with a cryptic filtergraph error instead
    # of the codebase's normal clear message.
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.waveform(runner, "in.mp4", "wave.png")


def test_waveform_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.waveform(runner, "in.mp4", "wave.png", 800, 120)
    assert "showwavespic=s=800x120" in capsys.readouterr().out


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


def test_crop_to_aspect_dry_run_falls_back_instead_of_raising(capsys):
    # run_ffprobe always returns None in dry-run mode (no ffprobe call is made),
    # so crop_to_aspect used to always raise here instead of printing a command.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.crop_to_aspect(runner, "in.mp4", "out.mp4", 16, 9)
    out = capsys.readouterr().out
    assert "crop=" in out and "out.mp4" in out


def test_fade_dry_run_falls_back_instead_of_raising(capsys):
    # Same dry-run-never-probes gap as crop_to_aspect: fade() used to always
    # raise here instead of printing a command.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.fade(runner, "in.mp4", "out.mp4", 1.0)
    out = capsys.readouterr().out
    assert "fade=t=in" in out and "out.mp4" in out


def test_contact_sheet_dry_run_falls_back_instead_of_raising(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.contact_sheet(runner, "in.mp4", "out.jpg")
    out = capsys.readouterr().out
    assert "tile=" in out and "out.jpg" in out


def test_poster_frame_dry_run_falls_back_instead_of_crashing(capsys):
    # Real ffmpeg rejects a raw "<pct>%" -ss value ("Invalid duration for option
    # ss"), so poster_frame() must probe a real/placeholder duration rather than
    # letting build_poster_frame_args() emit that unusable percent-syntax string.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.poster_frame(runner, "in.mp4", "out.png", percent=25.0)
    out = capsys.readouterr().out
    assert "-ss" in out and "%" not in out and "out.png" in out


def test_trim_pct_dry_run_falls_back_instead_of_raising(capsys):
    # Same dry-run-never-probes gap as crop_to_aspect/contact_sheet: trim_pct()
    # used to feed a bare `dur or 0.0` straight into build_trim_pct_args, which
    # raises "duration_s must be positive" on 0.0 instead of printing a command.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.trim_pct(runner, "in.mp4", "out.mp4", start_pct=10.0, end_pct=50.0)
    out = capsys.readouterr().out
    assert "-ss" in out and "-to" in out and "out.mp4" in out


def test_compress_to_size_dry_run_falls_back_instead_of_raising(capsys):
    # target_mb=0.5 would be "too small" against the 60s dry-run placeholder
    # duration (negative bitrate budget), so use a target that clears it.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.compress_to_size(runner, "in.mp4", "out.mp4", 5)
    out = capsys.readouterr().out
    assert "-pass 1" in out and "-pass 2" in out and "out.mp4" in out


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


def test_xfade_args_basic():
    args = c.build_xfade_args(["a.mp4", "b.mp4"], "out.mp4", offset=3.0)
    assert args.count("-i") == 2
    fc = args[args.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=1.0:offset=3.0" in fc
    assert args[-1] == "out.mp4"


def test_xfade_args_custom_transition():
    args = c.build_xfade_args(["a.mp4", "b.mp4"], "out.mp4",
                               transition="wipeleft", duration=0.5, offset=2.5)
    fc = args[args.index("-filter_complex") + 1]
    assert "transition=wipeleft" in fc
    assert "duration=0.5" in fc
    assert "offset=2.5" in fc


def test_xfade_args_requires_two():
    with pytest.raises(ValueError):
        c.build_xfade_args(["only.mp4"], "out.mp4", offset=2.0)


def test_xfade_args_rejects_nonpositive_duration():
    with pytest.raises(ValueError):
        c.build_xfade_args(["a.mp4", "b.mp4"], "out.mp4", duration=0.0, offset=2.0)


def test_xfade_args_rejects_negative_offset():
    with pytest.raises(ValueError):
        c.build_xfade_args(["a.mp4", "b.mp4"], "out.mp4", duration=1.0, offset=-1.0)


def test_xfade_concat_auto_probes_offset_from_clip1(monkeypatch, capsys):
    # Regression: the CLI's xfade-concat subcommand required --offset
    # unconditionally, unlike the UI sidecar (which auto-probes clip 1's
    # duration and derives offset = clip1_duration - transition_duration when
    # omitted) — there was no commands.py wrapper backing that behavior for
    # the CLI to call.
    monkeypatch.setattr(c, "probe_duration", lambda runner, path: 9.0)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.xfade_concat(runner, ["a.mp4", "b.mp4"], "out.mp4", duration=1.5)
    out = capsys.readouterr().out
    assert "offset=7.5" in out


def test_xfade_concat_explicit_offset_skips_probe(monkeypatch, capsys):
    def _boom(runner, path):
        raise AssertionError("probe_duration should not be called when offset is given")
    monkeypatch.setattr(c, "probe_duration", _boom)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.xfade_concat(runner, ["a.mp4", "b.mp4"], "out.mp4", offset=3.0)
    out = capsys.readouterr().out
    assert "offset=3.0" in out


def test_xfade_concat_requires_two_inputs():
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="exactly two"):
        c.xfade_concat(runner, ["only.mp4"], "out.mp4")


def test_xfade_concat_dry_run_falls_back_instead_of_raising(capsys):
    # Same dry-run-never-probes gap as crop_to_aspect/trim_pct/fade/poster_frame:
    # run_ffprobe always returns None in dry-run mode, so xfade_concat() must
    # fall back to a placeholder duration instead of raising when offset is
    # omitted and no real probe is possible.
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.xfade_concat(runner, ["a.mp4", "b.mp4"], "out.mp4")
    out = capsys.readouterr().out
    assert "xfade=" in out and "out.mp4" in out


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


def test_autorotate_args_strips_rotate_tag():
    args = c.build_autorotate_args("in.mp4", "out.mp4")
    assert "-vf" in args
    assert args[args.index("-vf") + 1] == "null"
    assert "-metadata:s:v:0" in args
    assert args[args.index("-metadata:s:v:0") + 1] == "rotate=0"
    assert "-c:a" in args
    assert args[args.index("-c:a") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_deinterlace_args_build_filter():
    args = c.build_deinterlace_args("in.mp4", "out.mp4")
    assert args[args.index("-vf") + 1] == "yadif"
    assert args[-1] == "out.mp4"


def test_sharpen_args_default():
    args = c.build_sharpen_args("in.mp4", "out.mp4")
    vf = args[args.index("-vf") + 1]
    assert "unsharp" in vf and "la=1.5" in vf
    assert args[-1] == "out.mp4"


def test_sharpen_args_custom_amount():
    args = c.build_sharpen_args("in.mp4", "out.mp4", amount=3.0)
    vf = args[args.index("-vf") + 1]
    assert "la=3.0" in vf


def test_sharpen_args_negative_softens():
    args = c.build_sharpen_args("in.mp4", "out.mp4", amount=-1.0)
    vf = args[args.index("-vf") + 1]
    assert "la=-1.0" in vf


def test_sharpen_args_rejects_out_of_range():
    with pytest.raises(ValueError):
        c.build_sharpen_args("in.mp4", "out.mp4", amount=99)


def test_denoise_args_default():
    args = c.build_denoise_args("in.mp4", "out.mp4")
    vf = args[args.index("-vf") + 1]
    assert "hqdn3d" in vf and "4" in vf
    assert args[-1] == "out.mp4"


def test_denoise_args_custom_strength():
    args = c.build_denoise_args("in.mp4", "out.mp4", strength=8.0)
    vf = args[args.index("-vf") + 1]
    assert "8.0" in vf


def test_denoise_args_rejects_zero_strength():
    with pytest.raises(ValueError):
        c.build_denoise_args("in.mp4", "out.mp4", strength=0)


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


def test_loudnorm_rejects_no_audio_input(monkeypatch):
    # Regression: loudnorm/volume/mono/sample-rate/trim-silence are audio-only
    # transforms that used to be sent straight to ffmpeg with no audio-stream
    # check, crashing with a cryptic "matches no streams" error on a video-only
    # input instead of a clear message.
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.loudnorm(runner, "in.mp4", "out.mp4")


def test_loudnorm_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.loudnorm(runner, "in.mp4", "out.mp4", -14.0)
    assert "loudnorm=I=-14.0" in capsys.readouterr().out


def test_volume_rejects_no_audio_input(monkeypatch):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.volume(runner, "in.mp4", "out.mp4", -6.0)


def test_volume_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.volume(runner, "in.mp4", "out.mp4", -6.0)
    assert "volume=-6.0dB" in capsys.readouterr().out


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


def test_scene_thumbs_args_build_select():
    args = c.build_scene_thumbs_args("in.mp4", "s_%04d.png", threshold=0.3)
    vf = args[args.index("-vf") + 1]
    assert vf == "select=gt(scene\\,0.3)"
    assert args[args.index("-fps_mode") + 1] == "vfr"
    assert args[-1] == "s_%04d.png"


def test_scene_thumbs_args_with_width():
    args = c.build_scene_thumbs_args("in.mp4", "s_%04d.png", threshold=0.2, width=320)
    vf = args[args.index("-vf") + 1]
    assert vf == "select=gt(scene\\,0.2),scale=320:-1"


def test_scene_thumbs_args_reject_bad_threshold():
    with pytest.raises(ValueError):
        c.build_scene_thumbs_args("in.mp4", "s_%04d.png", threshold=0)
    with pytest.raises(ValueError):
        c.build_scene_thumbs_args("in.mp4", "s_%04d.png", threshold=1.1)


def test_scene_thumbs_requires_pattern():
    with pytest.raises(ValueError):
        c.build_scene_thumbs_args("in.mp4", "scene.png")  # no %d token


def test_loop_args_use_stream_loop_count_minus_one():
    args = c.build_loop_args("in.mp4", "out.mp4", 3)
    assert args[args.index("-stream_loop") + 1] == "2"  # 3 plays = 2 extra loops
    assert "-c" in args and args[args.index("-c") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_loop_args_reject_zero():
    with pytest.raises(ValueError):
        c.build_loop_args("in.mp4", "out.mp4", 0)


def test_blur_region_args_build_filter():
    args = c.build_blur_region_args("in.mp4", "out.mp4", 10, 20, 80, 60, sigma=15)
    fc = args[args.index("-filter_complex") + 1]
    assert "split=2[main][tmp]" in fc
    assert "crop=80:60:10:20" in fc
    assert "gblur=sigma=15" in fc
    assert "overlay=10:20[v]" in fc
    assert args[args.index("-map") + 1] == "[v]"
    assert "-c:a" in args
    assert "copy" in args


def test_blur_region_args_reject_bad_values():
    with pytest.raises(ValueError):
        c.build_blur_region_args("in.mp4", "out.mp4", 0, 0, 0, 60)  # w=0
    with pytest.raises(ValueError):
        c.build_blur_region_args("in.mp4", "out.mp4", -1, 0, 80, 60)  # x<0
    with pytest.raises(ValueError):
        c.build_blur_region_args("in.mp4", "out.mp4", 0, 0, 80, 60, sigma=0)  # sigma<=0


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


def test_blur_pad_args_reject_bad_sigma():
    with pytest.raises(ValueError):
        c.build_blur_pad_args("in.mp4", "out.mp4", 480, 480, sigma=0)
    with pytest.raises(ValueError):
        c.build_blur_pad_args("in.mp4", "out.mp4", 480, 480, sigma=-5)


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


def test_image_to_video_args_with_audio():
    args = c.build_image_to_video_args(
        "photo.png", "out.mp4", 5.0, fps=24, audio_path="track.mp3"
    )
    assert args.count("-i") == 2
    i_indexes = [i for i, a in enumerate(args) if a == "-i"]
    assert args[i_indexes[0] + 1] == "photo.png"
    assert args[i_indexes[1] + 1] == "track.mp3"
    assert args[args.index("-t") + 1] == "5.0"  # -t still an output option
    assert args[args.index("-c:a") + 1] == "aac"
    assert "0:v" in args
    assert "1:a" in args
    assert args[-1] == "out.mp4"


def test_image_to_video_args_without_audio_has_no_audio_map():
    args = c.build_image_to_video_args("photo.png", "out.mp4", 5.0)
    assert args.count("-i") == 1
    assert "-c:a" not in args
    assert "-map" not in args


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


def test_sample_rate_rejects_no_audio_input(monkeypatch):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.sample_rate(runner, "in.mp4", "out.mp4", 22050)


def test_sample_rate_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.sample_rate(runner, "in.mp4", "out.mp4", 22050)
    assert "-ar" in capsys.readouterr().out


def test_mono_rejects_no_audio_input(monkeypatch):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.mono(runner, "in.mp4", "out.mp4")


def test_mono_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.mono(runner, "in.mp4", "out.mp4")
    assert "-ac" in capsys.readouterr().out


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
    # Regression: "none" was in VALID_DITHERS but is not a valid ffmpeg paletteuse
    # dither mode — passing it caused ffmpeg to fail with "Option dither not found".
    with pytest.raises(ValueError):
        c.make_gif(runner, "in.mp4", "out.gif", dither="none")


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


def test_timecode_args_default():
    args = c.build_timecode_args("in.mp4", "out.mp4")
    vf = args[args.index("-vf") + 1]
    assert "drawtext" in vf
    assert "pts" in vf
    assert "fontsize=24" in vf
    assert "x=10" in vf and "y=10" in vf
    assert "fontcolor=white" in vf
    assert args[-1] == "out.mp4"
    assert "-c:a" in args and "copy" in args


def test_timecode_args_custom_options():
    args = c.build_timecode_args("in.mp4", "out.mp4", font_size=36, position="bottom-right", color="yellow")
    vf = args[args.index("-vf") + 1]
    assert "fontsize=36" in vf
    assert "w-tw-10" in vf and "h-th-10" in vf
    assert "fontcolor=yellow" in vf


def test_timecode_args_rejects_small_font():
    with pytest.raises(ValueError, match="font_size"):
        c.build_timecode_args("in.mp4", "out.mp4", font_size=3)


def test_timecode_args_rejects_bad_position():
    with pytest.raises(ValueError, match="position"):
        c.build_timecode_args("in.mp4", "out.mp4", position="center")


def test_timecode_args_rejects_bad_color():
    with pytest.raises(ValueError, match="color"):
        c.build_timecode_args("in.mp4", "out.mp4", color="white; rm -rf /")


def test_compress_to_size_runs_two_passes_dry_run(capsys):
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    vkbps = c.compress_to_size(runner, "in.mp4", "out.mp4", 0.5, duration_s=5)
    assert vkbps == 672
    out = capsys.readouterr().out
    assert "-pass 1" in out and "-pass 2" in out
    assert "out.mp4" in out


def test_build_trim_silence_args_defaults():
    args = c.build_trim_silence_args("in.mp4", "out.mp4")
    assert args[0] == "-i" and args[1] == "in.mp4"
    assert "-af" in args
    af = args[args.index("-af") + 1]
    assert "silenceremove" in af
    assert "start_periods=1" in af
    assert "stop_periods=1" in af
    assert "-50.0dB" in af
    assert "0.5" in af
    assert args[-1] == "out.mp4"
    assert "-c:v" in args and "copy" in args[args.index("-c:v") + 1]


def test_build_trim_silence_args_custom():
    args = c.build_trim_silence_args("a.mp3", "b.mp3", threshold_db=-60.0, min_duration=1.0)
    af = args[args.index("-af") + 1]
    assert "-60.0dB" in af
    assert "1.0" in af
    assert args[-1] == "b.mp3"


def test_build_trim_silence_args_rejects_negative_duration():
    with pytest.raises(ValueError, match="min_duration"):
        c.build_trim_silence_args("in.mp4", "out.mp4", min_duration=-0.1)


def test_trim_silence_rejects_no_audio_input(monkeypatch):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: False)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    with pytest.raises(ValueError, match="no audio stream"):
        c.trim_silence(runner, "in.mp4", "out.mp4")


def test_trim_silence_runs_when_audio_present(monkeypatch, capsys):
    monkeypatch.setattr(c, "has_audio", lambda runner, path: True)
    runner = FfmpegRunner(ffmpeg="ffmpeg-sentinel-not-on-path", dry_run=True)
    c.trim_silence(runner, "in.mp4", "out.mp4")
    assert "silenceremove" in capsys.readouterr().out


def test_build_remux_args_uses_copy():
    args = c.build_remux_args("in.mkv", "out.mp4")
    assert args == ["-i", "in.mkv", "-c", "copy", "out.mp4"]


def test_parse_timestamp_s_accepts_seconds():
    assert c._parse_timestamp_s("90") == 90.0
    assert c._parse_timestamp_s("1.5") == 1.5


def test_parse_timestamp_s_accepts_mmss():
    assert c._parse_timestamp_s("1:30") == 90.0
    assert c._parse_timestamp_s("0:05") == 5.0


def test_parse_timestamp_s_accepts_hhmmss():
    assert c._parse_timestamp_s("1:00:00") == 3600.0
    assert c._parse_timestamp_s("0:01:30") == 90.0


def test_parse_timestamp_s_rejects_garbage():
    with pytest.raises(ValueError):
        c._parse_timestamp_s("abc")


def test_parse_chapters_text_basic():
    text = "0:00 Intro\n0:30 Chapter 2\n1:00 The End"
    chapters = c.parse_chapters_text(text)
    assert len(chapters) == 3
    assert chapters[0] == {"start_s": 0.0, "title": "Intro"}
    assert chapters[1] == {"start_s": 30.0, "title": "Chapter 2"}
    assert chapters[2] == {"start_s": 60.0, "title": "The End"}


def test_parse_chapters_text_skips_blanks_and_comments():
    text = "# a comment\n\n0:00 Start\n\n# another\n0:30 End"
    chapters = c.parse_chapters_text(text)
    assert len(chapters) == 2


def test_parse_chapters_text_sorts_by_start():
    text = "1:00 Late\n0:00 Early"
    chapters = c.parse_chapters_text(text)
    assert chapters[0]["title"] == "Early"
    assert chapters[1]["title"] == "Late"


def test_parse_chapters_text_empty_raises():
    with pytest.raises(ValueError, match="No chapters"):
        c.parse_chapters_text("   \n# only a comment\n")


def test_parse_chapters_text_missing_title_raises():
    with pytest.raises(ValueError):
        c.parse_chapters_text("0:00")


def test_write_chapters_meta(tmp_path):
    meta = tmp_path / "chaps.txt"
    chapters = [{"start_s": 0.0, "title": "Intro"}, {"start_s": 30.0, "title": "Part 2"}]
    c.write_chapters_meta(chapters, 60.0, str(meta))
    content = meta.read_text(encoding="utf-8")
    assert ";FFMETADATA1" in content
    assert "title=Intro" in content
    assert "title=Part 2" in content
    assert "START=0\n" in content
    assert "START=30000\n" in content
    assert "END=30000\n" in content
    assert "END=60000\n" in content


def test_build_chapters_args_structure():
    args = c.build_chapters_args("in.mp4", "meta.txt", "out.mp4")
    assert args[0] == "-i" and args[1] == "in.mp4"
    assert "-f" in args and args[args.index("-f") + 1] == "ffmetadata"
    assert "-map_metadata" in args and args[args.index("-map_metadata") + 1] == "1"
    assert "-map" in args and args[args.index("-map") + 1] == "0"
    assert "-c" in args and args[args.index("-c") + 1] == "copy"
    assert args[-1] == "out.mp4"


def test_parse_segments_text_basic():
    text = "0 5\n10 15\n20 25"
    segments = c.parse_segments_text(text)
    assert segments == [(0.0, 5.0), (10.0, 15.0), (20.0, 25.0)]


def test_parse_segments_text_keeps_given_order():
    text = "10 15\n0 5"
    segments = c.parse_segments_text(text)
    assert segments == [(10.0, 15.0), (0.0, 5.0)]


def test_parse_segments_text_skips_blanks_and_comments():
    text = "# a comment\n\n0 5\n\n# another\n10 15"
    segments = c.parse_segments_text(text)
    assert len(segments) == 2


def test_parse_segments_text_empty_raises():
    with pytest.raises(ValueError, match="No segments"):
        c.parse_segments_text("   \n# only a comment\n")


def test_parse_segments_text_wrong_field_count_raises():
    with pytest.raises(ValueError, match="Expected"):
        c.parse_segments_text("0 5 extra")


def test_parse_segments_text_end_before_start_raises():
    with pytest.raises(ValueError, match="End must be after start"):
        c.parse_segments_text("5 5")


def test_build_trim_segments_args_structure():
    args = c.build_trim_segments_args("in.mp4", "out.mp4", [(0.0, 5.0), (10.0, 15.0)])
    assert args[0] == "-i" and args[1] == "in.mp4"
    fc = args[args.index("-filter_complex") + 1]
    assert "trim=start=0.0:end=5.0" in fc
    assert "trim=start=10.0:end=15.0" in fc
    assert "atrim=start=0.0:end=5.0" in fc
    assert "concat=n=2:v=1:a=1[v][a]" in fc
    assert "-map" in args and "[v]" in args
    assert "[a]" in args
    assert args[-1] == "out.mp4"


def test_build_trim_segments_args_requires_a_segment():
    with pytest.raises(ValueError):
        c.build_trim_segments_args("in.mp4", "out.mp4", [])


def test_build_trim_segments_args_no_audio():
    args = c.build_trim_segments_args(
        "in.mp4", "out.mp4", [(0.0, 5.0), (10.0, 15.0)], audio=False
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "atrim" not in fc
    assert "concat=n=2:v=1:a=0[v]" in fc
    assert "[a]" not in fc
    assert "-c:a" not in args
    assert args[-1] == "out.mp4"


def test_build_remux_args_preserves_output_path():
    args = c.build_remux_args("video.mp4", "video.mov")
    assert args[0] == "-i" and args[1] == "video.mp4"
    assert args[-1] == "video.mov"


def test_build_preview_clip_args_defaults():
    args = c.build_preview_clip_args("in.mp4", "out.mp4")
    assert args[args.index("-t") + 1] == "5.0"
    vf = args[args.index("-vf") + 1]
    assert vf == "scale=320:-2"
    assert args[-1] == "out.mp4"


def test_build_preview_clip_args_custom():
    args = c.build_preview_clip_args("in.mp4", "out.mp4", seconds=10.0, width=640)
    assert args[args.index("-t") + 1] == "10.0"
    assert args[args.index("-vf") + 1] == "scale=640:-2"


def test_build_preview_clip_args_rejects_bad_seconds():
    with pytest.raises(ValueError, match="seconds"):
        c.build_preview_clip_args("in.mp4", "out.mp4", seconds=0)
    with pytest.raises(ValueError, match="seconds"):
        c.build_preview_clip_args("in.mp4", "out.mp4", seconds=-1)


def test_build_preview_clip_args_rejects_bad_width():
    with pytest.raises(ValueError, match="width"):
        c.build_preview_clip_args("in.mp4", "out.mp4", width=0)


def test_build_poster_frame_args_percent_syntax():
    # Without duration_s, ffmpeg receives the raw "<pct>%" string.
    args = c.build_poster_frame_args("in.mp4", "out.png", percent=50.0)
    assert args[args.index("-ss") + 1] == "50.0%"
    assert "-frames:v" in args
    assert args[args.index("-frames:v") + 1] == "1"
    assert args[-1] == "out.png"


def test_build_poster_frame_args_with_duration():
    # With duration_s=10, percent=25 → timestamp = 2.5 s.
    args = c.build_poster_frame_args("in.mp4", "out.png", percent=25.0, duration_s=10.0)
    assert args[args.index("-ss") + 1] == "2.5"


def test_build_poster_frame_args_with_width():
    args = c.build_poster_frame_args("in.mp4", "out.png", percent=10.0, width=640)
    assert "-vf" in args
    assert "scale=640:-1" in args[args.index("-vf") + 1]


def test_build_poster_frame_args_rejects_bad_percent():
    with pytest.raises(ValueError, match="percent"):
        c.build_poster_frame_args("in.mp4", "out.png", percent=-1)
    with pytest.raises(ValueError, match="percent"):
        c.build_poster_frame_args("in.mp4", "out.png", percent=101)


def test_build_poster_frame_args_rejects_bad_duration():
    with pytest.raises(ValueError, match="duration"):
        c.build_poster_frame_args("in.mp4", "out.png", duration_s=0)


def test_build_trim_pct_args_basic():
    # 10s clip, 25%–75% → start=2.5s, end=7.5s
    args = c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=25.0, end_pct=75.0, duration_s=10.0)
    assert "-ss" in args
    ss_val = args[args.index("-ss") + 1]
    assert float(ss_val) == pytest.approx(2.5)
    assert "-to" in args
    to_val = args[args.index("-to") + 1]
    assert float(to_val) == pytest.approx(7.5)
    assert "-i" in args
    assert args[-1] == "out.mp4"


def test_build_trim_pct_args_stream_copy_default():
    args = c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=0.0, end_pct=50.0, duration_s=10.0)
    assert "-c" in args and args[args.index("-c") + 1] == "copy"


def test_build_trim_pct_args_reencode():
    # 10s clip, 25%–75% with reencode → must use -t 5.0 (duration), not -to 7.5.
    # Input-seeking (-ss before -i) resets PTS to 0 during re-encode, so -to end_s
    # would produce end_s seconds of output instead of (end_s - start_s).
    args = c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=25.0, end_pct=75.0, duration_s=10.0, reencode=True)
    assert "-c" not in args
    assert "-to" not in args, "reencode must use -t (duration), not -to (absolute end)"
    assert "-t" in args
    t_val = args[args.index("-t") + 1]
    assert float(t_val) == pytest.approx(5.0)


def test_build_trim_pct_args_rejects_bad_start_pct():
    with pytest.raises(ValueError, match="start_pct"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=-1, end_pct=50.0, duration_s=10.0)
    with pytest.raises(ValueError, match="start_pct"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=101, end_pct=50.0, duration_s=10.0)


def test_build_trim_pct_args_rejects_bad_end_pct():
    with pytest.raises(ValueError, match="end_pct"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=0.0, end_pct=101, duration_s=10.0)


def test_build_trim_pct_args_rejects_start_ge_end():
    with pytest.raises(ValueError, match="start_pct must be less than end_pct"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=50.0, end_pct=50.0, duration_s=10.0)
    with pytest.raises(ValueError, match="start_pct must be less than end_pct"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=75.0, end_pct=25.0, duration_s=10.0)


def test_build_trim_pct_args_requires_duration():
    with pytest.raises(ValueError, match="duration_s is required"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=25.0, end_pct=75.0)


def test_build_trim_pct_args_rejects_bad_duration():
    with pytest.raises(ValueError, match="duration_s must be positive"):
        c.build_trim_pct_args("in.mp4", "out.mp4", start_pct=0.0, end_pct=50.0, duration_s=0)


def test_build_vidstab_detect_args_defaults():
    args = c.build_vidstab_detect_args("in.mp4", "out.trf")
    assert args[args.index("-i") + 1] == "in.mp4"
    vf = args[args.index("-vf") + 1]
    assert "vidstabdetect" in vf
    assert "shakiness=5" in vf
    assert "accuracy=15" in vf
    assert "out.trf" in vf
    assert args[-1] == "-"


def test_build_vidstab_detect_args_custom():
    args = c.build_vidstab_detect_args("in.mp4", "t.trf", shakiness=8, accuracy=10)
    vf = args[args.index("-vf") + 1]
    assert "shakiness=8" in vf
    assert "accuracy=10" in vf


def test_build_vidstab_detect_args_rejects_bad_shakiness():
    with pytest.raises(ValueError, match="shakiness"):
        c.build_vidstab_detect_args("in.mp4", "t.trf", shakiness=0)
    with pytest.raises(ValueError, match="shakiness"):
        c.build_vidstab_detect_args("in.mp4", "t.trf", shakiness=11)


def test_build_vidstab_detect_args_rejects_bad_accuracy():
    with pytest.raises(ValueError, match="accuracy"):
        c.build_vidstab_detect_args("in.mp4", "t.trf", accuracy=0)
    with pytest.raises(ValueError, match="accuracy"):
        c.build_vidstab_detect_args("in.mp4", "t.trf", accuracy=16)


def test_build_vidstab_transform_args_defaults():
    args = c.build_vidstab_transform_args("in.mp4", "out.mp4", "t.trf")
    assert args[args.index("-i") + 1] == "in.mp4"
    vf = args[args.index("-vf") + 1]
    assert "vidstabtransform" in vf
    assert "smoothing=10" in vf
    assert "t.trf" in vf
    assert "unsharp" in vf
    assert args[-1] == "out.mp4"


def test_build_vidstab_transform_args_custom_smoothing():
    args = c.build_vidstab_transform_args("in.mp4", "out.mp4", "t.trf", smoothing=25)
    vf = args[args.index("-vf") + 1]
    assert "smoothing=25" in vf


def test_build_vidstab_transform_args_rejects_bad_smoothing():
    with pytest.raises(ValueError, match="smoothing"):
        c.build_vidstab_transform_args("in.mp4", "out.mp4", "t.trf", smoothing=0)


def test_build_watermark_args_default():
    args = c.build_watermark_args("in.mp4", "out.mp4", text="© 2024")
    vf = args[args.index("-vf") + 1]
    assert "drawtext" in vf
    assert "© 2024" in vf
    assert "fontsize=24" in vf
    assert "w-tw-10" in vf and "h-th-10" in vf  # bottom-right
    assert "fontcolor=white" in vf
    assert args[-1] == "out.mp4"
    assert "-c:a" in args and "copy" in args


def test_build_watermark_args_positions():
    for pos, (x, y) in [
        ("top-left", ("10", "10")),
        ("top-right", ("w-tw-10", "10")),
        ("bottom-left", ("10", "h-th-10")),
        ("center", ("(w-tw)/2", "(h-th)/2")),
    ]:
        args = c.build_watermark_args("in.mp4", "out.mp4", text="hi", position=pos)
        vf = args[args.index("-vf") + 1]
        assert x in vf and y in vf, f"position={pos}: expected {x},{y} in {vf}"


def test_build_watermark_args_opacity():
    args = c.build_watermark_args("in.mp4", "out.mp4", text="hi", opacity=0.5)
    vf = args[args.index("-vf") + 1]
    assert "fontcolor=white@0.50" in vf


def test_build_watermark_args_opacity_1_no_alpha():
    args = c.build_watermark_args("in.mp4", "out.mp4", text="hi", opacity=1.0)
    vf = args[args.index("-vf") + 1]
    # Fully opaque: no @alpha suffix on color
    assert "fontcolor=white" in vf
    assert "fontcolor=white@" not in vf


def test_build_watermark_args_escapes_colon_in_text():
    args = c.build_watermark_args("in.mp4", "out.mp4", text="https://example.com")
    vf = args[args.index("-vf") + 1]
    # Colon must be escaped so drawtext doesn't treat it as option separator
    assert "https\\://example.com" in vf or "https" in vf


def test_build_watermark_args_rejects_empty_text():
    with pytest.raises(ValueError, match="text"):
        c.build_watermark_args("in.mp4", "out.mp4", text="")


def test_build_watermark_args_rejects_small_font():
    with pytest.raises(ValueError, match="font_size"):
        c.build_watermark_args("in.mp4", "out.mp4", text="hi", font_size=3)


def test_build_watermark_args_rejects_bad_position():
    with pytest.raises(ValueError, match="position"):
        c.build_watermark_args("in.mp4", "out.mp4", text="hi", position="nowhere")


def test_build_watermark_args_rejects_bad_color():
    with pytest.raises(ValueError, match="color"):
        c.build_watermark_args("in.mp4", "out.mp4", text="hi", color="white; rm -rf /")


def test_build_hardsub_args_basic():
    args = c.build_hardsub_args("in.mp4", "subs.srt", "out.mp4")
    assert args[0] == "-i" and args[1] == "in.mp4"
    vf_idx = args.index("-vf")
    assert "subtitles=" in args[vf_idx + 1]
    assert "subs.srt" in args[vf_idx + 1]
    assert args[-1] == "out.mp4"
    assert "-c:a" in args and "copy" in args


def test_build_hardsub_args_escapes_windows_path():
    args = c.build_hardsub_args("in.mp4", r"C:\Users\me\subs.srt", "out.mp4")
    vf_idx = args.index("-vf")
    vf = args[vf_idx + 1]
    assert "C\\:" in vf or "C/" in vf
    assert "\\" not in vf.replace("\\:", "").replace("\\'", "")


def test_build_hardsub_args_escapes_colon_in_path():
    args = c.build_hardsub_args("in.mp4", "/path/with:colon/subs.srt", "out.mp4")
    vf_idx = args.index("-vf")
    vf = args[vf_idx + 1]
    assert "\\:" in vf


def test_build_pip_args_two_inputs():
    args = c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4")
    assert args.count("-i") == 2
    assert args[args.index("-i") + 1] == "base.mp4"
    assert "overlay.mp4" in args
    assert args[-1] == "out.mp4"


def test_build_pip_args_filter_complex():
    args = c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4", size_pct=30, position="top-left")
    fc = args[args.index("-filter_complex") + 1]
    assert "scale=iw*30/100:-2[ov]" in fc
    assert "overlay=10:10[v]" in fc


def test_build_pip_args_bottom_right():
    args = c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4", position="bottom-right")
    fc = args[args.index("-filter_complex") + 1]
    assert "overlay=W-w-10:H-h-10[v]" in fc


def test_build_pip_args_invalid_position():
    with pytest.raises(ValueError, match="position must be"):
        c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4", position="center")


def test_build_pip_args_invalid_size():
    with pytest.raises(ValueError, match="size_pct"):
        c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4", size_pct=80)


def test_build_pip_args_maps_video():
    # overlay output must be labeled [v] and explicitly mapped so ffmpeg includes
    # the video stream — without -map [v], only audio would be in the output
    args = c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4")
    fc = args[args.index("-filter_complex") + 1]
    assert "[v]" in fc, "filter_complex overlay output must be labeled [v]"
    map_indices = [i for i, a in enumerate(args) if a == "-map"]
    mapped = [args[i + 1] for i in map_indices]
    assert "[v]" in mapped, "-map [v] required to include video in output"


def test_build_pip_args_keeps_base_audio():
    args = c.build_pip_args("base.mp4", "overlay.mp4", "out.mp4")
    assert "-map" in args
    assert "0:a?" in args


def test_build_pixfmt_args_default_format():
    args = c.build_pixfmt_args("input.mp4", "output.mp4")
    assert args[args.index("-vf") + 1] == "format=yuv420p"
    assert "-c:a" in args
    assert "copy" in args
    assert args[-1] == "output.mp4"


def test_build_pixfmt_args_custom_format():
    args = c.build_pixfmt_args("input.mp4", "output.mp4", "yuv420p10le")
    assert args[args.index("-vf") + 1] == "format=yuv420p10le"


def test_build_pixfmt_args_invalid_format_space():
    with pytest.raises(ValueError, match="Invalid pixel format"):
        c.build_pixfmt_args("input.mp4", "output.mp4", "yuv 420p")


def test_build_pixfmt_args_invalid_format_injection():
    with pytest.raises(ValueError, match="Invalid pixel format"):
        c.build_pixfmt_args("input.mp4", "output.mp4", "format=yuv420p")
