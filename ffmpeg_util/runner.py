"""Binary discovery and subprocess execution for ffmpeg/ffprobe."""

import os
import shutil
import subprocess
import tempfile
from typing import Sequence

from .errors import FfmpegError, FfmpegNotFoundError


def find_binary(name: str, *, override: str | None = None, env_var: str | None = None) -> str:
    """Locate an executable, preferring an explicit override, then an env var, then PATH.

    ``name`` is the base tool name, e.g. ``"ffmpeg"`` or ``"ffprobe"``.

    An explicit ``override`` or ``env_var`` is treated as the caller's deliberate
    choice: if it resolves on PATH we use the resolved path, otherwise we trust it
    verbatim (it may be a bare command the caller knows is valid, or a path that
    only exists at run time). Only when nothing explicit is given do we require a
    hit on PATH, raising :class:`FfmpegNotFoundError` otherwise.
    """
    explicit = override or (os.environ.get(env_var) if env_var else None)
    if explicit:
        return shutil.which(explicit) or explicit

    on_path = shutil.which(name)
    if on_path:
        return on_path

    raise FfmpegNotFoundError(
        f"Could not find '{name}'. Install ffmpeg and ensure it is on your PATH, "
        f"or pass --{name} / set {env_var or name.upper() + '_BIN'}."
    )


class FfmpegRunner:
    """Thin wrapper that builds and runs ffmpeg/ffprobe commands.

    With ``dry_run=True`` commands are returned/printed but never executed, which
    keeps the command-building logic testable without ffmpeg installed.
    """

    def __init__(
        self,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        overwrite: bool = False,
    ):
        self._ffmpeg_override = ffmpeg
        self._ffprobe_override = ffprobe
        self.dry_run = dry_run
        self.verbose = verbose
        self.overwrite = overwrite
        self._ffmpeg_path: str | None = None
        self._ffprobe_path: str | None = None

    @property
    def ffmpeg(self) -> str:
        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_binary(
                "ffmpeg", override=self._ffmpeg_override, env_var="FFMPEG_BIN"
            )
        return self._ffmpeg_path

    @property
    def ffprobe(self) -> str:
        if self._ffprobe_path is None:
            self._ffprobe_path = find_binary(
                "ffprobe", override=self._ffprobe_override, env_var="FFPROBE_BIN"
            )
        return self._ffprobe_path

    def build_ffmpeg_args(self, args: Sequence[str]) -> list[str]:
        """Prepend the ffmpeg binary and global flags (overwrite/loglevel)."""
        cmd = [self.ffmpeg, "-hide_banner"]
        cmd += ["-loglevel", "verbose" if self.verbose else "error"]
        cmd.append("-y" if self.overwrite else "-n")
        cmd += list(args)
        return cmd

    @staticmethod
    def format_command(cmd: Sequence[str]) -> str:
        """Render a command list as a copy-pasteable shell string."""
        return subprocess.list2cmdline(list(cmd))

    def run_ffmpeg(self, args: Sequence[str]) -> subprocess.CompletedProcess | None:
        """Run an ffmpeg command. Returns None in dry-run mode."""
        cmd = self.build_ffmpeg_args(args)
        return self._run(cmd)

    def run_ffprobe(self, args: Sequence[str]) -> subprocess.CompletedProcess | None:
        """Run an ffprobe command. Returns None in dry-run mode."""
        cmd = [self.ffprobe, "-hide_banner"] + list(args)
        return self._run(cmd)

    def iter_ffmpeg_progress(self, args: Sequence[str]):
        """Run ffmpeg with ``-progress`` and yield each progress block as a dict.

        ffmpeg writes ``key=value`` lines to stdout; each block ends with a
        ``progress=continue|end`` line. We accumulate keys and yield the dict at
        each block boundary, so callers get periodic updates (``out_time_us``,
        ``speed``, ``total_size``, …). Raises :class:`FfmpegError` on a non-zero
        exit. In dry-run mode it prints the command and yields nothing.
        """
        cmd = self.build_ffmpeg_args(["-progress", "pipe:1", "-nostats", *args])
        rendered = self.format_command(cmd)
        if self.dry_run:
            print(rendered)
            return
        if self.verbose:
            print(f"+ {rendered}")
        # Drain stderr to a temp file rather than a pipe: we read stdout
        # incrementally for progress, so a pipe-buffered stderr could fill and
        # deadlock ffmpeg (it blocks writing logs while we wait on stdout).
        err_file = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            list(cmd), stdout=subprocess.PIPE, stderr=err_file, text=True
        )
        try:
            fields: dict[str, str] = {}
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                fields[key] = value
                if key == "progress":
                    yield fields
                    fields = {}
            proc.wait()
            err_file.seek(0)
            stderr = err_file.read().decode("utf-8", "replace")
            if proc.returncode != 0:
                raise FfmpegError(
                    f"Command failed (exit {proc.returncode}): {rendered}",
                    returncode=proc.returncode,
                    stderr=stderr,
                )
        finally:
            # If the consumer stopped early (cancel / client disconnect), don't
            # leave ffmpeg running.
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            err_file.close()

    def _run(self, cmd: Sequence[str]) -> subprocess.CompletedProcess | None:
        rendered = self.format_command(cmd)
        if self.dry_run:
            print(rendered)
            return None
        if self.verbose:
            print(f"+ {rendered}")
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise FfmpegError(
                f"Command failed (exit {proc.returncode}): {rendered}",
                returncode=proc.returncode,
                stderr=proc.stderr,
            )
        return proc
