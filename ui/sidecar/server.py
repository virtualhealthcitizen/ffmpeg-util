"""Local HTTP sidecar exposing the ffmpeg_util library to the Electron renderer.

Binds to 127.0.0.1 on a port chosen by the Electron main process (SIDECAR_PORT)
and requires a per-launch bearer token (SIDECAR_TOKEN) on every endpoint except
/health. This is the bridge that keeps the UI on the library API rather than
re-implementing ffmpeg logic in Node.
"""

import json
import os
import queue
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


@app.post("/concat")
def concat(req: ConcatReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
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
        runner.run_ffmpeg(commands.build_waveform_args(req.input, req.output, req.width, req.height))
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
    overwrite: bool = True


@app.post("/image-to-video")
def image_to_video(req: ImageToVideoReq, _: None = Depends(require_token)) -> dict:
    runner = FfmpegRunner(overwrite=req.overwrite)
    try:
        commands.require_output_extension(req.output)
        commands.require_output_dir(req.output)
        runner.run_ffmpeg(
            commands.build_image_to_video_args(req.input, req.output, req.seconds, fps=req.fps)
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
        runner.run_ffmpeg(commands.build_loudnorm_args(req.input, req.output, req.target_i))
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
        runner.run_ffmpeg(commands.build_volume_args(req.input, req.output, req.gain))
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
        runner.run_ffmpeg(commands.build_sample_rate_args(req.input, req.output, req.rate))
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
        runner.run_ffmpeg(commands.build_mono_args(req.input, req.output))
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
            commands.compress_to_size(
                runner, req.input, req.output, req.target_size,
                vcodec=req.vcodec, preset=req.preset,
            )
        else:
            runner.run_ffmpeg(commands.build_compress_args(
                req.input, req.output, crf=req.crf, bitrate=req.bitrate,
                width=req.width, height=req.height, vcodec=req.vcodec, preset=req.preset,
            ))
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
    # gif
    fps: int = 12
    # speed
    factor: float = 1.0
    # frames
    every: int = 1
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
    # crop-aspect
    aspect: str = "16:9"
    # blur-pad
    sigma: float = 20
    # image-to-video
    seconds: float = 5.0
    # autocrop
    limit: int = 24
    # title (metadata)
    title: str = ""
    # sample-rate
    rate: int = 44100
    # crop (uses width/height above for the rectangle size)
    x: int = 0
    y: int = 0
    # compress
    crf: int | None = None
    bitrate: str | None = None
    target_size: float | None = None
    height: int | None = None
    preset: str = "medium"


def _build_op_args(req: RunReq, total: float | None = None) -> tuple[list, str | None]:
    """Return (ffmpeg args, temp-file-to-clean-up-or-None) for the requested op."""
    op = req.op
    if op == "waveform":
        return commands.build_waveform_args(
            req.input, req.output, req.width or 1000, req.height or 200
        ), None
    if op == "fps":
        return commands.build_fps_args(req.input, req.output, req.fps), None
    if op == "eq":
        return commands.build_eq_args(
            req.input, req.output,
            brightness=req.brightness, contrast=req.contrast, saturation=req.saturation,
        ), None
    if op == "loudnorm":
        return commands.build_loudnorm_args(req.input, req.output, req.target_i), None
    if op == "grayscale":
        return commands.build_grayscale_args(req.input, req.output), None
    if op == "invert":
        return commands.build_invert_args(req.input, req.output), None
    if op == "boomerang":
        return commands.build_boomerang_args(req.input, req.output), None
    if op == "hstack":
        return commands.build_hstack_args(req.inputs or [], req.output), None
    if op == "vstack":
        return commands.build_vstack_args(req.inputs or [], req.output), None
    if op == "volume":
        return commands.build_volume_args(req.input, req.output, req.gain), None
    if op == "frames":
        return commands.build_extract_frames_args(req.input, req.output, req.every), None
    if op == "loop":
        return commands.build_loop_args(req.input, req.output, req.count), None
    if op == "pad":
        if not req.width or not req.height:
            raise ValueError("pad requires width and height")
        return commands.build_pad_args(req.input, req.output, req.width, req.height), None
    if op == "blur_pad":
        if not req.width or not req.height:
            raise ValueError("blur-pad requires width and height")
        return commands.build_blur_pad_args(
            req.input, req.output, req.width, req.height, req.sigma
        ), None
    if op == "image_to_video":
        return commands.build_image_to_video_args(
            req.input, req.output, req.seconds, fps=req.fps or 30
        ), None
    if op == "mute":
        return commands.build_mute_args(req.input, req.output), None
    if op == "replace_audio":
        if not req.audio:
            raise ValueError("replace-audio requires an audio file")
        return commands.build_replace_audio_args(req.input, req.audio, req.output), None
    if op == "mono":
        return commands.build_mono_args(req.input, req.output), None
    if op == "sample_rate":
        return commands.build_sample_rate_args(req.input, req.output, req.rate), None
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
                      height=req.height, preset=req.preset)
        if req.vcodec:
            kwargs["vcodec"] = req.vcodec
        return commands.build_compress_args(req.input, req.output, **kwargs), None
    if op == "concat":
        fd, list_file = tempfile.mkstemp(suffix=".txt", prefix="ffconcat_")
        os.close(fd)
        commands.write_concat_list(req.inputs or [], list_file)
        return commands.build_concat_args(req.inputs or [], req.output, list_file), list_file
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
) -> float | None:
    """Output duration for progress %, since some ops change length vs the input."""
    if op == "image_to_video":
        # A still image has no input duration; the output runs for `seconds`.
        return seconds
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
                filt = commands.gif_filter(req.fps, req.width or 480)
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
                         "-lavfi", f"{filt} [x];[x][1:v] paletteuse", req.output],
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
            if req.op in ("speed", "reverse", "fade"):
                # These need audio detection (and fade needs duration) and don't fit
                # the pure _build_op_args path.
                audio = commands.has_audio(runner, req.input)
                if req.op == "speed":
                    args = commands.build_speed_args(req.input, req.output, req.factor, audio=audio)
                elif req.op == "fade":
                    if not total:
                        raise ValueError("could not determine input duration for fade")
                    args = commands.build_fade_args(req.input, req.output, req.fade, total, audio=audio)
                else:
                    args = commands.build_reverse_args(req.input, req.output, audio=audio)
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
                seconds=req.seconds,
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
