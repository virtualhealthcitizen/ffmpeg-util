"""Make the sidecar package importable and provide shared fixtures.

These are integration tests: they import the real FastAPI app and drive real
ffmpeg/ffprobe. They skip cleanly when ffmpeg isn't on PATH (CI-friendly).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIDECAR_DIR))

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# Applies to every test in this directory.
pytestmark = pytest.mark.skipif(
    not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not on PATH"
)

TOKEN = "test-token"


@pytest.fixture(scope="session")
def client():
    if not (FFMPEG and FFPROBE):
        pytest.skip("ffmpeg/ffprobe not on PATH")
    import server  # imported lazily so collection doesn't fail without deps
    from fastapi.testclient import TestClient

    server.TOKEN = TOKEN  # require_token reads the module global each call
    return TestClient(server.app)


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """A real 3s test clip (video + tone) plus its directory."""
    d = tmp_path_factory.mktemp("media")
    src = d / "in.mp4"
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src),
        ],
        check=True,
    )
    return d, src


@pytest.fixture(scope="session")
def media_no_audio(tmp_path_factory):
    """A real 3s video-only clip (no audio stream) plus its directory."""
    d = tmp_path_factory.mktemp("media_no_audio")
    src = d / "in_no_audio.mp4"
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-c:v", "libx264", "-an", str(src),
        ],
        check=True,
    )
    return d, src


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="session")
def nvenc_available(tmp_path_factory):
    """Probe once whether h264_nvenc can actually encode (needs an NVIDIA GPU +
    driver, not just an ffmpeg build with the codec compiled in)."""
    if not FFMPEG:
        return False
    out = tmp_path_factory.mktemp("nvenc_probe") / "probe.mp4"
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
         "-c:v", "h264_nvenc", "-rc", "vbr", "-cq", "30", str(out)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and out.exists() and out.stat().st_size > 0
