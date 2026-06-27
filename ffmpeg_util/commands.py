"""Command builders: pure functions that turn options into ffmpeg arg lists.

Keeping argument construction separate from execution makes every command
unit-testable without ffmpeg installed (build the args, assert on them) and lets
the runner handle dry-run/overwrite/verbose uniformly.
"""

import json
import os
import tempfile
from typing import Sequence

from .runner import FfmpegRunner

# Container -> sensible default codecs for re-encode paths.
_AUDIO_ONLY_EXT = {".mp3", ".aac", ".m4a", ".wav", ".flac", ".ogg", ".opus"}


def probe(runner: FfmpegRunner, path: str, *, as_json: bool = False) -> str:
    """Return ffprobe output for ``path`` as pretty JSON or a short summary."""
    args = [
        "-loglevel", "error",
        "-show_format",
        "-show_streams",
        "-print_format", "json",
        path,
    ]
    proc = runner.run_ffprobe(args)
    if proc is None:  # dry-run
        return ""
    data = json.loads(proc.stdout or "{}")
    if as_json:
        return json.dumps(data, indent=2)
    return _summarize_probe(data, path)


def _summarize_probe(data: dict, path: str) -> str:
    fmt = data.get("format", {})
    lines = [f"{path}"]
    duration = fmt.get("duration")
    if duration:
        lines.append(f"  duration: {float(duration):.2f}s")
    if fmt.get("format_long_name"):
        lines.append(f"  format:   {fmt['format_long_name']}")
    if fmt.get("bit_rate"):
        lines.append(f"  bitrate:  {int(fmt['bit_rate']) // 1000} kb/s")
    for s in data.get("streams", []):
        kind = s.get("codec_type", "?")
        codec = s.get("codec_name", "?")
        extra = ""
        if kind == "video":
            extra = f" {s.get('width')}x{s.get('height')} {s.get('r_frame_rate', '')}".rstrip()
        elif kind == "audio":
            extra = f" {s.get('sample_rate', '')}Hz {s.get('channels', '')}ch".rstrip()
        lines.append(f"  stream {s.get('index')}: {kind} ({codec}){extra}")
    return "\n".join(lines)


def probe_duration(runner: FfmpegRunner, path: str) -> float | None:
    """Return the media duration in seconds via ffprobe, or None if unavailable.

    Used to turn ffmpeg's ``out_time`` progress into a percentage.
    """
    proc = runner.run_ffprobe(
        ["-loglevel", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path]
    )
    if proc is None:
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def build_convert_args(
    input_path: str,
    output_path: str,
    *,
    vcodec: str | None = None,
    acodec: str | None = None,
    extract_audio: bool = False,
) -> list[str]:
    """Build args for a container/codec conversion or audio extraction."""
    args = ["-i", input_path]
    if extract_audio:
        args += ["-vn"]
        if acodec:
            args += ["-c:a", acodec]
    else:
        args += ["-c:v", vcodec] if vcodec else ["-c:v", "copy"]
        args += ["-c:a", acodec] if acodec else ["-c:a", "copy"]
    args.append(output_path)
    return args


def build_trim_args(
    input_path: str,
    output_path: str,
    *,
    start: str | None = None,
    end: str | None = None,
    duration: str | None = None,
    reencode: bool = False,
) -> list[str]:
    """Build args to cut a clip.

    ``start``/``end``/``duration`` accept ffmpeg time syntax (``HH:MM:SS`` or
    seconds). ``end`` and ``duration`` are mutually exclusive. Stream-copy by
    default (fast, keyframe-aligned); pass ``reencode=True`` for frame-accuracy.
    """
    if end is not None and duration is not None:
        raise ValueError("Pass only one of end / duration, not both.")

    # -ss before -i is fast (input seek); accurate enough with re-encode.
    args: list[str] = []
    if start is not None:
        args += ["-ss", start]
    args += ["-i", input_path]
    if duration is not None:
        args += ["-t", duration]
    elif end is not None:
        args += ["-to", end]
    args += [] if reencode else ["-c", "copy"]
    args.append(output_path)
    return args


def build_concat_args(
    inputs: Sequence[str],
    output_path: str,
    list_file: str,
) -> list[str]:
    """Build args for the concat demuxer. ``list_file`` is the path to a
    pre-written manifest (see :func:`write_concat_list`)."""
    if len(inputs) < 2:
        raise ValueError("concat needs at least two input files.")
    return [
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path,
    ]


def write_concat_list(inputs: Sequence[str], list_file: str) -> None:
    """Write a concat-demuxer manifest, escaping single quotes per ffmpeg rules.

    Paths are made absolute: ffmpeg resolves relative entries against the
    manifest's own directory (often a temp dir), not the caller's cwd, so a bare
    ``clip.mp4`` would otherwise be looked up in the wrong place.
    """
    with open(list_file, "w", encoding="utf-8") as fh:
        for path in inputs:
            safe = os.path.abspath(path).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")


def concat(runner: FfmpegRunner, inputs: Sequence[str], output_path: str) -> None:
    """Join ``inputs`` into ``output_path`` via the concat demuxer.

    Handles the temp manifest lifecycle so callers (CLI, sidecar) don't repeat it.
    """
    fd, list_file = tempfile.mkstemp(suffix=".txt", prefix="ffconcat_")
    os.close(fd)
    try:
        write_concat_list(inputs, list_file)
        runner.run_ffmpeg(build_concat_args(inputs, output_path, list_file))
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass


def build_thumbnail_args(
    input_path: str,
    output_path: str,
    *,
    time: str = "00:00:01",
    count: int = 1,
    width: int | None = None,
) -> list[str]:
    """Build args for a single frame (``count==1``) or an evenly-spaced grid.

    For ``count==1`` we seek to ``time`` and grab one frame. For ``count>1`` we
    use the ``thumbnail`` filter to pick representative frames; ``output_path``
    should contain a ``%d`` pattern in that case.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    args: list[str] = []
    if count == 1:
        args += ["-ss", time, "-i", input_path, "-frames:v", "1"]
        if width:
            args += ["-vf", f"scale={width}:-1"]
    else:
        vf = f"thumbnail,scale={width}:-1" if width else "thumbnail"
        args += ["-i", input_path, "-vf", vf, "-frames:v", str(count)]
    args.append(output_path)
    return args


def target_video_bitrate_kbps(target_mb: float, duration_s: float, audio_kbps: int = 128) -> int:
    """Video bitrate (kbps) to hit ``target_mb`` over ``duration_s``.

    Uses decimal units (1 MB = 1,000,000 bytes; 1 kbps = 1000 bits/s) so it lines
    up with how ffmpeg interprets ``-b:v``. Subtracts the audio budget.
    """
    if duration_s <= 0:
        raise ValueError("duration must be > 0 to compute a target bitrate")
    kbps = target_mb * 8000.0 / duration_s - audio_kbps
    if kbps < 1:
        raise ValueError("target size too small for this duration and audio bitrate")
    return int(kbps)


def compress_to_size(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    target_mb: float,
    *,
    duration_s: float | None = None,
    vcodec: str = "libx264",
    preset: str = "medium",
    audio_kbps: int = 128,
) -> int:
    """Two-pass encode ``input_path`` to roughly ``target_mb`` megabytes.

    Returns the chosen video bitrate (kbps). Handles the passlog file lifecycle.
    """
    if duration_s is None:
        duration_s = probe_duration(runner, input_path)
    if not duration_s:
        raise ValueError("could not determine input duration for target-size encoding")
    vkbps = target_video_bitrate_kbps(target_mb, duration_s, audio_kbps)

    fd, log = tempfile.mkstemp(prefix="ff2pass_")
    os.close(fd)
    common = ["-c:v", vcodec, "-preset", preset, "-b:v", f"{vkbps}k", "-passlogfile", log]
    try:
        # Pass 1: analysis only, no audio, discard output.
        runner.run_ffmpeg(["-y", "-i", input_path, *common, "-pass", "1", "-an", "-f", "null", os.devnull])
        # Pass 2: real encode with audio.
        runner.run_ffmpeg(["-y", "-i", input_path, *common, "-pass", "2",
                           "-c:a", "aac", "-b:a", f"{audio_kbps}k", output_path])
    finally:
        for suffix in ("", "-0.log", "-0.log.mbtree", ".log", ".log.mbtree"):
            try:
                os.remove(log + suffix)
            except OSError:
                pass
    return vkbps


def gif_filter(fps: int, width: int) -> str:
    """Shared filter chain for GIF passes: resample fps + high-quality scale."""
    return f"fps={fps},scale={width}:-1:flags=lanczos"


def make_gif(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    fps: int = 12,
    width: int = 480,
    start: str | None = None,
    duration: str | None = None,
) -> None:
    """Export an animated GIF using a two-pass palette (palettegen/paletteuse)
    for far better quality than a naive single pass. Optional trim via
    ``start``/``duration``."""
    if fps < 1:
        raise ValueError("fps must be >= 1")
    if width < 1:
        raise ValueError("width must be >= 1")
    seek = ["-ss", start] if start is not None else []
    dur = ["-t", duration] if duration is not None else []
    filt = gif_filter(fps, width)

    fd, palette = tempfile.mkstemp(suffix=".png", prefix="ffgifpal_")
    os.close(fd)
    try:
        runner.run_ffmpeg([*seek, "-i", input_path, *dur, "-vf", f"{filt},palettegen", "-y", palette])
        runner.run_ffmpeg([
            *seek, "-i", input_path, *dur, "-i", palette,
            "-lavfi", f"{filt} [x];[x][1:v] paletteuse", "-y", output_path,
        ])
    finally:
        try:
            os.remove(palette)
        except OSError:
            pass


def atempo_chain(factor: float) -> str:
    """Build an `atempo` filter chain for ``factor`` speed.

    ffmpeg's atempo only accepts 0.5–2.0, so larger/smaller factors are split
    into a product of in-range steps (e.g. 4x -> atempo=2.0,atempo=2.0).
    """
    if factor <= 0:
        raise ValueError("factor must be > 0")
    steps: list[float] = []
    f = factor
    while f > 2.0:
        steps.append(2.0)
        f /= 2.0
    while f < 0.5:
        steps.append(0.5)
        f /= 0.5
    steps.append(f)
    return ",".join(f"atempo={s:.6f}" for s in steps)


def build_speed_args(input_path: str, output_path: str, factor: float, *, audio: bool = True) -> list[str]:
    """Build args to change playback speed by ``factor`` (>1 faster, <1 slower).

    Video PTS is scaled by 1/factor; audio (if present) is retimed with atempo.
    """
    if factor <= 0:
        raise ValueError("factor must be > 0")
    setpts = f"setpts={1 / factor:.6f}*PTS"
    if audio:
        fc = f"[0:v]{setpts}[v];[0:a]{atempo_chain(factor)}[a]"
        return ["-i", input_path, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", output_path]
    return ["-i", input_path, "-vf", setpts, "-an", output_path]


def has_audio(runner: FfmpegRunner, path: str) -> bool:
    """True if ``path`` has at least one audio stream (assumes True in dry-run)."""
    proc = runner.run_ffprobe(
        ["-loglevel", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", path]
    )
    if proc is None:
        return True
    return bool((proc.stdout or "").strip())


def change_speed(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    factor: float,
    *,
    audio: bool | None = None,
) -> None:
    """Re-time ``input_path`` by ``factor``, retiming audio when present."""
    if factor <= 0:
        raise ValueError("factor must be > 0")
    if audio is None:
        audio = has_audio(runner, input_path)
    runner.run_ffmpeg(build_speed_args(input_path, output_path, factor, audio=audio))


# Orientation transforms -> ffmpeg video filter. transpose swaps width/height
# for the 90° rotations; 180 and flips preserve dimensions.
TRANSFORM_FILTERS = {
    "rotate-cw": "transpose=1",
    "rotate-ccw": "transpose=2",
    "rotate-180": "transpose=2,transpose=2",
    "hflip": "hflip",
    "vflip": "vflip",
}


def build_fade_args(
    input_path: str, output_path: str, fade_s: float, total_s: float, *, audio: bool = True
) -> list[str]:
    """Build args for a ``fade_s``-second fade in (from black) and fade out (to
    black) at the start and end of a ``total_s``-long clip; audio fades too."""
    if fade_s <= 0:
        raise ValueError("fade duration must be > 0")
    if total_s <= 0:
        raise ValueError("total duration must be > 0")
    out_start = max(0.0, total_s - fade_s)
    vf = f"fade=t=in:st=0:d={fade_s},fade=t=out:st={out_start:.3f}:d={fade_s}"
    if audio:
        af = f"afade=t=in:st=0:d={fade_s},afade=t=out:st={out_start:.3f}:d={fade_s}"
        return ["-i", input_path, "-vf", vf, "-af", af, output_path]
    return ["-i", input_path, "-vf", vf, output_path]


def fade(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    fade_s: float,
    *,
    total_s: float | None = None,
    audio: bool | None = None,
) -> None:
    """Apply a fade in/out, probing duration and audio presence when not given."""
    if total_s is None:
        total_s = probe_duration(runner, input_path)
    if not total_s:
        raise ValueError("could not determine input duration for fade")
    if audio is None:
        audio = has_audio(runner, input_path)
    runner.run_ffmpeg(build_fade_args(input_path, output_path, fade_s, total_s, audio=audio))


def build_volume_args(input_path: str, output_path: str, gain_db: float) -> list[str]:
    """Build args to adjust audio loudness by ``gain_db`` decibels (video copied)."""
    return ["-i", input_path, "-c:v", "copy", "-af", f"volume={gain_db}dB", output_path]


def build_reverse_args(input_path: str, output_path: str, *, audio: bool = True) -> list[str]:
    """Build args to play a clip backwards (``reverse`` video, ``areverse`` audio).

    Note: the reverse filters buffer the whole stream in memory — fine for short
    clips, heavy for long ones.
    """
    if audio:
        fc = "[0:v]reverse[v];[0:a]areverse[a]"
        return ["-i", input_path, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", output_path]
    return ["-i", input_path, "-vf", "reverse", "-an", output_path]


def reverse_media(
    runner: FfmpegRunner, input_path: str, output_path: str, *, audio: bool | None = None
) -> None:
    """Reverse ``input_path``, retiming audio when present."""
    if audio is None:
        audio = has_audio(runner, input_path)
    runner.run_ffmpeg(build_reverse_args(input_path, output_path, audio=audio))


def build_extract_frames_args(input_path: str, output_pattern: str, every: int = 1) -> list[str]:
    """Build args to extract frames as an image sequence, keeping every ``every``th
    frame. ``output_pattern`` should contain a printf token, e.g. ``frame_%04d.png``."""
    if every < 1:
        raise ValueError("every must be >= 1")
    # The comma inside mod() must be escaped so it isn't read as a filter separator.
    return ["-i", input_path, "-vf", f"select=not(mod(n\\,{every}))", "-fps_mode", "vfr", output_pattern]


def build_loop_args(input_path: str, output_path: str, count: int) -> list[str]:
    """Build args to repeat the input ``count`` times (total plays).

    ffmpeg's ``-stream_loop`` is the number of *extra* loops, so we pass
    ``count - 1``. Stream-copies, so it's fast.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    return ["-stream_loop", str(count - 1), "-i", input_path, "-c", "copy", output_path]


def build_pad_args(input_path: str, output_path: str, width: int, height: int) -> list[str]:
    """Build args to letterbox into a ``width``x``height`` frame: scale to fit
    (preserving aspect), then pad with black bars, centered."""
    if width < 1 or height < 1:
        raise ValueError("pad width and height must be >= 1")
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    return ["-i", input_path, "-vf", vf, output_path]


def build_mute_args(input_path: str, output_path: str) -> list[str]:
    """Build args to strip the audio track (stream-copies video, drops audio)."""
    return ["-i", input_path, "-c", "copy", "-an", output_path]


def build_crop_args(
    input_path: str, output_path: str, width: int, height: int, x: int = 0, y: int = 0
) -> list[str]:
    """Build args to crop a ``width``x``height`` rectangle at offset (``x``, ``y``)."""
    if width < 1 or height < 1:
        raise ValueError("crop width and height must be >= 1")
    if x < 0 or y < 0:
        raise ValueError("crop x and y must be >= 0")
    return ["-i", input_path, "-vf", f"crop={width}:{height}:{x}:{y}", output_path]


def build_transform_args(input_path: str, output_path: str, op: str) -> list[str]:
    """Build args to rotate or flip a video. ``op`` is one of TRANSFORM_FILTERS."""
    if op not in TRANSFORM_FILTERS:
        raise ValueError(
            f"unknown transform {op!r}; choose from {sorted(TRANSFORM_FILTERS)}"
        )
    return ["-i", input_path, "-vf", TRANSFORM_FILTERS[op], output_path]


def build_contact_sheet_args(
    input_path: str,
    output_path: str,
    *,
    duration_s: float,
    cols: int = 4,
    rows: int = 4,
    width: int = 320,
) -> list[str]:
    """Build args for a contact sheet: ``cols``x``rows`` frames sampled evenly
    across the clip, scaled to ``width`` per tile, tiled into one image.

    ``width`` is the per-tile width; the montage is ``cols*width`` wide.
    """
    if cols < 1 or rows < 1:
        raise ValueError("cols and rows must be >= 1")
    if duration_s <= 0:
        raise ValueError("duration must be > 0 for a contact sheet")
    fps = (cols * rows) / duration_s  # sample exactly cols*rows frames over the clip
    vf = f"fps={fps:.6f},scale={width}:-1,tile={cols}x{rows}"
    return ["-i", input_path, "-vf", vf, "-frames:v", "1", output_path]


def contact_sheet(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    cols: int = 4,
    rows: int = 4,
    width: int = 320,
    duration_s: float | None = None,
) -> None:
    """Generate a contact-sheet montage, probing the duration if not given."""
    if duration_s is None:
        duration_s = probe_duration(runner, input_path)
    if not duration_s:
        raise ValueError("could not determine input duration for the contact sheet")
    runner.run_ffmpeg(
        build_contact_sheet_args(
            input_path, output_path, duration_s=duration_s, cols=cols, rows=rows, width=width
        )
    )


def build_compress_args(
    input_path: str,
    output_path: str,
    *,
    crf: int | None = None,
    bitrate: str | None = None,
    width: int | None = None,
    height: int | None = None,
    vcodec: str = "libx264",
    preset: str = "medium",
) -> list[str]:
    """Build args to compress/resize. CRF (quality) and bitrate are mutually
    exclusive; CRF defaults to 23 when neither is given."""
    if crf is not None and bitrate is not None:
        raise ValueError("Pass only one of crf / bitrate, not both.")
    args = ["-i", input_path, "-c:v", vcodec, "-preset", preset]
    if bitrate is not None:
        args += ["-b:v", bitrate]
    else:
        args += ["-crf", str(crf if crf is not None else 23)]
    if width or height:
        args += ["-vf", f"scale={width or -1}:{height or -1}"]
    args += ["-c:a", "aac", "-b:a", "128k"]
    args.append(output_path)
    return args
