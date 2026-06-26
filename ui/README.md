# ffmpeg-util UI (Electron + Python sidecar)

A desktop UI for `ffmpeg-util`. Electron renders the web UI; a small local
**FastAPI sidecar** exposes the `ffmpeg_util` Python library, so the UI calls the
library API instead of re-implementing ffmpeg logic in Node.

```
ui/
  main.js            Electron main: launches sidecar, opens window
  preload.js         Exposes sidecar URL/token + file dialogs to the renderer
  renderer/          Web UI (index.html, renderer.js, styles.css)
  sidecar/
    server.py        FastAPI app over ffmpeg_util (/health, /probe, /convert)
    requirements.txt fastapi, uvicorn
```

## How it talks to Python

1. Electron main picks a free loopback port and generates a per-launch bearer token.
2. It spawns the sidecar (`python sidecar/server.py`) with `SIDECAR_PORT` / `SIDECAR_TOKEN`.
3. It waits for `GET /health` to succeed, then opens the window.
4. The renderer calls `http://127.0.0.1:<port>/…` with the bearer token.
5. On quit, the sidecar process is killed.

## Prerequisites

- The `ffmpeg_util` package importable by the Python the sidecar runs
  (`pip install -e .` from the repo root).
- Sidecar deps: `pip install -r sidecar/requirements.txt`.
- `ffmpeg`/`ffprobe` on PATH (or configured via env, as in the core library).
- Node.js + Electron deps: `npm install` in this folder.

## Run

```bash
# from ui/
npm install
pip install -r sidecar/requirements.txt
npm start
```

On startup the app **auto-discovers** a Python that has the sidecar deps installed
(it probes `FFMPEG_UTIL_PYTHON`, then pyenv-win versions, then `py`/`python3`/`python`,
keeping the first that can `import ffmpeg_util, fastapi, uvicorn`). This sidesteps
the Windows Store `python` stub and pyenv's `.bat` shim, which Node's `spawn` can't use.

To force a specific interpreter, set `FFMPEG_UTIL_PYTHON`:

```bash
# PowerShell
$env:FFMPEG_UTIL_PYTHON = "C:\path\to\python.exe"; npm start
```

If no usable interpreter is found, the app shows an error dialog with the fix.

## Tests

The sidecar has end-to-end integration tests (FastAPI `TestClient` driving real
ffmpeg). They skip automatically when ffmpeg isn't on PATH.

```bash
pip install -r sidecar/requirements-dev.txt
pytest sidecar/tests          # from ui/ — sidecar integration tests
npm test                      # renderer logic unit tests (node:test, no deps)
```

## Status

All operations are wired: **probe, convert (incl. audio extraction), trim, concat,
thumbnail, compress**, plus **live progress streaming** (SSE → progress bar).
Remaining: drag-and-drop, output preview, settings persistence, packaging, and
renderer-side logic tests.
