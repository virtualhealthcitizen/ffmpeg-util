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
- [x] Animated GIF export (palette two-pass: palettegen + paletteuse), fps/width/trim —
      core `make_gif`, CLI `gif`, sidecar (`/gif` + `/run/stream`), GIF tab (auto-previews).
      Verified E2E: CLI/sidecar produce a valid gif (codec=gif, width matches).
- [x] Transforms: rotate (cw/ccw/180) + flip (h/v) — core `build_transform_args`,
      CLI `transform --op`, sidecar (`/transform` + `/run/stream`), Transform tab.
      Verified E2E: rotate-cw swaps 320x240 -> 240x320. (Crop still pending.)
- [ ] Playback speed: speed up / slow down (setpts + atempo)
- [x] Volume gain — core `build_volume_args` (`volume=NdB`), CLI `volume --gain`,
      sidecar (`/volume` + `/run/stream`), Volume tab. Verified E2E: -6 dB drops measured
      mean_volume by ~6 dB.
- [x] Loudness normalization (EBU R128 `loudnorm`) — core `build_loudnorm_args`,
      CLI `loudnorm --target`, sidecar (`/loudnorm` + `/run/stream`), Loudness tab.
      Verified E2E: output integrated loudness hits target (-16 LUFS, measured via ebur128).
- [ ] Audio: replace/mux an audio track; mix or strip tracks
- [ ] Subtitles: burn-in (hardsub) or mux soft subs; extract subtitles
- [ ] Watermark / text overlay (drawtext, image overlay with position)
- [x] Image → video: loop a still image into a fixed-length clip — core
      `build_image_to_video_args`, CLI `image-to-video --seconds/--fps`, sidecar
      (`/image-to-video` + `/run/stream`), Image → video tab. Verified E2E:
      a PNG → 3s h264 320×240 clip (duration measured via ffprobe).
      (video → frames already shipped as `frames`.)
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

### More ideas (round 2)
- [x] Playback speed change (setpts + atempo chain) — core `change_speed`/`build_speed_args`,
      CLI `speed`, sidecar (`/speed` + `/run/stream`), Speed tab. Verified E2E: 2× -> ~half duration.
- [x] Auto-crop black bars (`cropdetect` → `crop`) — core `parse_cropdetect`/
      `detect_crop`/`autocrop` + `runner.run_ffmpeg_capture` (info-loglevel capture),
      CLI `autocrop --limit`, sidecar (`/autocrop` + `/run/stream`), Auto-crop tab.
      Verified E2E: a 320×240 letterboxed clip → 320×180 (bars removed), via CLI and
      the sidecar TestClient. Unit tests for the pure `parse_cropdetect` parser.
- [ ] Scene-change thumbnails (`select='gt(scene,…)'`)
- [ ] Trim multiple segments and join them in one go
- [ ] Output filename templating (tokens: `{name}`, `{w}x{h}`, `{date}`)
- [ ] "Show ffmpeg command" / copy-to-clipboard for any op (dry-run surfaced in UI)
- [ ] Estimate output size before encoding (compress preview)
- [ ] GIF tuning: dithering mode + loop count
- [x] Grayscale (desaturate) — core `build_grayscale_args` (`hue=s=0`), CLI `grayscale`,
      sidecar (`/grayscale` + `/run/stream`), Grayscale tab. Verified E2E: SATAVG -> ~0.
- [ ] Denoise / sharpen / deinterlace filter presets
- [ ] System notification (and optional sound) on completion
- [ ] Remember window size & position across launches
- [ ] A/B compare: input vs output side-by-side preview

### More ideas (round 3)
- [x] Crop (manual x/y/w/h rectangle) — core `build_crop_args`, CLI `crop`,
      sidecar (`/crop` + `/run/stream`), Crop tab. Verified E2E: 320x240 -> 160x120.
- [x] Mute / strip audio track — core `build_mute_args`, CLI `mute`, sidecar
      (`/mute` + `/run/stream`), Mute tab. Verified E2E: output has 0 audio streams.
- [x] Reverse a clip (video + audio) — core `reverse_media`/`build_reverse_args`, CLI `reverse`,
      sidecar (`/reverse` + `/run/stream`), Reverse tab. Verified E2E: output duration preserved.
- [x] Fade in/out (video fade + audio afade) — core `build_fade_args`/`fade`,
      CLI `fade --duration`, sidecar (`/fade` + `/run/stream`), Fade tab.
      Verified E2E: fade-in makes the first frame near-black (YAVG drops).
- [x] Extract every Nth frame as images — core `build_extract_frames_args`, CLI `frames`,
      sidecar (`/frames` + `/run/stream`), Frames tab. Verified E2E: 90 frames, every 30 -> 3 files.
- [x] Pad / letterbox to a target frame — core `build_pad_args` (scale-to-fit +
      centered pad), CLI `pad`, sidecar (`/pad` + `/run/stream`), Pad tab.
      Verified E2E: 320x240 -> exact 640x640 frame.
- [ ] Concatenate with automatic re-encode when inputs differ
- [ ] Per-op "open output folder" after completion
- [ ] Aspect-ratio presets (16:9, 9:16, 1:1) for compress/transform
- [x] Loop a short clip N times — core `build_loop_args` (-stream_loop), CLI `loop`,
      sidecar (`/loop` + `/run/stream`), Loop tab. Verified E2E: count=3 -> ~3x duration.

### More ideas (round 4)
- [x] Boomerang (play forward then reversed — duration doubles) — core
      `build_boomerang_args`, CLI `boomerang`, sidecar (`/boomerang` + `/run/stream`),
      Boomerang tab. Verified E2E: output duration ~= 2x input.
- [x] Brightness / contrast / saturation adjust (`eq` filter) — core `build_eq_args`,
      CLI `eq`, sidecar (`/eq` + `/run/stream`), Adjust tab. Verified E2E: brightness +0.3 raises YAVG.
- [ ] Invert colors (`negate`) / sepia tone
- [ ] Sharpen (`unsharp`) and denoise (`hqdn3d`) presets
- [ ] Deinterlace (`yadif`)
- [x] Crop-to-aspect (auto-crop to 16:9 / 9:16 / 1:1) — core `compute_aspect_crop`/
      `crop_to_aspect`, CLI `crop-aspect`, sidecar (`/crop-aspect` + `/run/stream`),
      Aspect tab. Verified E2E: 320x240 -> 320x180 (16:9).
- [x] Side-by-side (`hstack`) two videos — core `build_hstack_args`, CLI `hstack`, sidecar (`/hstack` + `/run/stream`), Side-by-side tab. Verified E2E: 320 + 320 -> 640 wide. Plus vstack.
- [ ] Picture-in-picture overlay
- [ ] Still image → video (image + duration, optional audio)
- [ ] Replace the audio track with an external audio file
- [ ] Set / clear metadata title

### More ideas (round 5)
- [x] Change frame rate without changing speed (`fps` filter) — core `build_fps_args`,
      CLI `fps`, sidecar (`/fps` + `/run/stream`), FPS tab. Verified E2E: 30fps -> 15fps.
- [x] Downmix audio to mono — core `build_mono_args` (`-ac 1`), CLI `mono`, sidecar
      (`/mono` + `/run/stream`), Mono tab. Verified E2E: stereo source -> 1 channel out.
- [ ] Trim silence from the ends (`silenceremove`)
- [ ] Blur or pixelate a region
- [ ] Crossfade-concatenate two clips (`xfade`)
- [ ] Timestamp / timecode overlay (`drawtext`)
- [x] Blurred-fill pad — core `build_blur_pad_args`, CLI `blur-pad`, sidecar (`/blur-pad` + `/run/stream`), Blur pad tab. Verified E2E: 320x240 -> 480x480.
- [ ] Stabilize shaky video (`vidstab`, two-pass)
- [ ] Convert to a specific pixel format / 10-bit
- [x] Generate a waveform PNG from audio (`showwavespic`) — core `build_waveform_args`, CLI `waveform`, sidecar (`/waveform` + `/run/stream`), Waveform tab. Verified E2E: 640x120 image.

### More ideas (round 6)
- [x] Set / clear a metadata title tag — core `build_title_args`, CLI `title`, sidecar (`/title` + `/run/stream`), Title tab. Verified E2E: ffprobe title tag set.
- [ ] Extract a poster frame at a percentage of the duration
- [ ] Two-up compare grid (input vs output, hstack)
- [ ] Trim by percentage (e.g. middle 50%)
- [ ] Add chapters from a list
- [ ] Burn a timestamp/elapsed overlay
- [ ] Auto-orient from rotation metadata, then strip it
- [ ] Export a short preview clip (first N seconds, downscaled)
- [x] Convert audio sample rate — core `build_sample_rate_args`, CLI `sample-rate`, sidecar (`/sample-rate` + `/run/stream`), Sample rate tab. Verified E2E: 44100 -> 22050.
- [ ] Change container only (remux) with codec compatibility check

### UI/UX components (round 7) — specialized components to ease individual tools
> Theme: the app now has ~30 near-identical "input / output / fields / run" tabs in
> one wrap-around nav. The friction is no longer *missing operations* — it's
> *navigation, parameter entry, and feedback*. These are specialized UI components,
> not new ffmpeg ops.

Navigation (cross-cutting — the 30-tab wall):
- [ ] **Tool search / command palette** — a filter box above the tabs that narrows
      the 30 buttons live by name + aliases (e.g. "rotate"→Transform, "resize"→Compress,
      "square"→Aspect). Ctrl/Cmd+K focuses it; Enter jumps to the first match; Esc clears.
      *(Highest leverage: every session starts by finding the right tool.)*
- [ ] Group the tabs into labeled categories (Convert · Trim/Frames · Resize/Frame ·
      Video FX · Color · Audio · Combine · Metadata) so the nav scans in seconds.
- [ ] Favorites / recently-used tools pinned to the top of the nav.

Direct-manipulation (visual instead of typed numbers):
- [ ] **Visual crop selector** — draggable rectangle over a source frame; fills the
      Crop x/y/w/h (and Aspect) instead of typing pixels.
- [ ] Trim/GIF timeline scrubber — load the video, drag in/out handles to set
      start/end/duration visually (trim, gif, thumbnail time, poster frame).
- [ ] Before/after compare slider on the output preview (drag a divider over input↔output).

Input affordances (kill the typed-number friction — this is what bit "Blur pad"):
- [x] **Auto source-preview + friendly probe card** — on file select/drop/type, the
      active tab's input auto-shows an inline player/thumbnail plus a chip summary
      (duration · W×H · fps · codecs · channels · rate · file size). Pure
      `summarizeProbe`/`formatBytes`/`formatDuration`/`parseFrameRate` in `logic.js`;
      renderer reuses `/probe?as_json` + `/file`. Verified: node:test (7 new cases,
      28 total) + headless Electron E2E against the real sidecar (320×240 clip →
      correct chips + video preview, screenshot).
- [ ] **Dimension / aspect presets** — clickable chips (16:9, 9:16, 1:1, 720p, 1080p,
      "match source") that fill Width/Height for pad, blur_pad, crop, compress.
- [ ] Sliders with live readouts for the numeric ops — volume (dB), speed (×),
      eq (brightness/contrast/saturation), fade (s), loudnorm (LUFS), blur sigma.
- [ ] Auto-fill the output path from input + op suffix (in.mp4 → in.blurpad.mp4) so
      "output required" stops being a manual step.

Workflow / feedback components:
- [ ] Cancel button — kill the running ffmpeg process mid-op.
- [ ] "Show ffmpeg command" + copy-to-clipboard (surface the dry-run for any op).
- [ ] Drag-to-reorder the concat list, with per-row thumbnails.
- [ ] Output presets dropdown ("Web MP4", "Discord 8 MB", "GIF", …).
- [ ] Job history strip — recent runs with re-run / reveal-in-Explorer.
- [ ] "Reveal in Explorer" / open-output button on completion.
- [ ] Before/after size + duration summary on completion.
- [ ] Inline per-field validation (highlight the offending field, not just the status line).
- [ ] System notification (+ optional sound) on completion; light/dark theme toggle;
      remember window size & position.

**Priority for this round (highest first):**
1. ~~Tool search / command palette~~ — DONE (round 7).
2. ~~Auto source-preview + friendly probe card~~ — DONE (round 7).
3. Dimension / aspect presets — directly fixes the Blur-pad width/height pain. **← next.**
4. Sliders with live readouts; 5. Visual crop selector; 6. the rest.

- [x] **Tool search / command palette** — filter box above the tabs (pure
      `filterTools`/`TOOL_ALIASES` in `logic.js`), live-narrows the 30 buttons by
      name + alias; Ctrl/Cmd+K focus, Enter jumps to first match, Esc clears, "no
      tools match" state. CLI/sidecar untouched. Verified: node:test unit tests +
      headless Electron E2E (typed "rotate" → only Transform visible, screenshot).

### UI/UX components (round 8) — build on the source card + search
> Now that there's an embedded source player + live probe data on every tab, a lot
> of "type a number by hand" friction can become "click what you can already see."
> These ideas mostly *consume* the round-7 source card rather than add ffmpeg ops.

Make the probe data actionable (the source card is read-only today):
- [x] **Clickable probe chips** — the Size chip fills Width/Height on
      crop/pad/blur_pad/compress/thumbnail/gif/waveform; the FPS chip fills the FPS
      tab (accent-highlighted + cursor when actionable). Pure `sourceFillActions`/
      `DIMENSION_FIELDS`/`FPS_FIELDS` in `logic.js`. This finishes the Blur-pad story
      (the card shows the size — now one click fills it). Verified: node:test (3 new,
      31 total) + headless Electron E2E against the real sidecar (click Size on Blur
      pad → width/height = 320/240; click FPS → 30; non-fillable on Convert; shot).
      Folds in the "Match source" idea below — the chip *is* the match-source action.
- [~] "Match source" buttons — subsumed by clickable chips above.
- [x] **Multi-input probe + mismatch guard** for hstack/vstack/concat — a compat
      banner probes all inputs and warns before running when they're incompatible
      (hstack=equal heights, vstack=equal widths, concat=matching size), green-OK
      otherwise. Pure `videoDims`/`compatReport` in `logic.js`; `refreshCompat()` in
      the renderer (debounced, supersede-safe). Verified: node:test (4 new, 35 total)
      + headless Electron E2E vs the real sidecar (320×240 + 320×360 → hstack warns
      "Heights differ", vstack OK, concat warns; hidden on single-input tabs; shot).
- [ ] Estimated-output readout — live size/duration estimate from the probed input
      + current settings (compress CRF, gif fps/width, speed factor, trim range).

Direct manipulation on the embedded source player (it's already there):
- [ ] **Scrub-to-set-time** — "Use current time" buttons that read the source
      player's playhead into Trim start/end, GIF start, Thumbnail time, poster frame.
- [ ] Draw-a-rectangle crop overlay on the source frame → fills Crop x/y/w/h.
- [ ] In/out range handles on the player's scrub bar for Trim/GIF duration.

Workflow / re-use:
- [ ] Recent files dropdown on inputs + remembered last-used input directory.
- [ ] "Run again" / re-run last op with the same settings; per-tab last output path.
- [ ] Output filename templating with tokens ({name}, {op}, {w}x{h}, {date}).
- [ ] Toast on completion with inline "Open" / "Reveal in Explorer" actions.
- [ ] Friendlier error surface — map common ffmpeg stderr (no such file, codec not
      found, dimensions not divisible by 2) to a one-line hint above the raw text.

Navigation / layout polish (the 30-tab nav is still a wall when search is empty):
- [ ] Group tabs into labeled categories (carried from round 7) — pairs well with search.
- [ ] Favorites: pin frequently-used tools to a top row; persist across launches.
- [ ] Collapse/expand the Source and Probe cards to reclaim vertical space.
- [ ] Keyboard: Enter runs the active tab's primary action; arrows cycle tabs.

**Priority for round 8 (highest first):**
1. ~~Clickable probe chips + "Match source"~~ — DONE.
2. ~~Multi-input probe + mismatch guard~~ — DONE.
3. Scrub-to-set-time — high-value, reuses the player we just shipped. **← next.**
4. Estimated-output readout; 5. friendlier errors; 6. the rest.

### UI/UX components (round 9) — safety, persistence, power-user flow
> A different angle from rounds 7–8: not new affordances, but making the existing
> flow safe, sticky, and faster for repeat use. Some of these are latent gaps in
> the current renderer, not just nice-to-haves.

Safety / correctness (latent gaps in the current UI):
- [ ] **Overwrite confirmation** — every run sends `overwrite: true`, so the UI
      silently clobbers existing outputs. Probe the output path and confirm first.
- [ ] **Disable the Run button while an op is in flight** — today buttons stay live,
      so a double-click fires the op twice against the same output.
- [ ] Pre-run validation — verify the input exists and the output dir is writable
      before launching ffmpeg; highlight the offending field instead of a late error.
- [ ] Warn on odd width/height for x264 (must be even) before the run fails.
- [ ] Cancel a running op (kill the ffmpeg process) and reset the UI.

Persistence / memory:
- [ ] Remember the active tab + window size/position across launches.
- [ ] Recent inputs/outputs per tab; remember the last-used directory for pickers.
- [ ] Save/load named presets (profiles) per tool.

Power-user flow:
- [ ] Operation queue — line up several ops and run them in sequence.
- [ ] Chain ops on one file (trim → compress …) without manual disk round-trips.
- [ ] "Copy as CLI" — emit the equivalent `ffmpeg-util` command for any op.

Help / discoverability:
- [ ] Per-tab one-line example + a "?" tooltip explaining each field.
- [ ] Friendly error mapping (carried from round 8) surfaced above the raw stderr.

**Priority for round 9 (highest first):**
1. Overwrite confirmation + Run-button-disabled-while-running — the two real safety
   gaps; small, high-confidence, E2E-verifiable.
2. Cancel a running op; 3. remember tab + window; 4. presets; 5. the rest.

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
