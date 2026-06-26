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

    # contact-sheet
    p = sub.add_parser("contact-sheet", help="Tiled montage of frames sampled across a video.")
    p.add_argument("input")
    p.add_argument("output", help="Output image (e.g. sheet.png).")
    p.add_argument("--cols", type=int, default=4, help="Columns (default 4).")
    p.add_argument("--rows", type=int, default=4, help="Rows (default 4).")
    p.add_argument("--width", type=int, default=320, help="Per-tile width (default 320).")
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

    if args.command == "contact-sheet":
        commands.contact_sheet(
            runner, args.input, args.output,
            cols=args.cols, rows=args.rows, width=args.width,
        )
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
