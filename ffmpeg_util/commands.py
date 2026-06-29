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


def build_image_to_video_args(
    image_path: str, output_path: str, seconds: float, fps: int = 30
) -> list[str]:
    """Build args to turn a still image into a ``seconds``-long video at ``fps``."""
    if seconds <= 0:
        raise ValueError("seconds must be > 0")
    if fps < 1:
        raise ValueError("fps must be >= 1")
    return [
        "-loop", "1", "-i", image_path, "-t", str(seconds), "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        output_path,
    ]


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
        raise ValueError("could not determine input duration for fade")
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


def build_blur_pad_args(
    input_path: str, output_path: str, width: int, height: int, sigma: float = 20
) -> list[str]:
    """Build args to fit the video into a ``width``x``height`` frame over a blurred,
    zoomed copy of itself (instead of black bars). Keeps audio."""
    if width < 1 or height < 1:
        raise ValueError("blur-pad width and height must be >= 1")
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


def build_mono_args(input_path: str, output_path: str) -> list[str]:
    """Downmix audio to a single (mono) channel; the video is stream-copied."""
    return ["-i", input_path, "-c:v", "copy", "-ac", "1", output_path]


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
        raise ValueError("could not determine input dimensions for crop-to-aspect")
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
        raise ValueError("could not determine input duration for the contact sheet")
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
