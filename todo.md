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
- [x] GitHub Actions CI running pytest on push — `.github/workflows/ci.yml`: python-tests (pytest root + sidecar, with ffmpeg) + node-tests (npm test); verified local pytest 97+65 passed, node:test 118 passed + E2E smoke (sidecar health, 33 tabs, compress output). ← next

## Feature ideas (ideation backlog)

### Media operations
- [x] Animated GIF export (palette two-pass: palettegen + paletteuse), fps/width/trim —
      core `make_gif`, CLI `gif`, sidecar (`/gif` + `/run/stream`), GIF tab (auto-previews).
      Verified E2E: CLI/sidecar produce a valid gif (codec=gif, width matches).
      **Bug fix (hunt):** encode pass placed `-t duration` between the two `-i` args,
      making it an ffmpeg *input* option for the palette instead of an *output* option —
      so GIFs with a `duration` encoded from `start` to EOF. Fixed by moving `*dur`
      after both `-i` args in `make_gif` (commands.py) and the streaming GIF path
      (sidecar/server.py); 1 new regression test (99 total); all 126 node:tests + 67
      sidecar tests green; E2E smoke passes.
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
- [x] Audio: replace an audio track — core `build_replace_audio_args` (map 0:v + 1:a,
      `-c:v copy -c:a aac -shortest`), CLI `replace-audio --audio`, sidecar
      (`/replace-audio` + `/run/stream` op `replace_audio`), Replace audio tab.
      Verified E2E: swap in a 22050 Hz track -> output audio is 22050 Hz, video
      stream-copied unchanged (320x240 h264). (mix/strip still open; strip = `mute`.)
- [x] Subtitles: burn-in (hardsub) — core `build_hardsub_args` (`subtitles=` filter, Windows path escaping), CLI `hardsub --subtitle`, sidecar (`/hardsub` + `/run/stream` op `hardsub`), Hardsub tab (Video FX, after Watermark). Verified E2E: 169 root pytest + 104 sidecar pytest + 190 node:test + smoke 5/5 (49 nav tabs).
- [x] Watermark / text overlay (drawtext text= with position/opacity/color/font-size) — core `build_watermark_args`, CLI `watermark`, sidecar (`/watermark` + `/run/stream` op `watermark`), Watermark tab (Video FX, after Timecode). Verified E2E: 185 node:test + 164 root pytest + 101 sidecar pytest + smoke 5/5 (48 nav tabs).
      **Bug fix (hunt):** `watermark` was never registered as a CLI subcommand — `build_parser()` had no `add_parser("watermark", …)` entry and `_dispatch()` had no matching branch, so `ffmpeg-util watermark …` failed with "invalid choice: watermark" and the renderer's "Copy as CLI" produced a non-functional command. Fixed by adding the `watermark` subparser (`--text`, `--font-size`, `--position`, `--color`, `--opacity`) and dispatch case; 1 new CLI dry-run regression test. 165 root + 101 sidecar + 185 node:test + smoke 5/5 green.
- [x] Image → video: loop a still image into a fixed-length clip — core
      `build_image_to_video_args`, CLI `image-to-video --seconds/--fps`, sidecar
      (`/image-to-video` + `/run/stream`), Image → video tab. Verified E2E:
      a PNG → 3s h264 320×240 clip (duration measured via ffprobe).
      (video → frames already shipped as `frames`.)
      **Bug fix (hunt):** `RunReq.fps` defaulted to 12 (GIF's default), so calling
      `/run/stream` with `op=image_to_video` without an explicit fps used 12 fps
      instead of the expected 30 fps (the CLI and `/image-to-video` endpoint default).
      Fixed by changing `fps: int = 12` to `fps: int | None = None` in `RunReq` and
      updating the GIF path to `req.fps or 12`; the existing `req.fps or 30` guard
      for image_to_video now works correctly. 1 new regression test (77 sidecar);
      117 core + 77 sidecar + 144 node:test + E2E smoke all green. ← next
- [ ] Hardware-accelerated encoding option (NVENC/QSV) when available

### Workflow
- [x] Cancel a running operation (kill the ffmpeg process mid-run) — Cancel button
      aborts the stream; sidecar kills ffmpeg on disconnect. (See round 9.)
- [ ] Batch mode: apply one operation to many files / a whole folder
- [ ] Job queue + history (recent runs, re-run, clear)
- [ ] Output presets ("web mp4", "Discord 8 MB", "GIF", …)
- [x] "Reveal in Explorer" / open output after completion
- [x] Before/after size + duration summary on completion — see round 8 below.

### UI / UX
- [x] Recent files list / remembered last input dir — a "Recent" dropdown above
      the tabs lists the most-recently-loaded inputs (newest first, deduped
      case-insensitively, capped); picking one loads it into the active tab (reuses
      `dropUpdate`). Recording hooks the picker/drop/typed-change paths; the picker's
      `defaultPath` is seeded from the last-used dir. Pure `addRecentFile`/
      `recentFileLabel`/`recentDir` in `logic.js`; persisted as `recentFiles` in
      `settings.json` (shallow-merge → coexists with sticky fields/presets/favorites).
      Verified: node:test (3 new, 109 total) + headless Electron E2E vs the real
      sidecar across two launches (load A then B → dropdown [B,A] + persisted; pick A
      → loads into input, moves to front; reorder persisted; restored on relaunch).
- [x] Drag-to-reorder the concat list — a draggable row list mirrors the
      `#concat-inputs` textarea (the canonical store, untouched); dragging a row
      reorders the lines and writes them back so every existing reader (run, drop,
      compat banner) is unchanged. Pure `reorderList` in `logic.js` (immutable,
      out-of-range-safe); `renderConcatList`/`setupConcatReorder` in renderer.js
      (HTML5 DnD, delegated handlers, hidden below 2 inputs). Verified: node:test
      (3 new, 112 total) + headless Electron E2E vs the real sidecar (3 clips →
      rows a,b,c; drag a→end → textarea+rows reorder to b,c,a; single input hides
      the list). ← next
- [x] Light/dark theme toggle — a top-right ☀/☾ button swaps the palette via
      `data-theme="light"` on `<html>`; styles.css gains a `:root[data-theme="light"]`
      override (added `--inset`/`--btn`/`--chip-hover` vars so hardcoded sunken
      fields/buttons follow the theme). Pure `resolveTheme`/`nextTheme`/
      `themeToggleLabel` in `logic.js`; renderer applies + persists `theme` in
      `settings.json` (shallow-merge → coexists with sticky fields/window bounds).
      Verified: node:test (3 new, 106 total) + headless Electron E2E vs the real
      sidecar (default dark; toggle → light palette/label/data-theme; persisted +
      restored across two launches; toggle back to dark; real compress still runs).
- [x] Drag-to-reorder the concat list — DONE (see the entry under UI/UX above:
      `reorderList` in `logic.js`, `renderConcatList` rows in renderer.js).
- [x] Keyboard shortcuts (run, switch tabs) — Ctrl/Cmd+Enter runs the active tab's
      primary action; Ctrl/Cmd+]/[ (or ./,) cycle the *visible* tabs (search-aware,
      wrap-around). Pure `keyboardAction`/`nextVisibleTab` in `logic.js`; a global
      keydown dispatcher in renderer.js; discoverability hint under the search box.
      Verified: node:test (5 new, 89 total) + headless Electron E2E vs the real
      sidecar (Ctrl+] convert→trim, Ctrl+[ back, wrap to last; Ctrl+Enter runs a
      real compress → output file produced).
- [x] **Progress ETA estimate (from speed + remaining duration)** — the sidecar
      progress event now also carries `out_time` (output position) + `total`
      (expected output duration); a live "ETA ~m:ss" readout under the progress bar
      counts down during a run. Pure `parseSpeed`/`etaSeconds`/`etaLabel` in
      `logic.js` (ETA = remaining output secs ÷ encode speed); `#eta` rendered/
      cleared by the renderer. Verified: node:test (4 new, 118 total) + sidecar
      pytest (progress events expose out_time/total) + headless Electron E2E vs the
      real sidecar (heavy 1080p compress → 107 ETA samples counting down
      1:08→0:11, hidden after completion, output produced).

### Project / infra
- [x] GitHub Actions CI (pytest + node:test) — DONE (see entry above in Possible v2)
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
- [x] Scene-change thumbnails (`select='gt(scene,…)'`) — core `build_scene_thumbs_args`
      (threshold + optional width), CLI `scene-thumbs --threshold/--width`, sidecar
      (`/scene-thumbs` + `/run/stream` op `scene_thumbs`), Scene thumbs tab (Trim & Frames
      category). Verified E2E: red→blue hard-cut clip → ≥1 PNG at threshold 0.1 (standalone
      + streaming); pytest 123 root + 81 sidecar; node:test 152; smoke 5/5 (40 tabs).
      **Bug fix (hunt):** `scene_thumbs` panel in `index.html` used hyphen-format element IDs
      (`scene-thumbs-input/output/threshold/width`) while every logic.js function that derives
      IDs from the tab name concatenates underscores (`tab + "-input"` → `scene_thumbs-input`),
      so drag-and-drop, source preview, output auto-fill, and field highlights were all silently
      broken on the Scene thumbs tab. Fixed by standardising all 7 element IDs/data-* attributes
      in `index.html` + the 5 hardcoded strings in `renderer.js` + 2 FIELD_TOOLTIPS keys in
      `logic.js`; test assertions in `logic.test.js` updated to match. Verified: 190 node:test
      + headless Electron E2E ok=True. ← next
- [ ] Trim multiple segments and join them in one go
- [x] Output filename templating (tokens: `{name}`, `{w}x{h}`, `{date}`) — see
      "Output filename templating with tokens" under round 8.
- [ ] "Show ffmpeg command" / copy-to-clipboard for any op (dry-run surfaced in UI)
- [ ] Estimate output size before encoding (compress preview)
- [x] GIF tuning: dithering mode + loop count — `make_gif` gains `dither` (sierra2_4a/bayer/floyd_steinberg/none) + `loop` (0=∞, -1=once); CLI `--dither`/`--loop`; sidecar `GifReq` + streaming path; Dither select + Loop field on GIF tab; persisted via STICKY. Verified: pytest 101+69 + node:test 126 + headless Electron E2E 6/6 (bayer+floyd_steinberg GIFs produced; all 4 dither options present; loop=-1 GIF produced). ← next
- [x] Grayscale (desaturate) — core `build_grayscale_args` (`hue=s=0`), CLI `grayscale`,
      sidecar (`/grayscale` + `/run/stream`), Grayscale tab. Verified E2E: SATAVG -> ~0.
- [ ] Denoise / sharpen / deinterlace filter presets
- [x] System notification (and optional sound) on completion — DONE (see round 9 entry above)
- [x] Remember window size & position across launches — done (see round 9: window
      bounds persisted in `settings.json`, restored via `windowOptions`).
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
      **Bug fix (hunt):** `previewPath` replaced only bare `%d` (regex `/%d/g`), so the zero-padded
      pattern `%04d` in the frames output spec (`OUTPUT_SPECS.frames.tag = "frame_%04d"`) was never
      resolved — the renderer tried to display and probe the literal `%04d` filename rather than the
      real first-frame file (`frame_0001.png`). Fixed by widening the regex to `/%(\d*)d/g` so
      `%04d` → `"0001"`, `%3d` → `"001"`, and bare `%d` → `"1"` (backward-compatible). 2 new
      node:tests (146 total); E2E smoke 5/5 green.
- [x] Pad / letterbox to a target frame — core `build_pad_args` (scale-to-fit +
      centered pad), CLI `pad`, sidecar (`/pad` + `/run/stream`), Pad tab.
      Verified E2E: 320x240 -> exact 640x640 frame.
- [ ] Concatenate with automatic re-encode when inputs differ
- [x] Per-op "open output folder" after completion
- [ ] Aspect-ratio presets (16:9, 9:16, 1:1) for compress/transform
- [x] Loop a short clip N times — core `build_loop_args` (-stream_loop), CLI `loop`,
      sidecar (`/loop` + `/run/stream`), Loop tab. Verified E2E: count=3 -> ~3x duration.

### More ideas (round 4)
- [x] Boomerang (play forward then reversed — duration doubles) — core
      `build_boomerang_args`, CLI `boomerang`, sidecar (`/boomerang` + `/run/stream`),
      Boomerang tab. Verified E2E: output duration ~= 2x input.
- [x] Brightness / contrast / saturation adjust (`eq` filter) — core `build_eq_args`,
      CLI `eq`, sidecar (`/eq` + `/run/stream`), Adjust tab. Verified E2E: brightness +0.3 raises YAVG.
- [x] Invert colors — core `build_invert_args` (`negate`), CLI `invert`, sidecar
      (`/invert` + `/run/stream` op `invert`), Invert tab + search alias. Verified
      E2E: first-frame YAVG_out ≈ 255 − YAVG_in (negate inverts each sample).
      (sepia tone still open.)
- [x] Sharpen (`unsharp`) and denoise (`hqdn3d`) presets — core `build_sharpen_args` (`unsharp=lx=5:ly=5:la={amount}`)
      and `build_denoise_args` (`hqdn3d` scaled from defaults), CLI `sharpen --amount` / `denoise --strength`,
      sidecar (`/sharpen` + `/denoise` + `/run/stream` ops), Sharpen + Denoise tabs (Color category, sliders).
      Verified E2E: both endpoints produce output, tabs/sliders/buttons present (14/14 checks); pytest 109 root + 72 sidecar; node:test 133. ← next
- [x] Deinterlace (`yadif`) — core `build_deinterlace_args` (`-vf yadif`), CLI `deinterlace`,
      sidecar (`/deinterlace` + `/run/stream` op `deinterlace`), Deinterlace tab (Color category).
      Verified E2E: tab present + nav, output produced via headless Electron against real sidecar
      (5/5 checks); pytest 102 root + 70 sidecar; node:test 130.
- [x] Crop-to-aspect (auto-crop to 16:9 / 9:16 / 1:1) — core `compute_aspect_crop`/
      `crop_to_aspect`, CLI `crop-aspect`, sidecar (`/crop-aspect` + `/run/stream`),
      Aspect tab. Verified E2E: 320x240 -> 320x180 (16:9).
- [x] Side-by-side (`hstack`) two videos — core `build_hstack_args`, CLI `hstack`, sidecar (`/hstack` + `/run/stream`), Side-by-side tab. Verified E2E: 320 + 320 -> 640 wide. Plus vstack.
- [x] Picture-in-picture overlay — core `build_pip_args` (scale overlay to % of base width + corner overlay), CLI `pip --overlay/--size/--position`, sidecar (`/pip` + `/run/stream` op `pip`), PiP tab (Combine, size slider + position select). Verified E2E: 176 root + 108 sidecar pytest + 195 node:test + smoke 5/5 (50 nav tabs).
- [ ] Still image → video (image + duration, optional audio)
- [x] Replace the audio track with an external audio file (see `replace-audio` above)
- [ ] Set / clear metadata title

### More ideas (round 5)
- [x] Change frame rate without changing speed (`fps` filter) — core `build_fps_args`,
      CLI `fps`, sidecar (`/fps` + `/run/stream`), FPS tab. Verified E2E: 30fps -> 15fps.
- [x] Downmix audio to mono — core `build_mono_args` (`-ac 1`), CLI `mono`, sidecar
      (`/mono` + `/run/stream`), Mono tab. Verified E2E: stereo source -> 1 channel out.
- [x] Trim silence from the ends (`silenceremove`) — core `build_trim_silence_args` (threshold_db/min_duration),
      CLI `trim-silence`, sidecar (`/trim-silence` + `/run/stream` op `trim_silence`), Trim silence tab
      (threshold + min-duration sliders, Audio category). Verified E2E: 8/8 checks (tab/panel/sliders/run button
      present, output produced via UI); pytest 117 root + 76 sidecar; node:test 144.
      **Bug fix (hunt):** `stop_periods=-1` removed ALL silence (including internal pauses), not just
      leading and trailing. Fixed to `stop_periods=1` so only one trailing silence period is stripped,
      matching the documented "trim leading and trailing silence" behavior.
- [x] Blur or pixelate a region — core `build_blur_region_args` (split/crop/gblur/overlay filter_complex), CLI `blur-region`, sidecar (`/blur-region` + `/run/stream` op `blur_region`), Blur region tab (Video FX category). Verified E2E: 320x240 clip → output unchanged at 320x240 with blurred 80×60 region at (40,20); tab/panel/all fields present (8/8 checks); pytest 129 root + 85 sidecar; node:test 157.
- [x] Crossfade-concatenate two clips (`xfade`) — core `build_xfade_args` (transition/duration/offset,
      auto-probed from clip 1 if omitted), CLI `xfade-concat`, sidecar (`/xfade-concat` +
      `/run/stream` op `xfade_concat`), Crossfade tab (Combine). Verified E2E: 148 core +
      96 sidecar + 162 node:test + smoke 5/5 (46 nav tabs).
- [x] Timestamp / timecode overlay (`drawtext`) — core `build_timecode_args` (fontfile auto-detect for Windows), CLI `timecode --font-size/--position/--color`, sidecar (`/timecode` + `/run/stream` op `timecode`), Timecode tab (font-size slider, position + color dropdowns). Verified E2E: timecode endpoint 200, output has video+audio (copied), tab/fields/dropdowns present (11/11); pytest 114 root + 73 sidecar; node:test 138. ← next
- [x] Blurred-fill pad — core `build_blur_pad_args`, CLI `blur-pad`, sidecar (`/blur-pad` + `/run/stream`), Blur pad tab. Verified E2E: 320x240 -> 480x480.
- [x] Stabilize shaky video (`vidstab`, two-pass) — core `build_vidstab_detect_args` / `build_vidstab_transform_args` / `stabilize` (mkdtemp + bare trf filename + cwd to avoid Windows drive-colon filter-parse bug), CLI `stabilize --shakiness/--smoothing`, sidecar (`/stabilize` + `/run/stream` op `stabilize` with two-pass streaming: thread-based detect + heartbeat SSE + pass 2 progress), Stabilize tab (Video FX, after Auto-orient). Verified E2E: 155 core + 97 sidecar + 168 node:test + smoke 5/5 (47 nav tabs). ← next
- [x] Convert to a specific pixel format / 10-bit — core `build_pixfmt_args` (`format=` filter), CLI `pixfmt --pix-fmt`, sidecar (`/pixfmt` + `/run/stream` op `pixfmt`), Pixel format tab (Convert, curated dropdown). Verified E2E: 180 root + 111 sidecar pytest + 199 node:test + smoke 5/5 (51 nav tabs).
- [x] Generate a waveform PNG from audio (`showwavespic`) — core `build_waveform_args`, CLI `waveform`, sidecar (`/waveform` + `/run/stream`), Waveform tab. Verified E2E: 640x120 image.

### More ideas (round 6)
- [x] Set / clear a metadata title tag — core `build_title_args`, CLI `title`, sidecar (`/title` + `/run/stream`), Title tab. Verified E2E: ffprobe title tag set.
- [x] Extract a poster frame at a percentage of the duration — `build_poster_frame_args` (core), CLI `poster-frame --percent`, sidecar (`/poster-frame` + `/run/stream` op `poster_frame`), Poster frame tab (Trim & Frames). Verified E2E: 6/6 (tab+panel present, 3s clip at 50% → PNG output, "Done" status); 134 core + 88 sidecar + 157 node:test + smoke 5/5 (43 tabs).
- [x] Two-up compare grid (input vs output) — `shouldShowCompare` pure helper in `logic.js`; `#compare-panel` two-column card (Before/After) in `index.html`; `showCompare`/`hideCompare`/`loadCompareMedia` in `renderer.js` (hidden at run start, filled via `/file` blob URLs after a successful op, visible when both input and output are previewable). Verified E2E: panel hidden before run, visible after compress (video/video), both compare-in-vid + compare-out-vid visible, panel re-hides on re-run start; 200 node:test + smoke 5/5 (51 tabs). ← next
- [x] Trim by percentage (e.g. middle 50%) — core `build_trim_pct_args` (duration-based timestamps), CLI `trim-pct --start-pct/--end-pct`, sidecar (`/trim-pct` + `/run/stream` op `trim_pct`), Trim % tab. Verified: 142 core + 91 sidecar + 159 node:test + E2E smoke 5/5 (44 tabs).
      **Bug fix (hunt):** `_build_op_args` in server.py built `trim_pct` args without forwarding `reencode=req.reencode`, so the "Re-encode (frame-accurate)" checkbox in the UI was silently ignored on the streaming path — the operation always used stream-copy regardless. Fixed by adding `reencode=req.reencode` to the `trim_pct` branch; 1 new regression test (`test_run_stream_trim_pct_reencode`); 143 core + 93 sidecar + 160 node:test + smoke 5/5 green.
      **Bug fix (hunt):** `build_trim_pct_args` used `-to end_s` for both stream-copy and re-encode paths. With stream copy, input PTS is preserved so `-to end_s` correctly stops at the absolute timestamp. But with re-encode, input-seeking (`-ss` before `-i`) resets output PTS to 0, so `-to end_s` produced `end_s` seconds of output instead of the intended `(end_s − start_s)`. Fixed by splitting the paths: stream copy keeps `-to end_s`; re-encode uses `-t (end_s − start_s)`. 1 new duration regression test (`test_run_stream_trim_pct_reencode_duration`); 139 core + 98 sidecar + 168 node:test + smoke 5/5 green. ← next
- [ ] Add chapters from a list
- [x] Burn a timestamp/elapsed overlay — see "Timestamp / timecode overlay" in round 5 above.
- [x] Auto-orient from rotation metadata, then strip it — core `build_autorotate_args` (-vf null forces decode-through-filter-graph applying the display matrix; -metadata:s:v:0 rotate=0 strips the tag), CLI `auto-orient`, sidecar (`/autorotate` + `/run/stream` op `auto_orient`), Auto-orient tab (Video FX). Verified E2E: 143 core + 92 sidecar + 160 node:test + smoke 5/5 (45 tabs). ← next
- [x] Export a short preview clip (first N seconds, downscaled) — core `build_preview_clip_args` (-t + scale=W:-2 + -c:a copy), CLI `preview-clip --seconds/--width`, sidecar (`/preview-clip` + `/run/stream` op `preview_clip`), Preview clip tab (Trim & Frames). Verified E2E: 10s clip → 3.018s output at 160px; 127 core + 84 sidecar + 154 node:test + E2E 9/9 (sidecar, endpoint, duration ≤3.5s, tab/panel present, 41 nav tabs). ← next
- [x] Convert audio sample rate — core `build_sample_rate_args`, CLI `sample-rate`, sidecar (`/sample-rate` + `/run/stream`), Sample rate tab. Verified E2E: 44100 -> 22050.
- [x] Change container only (remux, `-c copy`) — core `build_remux_args`, CLI `remux`, sidecar
      (`/remux` + `/run/stream` op `remux`), Remux tab (Convert category). Verified E2E: 119 core
      + 79 sidecar + 142 logic:test + E2E smoke 5/5 (39 nav tabs).

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
- [x] **Group the tabs into labeled categories** (Convert · Trim & Frames · Resize &
      Frame · Video FX · Color · Audio · Combine · Metadata) so the nav scans in
      seconds. Pure `TOOL_CATEGORIES`/`groupTabs` in `logic.js` partition all 33 tabs;
      `layoutNavGroups` rearranges the flat nav into full-width labeled rows at load
      and search hides a category label when all its tools filter away. Verified:
      node:test (3 new, 92 total) + headless Electron E2E vs the real sidecar (nav
      lays out into 8 ordered category rows; "rotate" → only Transform + the Video FX
      label; clear restores all 8 labels; real compress still runs → output produced).
- [x] Favorites / recently-used tools pinned to the top of the nav — DONE (see
      round 8 "Favorites: pin frequently-used tools to a top row").

Direct-manipulation (visual instead of typed numbers):
- [x] **Visual crop selector** — drag a rectangle over the source preview on the
      Crop tab to fill x/y/w/h (scaled to source px, even-rounded). Pure
      `rectToCrop`/`cropToRect`/`normalizeDragRect`/`clampPoint` in `logic.js`; a
      `#crop-overlay` marquee in the renderer (pointer-capture drag, hidden off the
      Crop tab, redraws from typed/chip/preset values). Verified: node:test (7 new,
      65 total) + headless Electron E2E vs the real sidecar (320×240 clip →
      full-frame drag fills 0,0,320×240; quarter drag fills even ~160×120; real
      crop output ffprobes to the selected 160×120; overlay hidden on Convert).
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
- [x] **Dimension / aspect presets** — clickable chips (480p–4K, 16:9/9:16/1:1/4:3,
      Match source) fill Width/Height on tabs with both fields (compress, crop, pad,
      blur_pad, waveform). Pure `DIMENSION_PRESETS`/`presetDimensions`/`evenRound`/
      `dimensionPresetTabs` in `logic.js` (ratio presets derive an even height from
      the current/source width; Match copies probed dims). Verified: node:test
      (5 new, 50 total) + headless Electron E2E (720p→1280×720; 16:9 from 1000→
      1000×564; row hidden on gif). [Adopted a stranded 2h-old burn WIP.]
- [x] **Sliders with live readouts** for the numeric ops — volume (dB), speed (×),
      eq (brightness/contrast/saturation), fade (s), loudnorm (LUFS). `SLIDER_SPECS`
      + `formatSliderOut` in `logic.js`; `.sl-group` (range + readout span + number)
      in `index.html`; `setupSliders`/`refreshSliders` wired in `renderer.js`; presets
      exclude range inputs. Verified: node:test (4 new, 122 total) + headless Electron
      E2E (11/11: all sliders present, bidirectional sync, Volume run via slider).
- [x] **Auto-fill the output path** from input + op suffix (in.mp4 → in.small.mp4)
      so "output required" stops being a manual step. Pure `suggestOutputForTab`/
      `extOf` + `OUTPUT_SPECS` in `logic.js` (per-tab tag; gif/waveform/thumbnail/
      frames/image_to_video override the extension); `maybeFillOutput` in the
      renderer fills an empty output on every input change, never clobbering a
      user-set path. Verified: node:test (4 new, 62 total) + headless Electron E2E
      vs the real sidecar (compress→.small.mp4, gif→.anim.gif, waveform→.wave.png,
      trim keeps a user-set output).
      **Bug fix (hunt):** `maybeFillOutput` ignored the `data-auto` tag, so changing
      the input after an auto-fill left the stale previous filename in the output
      field. Fixed by checking `!outEl.dataset.auto` alongside the empty-value
      guard — auto-generated outputs now refresh when the input changes, while
      user-typed outputs remain protected. node:test 126/126 + headless E2E 5/5
      (clip1→.small auto-filled; swap to clip2→output updates to clip2.small;
      user-typed path not clobbered; smoke compress still produces output). ← next

Workflow / feedback components:
- [ ] Cancel button — kill the running ffmpeg process mid-op.
- [x] "Show ffmpeg command" + copy-to-clipboard — delivered by the round-9 "Copy as
      CLI" component (`buildCliCommand` in `logic.js`, `#cli-command` row + Copy button).
- [ ] Drag-to-reorder the concat list, with per-row thumbnails.
- [ ] Output presets dropdown ("Web MP4", "Discord 8 MB", "GIF", …).
- [ ] Job history strip — recent runs with re-run / reveal-in-Explorer.
- [ ] "Reveal in Explorer" / open-output button on completion.
- [ ] Before/after size + duration summary on completion.
- [x] Inline per-field validation (highlight the offending field, not just the status line) —
      `FIELD_VALIDATORS` map in `logic.js` (auto-derived from SLIDER_SPECS + 14 hand-written
      rules: CRF 0–51, timecodes, trim_pct/poster_frame percentages, gif-fps/loop, etc.);
      `validateField(id, value)` pure fn; real-time `input` listener calls `markFieldInvalid`
      (adds `.field-error` + `data-field-err` on parent label rendered by CSS `::after`);
      `validateRunPaths` blocks the run if any visible validated field is invalid and names the
      field in the status line. Verified: node:test 176/176 (8 new) + headless Electron E2E 6/6
      (invalid CRF 99 → field-error + "Must be 0–51" label; fixed to 28 → cleared; bad timecode
      → "Use seconds or HH:MM:SS"; run blocked with status "start: Use seconds or HH:MM:SS";
      empty optional field not flagged; smoke 5/5). ← next
- [x] System notification on completion — a 🔔 checkbox in the header fires a native desktop
      notification (via Electron's `Notification` class in the main process) when an op finishes.
      Toggle persists in `settings.json` (shallow-merge). Light/dark theme + window size/position already done.
      Verified: node:test (3 new, 136 total) + headless Electron E2E 6/6 (checkbox present, starts unchecked,
      persists enable/disable, restores on relaunch, notifyComplete payload correct). ← next

**Priority for this round (highest first):**
1. ~~Tool search / command palette~~ — DONE (round 7).
2. ~~Auto source-preview + friendly probe card~~ — DONE (round 7).
3. ~~Dimension / aspect presets~~ — DONE. 4. ~~Sliders with live readouts~~ — DONE.
5. ~~Visual crop selector~~ — DONE. 6. ~~Auto-fill output path~~ — DONE. The rest — **← next.**

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
- [x] **Estimated-output readout** — a live "Estimated output: ~…" line predicts
      output DURATION for length-changing ops (trim/speed/loop/boomerang) and SIZE
      for compress when a target-MB or bitrate is given (CRF size isn't predictable
      → hidden). Pure `estimateOutput`/`parseTimeToSeconds`/`parseBitrateBps` in
      `logic.js`, fed by the probed source duration. Verified: node:test (5 new) +
      headless Electron E2E vs the real sidecar (2s clip → speed 2× ~0:01, loop ×3
      ~0:06, trim dur 1 ~0:01, compress target 5 → ~5.0 MB, CRF-only/convert hidden).
      **Bug fix (hunt):** `estimateFields(tab)` in `renderer.js` returned `null` for
      `preview_clip` and `trim_pct` (the two newest tabs), and the live-refresh input
      listener regex didn't cover their fields — so the "Estimated output: ~…" readout
      never appeared on those tabs despite `logic.js` having correct `estimateOutput`
      logic and passing unit tests. Fixed by adding two cases to `estimateFields` and
      extending the listener regex to include `preview_clip-seconds`,
      `trim_pct-start-pct`, `trim_pct-end-pct`. node:test 159/159 + headless E2E
      smoke green. ← next

Direct manipulation on the embedded source player (it's already there):
- [x] **Scrub-to-set-time** — a "Set from playhead:" button row under the source
      player fills the active tab's time field(s) from the video's currentTime
      (Trim start/end, GIF start, Thumbnail time); hidden on tabs without a time
      field or for image sources. Pure `formatTimecode`/`timeTargetsForTab` in
      `logic.js`. Verified: node:test (2 new, 37 total) + headless Electron E2E vs
      the real sidecar (playhead 1.5s → trim-start "00:00:01.500"; GIF/Thumbnail
      fill; hidden on Convert + image; shot).
- [x] Draw-a-rectangle crop overlay on the source frame → fills Crop x/y/w/h.
      (Shipped as the round-7 "Visual crop selector" above.)
- [ ] In/out range handles on the player's scrub bar for Trim/GIF duration.

Workflow / re-use:
- [x] Recent files dropdown on inputs + remembered last-used input directory —
      DONE (see "Recent files list / remembered last input dir" under UI/UX above).
- [x] **"Run again"** — after a successful run, a "Run again" button appears next to
      Open/Reveal in `#completion-actions`; clicking it re-fires the exact same op
      with the exact same parameters (stored as `lastRunRecord` in renderer.js).
      No new pure logic — pure renderer state management. Verified: 146/146
      node:test + headless Electron E2E 8/8 (button hidden before any run; visible
      + enabled after first run; click re-runs compress → output reproduced; status
      "Done" after re-run; committed smoke 5/5 green). ← next
- [x] **Output filename templating with tokens** ({name}, {op}, {w}, {h}, {wxh},
      {date}) — a global "Name template" box fills the auto-suggested output
      filename from the input + op + probed dims + date. Pure `applyOutputTemplate`/
      `templatedOutputForTab`/`splitPath` in `logic.js` (keeps the input dir + op
      extension, strips path separators/reserved chars; "" signals fallback);
      renderer `maybeFillOutput` prefers the template, re-fills once the probe
      lands ({w}/{h}), tags auto-fills so a template edit refreshes them but a
      user-typed path is never clobbered; persisted in `settings.json` (STICKY).
      Verified: node:test (6 new, 98 total) + headless Electron E2E vs the real
      sidecar (320×240 clip → compress "clip-compress-320x240.mp4"; user path
      kept; blank → ".out.mp4" fallback; template persisted).
- [x] **"Open" + "Reveal in Explorer/Finder/Files" buttons on completion** — after
      a successful run, two buttons appear below the summary: "Open" (OS default
      app via `shell.openPath` IPC) and "Reveal in Explorer/Finder/Files" (file
      manager via `shell.showItemInFolder`; label adapts via `revealLabel(platform)`
      in `logic.js`). Buttons are hidden before any run and cleared at each new run.
      The "Done" status line shows just the filename (`outputBaseName` in `logic.js`).
      Verified: node:test 124/124 (6 new: revealLabel + outputBaseName) + headless
      Electron E2E 8/8 (hidden at start; visible + enabled after compress; status
      "Done — ffu_ca_out.mp4"; Reveal label = "Reveal in Explorer" on win32).
- [x] **Before/after result summary** — once an op completes, a green readout
      compares the output to the input: size delta with percent (e.g. "774 KB →
      61 KB (−92%)") plus a duration segment when the length changed
      ("… · 0:03 → 0:01"). Pure `summarizeBeforeAfter` in `logic.js` (probe
      `format.size`/`duration` before vs after; %d resolves to frame 1 for
      sequences); `#summary` rendered by the renderer, cleared on each run.
      Verified: node:test (4 new, 73 total) + headless Electron E2E vs the real
      sidecar (compress 320×240→160×120 shows "−92%"; trim to 1s adds
      "0:03 → 0:01"; hidden before any run).
- [x] **Friendlier error surface** — a friendly one-line hint now appears above the
      raw stderr when an op fails. Pure `friendlyError`/`ERROR_HINTS` in `logic.js`
      map common ffmpeg failures (no such file, codec not found, dims not divisible
      by 2, bad output format, corrupt input, missing stream, disk full) to a hint;
      `#error-hint` renders it in the renderer (cleared on each run). Verified:
      node:test (3 new, 58 total) + headless Electron E2E vs the real sidecar
      (missing input → "A path doesn't exist…" hint above the raw "No such file" text).

Navigation / layout polish (the 30-tab nav is still a wall when search is empty):
- [x] Group tabs into labeled categories (carried from round 7) — DONE (see round 7
      "Group the tabs into labeled categories": `TOOL_CATEGORIES`/`groupTabs`). ← next
- [x] **Favorites: pin frequently-used tools to a top row; persist across launches.**
      A ☆/★ toggle on every tab pins it into a leading "★ Favorites" nav row
      (pinned tabs move out of their category, not cloned). Pure
      `normalizeFavorites`/`isFavorite`/`toggleFavorite`/`groupTabsWithFavorites`
      in `logic.js`; renderer injects the star, re-lays-out the nav, and persists
      `favorites` in `settings.json` (shallow-merge → coexists with sticky fields).
      Verified: node:test (5 new, 103 total) + headless Electron E2E vs the real
      sidecar (pin Crop+GIF → "★ Favorites" row leads in pin order, star click
      doesn't switch tabs, moved-not-cloned, persisted + restored across two
      launches, unpin updates settings, real compress still runs). ← next
- [x] Collapse/expand the Source and Probe cards to reclaim vertical space — a ▲/▼ toggle in each card header collapses/expands the body; state persists in settings.json. Verified E2E: collapse/expand both cards, persisted across two launches, real compress still runs. ← next
- [x] Keyboard: run the active tab + cycle tabs — DONE (see "Keyboard shortcuts"
      under UI/UX above: Ctrl/Cmd+Enter runs, Ctrl/Cmd+]/[ cycle visible tabs).

**Priority for round 8 (highest first):**
1. ~~Clickable probe chips + "Match source"~~ — DONE.
2. ~~Multi-input probe + mismatch guard~~ — DONE.
3. ~~Scrub-to-set-time~~ — DONE.
4. ~~Estimated-output readout~~ — DONE. 5. ~~friendlier errors~~ — DONE. 6. the rest — **← next.**

### UI/UX components (round 9) — safety, persistence, power-user flow
> A different angle from rounds 7–8: not new affordances, but making the existing
> flow safe, sticky, and faster for repeat use. Some of these are latent gaps in
> the current renderer, not just nice-to-haves.

Safety / correctness (latent gaps in the current UI):
- [x] **Overwrite confirmation** — before a run, the renderer probes the output
      via a new sidecar `GET /exists` and, if present, asks `window.confirm`
      (pure `overwriteMessage` in `logic.js`); declining leaves the file in place.
      Best-effort: a failed check never blocks the run. Verified: node:test +
      sidecar pytest (`/exists` true/false + auth) + headless Electron E2E
      (decline → "Cancelled — existing file left in place.", op never starts).
- [x] **Disable the Run button while an op is in flight** — an `opInFlight` guard
      ignores re-clicks and `setRunButtonsDisabled` disables every `run-*` button
      for the op's duration, re-enabled in a `finally`. Verified: Electron E2E
      (button observed disabled mid-run via MutationObserver, re-enabled after).
- [x] **Pre-run validation** — before launching ffmpeg, `/exists` checks each input
      file and the output directory; the first failing path gets `.field-error` (red
      border) and the status line names it. `runInputEntries`/`runOutputDirEntry` in
      `logic.js` (pure); `checkExists`/`clearFieldErrors`/`markFieldError`/
      `validateRunPaths` in `renderer.js`; `/exists` now uses `os.path.exists()` so
      it handles dirs too. Verified: node:test (2 new, 126 total) + sidecar pytest
      (dir existence, 67 total) + headless Electron E2E 10/10 (bad input → field-error
      + "Input not found:" status; bad output dir → field-error + "Output folder…"
      status; valid run clears highlight + output produced).
      **Bug fix (hunt):** `runInputEntries` missed `b.audio` on Replace Audio — a
      bad audio path bypassed field-error highlight and hit ffmpeg as a raw error.
      Fixed in `logic.js`; 2 new node:tests (128 total); E2E smoke green. ← next
- [x] **Warn on odd width/height for x264 (must be even) before the run fails** — a
      `#dim-warn` banner flags a typed odd width/height on the re-encode tabs
      (compress/crop/pad/blur_pad) with the nearest-even fix, before ffmpeg fails
      with "not divisible by 2". Pure `oddDimensionWarning`/`EVEN_DIM_TABS` in
      `logic.js` (PNG/GIF tabs excluded); `refreshDimWarning` in the renderer wired
      to field edits, tab switches, chip/preset fills. Verified: node:test (3 new,
      76 total) + headless Electron E2E vs the real sidecar (odd 161 → "width 161 →
      162"; both odd → plural; even hides it; hidden on Convert; real 160×120 crop
      succeeds).
- [x] Cancel a running op (kill the ffmpeg process) and reset the UI — a Cancel
      button aborts the `/run/stream` fetch; the disconnect makes the sidecar stop
      consuming progress, firing `iter_ffmpeg_progress`'s `finally` to kill ffmpeg
      (no new endpoint needed). The renderer shows "Cancelled — operation stopped."
      and re-enables the buttons. Verified: core pytest (kill-on-early-close spy
      test, 95) + headless Electron E2E (ffmpeg proc count 1→0 on Cancel, status +
      UI reset confirmed).

Persistence / memory:
- [x] Remember the active tab + window size/position across launches — main.js
      restores `BrowserWindow` bounds (pure `settingsStore.windowOptions`) and saves
      them (+ maximized) on close; the renderer persists `activeTab` on tab switch
      and restores it on load. `settings.save` now shallow-merges so the renderer's
      sticky fields and the window bounds share one `settings.json` without
      clobbering. Verified: node:test (4 new settings unit tests, 42 total) +
      headless Electron E2E across two launches (1024×700 @120,90 + Compress tab →
      both restored).
- [x] Recent inputs/outputs per tab; remember the last-used directory for pickers —
      recent inputs + last-used dir DONE (see UI/UX "Recent files list"); per-tab
      output history DONE: `setRecentOutput`/`recentOutputDir` in `logic.js`; after
      each successful run, the output path is saved per-tab in `settings.json` under
      `recentOutputs`; on next launch, empty output fields are seeded from history;
      the "Save as…" dialog defaults to the last output path for the active tab.
      Verified: node:test (178/178, +2 new fns) + headless Electron E2E 6/6 (run →
      saved in recentOutputs; second launch → field pre-populated; other tabs not
      affected). ← next
- [x] Save/load named presets (profiles) per tool — a Presets bar (save-as name +
      Save, a dropdown + Load/Delete) captures the active tab's option fields
      (path inputs excluded) under a name, scoped per tool, persisted in
      `settings.json` under `presets`. Pure `isPathFieldId`/`presetNames`/
      `getPreset`/`withPreset`/`withoutPreset` in `logic.js`. Verified: node:test
      (3 new, 45 total) + headless Electron E2E (save "web" on Compress → load
      after mutation restores CRF/width; survives relaunch; delete removes it).

Power-user flow:
- [ ] Operation queue — line up several ops and run them in sequence.
- [ ] Chain ops on one file (trim → compress …) without manual disk round-trips.
- [x] **"Copy as CLI"** — on each run, a `#cli-command` row shows the equivalent
      `ffmpeg-util <op> …` command (reconstructed from the op + request body) with a
      Copy button. Pure `buildCliCommand` in `logic.js` (kebab subcommand/flags,
      positional input/output or `inputs … -o`, boolean flags, `--flag=value` for
      negatives, shell-quoting; renames the three diverging body keys
      fade→--duration, transform→--op, target_i→--target). Verified: node:test (8 new,
      84 total) + headless Electron E2E vs the real sidecar (compress run →
      `ffmpeg-util compress … --crf 28 --width 160 --vcodec libx264 --preset medium -y`;
      row hidden before any run; Copy button feedback; real output produced).

Help / discoverability:
- [~] Per-tab one-line example — DONE: a `#tab-help` line between the nav and the
      source card shows the active tool's "what it does + a worked example" sentence
      (e.g. compress → "Shrink with CRF/bitrate… Example: CRF 28 + Width 1280…").
      Pure `TOOL_HELP`/`helpForTab` in `logic.js` (an entry for every nav tab);
      renderer `updateTabHelp` sets/hides it on tab switch and on load. Verified:
      node:test (2 new, 114 total) + headless Electron E2E vs the real sidecar
      (Convert help on load; switching to Compress updates it to the CRF line; all
      33 nav tabs show a non-empty visible help line; real compress still runs →
      output produced). (Per-field "?" tooltips: done — see entry below.)
- [x] **Per-field "?" tooltips** — a small `?` badge next to each non-obvious
      field label (label.inline) shows a native OS tooltip explaining the field and
      giving good example values. 38 badges covering ~40 fields across all 33 tabs
      (path inputs deliberately excluded). Pure `FIELD_TOOLTIPS`/`fieldTooltip` in
      `logic.js`; `setupFieldTooltips` (one DOM pass at startup) in `renderer.js`;
      `.field-tip` badge styled in `styles.css`. Verified: node:test (3 new, 129
      total: fieldTooltip lookups, no path-field leaks, length ≤ 160) + headless
      Electron E2E 6/6 (38 badges injected; CRF tooltip correct; loop tooltip
      correct; path fields have no badge; all badges carry aria-label).
- [x] Friendly error mapping (carried from round 8) — DONE (see round 8: friendlier
      error surface; `friendlyError` in `logic.js`, `#error-hint` above the raw stderr).

**Priority for round 9 (highest first):**
1. ~~Overwrite confirmation + Run-button-disabled-while-running~~ — DONE.
2. ~~Cancel a running op~~ — DONE. 3. ~~remember tab + window~~ — DONE. 4. ~~presets~~ — DONE. 5. the rest.

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
