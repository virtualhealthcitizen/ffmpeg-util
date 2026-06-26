"""ffmpeg-util: a small, scriptable CLI wrapper around ffmpeg."""

from .errors import FfmpegError, FfmpegNotFoundError
from .runner import FfmpegRunner, find_binary

__version__ = "0.1.0"

__all__ = [
    "FfmpegError",
    "FfmpegNotFoundError",
    "FfmpegRunner",
    "find_binary",
    "__version__",
]
