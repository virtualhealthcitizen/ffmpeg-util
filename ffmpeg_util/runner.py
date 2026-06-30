"""Binary discovery and subprocess execution for ffmpeg/ffprobe."""

import os
import shutil
import subprocess
import tempfile
import threading
from typing import Callable, Sequence

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

    def build_ffmpeg_args(
        self, args: Sequence[str], *, loglevel: str | None = None
    ) -> list[str]:
        """Prepend the ffmpeg binary and global flags (overwrite/loglevel).

        ``loglevel`` overrides the default (``verbose`` when verbose else
        ``error``) — e.g. ``info`` so a streamed run surfaces ffmpeg's normal
        Input/Output/stream-mapping lines for a console view.
        """
        cmd = [self.ffmpeg, "-hide_banner"]
        level = loglevel or ("verbose" if self.verbose else "error")
        cmd += ["-loglevel", level]
        cmd.append("-y" if self.overwrite else "-n")
        cmd += list(args)
        return cmd

    @staticmethod
    def format_command(cmd: Sequence[str]) -> str:
        """Render a command list as a copy-pasteable shell string."""
        return subprocess.list2cmdline(list(cmd))

    def run_ffmpeg(
        self, args: Sequence[str], *, cwd: str | None = None
    ) -> subprocess.CompletedProcess | None:
        """Run an ffmpeg command. Returns None in dry-run mode."""
        cmd = self.build_ffmpeg_args(args)
        return self._run(cmd, cwd=cwd)

    def run_ffprobe(self, args: Sequence[str]) -> subprocess.CompletedProcess | None:
        """Run an ffprobe command. Returns None in dry-run mode."""
        cmd = [self.ffprobe, "-hide_banner"] + list(args)
        return self._run(cmd)

    def run_ffmpeg_capture(
        self, args: Sequence[str], *, loglevel: str = "info"
    ) -> subprocess.CompletedProcess | None:
        """Run ffmpeg at a chosen loglevel, capturing output without raising.

        Detection passes (e.g. ``cropdetect``) write their results to stderr at
        the ``info`` level, which the normal ``error`` loglevel would suppress;
        and they exit non-zero in benign cases, so we don't treat that as fatal.
        Returns the CompletedProcess (None in dry-run mode).
        """
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", loglevel, *args]
        rendered = self.format_command(cmd)
        if self.dry_run:
            print(rendered)
            return None
        if self.verbose:
            print(f"+ {rendered}")
        return subprocess.run(list(cmd), capture_output=True, text=True)

    def iter_ffmpeg_progress(
        self,
        args: Sequence[str],
        *,
        on_log: Callable[[str], None] | None = None,
        cwd: str | None = None,
    ):
        """Run ffmpeg with ``-progress`` and yield each progress block as a dict.

        ffmpeg writes ``key=value`` lines to stdout; each block ends with a
        ``progress=continue|end`` line. We accumulate keys and yield the dict at
        each block boundary, so callers get periodic updates (``out_time_us``,
        ``speed``, ``total_size``, …). Raises :class:`FfmpegError` on a non-zero
        exit. In dry-run mode it prints the command and yields nothing.

        If ``on_log`` is given, ffmpeg's stderr log lines are read live on a
        background thread and passed to it one line at a time (e.g. to surface a
        console view in the UI), in addition to the progress dicts yielded here.
        A background reader keeps stderr drained, so it can't fill its pipe and
        deadlock the stdout progress read.
        """
        # With on_log, raise the log level to `info` so ffmpeg emits its
        # Input/Output/stream-mapping lines, and KEEP ``-stats`` (don't pass
        # ``-nostats``) so it also prints the live ``frame=… time=… speed=…``
        # readout to stderr — otherwise the console view goes silent for the
        # whole encode of a long file (only the structured progress bar moves).
        # Without on_log we keep ``-nostats`` (nothing reads the live stats).
        pre = ["-progress", "pipe:1"] if on_log is not None else ["-progress", "pipe:1", "-nostats"]
        cmd = self.build_ffmpeg_args(
            [*pre, *args],
            loglevel="info" if on_log is not None else None,
        )
        rendered = self.format_command(cmd)
        if self.dry_run:
            print(rendered)
            return
        if self.verbose:
            print(f"+ {rendered}")

        # Without on_log, drain stderr to a temp file (no extra thread). With it,
        # pipe stderr and drain it on a background thread, forwarding each line.
        err_file = tempfile.TemporaryFile() if on_log is None else None
        err_lines: list[str] = []
        proc = subprocess.Popen(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=err_file if on_log is None else subprocess.PIPE,
            text=True,
            cwd=cwd,
        )
        reader = None
        if on_log is not None:
            def _drain_stderr() -> None:
                # Split on BOTH \r and \n: ffmpeg's live -stats readout refreshes
                # the same line with a carriage return (no newline), so plain line
                # iteration would buffer the whole encode into one chunk. Reading
                # char-by-char and breaking on either lets each stats refresh
                # surface as its own console line. stderr volume is low.
                assert proc.stderr is not None
                buf = []
                read = proc.stderr.read
                while True:
                    ch = read(1)
                    if ch == "":
                        break
                    if ch in ("\r", "\n"):
                        if buf:
                            line = "".join(buf)
                            buf = []
                            if line.strip():
                                err_lines.append(line)
                                try:
                                    on_log(line)
                                except Exception:
                                    pass  # a bad consumer must not kill the run
                    else:
                        buf.append(ch)
                if buf:  # trailing partial without a terminator
                    line = "".join(buf)
                    if line.strip():
                        err_lines.append(line)
                        try:
                            on_log(line)
                        except Exception:
                            pass
            reader = threading.Thread(target=_drain_stderr, daemon=True)
            reader.start()
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
            if on_log is None:
                err_file.seek(0)
                stderr = err_file.read().decode("utf-8", "replace")
            else:
                if reader is not None:
                    reader.join(timeout=2)
                stderr = "\n".join(err_lines)
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
            if err_file is not None:
                err_file.close()

    def _run(
        self, cmd: Sequence[str], *, cwd: str | None = None
    ) -> subprocess.CompletedProcess | None:
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
            cwd=cwd,
        )
        if proc.returncode != 0:
            raise FfmpegError(
                f"Command failed (exit {proc.returncode}): {rendered}",
                returncode=proc.returncode,
                stderr=proc.stderr,
            )
        return proc
