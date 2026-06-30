"""argparse-based command-line interface for ffmpeg-util."""

import argparse
import sys

from . import __version__, commands
from .errors import FfmpegError
from .runner import FfmpegRunner


def _add_global_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ffmpeg", help="Path to the ffmpeg binary (overrides PATH/env).")
    p.add_argument("--ffprobe", help="Path to the ffprobe binary (overrides PATH/env).")
    p.add_argument("-y", "--overwrite", action="store_true", help="Overwrite output files.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ffmpeg command instead of running it.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ffmpeg-util",
        description="Scriptable helpers around ffmpeg for common media chores.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # probe
    p = sub.add_parser("probe", help="Show stream/format info via ffprobe.")
    p.add_argument("input")
    p.add_argument("--json", action="store_true", help="Emit raw ffprobe JSON.")
    _add_global_flags(p)

    # convert
    p = sub.add_parser("convert", help="Convert container/codec or extract audio.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--vcodec", help="Video codec (default: copy).")
    p.add_argument("--acodec", help="Audio codec (default: copy).")
    p.add_argument("--extract-audio", action="store_true", help="Drop video, keep audio.")
    _add_global_flags(p)

    # trim
    p = sub.add_parser("trim", help="Cut a clip by start/end/duration.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--start", help="Start time (HH:MM:SS or seconds).")
    p.add_argument("--end", help="End time (mutually exclusive with --duration).")
    p.add_argument("--duration", help="Clip length (mutually exclusive with --end).")
    p.add_argument("--reencode", action="store_true", help="Re-encode for frame accuracy.")
    _add_global_flags(p)

    # concat
    p = sub.add_parser("concat", help="Join multiple files (same codec/params).")
    p.add_argument("inputs", nargs="+", help="Two or more input files.")
    p.add_argument("-o", "--output", required=True, help="Output file.")
    _add_global_flags(p)

    # thumbnail
    p = sub.add_parser("thumbnail", help="Extract a frame or several thumbnails.")
    p.add_argument("input")
    p.add_argument("output", help="Output image; use %%d in the name when --count>1.")
    p.add_argument("--time", default="00:00:01", help="Timestamp for a single frame.")
    p.add_argument("--count", type=int, default=1, help="Number of thumbnails.")
    p.add_argument("--width", type=int, help="Scale width (keeps aspect).")
    _add_global_flags(p)

    # trim-pct
    p = sub.add_parser("trim-pct", help="Trim a clip by start/end as percentages of the total duration.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--start-pct", type=float, default=0.0,
                   help="Start position as %% of total duration (default 0).")
    p.add_argument("--end-pct", type=float, default=100.0,
                   help="End position as %% of total duration (default 100).")
    p.add_argument("--reencode", action="store_true",
                   help="Re-encode for frame-accurate cuts (slower; default is stream-copy).")
    _add_global_flags(p)

    # poster-frame
    p = sub.add_parser("poster-frame", help="Extract a single frame at a percentage of the duration.")
    p.add_argument("input")
    p.add_argument("output", help="Output image (e.g. poster.png).")
    p.add_argument("--percent", type=float, default=10.0,
                   help="Position as %% of total duration (default 10).")
    p.add_argument("--width", type=int, help="Scale width in pixels (keeps aspect).")
    _add_global_flags(p)

    # waveform
    p = sub.add_parser("waveform", help="Render the audio waveform as an image.")
    p.add_argument("input")
    p.add_argument("output", help="Output image (e.g. wave.png).")
    p.add_argument("--width", type=int, default=1000, help="Image width (default 1000).")
    p.add_argument("--height", type=int, default=200, help="Image height (default 200).")
    _add_global_flags(p)

    # crop-aspect
    p = sub.add_parser("crop-aspect", help="Center-crop to an aspect ratio (e.g. 16:9).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--aspect", required=True, help="Target aspect, e.g. 16:9, 9:16, 1:1.")
    _add_global_flags(p)

    # autocrop (remove black bars)
    p = sub.add_parser("autocrop", help="Detect and remove black bars (cropdetect).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--limit", type=int, default=24,
                   help="Black threshold 0-255 (higher = more aggressive; default 24).")
    _add_global_flags(p)

    # fps (resample frame rate)
    p = sub.add_parser("fps", help="Change frame rate without changing speed.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--fps", type=float, required=True, help="Target frames per second.")
    _add_global_flags(p)

    # hstack (side by side)
    p = sub.add_parser("hstack", help="Place two equal-height videos side by side.")
    p.add_argument("inputs", nargs=2, help="Two input files (same height).")
    p.add_argument("-o", "--output", required=True, help="Output file.")
    _add_global_flags(p)

    # vstack (stacked)
    p = sub.add_parser("vstack", help="Stack two equal-width videos vertically.")
    p.add_argument("inputs", nargs=2, help="Two input files (same width).")
    p.add_argument("-o", "--output", required=True, help="Output file.")
    _add_global_flags(p)

    # xfade-concat (crossfade transition)
    p = sub.add_parser("xfade-concat", help="Crossfade-concatenate two clips.")
    p.add_argument("inputs", nargs=2, help="Two input files.")
    p.add_argument("-o", "--output", required=True, help="Output file.")
    p.add_argument("--transition", default="fade",
                   help="xfade transition name (default: fade).")
    p.add_argument("--duration", type=float, default=1.0,
                   help="Transition duration in seconds (default: 1.0).")
    p.add_argument("--offset", type=float, required=True,
                   help="Second at which the transition starts (typically "
                        "clip1_duration - transition_duration).")
    _add_global_flags(p)

    # image-to-video
    p = sub.add_parser("image-to-video", help="Make a video from a still image.")
    p.add_argument("input", help="Input image (e.g. photo.png).")
    p.add_argument("output")
    p.add_argument("--seconds", type=float, required=True, help="Output duration in seconds.")
    p.add_argument("--fps", type=int, default=30, help="Frame rate (default 30).")
    _add_global_flags(p)

    # eq (color adjust)
    p = sub.add_parser("eq", help="Adjust brightness / contrast / saturation.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--brightness", type=float, default=0.0, help="-1.0..1.0 (default 0).")
    p.add_argument("--contrast", type=float, default=1.0, help="0..2+ (default 1).")
    p.add_argument("--saturation", type=float, default=1.0, help="0..3 (default 1).")
    _add_global_flags(p)

    # boomerang
    p = sub.add_parser("boomerang", help="Play forward then reversed (video only).")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # grayscale
    p = sub.add_parser("grayscale", help="Desaturate the video to grayscale.")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # invert
    p = sub.add_parser("invert", help="Invert the video's colors (photo-negative).")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # auto-orient
    p = sub.add_parser("auto-orient", help="Bake rotation metadata into pixels and strip the tag.")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # deinterlace
    p = sub.add_parser("deinterlace", help="Deinterlace a video (yadif filter).")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # sharpen
    p = sub.add_parser("sharpen", help="Sharpen or soften via unsharp mask (positive=sharpen, negative=soften).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--amount", type=float, default=1.5,
                   help="Luma strength: >0 sharpens, <0 softens, 0 no-op (default 1.5).")
    _add_global_flags(p)

    # denoise
    p = sub.add_parser("denoise", help="Reduce noise via hqdn3d (higher strength = more smoothing).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--strength", type=float, default=4.0,
                   help="Noise reduction strength 1–10 (default 4).")
    _add_global_flags(p)

    # stabilize
    p = sub.add_parser("stabilize", help="Stabilize shaky video via two-pass vidstab (detect + transform).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--shakiness", type=int, default=5,
                   help="Motion aggressiveness 1–10 (default 5; use 8–10 for very shaky footage).")
    p.add_argument("--smoothing", type=int, default=10,
                   help="Smoothing window in frames (default 10; higher = steadier but wider virtual crop).")
    _add_global_flags(p)

    # fade
    p = sub.add_parser("fade", help="Fade in from / out to black (video + audio).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--duration", type=float, default=1.0, help="Fade length in seconds (each end).")
    _add_global_flags(p)

    # loudnorm
    p = sub.add_parser("loudnorm", help="Normalize loudness to a target (EBU R128).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--target", type=float, default=-16.0, help="Integrated loudness target in LUFS (default -16).")
    _add_global_flags(p)

    # volume
    p = sub.add_parser("volume", help="Adjust audio loudness by a dB gain.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--gain", type=float, required=True, help="Gain in dB (e.g. -6 or 3). Use --gain=-6 for negatives.")
    _add_global_flags(p)

    # reverse
    p = sub.add_parser("reverse", help="Play a clip backwards (video + audio).")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # frames
    p = sub.add_parser("frames", help="Extract frames as an image sequence.")
    p.add_argument("input")
    p.add_argument("output", help="Output pattern, e.g. frame_%%04d.png")
    p.add_argument("--every", type=int, default=1, help="Keep every Nth frame (default 1).")
    _add_global_flags(p)

    # scene-thumbs
    p = sub.add_parser("scene-thumbs", help="Extract one thumbnail per scene cut.")
    p.add_argument("input")
    p.add_argument("output", help="Output pattern, e.g. scene_%%04d.png")
    p.add_argument("--threshold", type=float, default=0.3,
                   help="Scene-change score threshold 0–1 (lower = more frames, default 0.3).")
    p.add_argument("--width", type=int, default=None, help="Scale output to this width (height auto).")
    _add_global_flags(p)

    # loop
    p = sub.add_parser("loop", help="Repeat the input N times (stream-copy).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--count", type=int, required=True, help="Total number of plays (>=1).")
    _add_global_flags(p)

    # pad
    p = sub.add_parser("pad", help="Letterbox into a target frame (scale + pad).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--width", type=int, required=True, help="Target frame width.")
    p.add_argument("--height", type=int, required=True, help="Target frame height.")
    _add_global_flags(p)

    # blur-region
    p = sub.add_parser("blur-region", help="Blur a rectangular region of the video (Gaussian).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--x", type=int, default=0, help="Left edge of the region (default 0).")
    p.add_argument("--y", type=int, default=0, help="Top edge of the region (default 0).")
    p.add_argument("--width", type=int, required=True, help="Region width in pixels.")
    p.add_argument("--height", type=int, required=True, help="Region height in pixels.")
    p.add_argument("--sigma", type=float, default=10, help="Gaussian blur strength (default 10).")
    _add_global_flags(p)

    # blur-pad
    p = sub.add_parser("blur-pad", help="Fit into a frame over a blurred background fill.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--width", type=int, required=True, help="Target frame width.")
    p.add_argument("--height", type=int, required=True, help="Target frame height.")
    p.add_argument("--sigma", type=float, default=20, help="Background blur strength (default 20).")
    _add_global_flags(p)

    # title (set metadata title)
    p = sub.add_parser("title", help="Set (or clear) the title metadata tag.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--title", default="", help="Title text (empty clears it).")
    _add_global_flags(p)

    # sample-rate
    p = sub.add_parser("sample-rate", help="Resample audio to a sample rate (Hz).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--rate", type=int, required=True, help="Target sample rate, e.g. 44100.")
    _add_global_flags(p)

    # mono
    p = sub.add_parser("mono", help="Downmix audio to a single (mono) channel.")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # trim-silence
    p = sub.add_parser("trim-silence", help="Remove leading and trailing silence (silenceremove).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--threshold", type=float, default=-50.0,
                   help="Silence threshold in dB (default -50). Use --threshold=-60 for negatives.")
    p.add_argument("--min-duration", type=float, default=0.5,
                   help="Minimum silence run in seconds to strip (default 0.5).")
    _add_global_flags(p)

    # mute
    p = sub.add_parser("mute", help="Strip the audio track (keep video).")
    p.add_argument("input")
    p.add_argument("output")
    _add_global_flags(p)

    # replace-audio
    p = sub.add_parser("replace-audio", help="Replace a video's audio with an external file.")
    p.add_argument("input", help="Input video.")
    p.add_argument("output")
    p.add_argument("--audio", required=True, help="Audio file to use as the new track.")
    _add_global_flags(p)

    # crop
    p = sub.add_parser("crop", help="Crop a rectangle from the video.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--width", type=int, required=True, help="Crop width.")
    p.add_argument("--height", type=int, required=True, help="Crop height.")
    p.add_argument("--x", type=int, default=0, help="Left offset (default 0).")
    p.add_argument("--y", type=int, default=0, help="Top offset (default 0).")
    _add_global_flags(p)

    # transform
    p = sub.add_parser("transform", help="Rotate or flip a video.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--op", required=True,
                   choices=["rotate-cw", "rotate-ccw", "rotate-180", "hflip", "vflip"],
                   help="Transform to apply.")
    _add_global_flags(p)

    # speed
    p = sub.add_parser("speed", help="Change playback speed (>1 faster, <1 slower).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--factor", type=float, required=True, help="Speed factor, e.g. 2 (2x) or 0.5 (half).")
    _add_global_flags(p)

    # gif
    p = sub.add_parser("gif", help="Export an animated GIF (palette two-pass).")
    p.add_argument("input")
    p.add_argument("output", help="Output .gif")
    p.add_argument("--fps", type=int, default=12, help="Frames per second (default 12).")
    p.add_argument("--width", type=int, default=480, help="Output width (default 480).")
    p.add_argument("--start", help="Start time (HH:MM:SS or seconds).")
    p.add_argument("--duration", help="Clip length.")
    p.add_argument("--dither", default="sierra2_4a",
                   choices=list(commands.VALID_DITHERS),
                   help="Dither algorithm for paletteuse (default sierra2_4a).")
    p.add_argument("--loop", type=int, default=0,
                   help="GIF loop count: 0=infinite (default), -1=no loop.")
    _add_global_flags(p)

    # contact-sheet
    p = sub.add_parser("contact-sheet", help="Tiled montage of frames sampled across a video.")
    p.add_argument("input")
    p.add_argument("output", help="Output image (e.g. sheet.png).")
    p.add_argument("--cols", type=int, default=4, help="Columns (default 4).")
    p.add_argument("--rows", type=int, default=4, help="Rows (default 4).")
    p.add_argument("--width", type=int, default=320, help="Per-tile width (default 320).")
    _add_global_flags(p)

    # timecode
    p = sub.add_parser("timecode", help="Burn a running HH:MM:SS.ms timecode into the video.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--font-size", type=int, default=24, help="Font size in points (default 24).")
    p.add_argument(
        "--position", default="top-left",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
        help="Overlay corner (default top-left).",
    )
    p.add_argument("--color", default="white",
                   help="Text color: a name (white, yellow) or hex #rrggbb (default white).")
    _add_global_flags(p)

    # watermark
    p = sub.add_parser("watermark", help="Burn a static text watermark onto the video (drawtext).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--text", required=True, help="Watermark text to burn in.")
    p.add_argument("--font-size", type=int, default=24, help="Font size in points (default 24).")
    p.add_argument(
        "--position", default="bottom-right",
        choices=["top-left", "top-right", "bottom-left", "bottom-right", "center"],
        help="Overlay corner (default bottom-right).",
    )
    p.add_argument("--color", default="white",
                   help="Text color: a name (white, yellow) or hex #rrggbb (default white).")
    p.add_argument("--opacity", type=float, default=1.0,
                   help="Text opacity 0.0–1.0 (default 1.0, fully opaque).")
    _add_global_flags(p)

    # hardsub
    p = sub.add_parser("hardsub", help="Burn subtitle text into a video (hardsub).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--subtitle", required=True, help="Subtitle file (SRT, ASS, WebVTT).")
    _add_global_flags(p)

    # remux
    p = sub.add_parser("remux", help="Change container without re-encoding (-c copy).")
    p.add_argument("input")
    p.add_argument("output", help="Output file; extension sets the container (e.g. .mp4, .mkv).")
    _add_global_flags(p)

    # preview-clip
    p = sub.add_parser("preview-clip", help="Export a short downscaled preview (first N seconds).")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--seconds", type=float, default=5.0, help="Clip duration in seconds (default 5).")
    p.add_argument("--width", type=int, default=320,
                   help="Output width in pixels, height scales automatically (default 320).")
    _add_global_flags(p)

    # compress
    p = sub.add_parser("compress", help="Compress and/or resize a video.")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--crf", type=int, help="Quality (lower=better, default 23).")
    p.add_argument("--bitrate", help="Target video bitrate, e.g. 2M (vs --crf).")
    p.add_argument("--target-size", type=float, metavar="MB",
                   help="Target output size in MB via two-pass encoding (overrides --crf/--bitrate).")
    p.add_argument("--width", type=int, help="Scale width.")
    p.add_argument("--height", type=int, help="Scale height.")
    p.add_argument("--vcodec", default="libx264", help="Video codec.")
    p.add_argument("--preset", default="medium", help="x264/x265 preset.")
    _add_global_flags(p)

    return parser


def _runner(args: argparse.Namespace) -> FfmpegRunner:
    return FfmpegRunner(
        ffmpeg=getattr(args, "ffmpeg", None),
        ffprobe=getattr(args, "ffprobe", None),
        dry_run=getattr(args, "dry_run", False),
        verbose=getattr(args, "verbose", False),
        overwrite=getattr(args, "overwrite", False),
    )


def _dispatch(args: argparse.Namespace) -> int:
    runner = _runner(args)

    # Every command except probe writes an output file; catch a missing extension
    # early with a clear message instead of ffmpeg's cryptic muxer error.
    out = getattr(args, "output", None)
    if out is not None:
        commands.require_output_extension(out)
        commands.require_output_dir(out)

    if args.command == "probe":
        out = commands.probe(runner, args.input, as_json=args.json)
        if out:
            print(out)
        return 0

    if args.command == "convert":
        ff = commands.build_convert_args(
            args.input, args.output,
            vcodec=args.vcodec, acodec=args.acodec, extract_audio=args.extract_audio,
        )
        runner.run_ffmpeg(ff)
        return 0

    if args.command == "trim":
        ff = commands.build_trim_args(
            args.input, args.output,
            start=args.start, end=args.end, duration=args.duration, reencode=args.reencode,
        )
        runner.run_ffmpeg(ff)
        return 0

    if args.command == "concat":
        commands.concat(runner, args.inputs, args.output)
        return 0

    if args.command == "thumbnail":
        ff = commands.build_thumbnail_args(
            args.input, args.output,
            time=args.time, count=args.count, width=args.width,
        )
        runner.run_ffmpeg(ff)
        return 0

    if args.command == "trim-pct":
        dur = commands.probe_duration(runner, args.input)
        if dur is None and not runner.dry_run:
            print("Could not probe duration; cannot compute percentage timestamps.")
            return 1
        runner.run_ffmpeg(commands.build_trim_pct_args(
            args.input, args.output,
            start_pct=args.start_pct, end_pct=args.end_pct,
            duration_s=dur or 0.0,
            reencode=args.reencode,
        ))
        return 0

    if args.command == "poster-frame":
        runner.run_ffmpeg(commands.build_poster_frame_args(
            args.input, args.output, percent=args.percent, width=args.width,
        ))
        return 0

    if args.command == "waveform":
        runner.run_ffmpeg(commands.build_waveform_args(
            args.input, args.output, width=args.width, height=args.height))
        return 0

    if args.command == "crop-aspect":
        aw, ah = commands.parse_aspect(args.aspect)
        commands.crop_to_aspect(runner, args.input, args.output, aw, ah)
        return 0

    if args.command == "autocrop":
        crop = commands.autocrop(runner, args.input, args.output, limit=args.limit)
        if crop is None and not runner.dry_run:
            print("Could not detect a crop region (no black bars found?).")
            return 1
        return 0

    if args.command == "fps":
        runner.run_ffmpeg(commands.build_fps_args(args.input, args.output, args.fps))
        return 0

    if args.command == "hstack":
        runner.run_ffmpeg(commands.build_hstack_args(args.inputs, args.output))
        return 0

    if args.command == "vstack":
        runner.run_ffmpeg(commands.build_vstack_args(args.inputs, args.output))
        return 0

    if args.command == "xfade-concat":
        runner.run_ffmpeg(commands.build_xfade_args(
            args.inputs, args.output,
            transition=args.transition,
            duration=args.duration,
            offset=args.offset,
        ))
        return 0

    if args.command == "image-to-video":
        runner.run_ffmpeg(commands.build_image_to_video_args(
            args.input, args.output, args.seconds, fps=args.fps))
        return 0

    if args.command == "eq":
        runner.run_ffmpeg(commands.build_eq_args(
            args.input, args.output,
            brightness=args.brightness, contrast=args.contrast, saturation=args.saturation,
        ))
        return 0

    if args.command == "boomerang":
        runner.run_ffmpeg(commands.build_boomerang_args(args.input, args.output))
        return 0

    if args.command == "grayscale":
        runner.run_ffmpeg(commands.build_grayscale_args(args.input, args.output))
        return 0

    if args.command == "invert":
        runner.run_ffmpeg(commands.build_invert_args(args.input, args.output))
        return 0

    if args.command == "auto-orient":
        runner.run_ffmpeg(commands.build_autorotate_args(args.input, args.output))
        return 0

    if args.command == "deinterlace":
        runner.run_ffmpeg(commands.build_deinterlace_args(args.input, args.output))
        return 0

    if args.command == "sharpen":
        runner.run_ffmpeg(commands.build_sharpen_args(args.input, args.output, args.amount))
        return 0

    if args.command == "denoise":
        runner.run_ffmpeg(commands.build_denoise_args(args.input, args.output, args.strength))
        return 0

    if args.command == "stabilize":
        commands.stabilize(runner, args.input, args.output,
                           shakiness=args.shakiness, smoothing=args.smoothing)
        return 0

    if args.command == "fade":
        commands.fade(runner, args.input, args.output, args.duration)
        return 0

    if args.command == "loudnorm":
        runner.run_ffmpeg(commands.build_loudnorm_args(args.input, args.output, args.target))
        return 0

    if args.command == "volume":
        runner.run_ffmpeg(commands.build_volume_args(args.input, args.output, args.gain))
        return 0

    if args.command == "reverse":
        commands.reverse_media(runner, args.input, args.output)
        return 0

    if args.command == "frames":
        runner.run_ffmpeg(commands.build_extract_frames_args(args.input, args.output, args.every))
        return 0

    if args.command == "scene-thumbs":
        runner.run_ffmpeg(commands.build_scene_thumbs_args(
            args.input, args.output, threshold=args.threshold, width=args.width))
        return 0

    if args.command == "loop":
        runner.run_ffmpeg(commands.build_loop_args(args.input, args.output, args.count))
        return 0

    if args.command == "pad":
        runner.run_ffmpeg(commands.build_pad_args(args.input, args.output, args.width, args.height))
        return 0

    if args.command == "blur-region":
        runner.run_ffmpeg(commands.build_blur_region_args(
            args.input, args.output, args.x, args.y, args.width, args.height, sigma=args.sigma))
        return 0

    if args.command == "blur-pad":
        runner.run_ffmpeg(commands.build_blur_pad_args(
            args.input, args.output, args.width, args.height, args.sigma))
        return 0

    if args.command == "title":
        runner.run_ffmpeg(commands.build_title_args(args.input, args.output, args.title))
        return 0

    if args.command == "sample-rate":
        runner.run_ffmpeg(commands.build_sample_rate_args(args.input, args.output, args.rate))
        return 0

    if args.command == "mono":
        runner.run_ffmpeg(commands.build_mono_args(args.input, args.output))
        return 0

    if args.command == "trim-silence":
        runner.run_ffmpeg(commands.build_trim_silence_args(
            args.input, args.output,
            threshold_db=args.threshold,
            min_duration=args.min_duration,
        ))
        return 0

    if args.command == "mute":
        runner.run_ffmpeg(commands.build_mute_args(args.input, args.output))
        return 0

    if args.command == "replace-audio":
        runner.run_ffmpeg(commands.build_replace_audio_args(
            args.input, args.audio, args.output))
        return 0

    if args.command == "crop":
        runner.run_ffmpeg(commands.build_crop_args(
            args.input, args.output, args.width, args.height, args.x, args.y))
        return 0

    if args.command == "transform":
        runner.run_ffmpeg(commands.build_transform_args(args.input, args.output, args.op))
        return 0

    if args.command == "speed":
        commands.change_speed(runner, args.input, args.output, args.factor)
        return 0

    if args.command == "gif":
        commands.make_gif(
            runner, args.input, args.output,
            fps=args.fps, width=args.width, start=args.start, duration=args.duration,
            dither=args.dither, loop=args.loop,
        )
        return 0

    if args.command == "contact-sheet":
        commands.contact_sheet(
            runner, args.input, args.output,
            cols=args.cols, rows=args.rows, width=args.width,
        )
        return 0

    if args.command == "timecode":
        runner.run_ffmpeg(commands.build_timecode_args(
            args.input, args.output,
            font_size=args.font_size, position=args.position, color=args.color,
        ))
        return 0

    if args.command == "watermark":
        runner.run_ffmpeg(commands.build_watermark_args(
            args.input, args.output,
            text=args.text, font_size=args.font_size,
            position=args.position, color=args.color, opacity=args.opacity,
        ))
        return 0

    if args.command == "hardsub":
        runner.run_ffmpeg(commands.build_hardsub_args(
            args.input, args.subtitle, args.output))
        return 0

    if args.command == "remux":
        runner.run_ffmpeg(commands.build_remux_args(args.input, args.output))
        return 0

    if args.command == "preview-clip":
        runner.run_ffmpeg(commands.build_preview_clip_args(
            args.input, args.output, seconds=args.seconds, width=args.width,
        ))
        return 0

    if args.command == "compress":
        if args.target_size is not None:
            if args.crf is not None or args.bitrate is not None:
                raise ValueError("Pass only one of --target-size / --crf / --bitrate.")
            commands.compress_to_size(
                runner, args.input, args.output, args.target_size,
                vcodec=args.vcodec, preset=args.preset,
            )
            return 0
        ff = commands.build_compress_args(
            args.input, args.output,
            crf=args.crf, bitrate=args.bitrate, width=args.width, height=args.height,
            vcodec=args.vcodec, preset=args.preset,
        )
        runner.run_ffmpeg(ff)
        return 0

    return 2  # unreachable: argparse enforces a valid subcommand


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (FfmpegError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, FfmpegError) and exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
