"""Local HTTP sidecar exposing the ffmpeg_util library to the Electron renderer.

Binds to 127.0.0.1 on a port chosen by the Electron main process (SIDECAR_PORT)
and requires a per-launch bearer token (SIDECAR_TOKEN) on every endpoint except
/health. This is the bridge that keeps the UI on the library API rather than
re-implementing ffmpeg logic in Node.
"""

import json
import os
import queue
import sys
import tempfile
import threading
import time

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ffmpeg_util import commands
from ffmpeg_util.errors import FfmpegError
from ffmpeg_util.runner import FfmpegRunner

TOKEN = os.environ.get("SIDECAR_TOKEN", "")

app = FastAPI(title="ffmpeg-util sidecar", version="0.1.0")

# Renderer pages load from file:// (Electron), so allow cross-origin; access is
# already restricted to loopback + bearer token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(authorization: str = Header(default="")) -> None:
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _find_system_font() -> str | None:
    """Return an absolute path to a usable system font, or None.

    Needed on Windows builds of ffmpeg that lack fontconfig — drawtext requires
    an explicit fontfile= when fontconfig isn't available.
    """
    if sys.platform == "win32":
        win_fonts = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts")
        for name in ("arial.ttf", "segoeui.ttf", "consola.ttf", "cour.ttf"):
            p = os.path.join(win_fonts, name)
            if os.path.isfile(p):
                return p
    else:
        for p in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ):
            if os.path.isfile(p):
                return p
    return None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/file")
def get_file(path: str, _: None = Depends(require_token)) -> FileResponse:
    """Serve a local output file (e.g. a generated thumbnail) for in-UI preview.

    Token-protected and loopback-only; the renderer fetches the path it just
    produced so it can show the result inline.
    """
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.get("/exists")
def exists(path: str, _: None = Depends(require_token)) -> dict:
    """Report whether ``path`` already exists on disk.

    The renderer calls this before a run so it can warn about (and confirm)
    clobbering an existing output, instead of silently overwriting it.
    """
    return {"exists": os.path.exists(path)}


class ProbeReq(BaseModel):
    input: str
    as_json: bool = False


@app.post("/probe")
def probe(req: ProbeReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner()
    try:
        return {"result": commands.probe(runner, req.input, as_json=req.as_json)}
    except FfmpegError as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))


class ConvertReq(BaseModel):
    input: str
    output: str
    vcodec: str | None = None
    acodec: str | None = None
    extract_audio: bool = False
    overwrite: bool = True


@app.post("/convert")
def convert(req: ConvertReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_convert_args(
            req.input, req.output, vcodec=req.vcodec, acodec=req.acodec,
            extract_audio=req.extract_audio,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TrimReq(BaseModel):
    input: str
    output: str
    start: str | None = None
    end: str | None = None
    duration: str | None = None
    reencode: bool = False
    overwrite: bool = True


@app.post("/trim")
def trim(req: TrimReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        args = commands.build_trim_args(
            req.input,
            req.output,
            start=req.start,
            end=req.end,
            duration=req.duration,
            reencode=req.reencode,
        )
        runner.run_ffmpeg(args)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ConcatReq(BaseModel):
    inputs: list[str]
    output: str
    overwrite: bool = True
    reencode: bool = False


@app.post("/concat")
def concat(req: ConcatReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        if req.reencode:
            dims = commands.probe_dimensions(runner, req.inputs[0])
            if dims is None:
                raise ValueError("Could not probe dimensions of the first input.")
            tw, th = dims
            has_audio = [commands.probe_has_audio(runner, p) for p in req.inputs]
            ff = commands.build_concat_filter_args(req.inputs, req.output, tw, th, has_audio=has_audio)
            runner.run_ffmpeg(ff)
        else:
            commands.concat(runner, req.inputs, req.output)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ThumbnailReq(BaseModel):
    input: str
    output: str
    time: str = "00:00:01"
    count: int = 1
    width: int | None = None
    overwrite: bool = True


@app.post("/thumbnail")
def thumbnail(req: ThumbnailReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        args = commands.build_thumbnail_args(
            req.input, req.output, time=req.time, count=req.count, width=req.width
        )
        runner.run_ffmpeg(args)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class WaveformReq(BaseModel):
    input: str
    output: str
    width: int = 1000
    height: int = 200
    overwrite: bool = True


@app.post("/waveform")
def waveform(req: WaveformReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.waveform(runner, req.input, req.output, req.width, req.height)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class CropAspectReq(BaseModel):
    input: str
    output: str
    aspect: str = "16:9"
    overwrite: bool = True


@app.post("/crop-aspect")
def crop_aspect(req: CropAspectReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        aw, ah = commands.parse_aspect(req.aspect)
        commands.crop_to_aspect(runner, req.input, req.output, aw, ah)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class AutocropReq(BaseModel):
    input: str
    output: str
    limit: int = 24
    overwrite: bool = True


@app.post("/autocrop")
def autocrop(req: AutocropReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        crop = commands.autocrop(runner, req.input, req.output, limit=req.limit)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    if crop is None:
        raise HTTPException(
            status_code=400,
            detail="Could not detect a crop region (no black bars found?).",
        )
    return {"output": req.output}


class StabilizeReq(BaseModel):
    input: str
    output: str
    shakiness: int = 5
    smoothing: int = 10
    overwrite: bool = True


@app.post("/stabilize")
def stabilize(req: StabilizeReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.stabilize(runner, req.input, req.output,
                           shakiness=req.shakiness, smoothing=req.smoothing)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class FpsReq(BaseModel):
    input: str
    output: str
    fps: float
    overwrite: bool = True


@app.post("/fps")
def fps(req: FpsReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_fps_args(req.input, req.output, req.fps))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ImageToVideoReq(BaseModel):
    input: str
    output: str
    seconds: float
    fps: int = 30
    audio: str | None = None
    overwrite: bool = True


@app.post("/image-to-video")
def image_to_video(req: ImageToVideoReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(
            commands.build_image_to_video_args(
                req.input, req.output, req.seconds, fps=req.fps, audio_path=req.audio
            )
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class EqReq(BaseModel):
    input: str
    output: str
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    overwrite: bool = True


@app.post("/eq")
def eq(req: EqReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_eq_args(
            req.input, req.output,
            brightness=req.brightness, contrast=req.contrast, saturation=req.saturation,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class PipReq(BaseModel):
    input: str
    overlay: str
    output: str
    size_pct: int = 25
    position: str = "bottom-right"
    overwrite: bool = True


@app.post("/pip")
def pip_op(req: PipReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_pip_args(
            req.input, req.overlay, req.output,
            size_pct=req.size_pct, position=req.position,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class HstackReq(BaseModel):
    inputs: list[str]
    output: str
    overwrite: bool = True


@app.post("/hstack")
def hstack(req: HstackReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_hstack_args(req.inputs, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


@app.post("/vstack")
def vstack(req: HstackReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_vstack_args(req.inputs, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class XfadeConcatReq(BaseModel):
    inputs: list[str]
    output: str
    transition: str = "fade"
    duration: float = 1.0
    offset: float | None = None
    overwrite: bool = True


@app.post("/xfade-concat")
def xfade_concat(req: XfadeConcatReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        offset = req.offset
        if offset is None:
            dur = commands.probe_duration(runner, req.inputs[0])
            if dur is None:
                raise ValueError(
                    "Could not probe clip duration — pass offset explicitly."
                )
            offset = max(0.0, dur - req.duration)
        runner.run_ffmpeg(commands.build_xfade_args(
            req.inputs, req.output,
            transition=req.transition,
            duration=req.duration,
            offset=offset,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class BoomerangReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/boomerang")
def boomerang(req: BoomerangReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_boomerang_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class GrayscaleReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/grayscale")
def grayscale(req: GrayscaleReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_grayscale_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class InvertReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/invert")
def invert(req: InvertReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_invert_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class AutorotateReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/autorotate")
def autorotate(req: AutorotateReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_autorotate_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class DeinterlaceReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/deinterlace")
def deinterlace(req: DeinterlaceReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_deinterlace_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class SharpenReq(BaseModel):
    input: str
    output: str
    amount: float = 1.5
    overwrite: bool = True


@app.post("/sharpen")
def sharpen(req: SharpenReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_sharpen_args(req.input, req.output, req.amount))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class DenoiseReq(BaseModel):
    input: str
    output: str
    strength: float = 4.0
    overwrite: bool = True


@app.post("/denoise")
def denoise(req: DenoiseReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_denoise_args(req.input, req.output, req.strength))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TimecodeReq(BaseModel):
    input: str
    output: str
    font_size: int = 24
    position: str = "top-left"
    color: str = "white"
    overwrite: bool = True


@app.post("/timecode")
def timecode(req: TimecodeReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_timecode_args(
            req.input, req.output,
            font_size=req.font_size, position=req.position, color=req.color,
            font_file=_find_system_font(),
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class WatermarkReq(BaseModel):
    input: str
    output: str
    text: str
    font_size: int = 24
    position: str = "bottom-right"
    color: str = "white"
    opacity: float = 1.0
    overwrite: bool = True


@app.post("/watermark")
def watermark(req: WatermarkReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_watermark_args(
            req.input, req.output,
            text=req.text, font_size=req.font_size,
            position=req.position, color=req.color, opacity=req.opacity,
            font_file=_find_system_font(),
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class HardsubReq(BaseModel):
    input: str
    subtitle: str
    output: str
    overwrite: bool = True


@app.post("/hardsub")
def hardsub(req: HardsubReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_hardsub_args(req.input, req.subtitle, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class FadeReq(BaseModel):
    input: str
    output: str
    duration: float = 1.0
    overwrite: bool = True


@app.post("/fade")
def fade(req: FadeReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.fade(runner, req.input, req.output, req.duration)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class LoudnormReq(BaseModel):
    input: str
    output: str
    target_i: float = -16.0
    overwrite: bool = True


@app.post("/loudnorm")
def loudnorm(req: LoudnormReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.loudnorm(runner, req.input, req.output, req.target_i)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class VolumeReq(BaseModel):
    input: str
    output: str
    gain: float
    overwrite: bool = True


@app.post("/volume")
def volume(req: VolumeReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.volume(runner, req.input, req.output, req.gain)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ReverseReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/reverse")
def reverse(req: ReverseReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.reverse_media(runner, req.input, req.output)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class FramesReq(BaseModel):
    input: str
    output: str
    every: int = 1
    overwrite: bool = True


@app.post("/frames")
def frames(req: FramesReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_extract_frames_args(req.input, req.output, req.every))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class SceneThumbsReq(BaseModel):
    input: str
    output: str
    threshold: float = 0.3
    width: int | None = None
    overwrite: bool = True


@app.post("/scene-thumbs")
def scene_thumbs(req: SceneThumbsReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_scene_thumbs_args(
            req.input, req.output, threshold=req.threshold, width=req.width))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class LoopReq(BaseModel):
    input: str
    output: str
    count: int
    overwrite: bool = True


@app.post("/loop")
def loop(req: LoopReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_loop_args(req.input, req.output, req.count))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class BlurRegionReq(BaseModel):
    input: str
    output: str
    x: int = 0
    y: int = 0
    width: int
    height: int
    sigma: float = 10
    overwrite: bool = True


@app.post("/blur-region")
def blur_region(req: BlurRegionReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(
            commands.build_blur_region_args(
                req.input, req.output, req.x, req.y, req.width, req.height, sigma=req.sigma
            )
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class BlurPadReq(BaseModel):
    input: str
    output: str
    width: int
    height: int
    sigma: float = 20
    overwrite: bool = True


@app.post("/blur-pad")
def blur_pad(req: BlurPadReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(
            commands.build_blur_pad_args(req.input, req.output, req.width, req.height, req.sigma)
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class PadReq(BaseModel):
    input: str
    output: str
    width: int
    height: int
    overwrite: bool = True


@app.post("/pad")
def pad(req: PadReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_pad_args(req.input, req.output, req.width, req.height))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TitleReq(BaseModel):
    input: str
    output: str
    title: str = ""
    overwrite: bool = True


@app.post("/title")
def title(req: TitleReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_title_args(req.input, req.output, req.title))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class SampleRateReq(BaseModel):
    input: str
    output: str
    rate: int
    overwrite: bool = True


@app.post("/sample-rate")
def sample_rate(req: SampleRateReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.sample_rate(runner, req.input, req.output, req.rate)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class MonoReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/mono")
def mono(req: MonoReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.mono(runner, req.input, req.output)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TrimSilenceReq(BaseModel):
    input: str
    output: str
    threshold_db: float = -50.0
    min_duration: float = 0.5
    overwrite: bool = True


@app.post("/trim-silence")
def trim_silence_op(req: TrimSilenceReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.trim_silence(
            runner, req.input, req.output,
            threshold_db=req.threshold_db,
            min_duration=req.min_duration,
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class MuteReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/mute")
def mute(req: MuteReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_mute_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ReplaceAudioReq(BaseModel):
    input: str
    audio: str
    output: str
    overwrite: bool = True


@app.post("/replace-audio")
def replace_audio(req: ReplaceAudioReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_replace_audio_args(req.input, req.audio, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class CropReq(BaseModel):
    input: str
    output: str
    width: int
    height: int
    x: int = 0
    y: int = 0
    overwrite: bool = True


@app.post("/crop")
def crop(req: CropReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(
            commands.build_crop_args(req.input, req.output, req.width, req.height, req.x, req.y)
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TransformReq(BaseModel):
    input: str
    output: str
    op: str
    overwrite: bool = True


@app.post("/transform")
def transform(req: TransformReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_transform_args(req.input, req.output, req.op))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class SpeedReq(BaseModel):
    input: str
    output: str
    factor: float
    overwrite: bool = True


@app.post("/speed")
def speed(req: SpeedReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.change_speed(runner, req.input, req.output, req.factor)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class GifReq(BaseModel):
    input: str
    output: str
    fps: int = 12
    width: int = 480
    start: str | None = None
    duration: str | None = None
    dither: str = "sierra2_4a"
    loop: int = 0
    overwrite: bool = True


@app.post("/gif")
def gif(req: GifReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.make_gif(
            runner, req.input, req.output,
            fps=req.fps, width=req.width, start=req.start, duration=req.duration,
            dither=req.dither, loop=req.loop,
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ContactSheetReq(BaseModel):
    input: str
    output: str
    cols: int = 4
    rows: int = 4
    width: int = 320
    overwrite: bool = True


@app.post("/contact-sheet")
def contact_sheet(req: ContactSheetReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.contact_sheet(
            runner, req.input, req.output, cols=req.cols, rows=req.rows, width=req.width
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class CompressReq(BaseModel):
    input: str
    output: str
    crf: int | None = None
    bitrate: str | None = None
    target_size: float | None = None
    width: int | None = None
    height: int | None = None
    vcodec: str = "libx264"
    preset: str = "medium"
    hwaccel: str = "none"
    overwrite: bool = True


@app.post("/compress")
def compress(req: CompressReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        if req.target_size is not None:
            if req.crf is not None or req.bitrate is not None:
                raise ValueError("Pass only one of target_size / crf / bitrate.")
            if req.hwaccel != "none":
                raise ValueError("hwaccel is not supported with target_size (two-pass software only).")
            commands.compress_to_size(
                runner, req.input, req.output, req.target_size,
                vcodec=req.vcodec, preset=req.preset,
            )
        else:
            runner.run_ffmpeg(commands.build_compress_args(
                req.input, req.output, crf=req.crf, bitrate=req.bitrate,
                width=req.width, height=req.height, vcodec=req.vcodec, preset=req.preset,
                hwaccel=req.hwaccel,
            ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class CompressEstimateReq(BaseModel):
    input: str
    crf: int | None = None
    bitrate: str | None = None
    width: int | None = None
    height: int | None = None
    vcodec: str = "libx264"
    preset: str = "medium"
    hwaccel: str = "none"
    sample_seconds: float = 3.0


@app.post("/compress/estimate-size")
def compress_estimate_size(req: CompressEstimateReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=True)
    try:
        result = commands.estimate_compress_size(
            runner, req.input,
            crf=req.crf, bitrate=req.bitrate, width=req.width, height=req.height,
            vcodec=req.vcodec, preset=req.preset, hwaccel=req.hwaccel,
            sample_seconds=req.sample_seconds,
        )
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return result


class RemuxReq(BaseModel):
    input: str
    output: str
    overwrite: bool = True


@app.post("/remux")
def remux(req: RemuxReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_remux_args(req.input, req.output))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class PreviewClipReq(BaseModel):
    input: str
    output: str
    seconds: float = 5.0
    width: int = 320
    overwrite: bool = True


@app.post("/preview-clip")
def preview_clip_op(req: PreviewClipReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_preview_clip_args(
            req.input, req.output, seconds=req.seconds, width=req.width,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TrimPctReq(BaseModel):
    input: str
    output: str
    start_pct: float = 0.0
    end_pct: float = 100.0
    reencode: bool = False
    overwrite: bool = True


@app.post("/trim-pct")
def trim_pct_op(req: TrimPctReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        dur = commands.probe_duration(runner, req.input)
        if dur is None:
            raise ValueError("could not probe duration for trim-pct")
        runner.run_ffmpeg(commands.build_trim_pct_args(
            req.input, req.output,
            start_pct=req.start_pct, end_pct=req.end_pct,
            duration_s=dur, reencode=req.reencode,
        ))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class PosterFrameReq(BaseModel):
    input: str
    output: str
    percent: float = 10.0
    width: int | None = None
    overwrite: bool = True


@app.post("/poster-frame")
def poster_frame_op(req: PosterFrameReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        commands.poster_frame(runner, req.input, req.output, percent=req.percent, width=req.width)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class PixfmtReq(BaseModel):
    input: str
    output: str
    pix_fmt: str = "yuv420p"
    overwrite: bool = True


@app.post("/pixfmt")
def pixfmt(req: PixfmtReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(commands.build_pixfmt_args(req.input, req.output, req.pix_fmt))
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class ChaptersReq(BaseModel):
    input: str
    output: str
    chapters_text: str
    overwrite: bool = True


@app.post("/chapters")
def chapters_op(req: ChaptersReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        chapters = commands.parse_chapters_text(req.chapters_text)
        dur = commands.probe_duration(runner, req.input)
        if dur is None:
            raise ValueError("Could not probe input duration for chapters")
        fd, meta_file = tempfile.mkstemp(suffix=".txt", prefix="ffchapters_")
        os.close(fd)
        try:
            commands.write_chapters_meta(chapters, dur, meta_file)
            runner.run_ffmpeg(commands.build_chapters_args(req.input, meta_file, req.output))
        finally:
            try:
                os.remove(meta_file)
            except OSError:
                pass
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class TrimSegmentsReq(BaseModel):
    input: str
    output: str
    segments_text: str
    overwrite: bool = True


@app.post("/trim-segments")
def trim_segments_op(req: TrimSegmentsReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        segments = commands.parse_segments_text(req.segments_text)
        commands.trim_segments(runner, req.input, req.output, segments)
    except (FfmpegError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_msg(exc))
    return {"output": req.output}


class RunReq(BaseModel):
    op: str
    output: str
    overwrite: bool = True
    input: str | None = None
    inputs: list[str] | None = None
    # replace-audio
    audio: str | None = None
    # pip (picture-in-picture)
    overlay: str | None = None
    pip_size: int = 25
    # hardsub
    subtitle: str | None = None
    # convert
    vcodec: str | None = None
    acodec: str | None = None
    extract_audio: bool = False
    # trim
    start: str | None = None
    end: str | None = None
    duration: str | None = None
    reencode: bool = False
    # thumbnail
    time: str = "00:00:01"
    count: int = 1
    width: int | None = None
    # contact-sheet
    cols: int = 4
    rows: int = 4
    # gif (None = use per-op default: 12 for gif, 30 for image_to_video)
    fps: int | None = None
    dither: str = "sierra2_4a"
    loop: int = 0
    # speed
    factor: float = 1.0
    # frames
    every: int = 1
    # scene-thumbs
    threshold: float = 0.3
    # volume
    gain: float = 0.0
    # loudnorm
    target_i: float = -16.0
    # fade (seconds, each end)
    fade: float = 1.0
    # transform
    transform: str | None = None
    # eq (color adjust)
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    # sharpen
    amount: float = 1.5
    # denoise
    strength: float = 4.0
    # timecode / watermark / pip (None = use per-op default: top-left for
    # timecode, bottom-right for watermark/pip)
    font_size: int = 24
    position: str | None = None
    color: str = "white"
    # watermark
    text: str = ""
    opacity: float = 1.0
    # crop-aspect
    aspect: str = "16:9"
    # blur-region / blur-pad (None = use per-op default: 10 for blur-region, 20 for blur-pad)
    sigma: float | None = None
    # image-to-video
    seconds: float = 5.0
    # autocrop
    limit: int = 24
    # title (metadata)
    title: str = ""
    # sample-rate
    rate: int = 44100
    # trim-silence
    threshold_db: float = -50.0
    min_duration: float = 0.5
    # crop (uses width/height above for the rectangle size)
    x: int = 0
    y: int = 0
    # compress
    crf: int | None = None
    bitrate: str | None = None
    target_size: float | None = None
    height: int | None = None
    preset: str = "medium"
    hwaccel: str = "none"
    # poster-frame
    percent: float = 10.0
    # trim-pct
    start_pct: float = 0.0
    end_pct: float = 100.0
    # xfade-concat
    transition: str = "fade"
    xfade_duration: float = 1.0
    xfade_offset: float | None = None
    # stabilize
    shakiness: int = 5
    smoothing: int = 10
    # pixfmt (pixel format conversion)
    pix_fmt: str = "yuv420p"
    # chapters (metadata)
    chapters_text: str = ""
    # trim-segments
    segments_text: str = ""


def _build_op_args(req: RunReq, total: float | None = None) -> tuple[list, str | None]:
    """Return (ffmpeg args, temp-file-to-clean-up-or-None) for the requested op."""
    op = req.op
    if op == "remux":
        return commands.build_remux_args(req.input, req.output), None
    if op == "trim_pct":
        if total is None:
            raise ValueError("could not probe duration for trim-pct streaming")
        return commands.build_trim_pct_args(
            req.input, req.output,
            start_pct=req.start_pct, end_pct=req.end_pct,
            duration_s=total, reencode=req.reencode,
        ), None
    if op == "poster_frame":
        if total is None:
            raise ValueError("could not determine input duration for poster-frame")
        return commands.build_poster_frame_args(
            req.input, req.output, percent=req.percent, duration_s=total, width=req.width,
        ), None
    if op == "preview_clip":
        return commands.build_preview_clip_args(
            req.input, req.output, seconds=req.seconds, width=req.width or 320
        ), None
    if op == "fps":
        return commands.build_fps_args(req.input, req.output, req.fps or 0), None
    if op == "eq":
        return commands.build_eq_args(
            req.input, req.output,
            brightness=req.brightness, contrast=req.contrast, saturation=req.saturation,
        ), None
    if op == "grayscale":
        return commands.build_grayscale_args(req.input, req.output), None
    if op == "invert":
        return commands.build_invert_args(req.input, req.output), None
    if op == "auto_orient":
        return commands.build_autorotate_args(req.input, req.output), None
    if op == "deinterlace":
        return commands.build_deinterlace_args(req.input, req.output), None
    if op == "timecode":
        return commands.build_timecode_args(
            req.input, req.output,
            font_size=req.font_size, position=req.position or "top-left",
            color=req.color,
            font_file=_find_system_font(),
        ), None
    if op == "watermark":
        return commands.build_watermark_args(
            req.input, req.output,
            text=req.text or "", font_size=req.font_size,
            position=req.position or "bottom-right",
            color=req.color or "white", opacity=req.opacity,
            font_file=_find_system_font(),
        ), None
    if op == "pip":
        if not req.overlay:
            raise ValueError("pip requires an overlay video file")
        return commands.build_pip_args(
            req.input, req.overlay, req.output,
            size_pct=req.pip_size, position=req.position or "bottom-right",
        ), None
    if op == "hardsub":
        if not req.subtitle:
            raise ValueError("hardsub requires a subtitle file")
        return commands.build_hardsub_args(req.input, req.subtitle, req.output), None
    if op == "sharpen":
        return commands.build_sharpen_args(req.input, req.output, req.amount), None
    if op == "denoise":
        return commands.build_denoise_args(req.input, req.output, req.strength), None
    if op == "boomerang":
        return commands.build_boomerang_args(req.input, req.output), None
    if op == "hstack":
        return commands.build_hstack_args(req.inputs or [], req.output), None
    if op == "vstack":
        return commands.build_vstack_args(req.inputs or [], req.output), None
    if op == "xfade_concat":
        offset = req.xfade_offset
        if offset is None:
            inputs = req.inputs or []
            dur = commands.probe_duration(FfmpegRunner(), inputs[0] if inputs else "")
            if dur is None:
                raise ValueError(
                    "Could not probe clip duration — pass xfade_offset explicitly."
                )
            offset = max(0.0, dur - req.xfade_duration)
        return commands.build_xfade_args(
            req.inputs or [], req.output,
            transition=req.transition,
            duration=req.xfade_duration,
            offset=offset,
        ), None
    if op == "frames":
        return commands.build_extract_frames_args(req.input, req.output, req.every), None
    if op == "scene_thumbs":
        return commands.build_scene_thumbs_args(
            req.input, req.output, threshold=req.threshold, width=req.width
        ), None
    if op == "loop":
        return commands.build_loop_args(req.input, req.output, req.count), None
    if op == "pad":
        if not req.width or not req.height:
            raise ValueError("pad requires width and height")
        return commands.build_pad_args(req.input, req.output, req.width, req.height), None
    if op == "blur_region":
        if not req.width or not req.height:
            raise ValueError("blur-region requires width and height")
        return commands.build_blur_region_args(
            req.input, req.output, req.x, req.y, req.width, req.height,
            sigma=req.sigma if req.sigma is not None else 10,
        ), None
    if op == "blur_pad":
        if not req.width or not req.height:
            raise ValueError("blur-pad requires width and height")
        return commands.build_blur_pad_args(
            req.input, req.output, req.width, req.height,
            req.sigma if req.sigma is not None else 20,
        ), None
    if op == "image_to_video":
        return commands.build_image_to_video_args(
            req.input, req.output, req.seconds, fps=req.fps or 30, audio_path=req.audio
        ), None
    if op == "mute":
        return commands.build_mute_args(req.input, req.output), None
    if op == "replace_audio":
        if not req.audio:
            raise ValueError("replace-audio requires an audio file")
        return commands.build_replace_audio_args(req.input, req.audio, req.output), None
    if op == "title":
        return commands.build_title_args(req.input, req.output, req.title), None
    if op == "crop":
        if not req.width or not req.height:
            raise ValueError("crop requires width and height")
        return commands.build_crop_args(
            req.input, req.output, req.width, req.height, req.x, req.y
        ), None
    if op == "transform":
        return commands.build_transform_args(req.input, req.output, req.transform or ""), None
    if op == "contact_sheet":
        if not total:
            raise ValueError("could not determine input duration for the contact sheet")
        return commands.build_contact_sheet_args(
            req.input, req.output, duration_s=total,
            cols=req.cols, rows=req.rows, width=req.width or 320,
        ), None
    if op == "convert":
        return commands.build_convert_args(
            req.input, req.output, vcodec=req.vcodec, acodec=req.acodec,
            extract_audio=req.extract_audio,
        ), None
    if op == "trim":
        return commands.build_trim_args(
            req.input, req.output, start=req.start, end=req.end,
            duration=req.duration, reencode=req.reencode,
        ), None
    if op == "thumbnail":
        return commands.build_thumbnail_args(
            req.input, req.output, time=req.time, count=req.count, width=req.width,
        ), None
    if op == "compress":
        kwargs = dict(crf=req.crf, bitrate=req.bitrate, width=req.width,
                      height=req.height, preset=req.preset, hwaccel=req.hwaccel)
        if req.vcodec:
            kwargs["vcodec"] = req.vcodec
        return commands.build_compress_args(req.input, req.output, **kwargs), None
    if op == "concat":
        inputs = req.inputs or []
        if req.reencode:
            runner = FfmpegRunner()
            dims = commands.probe_dimensions(runner, inputs[0])
            if dims is None:
                raise ValueError("Could not probe dimensions of the first input.")
            tw, th = dims
            has_audio = [commands.probe_has_audio(runner, p) for p in inputs]
            return commands.build_concat_filter_args(inputs, req.output, tw, th, has_audio=has_audio), None
        fd, list_file = tempfile.mkstemp(suffix=".txt", prefix="ffconcat_")
        os.close(fd)
        try:
            commands.write_concat_list(inputs, list_file)
            args = commands.build_concat_args(inputs, req.output, list_file)
        except Exception:
            # build_concat_args raises for <2 inputs; don't leak the manifest
            # we already wrote to disk when that happens.
            try:
                os.remove(list_file)
            except OSError:
                pass
            raise
        return args, list_file
    if op == "pixfmt":
        return commands.build_pixfmt_args(req.input, req.output, req.pix_fmt), None
    if op == "chapters":
        chapters = commands.parse_chapters_text(req.chapters_text or "")
        dur = total if total is not None else commands.probe_duration(FfmpegRunner(), req.input)
        if dur is None:
            raise ValueError("Could not probe input duration for chapters")
        fd, meta_file = tempfile.mkstemp(suffix=".txt", prefix="ffchapters_")
        os.close(fd)
        commands.write_chapters_meta(chapters, dur, meta_file)
        return commands.build_chapters_args(req.input, meta_file, req.output), meta_file
    if op == "trim_segments":
        segments = commands.parse_segments_text(req.segments_text or "")
        audio = commands.has_audio(FfmpegRunner(), req.input)
        return commands.build_trim_segments_args(req.input, req.output, segments, audio=audio), None
    raise ValueError(f"Unknown op: {op!r}")


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _parse_time(t: str) -> float:
    """Parse an ffmpeg time (seconds, MM:SS, or HH:MM:SS, with optional .ms)."""
    parts = [float(p) for p in str(t).split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"unrecognized time: {t!r}")


def _expected_output_duration(
    op: str,
    total: float | None,
    *,
    factor: float = 1.0,
    count: int = 1,
    start: str | None = None,
    end: str | None = None,
    duration: str | None = None,
    seconds: float | None = None,
    start_pct: float = 0.0,
    end_pct: float = 100.0,
    segments_text: str | None = None,
    inputs: list[str] | None = None,
    xfade_duration: float = 1.0,
    xfade_offset: float | None = None,
) -> float | None:
    """Output duration for progress %, since some ops change length vs the input."""
    if op == "image_to_video":
        # A still image has no input duration; the output runs for `seconds`.
        return seconds
    if op == "preview_clip":
        s = seconds if seconds is not None else 5.0
        return min(total, s) if total else s
    if op == "trim_segments":
        # The joined output is the sum of each segment's own length, not the
        # original (pre-trim) input duration that `total` holds.
        try:
            segments = commands.parse_segments_text(segments_text or "")
            return sum(max(0.0, e - s) for s, e in segments)
        except ValueError:
            return total
    if op == "xfade_concat":
        # The output plays clip 1 up to the transition offset, then plays all
        # of clip 2 — its length is offset + clip 2's own duration, not
        # `total` (clip 1's duration alone, which `total` holds since only the
        # first input is probed above).
        ins = inputs or []
        if not total or len(ins) < 2:
            return total
        offset = xfade_offset if xfade_offset is not None else max(0.0, total - xfade_duration)
        dur2 = commands.probe_duration(FfmpegRunner(), ins[1])
        return offset + dur2 if dur2 else total
    if op == "concat":
        # The concat demuxer/filter joins every input sequentially, so the
        # output spans the SUM of all their durations — not `total` alone,
        # which only holds the first input's duration (the only one probed
        # above in run_stream). Same failure family as trim_segments/
        # xfade_concat above: without this, progress hits 100% after just
        # the first clip and stalls while ffmpeg keeps encoding the rest.
        ins = inputs or []
        if not total or len(ins) < 2:
            return total
        durs = [total]
        for p in ins[1:]:
            d = commands.probe_duration(FfmpegRunner(), p)
            if d is None:
                return total
            durs.append(d)
        return sum(durs)
    if not total:
        return total
    if op == "speed" and factor:
        return total / factor
    if op == "loop":
        return total * max(1, count)
    if op == "boomerang":
        return total * 2
    if op == "trim":
        try:
            if duration is not None:
                return _parse_time(duration)
            if end is not None:
                return max(0.0, _parse_time(end) - _parse_time(start or "0"))
            if start is not None:
                return max(0.0, total - _parse_time(start))
        except ValueError:
            return total
    if op == "trim_pct":
        return total * max(0.0, end_pct - start_pct) / 100.0
    return total


@app.post("/run/stream")
def run_stream(req: RunReq, _: None = Depends(require_token)) -> StreamingResponse:
    """Run an operation and stream Server-Sent progress events.

    Emits `{type:"progress", percent, speed}` blocks, then a final
    `{type:"done", output}` or `{type:"error", detail}`.
    """
    def gen():
        runner = FfmpegRunner(overwrite=req.overwrite)
        cleanup = None
        try:
            commands.require_output_extension(req.output)
            commands.require_output_dir(req.output)
            probe_target = req.input or (req.inputs[0] if req.inputs else None)
            total = commands.probe_duration(runner, probe_target) if probe_target else None
            # Two-pass target-size encoding doesn't map to a single streamed pass;
            # run it to completion and emit just a final done event.
            if req.op == "compress" and req.target_size is not None:
                if req.hwaccel != "none":
                    raise ValueError("hwaccel is not supported with target_size (two-pass software only).")
                commands.compress_to_size(
                    runner, req.input, req.output, req.target_size,
                    duration_s=total, vcodec=req.vcodec or "libx264", preset=req.preset,
                )
                yield _sse({"type": "done", "output": req.output})
                return
            if req.op == "gif":
                # Two-pass palette GIF, streamed so the UI isn't frozen on
                # "Making GIF…": emit a phase line + live ffmpeg log per pass,
                # and a progress bar over the (longer) encode pass.
                gif_dither = req.dither if req.dither in commands.VALID_DITHERS else "sierra2_4a"
                gif_loop = req.loop
                filt = commands.gif_filter(req.fps or 12, req.width or 480)
                seek = ["-ss", req.start] if req.start is not None else []
                dur = ["-t", req.duration] if req.duration is not None else []
                gif_total = total
                if req.duration is not None:
                    try:
                        gif_total = _parse_time(req.duration)
                    except ValueError:
                        gif_total = total
                # A temp path we own; remove it so the encode never needs -y.
                fd, palette = tempfile.mkstemp(suffix=".png", prefix="ffgifpal_")
                os.close(fd)
                try:
                    os.remove(palette)
                except OSError:
                    pass
                log_q: queue.Queue = queue.Queue()
                try:
                    # Pass 1 (palettegen) reads the WHOLE clip but only emits one
                    # output frame at the very end, so ffmpeg gives no progress or
                    # stats while it runs — on a long clip the console/progress sit
                    # dead for many seconds (looks frozen). Run it on a background
                    # thread and emit our own heartbeat lines so the console keeps
                    # ticking until the palette is ready.
                    yield _sse({"type": "log", "line": "Pass 1/2: building color palette (reads the whole clip)…"})
                    pal_state: dict = {}

                    def _palettegen() -> None:
                        try:
                            for _ in runner.iter_ffmpeg_progress(
                                [*seek, "-i", req.input, *dur, "-vf", f"{filt},palettegen", palette],
                                on_log=log_q.put,
                            ):
                                pass
                        except Exception as exc:  # surface to the generator
                            pal_state["error"] = exc
                        finally:
                            pal_state["done"] = True

                    pal_thread = threading.Thread(target=_palettegen, daemon=True)
                    pal_thread.start()
                    pal_started = time.monotonic()
                    while not pal_state.get("done"):
                        emitted = False
                        while not log_q.empty():
                            yield _sse({"type": "log", "line": log_q.get_nowait()})
                            emitted = True
                        if not emitted:
                            elapsed = int(time.monotonic() - pal_started)
                            yield _sse({"type": "log", "line": f"  …analyzing frames for the palette ({elapsed}s)…"})
                            yield _sse({"type": "progress", "percent": None, "phase": "palettegen",
                                        "speed": None, "out_time": None, "total": None})
                        pal_thread.join(timeout=1.2)
                    while not log_q.empty():
                        yield _sse({"type": "log", "line": log_q.get_nowait()})
                    if pal_state.get("error") is not None:
                        raise pal_state["error"]
                    yield _sse({"type": "log", "line": "Pass 2/2: encoding GIF…"})
                    for fields in runner.iter_ffmpeg_progress(
                        [*seek, "-i", req.input, "-i", palette, *dur,
                         "-lavfi", f"{filt} [x];[x][1:v] paletteuse=dither={gif_dither}",
                         "-loop", str(gif_loop), req.output],
                        on_log=log_q.put,
                    ):
                        while not log_q.empty():
                            yield _sse({"type": "log", "line": log_q.get_nowait()})
                        out_us = fields.get("out_time_us") or fields.get("out_time_ms")
                        out_time = None
                        if out_us:
                            try:
                                out_time = int(out_us) / 1_000_000
                            except ValueError:
                                out_time = None
                        percent = None
                        if gif_total and out_time is not None:
                            percent = max(0.0, min(100.0, round(out_time / gif_total * 100, 1)))
                        yield _sse({
                            "type": "progress", "percent": percent,
                            "speed": fields.get("speed"), "phase": fields.get("progress"),
                            "out_time": out_time, "total": gif_total,
                        })
                    while not log_q.empty():
                        yield _sse({"type": "log", "line": log_q.get_nowait()})
                finally:
                    try:
                        os.remove(palette)
                    except OSError:
                        pass
                yield _sse({"type": "done", "output": req.output})
                return
            if req.op == "stabilize":
                # Two-pass vidstab: pass 1 (detect) on a background thread with
                # heartbeat, then pass 2 (transform) with streaming progress.
                # A private temp dir keeps the trf filename bare (no drive colon)
                # so ffmpeg's filter option parser handles it correctly on Windows.
                import shutil as _shutil
                trf_dir = tempfile.mkdtemp(prefix="ffstab_")
                trf_name = "transforms.trf"
                log_q: queue.Queue = queue.Queue()
                try:
                    yield _sse({"type": "log", "line": "Pass 1/2: analysing motion (reads the whole clip)…"})
                    stab_state: dict = {}

                    def _detect() -> None:
                        try:
                            for _ in runner.iter_ffmpeg_progress(
                                commands.build_vidstab_detect_args(
                                    req.input, trf_name,
                                    shakiness=req.shakiness, accuracy=15,
                                ),
                                on_log=log_q.put,
                                cwd=trf_dir,
                            ):
                                pass
                        except Exception as exc:
                            stab_state["error"] = exc
                        finally:
                            stab_state["done"] = True

                    det_thread = threading.Thread(target=_detect, daemon=True)
                    det_thread.start()
                    det_started = time.monotonic()
                    while not stab_state.get("done"):
                        emitted = False
                        while not log_q.empty():
                            yield _sse({"type": "log", "line": log_q.get_nowait()})
                            emitted = True
                        if not emitted:
                            elapsed = int(time.monotonic() - det_started)
                            yield _sse({"type": "log",
                                        "line": f"  …detecting motion ({elapsed}s)…"})
                            yield _sse({"type": "progress", "percent": None, "phase": "detect",
                                        "speed": None, "out_time": None, "total": None})
                        det_thread.join(timeout=1.2)
                    while not log_q.empty():
                        yield _sse({"type": "log", "line": log_q.get_nowait()})
                    if stab_state.get("error") is not None:
                        raise stab_state["error"]

                    yield _sse({"type": "log", "line": "Pass 2/2: stabilizing…"})
                    for fields in runner.iter_ffmpeg_progress(
                        commands.build_vidstab_transform_args(
                            req.input, req.output, trf_name, smoothing=req.smoothing
                        ),
                        on_log=log_q.put,
                        cwd=trf_dir,
                    ):
                        while not log_q.empty():
                            yield _sse({"type": "log", "line": log_q.get_nowait()})
                        out_us = fields.get("out_time_us") or fields.get("out_time_ms")
                        out_time = None
                        if out_us:
                            try:
                                out_time = int(out_us) / 1_000_000
                            except ValueError:
                                out_time = None
                        percent = None
                        if total and out_time is not None:
                            percent = max(0.0, min(100.0, round(out_time / total * 100, 1)))
                        yield _sse({
                            "type": "progress", "percent": percent,
                            "speed": fields.get("speed"), "phase": fields.get("progress"),
                            "out_time": out_time, "total": total,
                        })
                    while not log_q.empty():
                        yield _sse({"type": "log", "line": log_q.get_nowait()})
                finally:
                    _shutil.rmtree(trf_dir, ignore_errors=True)
                yield _sse({"type": "done", "output": req.output})
                return
            if req.op in (
                "speed", "reverse", "fade",
                "volume", "loudnorm", "mono", "sample_rate", "trim_silence", "waveform",
            ):
                # These need audio detection (and fade needs duration) and don't fit
                # the pure _build_op_args path.
                audio = commands.has_audio(runner, req.input)
                if req.op == "speed":
                    args = commands.build_speed_args(req.input, req.output, req.factor, audio=audio)
                elif req.op == "fade":
                    if not total:
                        raise ValueError("could not determine input duration for fade")
                    args = commands.build_fade_args(req.input, req.output, req.fade, total, audio=audio)
                elif req.op == "reverse":
                    args = commands.build_reverse_args(req.input, req.output, audio=audio)
                else:
                    # volume/loudnorm/mono/sample_rate/trim_silence/waveform are
                    # audio-only transforms with no video-domain fallback — a
                    # missing audio stream leaves nothing for the op to do.
                    if not audio:
                        raise ValueError("input has no audio stream to adjust")
                    if req.op == "volume":
                        args = commands.build_volume_args(req.input, req.output, req.gain)
                    elif req.op == "loudnorm":
                        args = commands.build_loudnorm_args(req.input, req.output, req.target_i)
                    elif req.op == "mono":
                        args = commands.build_mono_args(req.input, req.output)
                    elif req.op == "sample_rate":
                        args = commands.build_sample_rate_args(req.input, req.output, req.rate)
                    elif req.op == "waveform":
                        args = commands.build_waveform_args(
                            req.input, req.output, req.width or 1000, req.height or 200
                        )
                    else:
                        args = commands.build_trim_silence_args(
                            req.input, req.output,
                            threshold_db=req.threshold_db, min_duration=req.min_duration,
                        )
                cleanup = None
            elif req.op == "crop_aspect":
                dims = commands.probe_dimensions(runner, req.input)
                if not dims:
                    raise ValueError("could not determine input dimensions for crop-to-aspect")
                aw, ah = commands.parse_aspect(req.aspect)
                cw, ch, x, y = commands.compute_aspect_crop(dims[0], dims[1], aw, ah)
                args = commands.build_crop_args(req.input, req.output, cw, ch, x, y)
                cleanup = None
            elif req.op == "autocrop":
                crop = commands.detect_crop(runner, req.input, limit=req.limit)
                if crop is None:
                    raise ValueError("could not detect a crop region (no black bars found?)")
                cw, ch, x, y = crop
                args = commands.build_crop_args(req.input, req.output, cw, ch, x, y)
                cleanup = None
            else:
                args, cleanup = _build_op_args(req, total)
            expected = _expected_output_duration(
                req.op, total, factor=req.factor, count=req.count,
                start=req.start, end=req.end, duration=req.duration,
                seconds=req.seconds, start_pct=req.start_pct, end_pct=req.end_pct,
                segments_text=req.segments_text,
                inputs=req.inputs, xfade_duration=req.xfade_duration,
                xfade_offset=req.xfade_offset,
            )
            log_q: queue.Queue = queue.Queue()
            for fields in runner.iter_ffmpeg_progress(args, on_log=log_q.put):
                # Flush any ffmpeg log lines first so the console view keeps pace.
                while not log_q.empty():
                    yield _sse({"type": "log", "line": log_q.get_nowait()})
                # out_time_ms is microseconds in ffmpeg (historical quirk), as is out_time_us.
                out_us = fields.get("out_time_us") or fields.get("out_time_ms")
                out_time = None
                if out_us:
                    try:
                        out_time = int(out_us) / 1_000_000
                    except ValueError:
                        out_time = None
                percent = None
                if expected and out_time is not None:
                    percent = max(0.0, min(100.0, round(out_time / expected * 100, 1)))
                yield _sse({
                    "type": "progress",
                    "percent": percent,
                    "speed": fields.get("speed"),
                    "phase": fields.get("progress"),
                    # out_time (output position, s) + total (expected output, s) let
                    # the renderer compute a live ETA from the encode speed.
                    "out_time": out_time,
                    "total": expected,
                })
            while not log_q.empty():
                yield _sse({"type": "log", "line": log_q.get_nowait()})
            yield _sse({"type": "done", "output": req.output})
        except (FfmpegError, ValueError) as exc:
            yield _sse({"type": "error", "detail": _msg(exc)})
        finally:
            if cleanup:
                try:
                    os.remove(cleanup)
                except OSError:
                    pass

    return StreamingResponse(gen(), media_type="text/event-stream")


def _msg(exc: Exception) -> str:
    stderr = getattr(exc, "stderr", "")
    return f"{exc}\n{stderr}".strip() if stderr else str(exc)


def main() -> None:
    port = int(os.environ.get("SIDECAR_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
