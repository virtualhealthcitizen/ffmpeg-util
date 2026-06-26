"""Exception types for ffmpeg-util."""


class FfmpegError(RuntimeError):
    """Raised when an ffmpeg/ffprobe invocation fails.

    Carries the return code and captured stderr so callers can surface a
    useful message instead of a bare non-zero exit.
    """

    def __init__(self, message: str, *, returncode: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class FfmpegNotFoundError(FfmpegError):
    """Raised when the ffmpeg (or ffprobe) binary cannot be located."""
