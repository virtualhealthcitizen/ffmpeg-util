"""Command builders: pure functions that turn options into ffmpeg arg lists.

Keeping argument construction separate from execution makes every command
unit-testable without ffmpeg installed (build the args, assert on them) and lets
the runner handle dry-run/overwrite/verbose uniformly.
"""

import json
import os
import re
import tempfile
from typing import Sequence

from .runner import FfmpegRunner

# Container -> sensible default codecs for re-encode paths.
_AUDIO_ONLY_EXT = {".mp3", ".aac", ".m4a", ".wav", ".flac", ".ogg", ".opus"}


def require_output_extension(path: str) -> None:
    """Raise a clear error if ``path`` has no extension.

    ffmpeg infers the container from the output extension; without one it fails
    with a cryptic "Unable to choose an output format" message, so we catch it early.
    """
    if not os.path.splitext(path)[1]:
        raise ValueError(
            f"Output '{path}' has no file extension — add one "
            f"(e.g. .mp4, .gif, .png) so the format is clear."
        )


def require_output_dir(path: str) -> None:
    """Raise a clear error if the output's parent directory doesn't exist
    (ffmpeg won't create it, and fails with an opaque 'No such file' error)."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        raise ValueError(f"Output folder '{parent}' does not exist — create it first.")


def require_sequence_pattern(path: str) -> None:
    """Raise a clear error if ``path`` lacks a printf frame token (e.g. %d, %04d),
    which image-sequence outputs need so each frame gets a distinct filename."""
    if not re.search(r"%\d*d", path):
        raise ValueError(
            f"Output '{path}' needs a frame-number token (e.g. %04d) so each "
            f"frame is written to a distinct file."
        )


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


def probe_has_audio(runner: FfmpegRunner, path: str) -> bool:
    """Return True if ``path`` contains at least one audio stream (assumes True in dry-run)."""
    proc = runner.run_ffprobe(
        ["-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path]
    )
    if proc is None:
        return True
    return bool((proc.stdout or "").strip())


def build_concat_filter_args(
    inputs: Sequence[str],
    output_path: str,
    target_w: int,
    target_h: int,
    *,
    has_audio: Sequence[bool] | None = None,
) -> list[str]:
    """Build args for a re-encoding concat using the concat filter.

    Scales every input to ``target_w`` x ``target_h`` (letterboxed, black bars),
    normalises audio to 44100 Hz stereo, and encodes as libx264/aac.  Inputs
    without an audio stream receive a silent audio track via anullsrc.
    ``has_audio`` is a parallel bool sequence; when omitted every input is
    assumed to carry audio.
    """
    if len(inputs) < 2:
        raise ValueError("concat needs at least two input files.")
    if target_w < 2 or target_h < 2:
        raise ValueError("target dimensions must be at least 2x2.")
    # Force even dimensions (x264 requirement).
    tw = target_w - (target_w % 2)
    th = target_h - (target_h % 2)
    n = len(inputs)
    audio_flags = list(has_audio) if has_audio is not None else [True] * n

    fc_parts: list[str] = []
    for i in range(n):
        # Scale to target, letterbox with black, set SAR=1, normalise fps.
        fc_parts.append(
            f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v{i}]"
        )
        if audio_flags[i]:
            fc_parts.append(
                f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100"
                f":channel_layouts=stereo[a{i}]"
            )
        else:
            # Generate silence for the duration we can't know here; use
            # shortest-safe approach: a long anullsrc trimmed by the concat.
            fc_parts.append(
                f"anullsrc=channel_layout=stereo:sample_rate=44100[a{i}]"
            )

    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
    fc_parts.append(f"{concat_in}concat=n={n}:v=1:a=1[v][a]")
    fc = ";".join(fc_parts)

    args: list[str] = []
    for inp in inputs:
        args += ["-i", inp]
    args += [
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-c:a", "aac",
    ]
    # A silent input's synthesized anullsrc is an INFINITE source, so the
    # concatenated [a] stream never reaches EOF and the encode would run forever.
    # -shortest bounds the output to the finite [v] stream (the real total length),
    # trimming that trailing silence. Only needed when we actually add anullsrc;
    # when every input has real audio, [v] and [a] end naturally together.
    if not all(audio_flags):
        args.append("-shortest")
    args.append(output_path)
    return args


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
        require_sequence_pattern(output_path)  # multiple frames need %d to differ
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
        if not runner.dry_run:
            raise ValueError("could not determine input duration for target-size encoding")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how crop-to-aspect/trim-pct/chapters tolerate a probe-less dry-run.
        duration_s = 60.0
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


VALID_DITHERS = frozenset({"sierra2_4a", "bayer", "floyd_steinberg", "sierra2"})


def make_gif(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    fps: int = 12,
    width: int = 480,
    start: str | None = None,
    duration: str | None = None,
    dither: str = "sierra2_4a",
    loop: int = 0,
) -> None:
    """Export an animated GIF using a two-pass palette (palettegen/paletteuse)
    for far better quality than a naive single pass. Optional trim via
    ``start``/``duration``. ``dither`` controls the paletteuse dithering
    algorithm; ``loop`` sets the GIF loop count (0=infinite, -1=no loop)."""
    if fps < 1:
        raise ValueError("fps must be >= 1")
    if width < 1:
        raise ValueError("width must be >= 1")
    if dither not in VALID_DITHERS:
        raise ValueError(f"dither must be one of: {', '.join(sorted(VALID_DITHERS))}")
    seek = ["-ss", start] if start is not None else []
    dur = ["-t", duration] if duration is not None else []
    filt = gif_filter(fps, width)

    fd, palette = tempfile.mkstemp(suffix=".png", prefix="ffgifpal_")
    os.close(fd)
    try:
        runner.run_ffmpeg([*seek, "-i", input_path, *dur, "-vf", f"{filt},palettegen", "-y", palette])
        runner.run_ffmpeg([
            *seek, "-i", input_path, "-i", palette, *dur,
            "-lavfi", f"{filt} [x];[x][1:v] paletteuse=dither={dither}",
            "-loop", str(loop), "-y", output_path,
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


def build_waveform_args(input_path: str, output_path: str, width: int = 1000, height: int = 200) -> list[str]:
    """Build args to render the audio waveform as a ``width``x``height`` image."""
    if width < 1 or height < 1:
        raise ValueError("waveform width and height must be >= 1")
    return [
        "-i", input_path,
        "-filter_complex", f"showwavespic=s={width}x{height}",
        "-frames:v", "1", output_path,
    ]


def waveform(
    runner: FfmpegRunner, input_path: str, output_path: str, width: int = 1000, height: int = 200
) -> None:
    """Render the audio waveform, rejecting inputs with no audio stream to draw."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to render a waveform from")
    runner.run_ffmpeg(build_waveform_args(input_path, output_path, width, height))


def build_image_to_video_args(
    image_path: str, output_path: str, seconds: float, fps: int = 30,
    audio_path: str | None = None,
) -> list[str]:
    """Build args to turn a still image into a ``seconds``-long video at ``fps``.

    When ``audio_path`` is given, its track is muxed in as-is (``-c:a copy``
    would fail across containers, so it's re-encoded to AAC); the output-level
    ``-t seconds`` (placed after both inputs) already bounds both streams, so a
    shorter audio track just ends early rather than looping or erroring.
    """
    if seconds <= 0:
        raise ValueError("seconds must be > 0")
    if fps < 1:
        raise ValueError("fps must be >= 1")
    args = ["-loop", "1", "-i", image_path]
    if audio_path:
        args += ["-i", audio_path]
    args += [
        "-t", str(seconds), "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    ]
    if audio_path:
        args += ["-c:a", "aac", "-map", "0:v", "-map", "1:a"]
    args += [output_path]
    return args


def build_grayscale_args(input_path: str, output_path: str) -> list[str]:
    """Build args to desaturate the video to grayscale (keeps the pixel format)."""
    return ["-i", input_path, "-vf", "hue=s=0", output_path]


def build_invert_args(input_path: str, output_path: str) -> list[str]:
    """Build args to invert the video's colors (photo-negative via ``negate``)."""
    return ["-i", input_path, "-vf", "negate", output_path]


def build_deinterlace_args(input_path: str, output_path: str) -> list[str]:
    """Build args to deinterlace a video via ``yadif`` (Yet Another DeInterlacing Filter).

    Uses mode=0 (send_frame): one output frame per input frame, no framerate change.
    Safe to run on progressive sources — yadif passes them through unchanged.
    """
    return ["-i", input_path, "-vf", "yadif", output_path]


def build_sharpen_args(input_path: str, output_path: str, amount: float = 1.5) -> list[str]:
    """Build args to sharpen (or soften) via the unsharp mask filter.

    A fixed 5×5 luma kernel is used; ``amount`` controls the luma gain:
    positive values sharpen, negative values soften/blur, 0 is a no-op.
    Chroma is left at the ffmpeg default (no chroma sharpening).
    """
    if not -10 <= amount <= 10:
        raise ValueError("amount must be in −10…10")
    return ["-i", input_path, "-vf", f"unsharp=lx=5:ly=5:la={amount}", output_path]


def build_denoise_args(input_path: str, output_path: str, strength: float = 4.0) -> list[str]:
    """Build args to reduce noise via ``hqdn3d``.

    ``strength`` scales all four hqdn3d parameters proportionally from the
    ffmpeg defaults (4:3:6:4.5). Higher values smooth more; 4 is a balanced
    starting point for moderate noise.
    """
    if strength <= 0:
        raise ValueError("strength must be > 0")
    ls = round(strength, 3)
    cs = round(strength * 0.75, 3)
    lt = round(strength * 1.5, 3)
    ct = round(strength * 1.125, 3)
    return ["-i", input_path, "-vf", f"hqdn3d={ls}:{cs}:{lt}:{ct}", output_path]


def build_fps_args(input_path: str, output_path: str, fps: float) -> list[str]:
    """Build args to resample to ``fps`` frames/sec (drops/dupes frames; same
    duration and speed, unlike the ``speed`` op)."""
    if fps <= 0:
        raise ValueError("fps must be > 0")
    return ["-i", input_path, "-vf", f"fps={fps}", output_path]


def build_eq_args(
    input_path: str,
    output_path: str,
    *,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> list[str]:
    """Build args to adjust color via the ``eq`` filter. Defaults are no-ops
    (brightness 0, contrast/saturation 1)."""
    vf = f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}"
    return ["-i", input_path, "-vf", vf, output_path]


def build_hstack_args(inputs: Sequence[str], output_path: str) -> list[str]:
    """Build args to place two equal-height videos side by side. Keeps the first
    input's audio if present."""
    if len(inputs) != 2:
        raise ValueError("hstack needs exactly two input files")
    return [
        "-i", inputs[0], "-i", inputs[1],
        "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "0:a?",
        output_path,
    ]


def build_vstack_args(inputs: Sequence[str], output_path: str) -> list[str]:
    """Build args to stack two equal-width videos vertically. Keeps the first
    input's audio if present."""
    if len(inputs) != 2:
        raise ValueError("vstack needs exactly two input files")
    return [
        "-i", inputs[0], "-i", inputs[1],
        "-filter_complex", "[0:v][1:v]vstack=inputs=2[v]",
        "-map", "[v]", "-map", "0:a?",
        output_path,
    ]


def build_xfade_args(
    inputs: Sequence[str],
    output_path: str,
    *,
    transition: str = "fade",
    duration: float = 1.0,
    offset: float,
) -> list[str]:
    """Crossfade-concatenate two clips with the xfade filter.

    ``offset`` is the second at which the transition starts — typically
    ``duration_of_clip1 - duration`` so the fade begins just before clip 1 ends.
    """
    if len(inputs) != 2:
        raise ValueError("xfade-concat needs exactly two input files")
    if duration <= 0:
        raise ValueError("transition duration must be positive")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    fc = (
        f"[0:v][1:v]xfade=transition={transition}"
        f":duration={duration}:offset={offset}[v]"
    )
    return [
        "-i", inputs[0], "-i", inputs[1],
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        output_path,
    ]


def xfade_concat(
    runner: FfmpegRunner,
    inputs: Sequence[str],
    output_path: str,
    *,
    transition: str = "fade",
    duration: float = 1.0,
    offset: float | None = None,
) -> None:
    """Crossfade-concatenate ``inputs``, probing clip 1's duration for the
    transition ``offset`` when not given explicitly (``offset = clip1_duration
    - duration``), mirroring the UI sidecar's auto-probe behavior."""
    if len(inputs) != 2:
        raise ValueError("xfade-concat needs exactly two input files")
    if offset is None:
        dur = probe_duration(runner, inputs[0])
        if not dur:
            if not runner.dry_run:
                raise ValueError(
                    "could not determine clip 1 duration for xfade-concat — pass offset explicitly"
                )
            # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
            # made), so a placeholder stands in just to let the command print, mirroring
            # how crop-to-aspect/trim-pct/chapters tolerate a probe-less dry-run.
            dur = 60.0
        offset = max(0.0, dur - duration)
    runner.run_ffmpeg(build_xfade_args(
        inputs, output_path, transition=transition, duration=duration, offset=offset,
    ))


def build_boomerang_args(input_path: str, output_path: str) -> list[str]:
    """Build args to boomerang a clip: play it forward then reversed (video only),
    so the output runs about twice the input duration."""
    fc = "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]"
    return ["-i", input_path, "-filter_complex", fc, "-map", "[v]", "-an", output_path]


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
        if not runner.dry_run:
            raise ValueError("could not determine input duration for fade")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how crop-to-aspect/trim-pct/chapters tolerate a probe-less dry-run.
        total_s = 60.0
    if audio is None:
        audio = has_audio(runner, input_path)
    runner.run_ffmpeg(build_fade_args(input_path, output_path, fade_s, total_s, audio=audio))


def build_loudnorm_args(
    input_path: str, output_path: str, target_i: float = -16.0, tp: float = -1.5, lra: float = 11.0
) -> list[str]:
    """Build args to normalize loudness to ``target_i`` LUFS (EBU R128), copying
    the video. ``tp`` is the true-peak ceiling (dBTP), ``lra`` the loudness range."""
    return [
        "-i", input_path, "-c:v", "copy",
        "-af", f"loudnorm=I={target_i}:TP={tp}:LRA={lra}",
        output_path,
    ]


def loudnorm(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    target_i: float = -16.0,
    tp: float = -1.5,
    lra: float = 11.0,
) -> None:
    """Normalize loudness, rejecting inputs with no audio stream to normalize."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to normalize")
    runner.run_ffmpeg(build_loudnorm_args(input_path, output_path, target_i, tp, lra))


def build_volume_args(input_path: str, output_path: str, gain_db: float) -> list[str]:
    """Build args to adjust audio loudness by ``gain_db`` decibels (video copied)."""
    return ["-i", input_path, "-c:v", "copy", "-af", f"volume={gain_db}dB", output_path]


def volume(runner: FfmpegRunner, input_path: str, output_path: str, gain_db: float) -> None:
    """Adjust audio loudness, rejecting inputs with no audio stream to adjust."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to adjust volume on")
    runner.run_ffmpeg(build_volume_args(input_path, output_path, gain_db))


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
    require_sequence_pattern(output_pattern)
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


def build_blur_region_args(
    input_path: str, output_path: str, x: int, y: int, w: int, h: int, *, sigma: float = 10
) -> list[str]:
    """Build args to blur a rectangular region of the video using a Gaussian blur.

    Splits the video, crops the region, blurs it, then composites it back at
    the original position. Audio is stream-copied.
    """
    if w < 1 or h < 1:
        raise ValueError("blur-region width and height must be >= 1")
    if x < 0 or y < 0:
        raise ValueError("blur-region x and y must be >= 0")
    if sigma <= 0:
        raise ValueError("blur-region sigma must be > 0")
    fc = (
        f"[0:v]split=2[main][tmp];"
        f"[tmp]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[blurred];"
        f"[main][blurred]overlay={x}:{y}[v]"
    )
    return ["-i", input_path, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:a", "copy", output_path]


def build_blur_pad_args(
    input_path: str, output_path: str, width: int, height: int, sigma: float = 20
) -> list[str]:
    """Build args to fit the video into a ``width``x``height`` frame over a blurred,
    zoomed copy of itself (instead of black bars). Keeps audio."""
    if width < 1 or height < 1:
        raise ValueError("blur-pad width and height must be >= 1")
    if sigma <= 0:
        raise ValueError("blur-pad sigma must be > 0")
    fc = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={sigma}[bg2];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2[v]"
    )
    return ["-i", input_path, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", output_path]


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


def build_title_args(input_path: str, output_path: str, title: str) -> list[str]:
    """Build args to set (or clear, with '') the title metadata tag; streams copy."""
    return ["-i", input_path, "-c", "copy", "-metadata", f"title={title}", output_path]


def build_sample_rate_args(input_path: str, output_path: str, rate: int) -> list[str]:
    """Build args to resample audio to ``rate`` Hz; the video is stream-copied."""
    if rate < 1:
        raise ValueError("sample rate must be >= 1")
    return ["-i", input_path, "-c:v", "copy", "-ar", str(rate), output_path]


def sample_rate(runner: FfmpegRunner, input_path: str, output_path: str, rate: int) -> None:
    """Resample audio, rejecting inputs with no audio stream to resample."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to resample")
    runner.run_ffmpeg(build_sample_rate_args(input_path, output_path, rate))


def build_mono_args(input_path: str, output_path: str) -> list[str]:
    """Downmix audio to a single (mono) channel; the video is stream-copied."""
    return ["-i", input_path, "-c:v", "copy", "-ac", "1", output_path]


def mono(runner: FfmpegRunner, input_path: str, output_path: str) -> None:
    """Downmix audio to mono, rejecting inputs with no audio stream to downmix."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to downmix")
    runner.run_ffmpeg(build_mono_args(input_path, output_path))


def build_mute_args(input_path: str, output_path: str) -> list[str]:
    """Build args to strip the audio track (stream-copies video, drops audio)."""
    return ["-i", input_path, "-c", "copy", "-an", output_path]


def build_trim_silence_args(
    input_path: str,
    output_path: str,
    *,
    threshold_db: float = -50.0,
    min_duration: float = 0.5,
) -> list[str]:
    """Build args to strip leading and trailing silence (silenceremove filter).

    Audio is re-encoded by the filter; the video stream is copied.
    ``threshold_db`` is the level below which audio is considered silence;
    ``min_duration`` is the minimum run of silence (s) before it is stripped.
    """
    if min_duration < 0:
        raise ValueError("min_duration must be >= 0")
    thr = f"{threshold_db}dB"
    dur = str(round(min_duration, 3))
    sr = (
        f"silenceremove="
        f"start_periods=1:start_threshold={thr}:start_duration={dur}:"
        f"stop_periods=1:stop_threshold={thr}:stop_duration={dur}"
    )
    return ["-i", input_path, "-c:v", "copy", "-af", sr, output_path]


def trim_silence(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    threshold_db: float = -50.0,
    min_duration: float = 0.5,
) -> None:
    """Trim silence, rejecting inputs with no audio stream to trim."""
    if not has_audio(runner, input_path):
        raise ValueError("input has no audio stream to trim silence from")
    runner.run_ffmpeg(build_trim_silence_args(
        input_path, output_path, threshold_db=threshold_db, min_duration=min_duration,
    ))


def build_replace_audio_args(
    video_path: str, audio_path: str, output_path: str, *, audio_codec: str = "aac"
) -> list[str]:
    """Replace a video's audio with the track from an external audio file.

    Keeps the original video stream untouched (``-c:v copy``) and takes the audio
    from the second input, re-encoding it to ``audio_codec`` for broad container
    compatibility. ``-shortest`` trims the result to whichever stream ends first
    so a longer music bed doesn't leave a frozen tail."""
    return [
        "-i", video_path, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", audio_codec, "-shortest",
        output_path,
    ]


def parse_aspect(s: str) -> tuple[int, int]:
    """Parse an aspect string like '16:9' into (16, 9)."""
    try:
        aw, ah = str(s).split(":")
        return int(aw), int(ah)
    except (ValueError, AttributeError):
        raise ValueError(f"aspect must look like '16:9', got {s!r}")


def compute_aspect_crop(width: int, height: int, aw: int, ah: int) -> tuple[int, int, int, int]:
    """Largest centered crop of ``width``x``height`` matching aspect ``aw:ah``.

    Returns (crop_w, crop_h, x, y) with even dimensions (for yuv420)."""
    if aw < 1 or ah < 1:
        raise ValueError("aspect parts must be >= 1")
    target = aw / ah
    if width / height > target:
        cw, ch = round(height * target), height
    else:
        cw, ch = width, round(width / target)
    cw -= cw % 2
    ch -= ch % 2
    cw = max(2, min(cw, width))
    ch = max(2, min(ch, height))
    return cw, ch, (width - cw) // 2, (height - ch) // 2


def probe_dimensions(runner: FfmpegRunner, path: str) -> tuple[int, int] | None:
    """Return (width, height) of the first video stream, or None."""
    proc = runner.run_ffprobe(
        ["-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path]
    )
    if proc is None:
        return None
    try:
        w, h = (proc.stdout or "").strip().split(",")
        return int(w), int(h)
    except ValueError:
        return None


def crop_to_aspect(runner: FfmpegRunner, input_path: str, output_path: str, aw: int, ah: int) -> None:
    """Crop ``input_path`` to the ``aw:ah`` aspect (centered), probing its size."""
    dims = probe_dimensions(runner, input_path)
    if not dims:
        if not runner.dry_run:
            raise ValueError("could not determine input dimensions for crop-to-aspect")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how trim-pct/chapters tolerate a probe-less dry-run.
        dims = (1920, 1080)
    cw, ch, x, y = compute_aspect_crop(dims[0], dims[1], aw, ah)
    runner.run_ffmpeg(build_crop_args(input_path, output_path, cw, ch, x, y))


def build_crop_args(
    input_path: str, output_path: str, width: int, height: int, x: int = 0, y: int = 0
) -> list[str]:
    """Build args to crop a ``width``x``height`` rectangle at offset (``x``, ``y``)."""
    if width < 1 or height < 1:
        raise ValueError("crop width and height must be >= 1")
    if x < 0 or y < 0:
        raise ValueError("crop x and y must be >= 0")
    return ["-i", input_path, "-vf", f"crop={width}:{height}:{x}:{y}", output_path]


_CROPDETECT_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def parse_cropdetect(text: str) -> tuple[int, int, int, int] | None:
    """Return the last ``crop=w:h:x:y`` suggestion from ffmpeg cropdetect output.

    ffmpeg's ``cropdetect`` filter logs one ``crop=…`` line per analyzed frame;
    the final one reflects the most stable estimate, so we take the last match.
    Pure (no ffmpeg) so it can be unit-tested. Returns None if nothing matched.
    """
    matches = _CROPDETECT_RE.findall(text or "")
    if not matches:
        return None
    w, h, x, y = matches[-1]
    return int(w), int(h), int(x), int(y)


def detect_crop(
    runner: FfmpegRunner, input_path: str, *, limit: int = 24, round_to: int = 2
) -> tuple[int, int, int, int] | None:
    """Detect the non-black crop region of a video via ffmpeg ``cropdetect``.

    Returns (w, h, x, y) or None if it could not be determined (e.g. dry-run or
    no usable output). ``limit`` is the black threshold (0-255); ``round_to``
    forces the crop size to a multiple (2 keeps it yuv420-friendly).
    """
    proc = runner.run_ffmpeg_capture(
        ["-i", input_path, "-vf", f"cropdetect=limit={limit}:round={round_to}",
         "-f", "null", "-"]
    )
    if proc is None:
        return None
    return parse_cropdetect(proc.stderr or "")


def autocrop(
    runner: FfmpegRunner, input_path: str, output_path: str, *, limit: int = 24
) -> tuple[int, int, int, int] | None:
    """Detect and remove black bars from ``input_path``, writing ``output_path``.

    Returns the applied (w, h, x, y), or None in dry-run / when detection fails
    (in which case nothing is written). Used by the CLI; the UI sidecar mirrors
    this two-pass flow (detect, then crop) so it can stream progress.
    """
    crop = detect_crop(runner, input_path, limit=limit)
    if crop is None:
        return None
    w, h, x, y = crop
    runner.run_ffmpeg(build_crop_args(input_path, output_path, w, h, x, y))
    return crop


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
        if not runner.dry_run:
            raise ValueError("could not determine input duration for the contact sheet")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how crop-to-aspect/trim-pct/chapters tolerate a probe-less dry-run.
        duration_s = 60.0
    runner.run_ffmpeg(
        build_contact_sheet_args(
            input_path, output_path, duration_s=duration_s, cols=cols, rows=rows, width=width
        )
    )


_TIMECODE_POSITIONS = {
    "top-left": ("10", "10"),
    "top-right": ("w-tw-10", "10"),
    "bottom-left": ("10", "h-th-10"),
    "bottom-right": ("w-tw-10", "h-th-10"),
}
_TIMECODE_COLOR_RE = re.compile(r"^[a-zA-Z0-9#@.]+$")


def _drawtext_escape_path(path: str) -> str:
    """Escape a file-system path for use in a drawtext fontfile= option.

    The drawtext filter uses ':' as an option separator and '\\' as an escape
    character, so Windows drive colons (C:/) and backslashes must be escaped.
    Forward slashes are safe on all platforms (ffmpeg accepts them on Windows).
    """
    normalized = str(path).replace("\\", "/")
    return normalized.replace(":", "\\:")


def build_timecode_args(
    input_path: str,
    output_path: str,
    *,
    font_size: int = 24,
    position: str = "top-left",
    color: str = "white",
    font_file: str | None = None,
) -> list[str]:
    """Build args to burn a running HH:MM:SS.ms timecode into the video.

    Uses ffmpeg's ``drawtext`` filter with PTS expansion so the overlay counts
    up from 00:00:00.000. A semi-transparent black box makes the text readable
    on any background. Audio is stream-copied unchanged.
    ``position`` is one of top-left / top-right / bottom-left / bottom-right.
    ``color`` is any ffmpeg color name or hex (e.g. white, yellow, #ffffff).
    ``font_file`` is an optional absolute path to a TTF/OTF font; required on
    systems where fontconfig is unavailable (e.g. some Windows builds of ffmpeg).
    """
    if font_size < 6:
        raise ValueError("font_size must be >= 6")
    if position not in _TIMECODE_POSITIONS:
        raise ValueError(
            f"position must be one of {sorted(_TIMECODE_POSITIONS)}; got {position!r}"
        )
    color = str(color).strip()
    if not color or not _TIMECODE_COLOR_RE.match(color):
        raise ValueError(
            "color must be a valid ffmpeg color name or hex value (e.g. white, #ffffff)"
        )
    x_expr, y_expr = _TIMECODE_POSITIONS[position]
    fontfile_opt = f"fontfile='{_drawtext_escape_path(font_file)}':" if font_file else ""
    vf = (
        f"drawtext={fontfile_opt}text='%{{pts\\:hms}}':"
        f"fontsize={font_size}:x={x_expr}:y={y_expr}:"
        f"fontcolor={color}:box=1:boxcolor=black@0.5:boxborderw=5"
    )
    return ["-i", input_path, "-vf", vf, "-c:a", "copy", output_path]


_WATERMARK_POSITIONS = {
    "top-left":     ("10",          "10"),
    "top-right":    ("w-tw-10",     "10"),
    "bottom-left":  ("10",          "h-th-10"),
    "bottom-right": ("w-tw-10",     "h-th-10"),
    "center":       ("(w-tw)/2",    "(h-th)/2"),
}


def _escape_drawtext_text(text: str) -> str:
    """Escape user text for a drawtext filter text= value.

    We wrap the value in single quotes in the filter string, so backslash,
    colon (option separator), and single-quote all need escaping.  Applied to
    the Python string fed to subprocess — not shell quoting.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text


def build_watermark_args(
    input_path: str,
    output_path: str,
    *,
    text: str,
    font_size: int = 24,
    position: str = "bottom-right",
    color: str = "white",
    opacity: float = 1.0,
    font_file: str | None = None,
) -> list[str]:
    """Build args to burn a static text watermark onto a video.

    Uses ffmpeg's ``drawtext`` filter with a semi-transparent black box.
    Audio is stream-copied unchanged.
    ``text`` is the watermark string.
    ``position`` is one of top-left / top-right / bottom-left / bottom-right / center.
    ``opacity`` is 0.0–1.0 (1.0 = fully opaque).
    ``color`` is any ffmpeg color name or hex.
    ``font_file`` is an optional absolute path to a TTF/OTF font.
    """
    if not text:
        raise ValueError("text must not be empty")
    if font_size < 6:
        raise ValueError("font_size must be >= 6")
    if position not in _WATERMARK_POSITIONS:
        raise ValueError(
            f"position must be one of {sorted(_WATERMARK_POSITIONS)}; got {position!r}"
        )
    color = str(color).strip()
    if not color or not _TIMECODE_COLOR_RE.match(color):
        raise ValueError(
            "color must be a valid ffmpeg color name or hex value (e.g. white, #ffffff)"
        )
    opacity = max(0.0, min(1.0, float(opacity)))
    x_expr, y_expr = _WATERMARK_POSITIONS[position]
    fontfile_opt = f"fontfile='{_drawtext_escape_path(font_file)}':" if font_file else ""
    color_with_alpha = f"{color}@{opacity:.2f}" if opacity < 1.0 else color
    escaped = _escape_drawtext_text(text)
    vf = (
        f"drawtext={fontfile_opt}text='{escaped}':"
        f"fontsize={font_size}:x={x_expr}:y={y_expr}:"
        f"fontcolor={color_with_alpha}:box=1:boxcolor=black@0.4:boxborderw=4"
    )
    return ["-i", input_path, "-vf", vf, "-c:a", "copy", output_path]


def _escape_subtitle_path(path: str) -> str:
    """Escape a subtitle file path for use in the subtitles= filter value.

    The subtitles filter uses ':' as an option separator.  Forward slashes
    are safe on all platforms; backslashes and drive colons need escaping.
    Single quotes are also escaped because the value is wrapped in single
    quotes in the filter string.
    """
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def build_hardsub_args(
    input_path: str,
    subtitle_path: str,
    output_path: str,
) -> list[str]:
    """Burn subtitle text into video frames (hardsub).

    Uses ffmpeg's ``subtitles`` filter to render an SRT, ASS/SSA, or WebVTT
    file directly onto the video.  Audio is stream-copied unchanged.
    The output file must be a video container (not .srt/.ass).
    """
    escaped = _escape_subtitle_path(subtitle_path)
    vf = f"subtitles='{escaped}'"
    return ["-i", input_path, "-vf", vf, "-c:a", "copy", output_path]


def build_scene_thumbs_args(
    input_path: str,
    output_pattern: str,
    *,
    threshold: float = 0.3,
    width: int | None = None,
) -> list[str]:
    """Build args to extract one frame per scene cut via the ``select`` filter.

    ffmpeg scores each frame 0–1 for how different it looks from the previous
    one; frames scoring above ``threshold`` are emitted (lower = more frames).
    ``output_pattern`` must contain a printf token (e.g. ``scene_%04d.png``).
    """
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    require_sequence_pattern(output_pattern)
    vf_parts = [f"select=gt(scene\\,{threshold})"]
    if width:
        vf_parts.append(f"scale={width}:-1")
    return ["-i", input_path, "-vf", ",".join(vf_parts), "-fps_mode", "vfr", output_pattern]


def build_remux_args(input_path: str, output_path: str) -> list[str]:
    """Remux (change container) without re-encoding using ``-c copy``.

    The output container is inferred from the output extension. ffmpeg will
    error if the existing codecs are incompatible with the target container
    (e.g. HEVC into an AVI that doesn't support it).
    """
    return ["-i", input_path, "-c", "copy", output_path]


def build_preview_clip_args(
    input_path: str,
    output_path: str,
    *,
    seconds: float = 5.0,
    width: int = 320,
) -> list[str]:
    """Build args to export a short downscaled preview (first N seconds).

    Places ``-t`` before ``-i`` so ffmpeg stops reading the input after
    ``seconds`` — fast even for very long files.  ``scale=W:-2`` rescales
    to the requested width keeping aspect ratio and rounding height to an
    even number (required by libx264).
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    if width <= 0:
        raise ValueError("width must be positive")
    return [
        "-t", str(seconds),
        "-i", input_path,
        "-vf", f"scale={width}:-2",
        "-c:a", "copy",
        output_path,
    ]


def build_trim_pct_args(
    input_path: str,
    output_path: str,
    *,
    start_pct: float = 0.0,
    end_pct: float = 100.0,
    duration_s: float | None = None,
    reencode: bool = False,
) -> list[str]:
    """Build args to trim a clip by start/end percentages of total duration.

    ``duration_s`` is required — pass the probed media duration so the
    timestamps can be computed.  Stream-copy by default (fast, keyframe-aligned);
    pass ``reencode=True`` for frame-accurate cuts.
    """
    if not 0.0 <= start_pct <= 100.0:
        raise ValueError("start_pct must be in [0, 100]")
    if not 0.0 <= end_pct <= 100.0:
        raise ValueError("end_pct must be in [0, 100]")
    if start_pct >= end_pct:
        raise ValueError("start_pct must be less than end_pct")
    if duration_s is None:
        raise ValueError("duration_s is required for trim-pct")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    start_s = duration_s * start_pct / 100.0
    end_s = duration_s * end_pct / 100.0
    args: list[str] = ["-ss", f"{start_s:.6f}", "-i", input_path]
    if reencode:
        # Input-seeking with -ss before -i resets output PTS to 0 during re-encode,
        # so -to end_s would produce end_s seconds instead of the intended
        # (end_s - start_s). Use -t (duration) which is PTS-reset-safe.
        args += ["-t", f"{(end_s - start_s):.6f}"]
    else:
        # Stream copy preserves the original timestamps, so -to references the
        # input clock and correctly stops at end_s.
        args += ["-to", f"{end_s:.6f}", "-c", "copy"]
    args.append(output_path)
    return args


def trim_pct(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    start_pct: float = 0.0,
    end_pct: float = 100.0,
    reencode: bool = False,
) -> None:
    """Trim ``input_path`` by percentage of its total duration, probing it first."""
    duration_s = probe_duration(runner, input_path)
    if not duration_s:
        if not runner.dry_run:
            raise ValueError("could not determine input duration for trim-pct")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how crop-to-aspect/contact-sheet tolerate a probe-less dry-run.
        duration_s = 60.0
    runner.run_ffmpeg(build_trim_pct_args(
        input_path, output_path,
        start_pct=start_pct, end_pct=end_pct,
        duration_s=duration_s, reencode=reencode,
    ))


def _parse_timestamp_s(ts: str) -> float:
    """Parse a timestamp string to seconds (float).

    Accepts: plain seconds ("90", "1.5"), MM:SS, or HH:MM:SS(.ms).
    """
    ts = ts.strip()
    try:
        return float(ts)
    except ValueError:
        pass
    parts = ts.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def parse_chapters_text(text: str) -> list[dict]:
    """Parse chapter lines into dicts with ``start_s`` and ``title`` keys.

    Each non-blank, non-comment line must be ``<timestamp> <title>`` where
    timestamp accepts plain seconds, MM:SS, or HH:MM:SS.
    Returns a list sorted ascending by start time.
    """
    chapters = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            raise ValueError(f"Expected '<timestamp> <title>', got: {line!r}")
        chapters.append({"start_s": _parse_timestamp_s(parts[0]), "title": parts[1].strip()})
    if not chapters:
        raise ValueError("No chapters found — each line should be '<timestamp> <title>'")
    chapters.sort(key=lambda c: c["start_s"])
    return chapters


def write_chapters_meta(chapters: list[dict], duration_s: float, meta_file: str) -> None:
    """Write an ffmetadata file with chapter markers.

    ``chapters`` is a list of ``{'start_s': float, 'title': str}`` dicts.
    The last chapter ends at ``duration_s``.  Uses a 1/1000 (ms) timebase.
    """
    tb = 1000
    with open(meta_file, "w", encoding="utf-8") as fh:
        fh.write(";FFMETADATA1\n\n")
        for i, ch in enumerate(chapters):
            start_ms = int(ch["start_s"] * tb)
            end_ms = (
                int(chapters[i + 1]["start_s"] * tb)
                if i + 1 < len(chapters)
                else int(duration_s * tb)
            )
            title = (
                ch["title"]
                .replace("\\", "\\\\")
                .replace("=", "\\=")
                .replace(";", "\\;")
                .replace("#", "\\#")
                .replace("\n", "\\\n")
            )
            fh.write("[CHAPTER]\n")
            fh.write(f"TIMEBASE=1/{tb}\n")
            fh.write(f"START={start_ms}\n")
            fh.write(f"END={end_ms}\n")
            fh.write(f"title={title}\n\n")


def build_chapters_args(input_path: str, meta_file: str, output_path: str) -> list[str]:
    """Build args to embed chapters from an ffmetadata ``meta_file`` into ``input_path``.

    All streams and existing metadata are stream-copied; the chapter markers from
    ``meta_file`` replace any prior chapter data.
    """
    return [
        "-i", input_path,
        "-f", "ffmetadata", "-i", meta_file,
        "-map_metadata", "1",
        "-map", "0",
        "-c", "copy",
        output_path,
    ]


def parse_segments_text(text: str) -> list[tuple[float, float]]:
    """Parse trim-segment lines into a list of ``(start_s, end_s)`` tuples.

    Each non-blank, non-comment line is ``<start> <end>`` (seconds, MM:SS, or
    HH:MM:SS). Segments are kept in the given order (not sorted), so the order
    of lines controls the order they appear in the joined output.
    """
    segments: list[tuple[float, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Expected '<start> <end>', got: {line!r}")
        start_s = _parse_timestamp_s(parts[0])
        end_s = _parse_timestamp_s(parts[1])
        if end_s <= start_s:
            raise ValueError(f"End must be after start: {line!r}")
        segments.append((start_s, end_s))
    if not segments:
        raise ValueError("No segments found — each line should be '<start> <end>'")
    return segments


def build_trim_segments_args(
    input_path: str,
    output_path: str,
    segments: Sequence[tuple[float, float]],
    *,
    audio: bool = True,
) -> list[str]:
    """Build args to cut multiple segments from one input and join them in order.

    Each segment is cut with the trim/atrim filters (frame-accurate — stream
    copy can't join arbitrary, non-keyframe-aligned cuts) and stitched together
    with the concat filter, re-encoding the result. Pass ``audio=False`` for an
    input with no audio stream — otherwise the ``[0:a]atrim`` filter references
    a stream specifier that matches nothing and ffmpeg errors out.
    """
    if len(segments) < 1:
        raise ValueError("Need at least one segment.")
    n = len(segments)
    fc_parts: list[str] = []
    for i, (start_s, end_s) in enumerate(segments):
        fc_parts.append(f"[0:v]trim=start={start_s}:end={end_s},setpts=PTS-STARTPTS[v{i}]")
        if audio:
            fc_parts.append(f"[0:a]atrim=start={start_s}:end={end_s},asetpts=PTS-STARTPTS[a{i}]")
    if audio:
        concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
        fc_parts.append(f"{concat_in}concat=n={n}:v=1:a=1[v][a]")
    else:
        concat_in = "".join(f"[v{i}]" for i in range(n))
        fc_parts.append(f"{concat_in}concat=n={n}:v=1:a=0[v]")
    fc = ";".join(fc_parts)

    args = ["-i", input_path, "-filter_complex", fc, "-map", "[v]"]
    if audio:
        args += ["-map", "[a]"]
    args += ["-c:v", "libx264", "-preset", "medium"]
    if audio:
        args += ["-c:a", "aac"]
    args.append(output_path)
    return args


def trim_segments(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    segments: Sequence[tuple[float, float]],
    *,
    audio: bool | None = None,
) -> None:
    """Cut and join ``segments`` from ``input_path``, detecting audio when present."""
    if audio is None:
        audio = has_audio(runner, input_path)
    runner.run_ffmpeg(build_trim_segments_args(input_path, output_path, segments, audio=audio))


def build_poster_frame_args(
    input_path: str,
    output_path: str,
    *,
    percent: float = 10.0,
    duration_s: float | None = None,
    width: int | None = None,
) -> list[str]:
    """Build args to extract a single frame at ``percent``% of the clip duration.

    When ``duration_s`` is supplied the timestamp is computed here; otherwise
    ``-ss`` falls back to a raw ``<pct>%`` string, which real ffmpeg does NOT
    accept as a time value (it errors with "Invalid duration for option ss") —
    this path only exists so callers that can't probe (e.g. ``--dry-run``) still
    get a command printed. Real runs must supply ``duration_s`` (see
    :func:`poster_frame`, which probes it and calls this).
    Outputs a PNG/JPEG depending on the output extension.
    """
    if not 0 <= percent <= 100:
        raise ValueError("percent must be in [0, 100]")
    if duration_s is not None:
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        ts = str(duration_s * percent / 100.0)
    else:
        ts = f"{percent}%"
    args: list[str] = ["-ss", ts, "-i", input_path, "-frames:v", "1"]
    if width:
        args += ["-vf", f"scale={width}:-1"]
    args.append(output_path)
    return args


def poster_frame(
    runner: FfmpegRunner,
    input_path: str,
    output_path: str,
    *,
    percent: float = 10.0,
    width: int | None = None,
) -> None:
    """Extract a single frame at ``percent``% of the clip duration, probing it first.

    Real ffmpeg has no percentage syntax for ``-ss`` (it only accepts elapsed-time
    formats and rejects e.g. ``25.0%`` outright), so a probed duration is required
    for a working command; ``build_poster_frame_args``'s ``duration_s``-less path
    exists only to let ``--dry-run`` still print something when ffprobe can't run.
    """
    duration_s = probe_duration(runner, input_path)
    if not duration_s:
        if not runner.dry_run:
            raise ValueError("could not determine input duration for poster-frame")
        # ``run_ffprobe`` always returns None in dry-run mode (no ffprobe call is
        # made), so a placeholder stands in just to let the command print, mirroring
        # how crop-to-aspect/trim-pct/chapters/fade/contact-sheet tolerate a
        # probe-less dry-run.
        duration_s = 60.0
    runner.run_ffmpeg(
        build_poster_frame_args(
            input_path, output_path, percent=percent, duration_s=duration_s, width=width
        )
    )


def build_autorotate_args(input_path: str, output_path: str) -> list[str]:
    """Build args to bake rotation metadata into pixels and strip the rotate tag.

    ffmpeg automatically applies the display-matrix rotation during decode when
    video passes through a filter graph. The null filter forces that decode-and-
    rewrite path; -metadata:s:v:0 rotate=0 strips the tag so players don't apply
    a second rotation on playback.
    """
    return [
        "-i", input_path,
        "-c:a", "copy",
        "-vf", "null",
        "-metadata:s:v:0", "rotate=0",
        output_path,
    ]


def build_vidstab_detect_args(
    input_path: str, trf_name: str, *, shakiness: int = 5, accuracy: int = 15
) -> list[str]:
    """Pass 1 of vidstab: analyse motion and write transform data.

    ``trf_name`` must be a bare filename (no directory separators or drive
    letter) so that ffmpeg's filter-option parser doesn't mis-interpret a
    Windows drive colon as an option delimiter. The caller is responsible for
    running ffmpeg with ``cwd`` set to the directory that should contain the
    trf file.
    """
    if not 1 <= shakiness <= 10:
        raise ValueError("shakiness must be 1–10")
    if not 1 <= accuracy <= 15:
        raise ValueError("accuracy must be 1–15")
    return [
        "-i", input_path,
        "-vf", f"vidstabdetect=shakiness={shakiness}:accuracy={accuracy}:result={trf_name}",
        "-f", "null", "-",
    ]


def build_vidstab_transform_args(
    input_path: str, output_path: str, trf_name: str, *, smoothing: int = 10
) -> list[str]:
    """Pass 2 of vidstab: apply stabilization from trf_name and sharpen slightly.

    Like :func:`build_vidstab_detect_args`, ``trf_name`` must be a bare
    filename; run ffmpeg with ``cwd`` pointing at the directory holding it.
    """
    if smoothing < 1:
        raise ValueError("smoothing must be >= 1")
    return [
        "-i", input_path,
        "-vf", f"vidstabtransform=input={trf_name}:smoothing={smoothing},unsharp=5:5:0.8:3:3:0.4",
        output_path,
    ]


def stabilize(
    runner: "FfmpegRunner",
    input_path: str,
    output_path: str,
    *,
    shakiness: int = 5,
    accuracy: int = 15,
    smoothing: int = 10,
) -> None:
    """Two-pass video stabilization using vidstab (detect → transform).

    Creates a private temp directory as the working directory for both ffmpeg
    passes so the trf filename used in filter options is a bare name with no
    drive-letter colon (which ffmpeg's filter parser would mis-interpret as an
    option separator on Windows).
    """
    import shutil as _shutil
    require_output_extension(output_path)
    require_output_dir(output_path)
    trf_dir = tempfile.mkdtemp(prefix="ffstab_")
    trf_name = "transforms.trf"
    try:
        runner.run_ffmpeg(
            build_vidstab_detect_args(input_path, trf_name, shakiness=shakiness, accuracy=accuracy),
            cwd=trf_dir,
        )
        runner.run_ffmpeg(
            build_vidstab_transform_args(input_path, output_path, trf_name, smoothing=smoothing),
            cwd=trf_dir,
        )
    finally:
        _shutil.rmtree(trf_dir, ignore_errors=True)


# Hardware encoder selected in place of the software `vcodec` when hwaccel is
# requested. Neither device accepts `-crf` (ffmpeg silently drops it — "Codec
# AVOption crf ... has not been used for any stream" — instead of erroring),
# so the quality flag is remapped per-device below.
HWACCEL_VCODECS = {"nvenc": "h264_nvenc", "qsv": "h264_qsv"}


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
    hwaccel: str = "none",
) -> list[str]:
    """Build args to compress/resize. CRF (quality) and bitrate are mutually
    exclusive; CRF defaults to 23 when neither is given.

    ``hwaccel`` ("none"/"nvenc"/"qsv") swaps in a hardware encoder in place of
    ``vcodec`` and its matching quality flag (nvenc: ``-rc vbr -cq``; qsv:
    ``-global_quality``) so CRF-style quality control keeps working."""
    if crf is not None and bitrate is not None:
        raise ValueError("Pass only one of crf / bitrate, not both.")
    if hwaccel != "none" and hwaccel not in HWACCEL_VCODECS:
        raise ValueError(f"hwaccel must be one of none/{'/'.join(HWACCEL_VCODECS)}; got {hwaccel!r}")
    if hwaccel != "none":
        vcodec = HWACCEL_VCODECS[hwaccel]
    args = ["-i", input_path, "-c:v", vcodec, "-preset", preset]
    if bitrate is not None:
        args += ["-b:v", bitrate]
    elif hwaccel == "nvenc":
        args += ["-rc", "vbr", "-cq", str(crf if crf is not None else 23)]
    elif hwaccel == "qsv":
        args += ["-global_quality", str(crf if crf is not None else 23)]
    else:
        args += ["-crf", str(crf if crf is not None else 23)]
    if width or height:
        args += ["-vf", f"scale={width or -1}:{height or -1}"]
    args += ["-c:a", "aac", "-b:a", "128k"]
    args.append(output_path)
    return args


def estimate_compress_size(
    runner: FfmpegRunner,
    input_path: str,
    *,
    crf: int | None = None,
    bitrate: str | None = None,
    width: int | None = None,
    height: int | None = None,
    vcodec: str = "libx264",
    preset: str = "medium",
    hwaccel: str = "none",
    duration_s: float | None = None,
    sample_seconds: float = 3.0,
) -> dict:
    """Predict a ``compress`` output size by really encoding a short sample
    with the exact same args and extrapolating by duration.

    CRF/quality encodes have no formula for output size (unlike an explicit
    bitrate or two-pass target), so the only reliable estimate is a real,
    short sample encode. Returns a dict with ``estimated_bytes``,
    ``sample_bytes``, ``sample_seconds`` (actual, may be less than the
    input's full duration), and ``duration_s``.
    """
    if duration_s is None:
        duration_s = probe_duration(runner, input_path)
    if not duration_s or duration_s <= 0:
        raise ValueError("could not determine input duration for size estimation")
    sample_dur = min(sample_seconds, duration_s)
    if sample_dur <= 0:
        raise ValueError("sample_seconds must be > 0")

    fd, tmp_out = tempfile.mkstemp(suffix=".mp4", prefix="ffsizeest_")
    os.close(fd)
    # ffmpeg refuses to run at all if both -y and -n land on its command line
    # (it doesn't just take the last one), so we can't force overwrite with an
    # extra flag alongside the caller's runner.overwrite-derived -y/-n. Instead,
    # remove the placeholder mkstemp created so the path doesn't exist yet —
    # then neither -y nor -n needs to make an overwrite decision.
    os.remove(tmp_out)
    try:
        args = build_compress_args(
            input_path, tmp_out,
            crf=crf, bitrate=bitrate, width=width, height=height,
            vcodec=vcodec, preset=preset, hwaccel=hwaccel,
        )
        # -t as an output option (before the trailing output path) caps the
        # sample to sample_dur regardless of where in the arg list it lands.
        args = [*args[:-1], "-t", str(sample_dur), args[-1]]
        runner.run_ffmpeg(args)
        sample_bytes = os.path.getsize(tmp_out)
        actual_sample_dur = probe_duration(runner, tmp_out) or sample_dur
    finally:
        try:
            os.remove(tmp_out)
        except OSError:
            pass

    estimated_bytes = int(sample_bytes * duration_s / actual_sample_dur)
    return {
        "estimated_bytes": estimated_bytes,
        "sample_bytes": sample_bytes,
        "sample_seconds": actual_sample_dur,
        "duration_s": duration_s,
    }


_PIP_POSITIONS = {
    "top-left":     ("10", "10"),
    "top-right":    ("W-w-10", "10"),
    "bottom-left":  ("10", "H-h-10"),
    "bottom-right": ("W-w-10", "H-h-10"),
}


def build_pip_args(
    base: str,
    overlay: str,
    output: str,
    *,
    size_pct: int = 25,
    position: str = "bottom-right",
) -> list[str]:
    """Picture-in-picture: overlay a smaller video in a corner of the base clip.

    The overlay is scaled to ``size_pct`` percent of the base width; height is
    derived with ``-2`` so it stays an even number (required by libx264).  Base
    audio is kept; overlay audio is discarded.
    """
    if position not in _PIP_POSITIONS:
        raise ValueError(
            f"position must be one of {sorted(_PIP_POSITIONS)}; got {position!r}"
        )
    if not 5 <= size_pct <= 75:
        raise ValueError("size_pct must be between 5 and 75")
    x, y = _PIP_POSITIONS[position]
    fc = f"[1:v]scale=iw*{size_pct}/100:-2[ov];[0:v][ov]overlay={x}:{y}[v]"
    return [
        "-i", base, "-i", overlay,
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "0:a?",
        output,
    ]


# Curated set of formats the UI dropdown offers; the CLI accepts any safe format.
_PIX_FMT_RE = re.compile(r"^[a-z0-9_]+$")


def build_pixfmt_args(input_path: str, output_path: str, pix_fmt: str = "yuv420p") -> list[str]:
    """Build args to convert the video to a specific pixel format.

    Uses ffmpeg's ``format`` filter so the conversion is explicit even when the
    encoder would otherwise silently pick a compatible format.  Audio is
    stream-copied unchanged.  ``pix_fmt`` must be a known ffmpeg pixel-format
    name (lowercase letters, digits, and underscores only).
    """
    if not pix_fmt or not _PIX_FMT_RE.match(pix_fmt):
        raise ValueError(
            f"Invalid pixel format {pix_fmt!r}: use a valid ffmpeg name "
            f"(e.g. yuv420p, yuv422p, gray)."
        )
    return ["-i", input_path, "-vf", f"format={pix_fmt}", "-c:a", "copy", output_path]
