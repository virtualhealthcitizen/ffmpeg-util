"""Tests for binary discovery and the runner (no real ffmpeg needed)."""

import os
import shutil

import pytest

from ffmpeg_util.errors import FfmpegError, FfmpegNotFoundError
from ffmpeg_util.runner import FfmpegRunner, find_binary


def test_find_binary_prefers_override(tmp_path):
    fake = tmp_path / "myffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert find_binary("ffmpeg", override=str(fake)) == str(fake)


def test_find_binary_uses_env(tmp_path, monkeypatch):
    fake = tmp_path / "envffmpeg"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("FFMPEG_BIN", str(fake))
    assert find_binary("ffmpeg", env_var="FFMPEG_BIN") == str(fake)


def test_find_binary_missing_raises():
    with pytest.raises(FfmpegNotFoundError):
        find_binary("definitely-not-a-real-binary-xyz")


# A sentinel that won't resolve on PATH, so the override is used verbatim and the
# assertions don't depend on whether a real ffmpeg is installed.
_FAKE_FFMPEG = "ffmpeg-sentinel-not-on-path"


def test_build_ffmpeg_args_overwrite_flag():
    r = FfmpegRunner(ffmpeg=_FAKE_FFMPEG, overwrite=True)
    cmd = r.build_ffmpeg_args(["-i", "in.mp4", "out.mp4"])
    assert cmd[0] == _FAKE_FFMPEG
    assert "-y" in cmd and "-n" not in cmd


def test_build_ffmpeg_args_no_overwrite_flag():
    r = FfmpegRunner(ffmpeg=_FAKE_FFMPEG, overwrite=False)
    cmd = r.build_ffmpeg_args(["-i", "in.mp4", "out.mp4"])
    assert "-n" in cmd and "-y" not in cmd


def test_dry_run_does_not_execute(capsys):
    r = FfmpegRunner(ffmpeg="ffmpeg", dry_run=True)
    result = r.run_ffmpeg(["-i", "in.mp4", "out.mp4"])
    assert result is None
    out = capsys.readouterr().out
    assert "ffmpeg" in out and "in.mp4" in out


def test_verbose_sets_loglevel():
    r = FfmpegRunner(ffmpeg="ffmpeg", verbose=True)
    cmd = r.build_ffmpeg_args(["-i", "in.mp4", "out.mp4"])
    assert cmd[cmd.index("-loglevel") + 1] == "verbose"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_iter_progress_captures_stderr_on_error(tmp_path):
    # Exercises the real streaming path: a failing run must raise with stderr
    # captured (proves stderr is drained, not lost to a pipe deadlock).
    r = FfmpegRunner(overwrite=True)
    args = [str(tmp_path / "does-not-exist.mp4"), str(tmp_path / "out.mp4")]
    args = ["-i"] + args
    with pytest.raises(FfmpegError) as excinfo:
        list(r.iter_ffmpeg_progress(args))
    assert excinfo.value.stderr.strip()  # non-empty stderr was captured


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_iter_progress_kills_process_on_early_close(monkeypatch):
    # Cancelling a run closes the generator early; the finally must kill ffmpeg so
    # nothing lingers. Spy on Popen to grab the spawned process, then assert it's
    # gone after close(). This is the mechanism the UI's Cancel button relies on.
    import subprocess

    spawned = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr("ffmpeg_util.runner.subprocess.Popen", spy)
    r = FfmpegRunner(overwrite=True)
    gen = r.iter_ffmpeg_progress(
        ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=30",
         "-f", "null", "-"]
    )
    next(gen)        # spawn ffmpeg and read the first progress block
    gen.close()      # simulate cancel/disconnect -> finally -> kill + wait
    assert spawned, "ffmpeg process was never spawned"
    assert spawned[0].poll() is not None  # terminated, not left running


def test_iter_progress_dry_run_emits_command_and_no_blocks(capsys):
    r = FfmpegRunner(ffmpeg=_FAKE_FFMPEG, dry_run=True)
    blocks = list(r.iter_ffmpeg_progress(["-i", "in.mp4", "out.mp4"]))
    assert blocks == []
    out = capsys.readouterr().out
    assert "-progress" in out and "pipe:1" in out and "out.mp4" in out
