# ffmpeg-util — TODO / Backlog

A small, scriptable command-line wrapper around `ffmpeg` for the common media
chores: convert, trim, concatenate, thumbnail, compress/resize, and probe.

## Design decisions (assumptions — revisit if wrong)

- **Language/runtime:** Python 3.11+ (stdlib only for the core; no hard 3rd-party deps).
- **Interface:** CLI with subcommands (`ffmpeg-util convert`, `... trim`, etc.).
  Internals are importable as a library (`ffmpeg_util` package).
- **UI:** Electron desktop app (local web app) over a Python sidecar — see the
  UI section below. The core library/CLI stay dependency-free; UI-only deps
  (Node/Electron + the sidecar's web framework) live in the `ui/` subproject.
- **ffmpeg binary:** use the binary on `PATH` by default; allow override via
  `--ffmpeg`/`--ffprobe` flags or `FFMPEG_BIN`/`FFPROBE_BIN` env vars. Fail with a
  clear message if not found.
- **Core scope (v1):** transcode/convert, trim/cut + concat, thumbnails/frames,
  compress/resize, probe.

## Backlog (remaining)

### UI — Electron local web app (DECIDED)
> **Stack:** Electron (Chromium renderer + web UI) over a **Python sidecar**.
> The core logic is the Python `ffmpeg_util` library, so Electron's main process
> launches a small local HTTP server (FastAPI/Flask) that exposes the library; the
> renderer (HTML/CSS/JS) calls that local API. This keeps the UI on the library
> API instead of re-implementing ffmpeg logic in Node.
>
> **Tradeoff (accepted):** Electron + Node + a Python sidecar is a heavy footprint,
> diverging from the core's stdlib-only property. Contained to the `ui/` subproject;
> the library and CLI stay dependency-free.

Architecture / setup:
- [x] Scaffold Electron app under `ui/` (main process, preload, renderer, build config)
- [x] Python sidecar (FastAPI) — `/health`, `/probe`, `/convert`, `/trim`,
      `/concat`, `/thumbnail`, `/compress` (all verified end-to-end)
- [x] Electron main spawns + health-checks the sidecar on launch; shuts it down on quit
      (verified: child python listens on loopback, killed on exit)
- [x] Define the HTTP API contract (request/response schemas) renderer ↔ sidecar (all endpoints)
- [x] Pick a free localhost port + per-launch bearer token (verified 401 without token)

Renderer (web UI):
- [x] File picker for source media
- [x] Drag-and-drop: drop files anywhere to load them into the active tab
      (concat appends; others take the first file). Uses Electron `webUtils`
      for paths; window highlights on drag-over. Pure drop logic unit-tested.
- [x] Operation screens for all commands (convert, trim, concat, thumbnail, compress) — tabbed UI
- [x] Show `probe` (stream/format) info for a selected file
- [x] Output path + overwrite handling; surface `FfmpegError` messages cleanly
- [x] Progress: stream ffmpeg `-progress` sidecar→renderer via SSE (`/run/stream`);
      renderer shows a live progress bar + percent/speed (verified incremental events)
- [x] Preview generated output inline — images via `<img>` and videos via
      `<video>` (range-served by `/file`). Verified via E2E tests + screenshots.
- [x] Persist last-used option fields (codecs, crf/bitrate, preset, sizes, trim start)
      across launches — userData JSON via IPC (`ui/settings.js`); BOM-tolerant.
      Verified E2E: save path writes settings, load path restores them in the UI.

Packaging / tests:
- [x] Package the app — sidecar bundled as a standalone PyInstaller binary
      (zero Python needed at runtime); `npm run pack` (@electron/packager)
      produces a runnable app. Verified E2E: packaged app launches with no
      Python on PATH, spawns the bundled sidecar, /health ok.
      (electron-builder config present but blocked by Windows symlink privilege.)
- [x] Automated sidecar E2E tests (pytest + FastAPI TestClient, real ffmpeg) —
      15 tests covering all endpoints, auth, SSE progress, and error events
      (`ui/sidecar/tests/`, skip cleanly when ffmpeg absent)
- [x] Renderer logic unit tests — extracted pure helpers to `renderer/logic.js`
      (path suggestion, image detection, SSE buffer parsing, line/field parsing);
      8 tests via Node's built-in `node:test` (zero new deps). `npm test`.

### Possible v2
- [x] `--target-size` (two-pass bitrate calc) for `compress` — core (`compress_to_size`,
      `target_video_bitrate_kbps`), CLI `--target-size MB`, sidecar (`/compress` +
      `/run/stream`), and a UI "Target MB" field. Verified E2E: 0.4 MB target → ~0.33 MB output.
- [x] Contact-sheet (`tile` filter) montage — core (`build_contact_sheet_args`,
      `contact_sheet`), CLI `contact-sheet`, sidecar (`/contact-sheet` + `/run/stream`),
      and Cols/Rows fields on the Thumbnail tab (reuses the image preview).
      Verified E2E: 3x2 grid of 160px tiles -> exactly 480x240.
- [x] Progress reporting via ffmpeg `-progress` (core `iter_ffmpeg_progress`; used by the UI sidecar)
- [ ] GitHub Actions CI running pytest on push

## Feature ideas (ideation backlog)

### Media operations
- [ ] Animated GIF export (palette two-pass: palettegen + paletteuse), fps/width/trim
- [ ] Transforms: crop, rotate, flip/hflip/vflip
- [ ] Playback speed: speed up / slow down (setpts + atempo)
- [ ] Loudness normalization (EBU R128 two-pass `loudnorm`); volume gain
- [ ] Audio: replace/mux an audio track; mix or strip tracks
- [ ] Subtitles: burn-in (hardsub) or mux soft subs; extract subtitles
- [ ] Watermark / text overlay (drawtext, image overlay with position)
- [ ] Image sequence ↔ video (frames to video, video to frames)
- [ ] Hardware-accelerated encoding option (NVENC/QSV) when available

### Workflow
- [ ] Cancel a running operation (kill the ffmpeg process mid-run)
- [ ] Batch mode: apply one operation to many files / a whole folder
- [ ] Job queue + history (recent runs, re-run, clear)
- [ ] Output presets ("web mp4", "Discord 8 MB", "GIF", …)
- [ ] "Reveal in Explorer" / open output after completion
- [ ] Before/after size + duration summary on completion

### UI / UX
- [ ] Recent files list / remembered last input dir
- [ ] Light/dark theme toggle
- [ ] Drag-to-reorder the concat list
- [ ] Keyboard shortcuts (run, switch tabs)
- [ ] Progress ETA estimate (from speed + remaining duration)

### Project / infra
- [ ] GitHub Actions CI (pytest + node:test); note: not E2E-verifiable locally
- [ ] Signed electron-builder installer (needs Windows Developer Mode/admin here)
- [ ] CLI: read defaults from a config file

## Done
- [x] Create package layout (`ffmpeg_util/`, `tests/`)
- [x] `pyproject.toml` with console entry point `ffmpeg-util`
- [x] `README.md` with install + usage
- [x] `.gitignore`
- [x] Binary discovery for ffmpeg/ffprobe (PATH, env, flag override)
- [x] Subprocess runner with error capture + clear failures (`FfmpegError`)
- [x] `--dry-run` (print the command instead of running it)
- [x] Global `--overwrite/-y` and `--verbose` handling
- [x] `probe` — JSON/summary of streams & format via ffprobe
- [x] `convert` — container/codec conversion, audio extraction
- [x] `trim` — cut by start/end/duration (stream-copy or re-encode)
- [x] `concat` — join multiple inputs (concat demuxer)
- [x] `thumbnail` — single frame or N evenly-spaced frames
- [x] `compress` — CRF or bitrate, with optional scaling
- [x] Unit tests for binary discovery + command building (no ffmpeg required)
- [x] CLI smoke tests via argparse (`--dry-run`)
- [x] Set up Python 3.11.9 via pyenv-win; pinned with `.python-version`
- [x] Run `pytest` — **29 passed** (surfaced + fixed a real bug: explicit
      ffmpeg/ffprobe overrides are now trusted verbatim when not on PATH)
- [x] Install ffmpeg 8.1.1 (winget Gyan.FFmpeg); fixed an environment-dependent
      unit test (sentinel binary name)
- [x] Real end-to-end run of every command against a generated clip; fixed a real
      `concat` bug — manifest now uses absolute paths (ffmpeg resolves relative
      entries against the manifest dir, not cwd). Verified: clean concat 10.02s,
      reencoded trim+concat 2.0s/4.02s.
