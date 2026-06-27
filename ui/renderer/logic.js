// Pure renderer logic — no DOM, no network — so it can be unit-tested under Node
// (node:test) and reused by renderer.js in the browser. Loaded before renderer.js.

(function () {
  const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"];
  const VIDEO_EXTS = [".mp4", ".mkv", ".webm", ".mov", ".m4v", ".ogv"];

  function isImagePath(p) {
    return IMAGE_EXTS.some((ext) => String(p).toLowerCase().endsWith(ext));
  }

  function isVideoPath(p) {
    return VIDEO_EXTS.some((ext) => String(p).toLowerCase().endsWith(ext));
  }

  // Decide how to preview an output path: { kind: "image"|"video"|null, path }.
  // path has any %d resolved to the first frame.
  function previewKind(outputPath) {
    const path = previewPath(outputPath);
    if (isImagePath(path)) return { kind: "image", path };
    if (isVideoPath(path)) return { kind: "video", path };
    return { kind: null, path };
  }

  // Derive a default output path from an input path (swap the extension).
  function suggestOutput(inputPath, ext = ".out.mp4") {
    if (!inputPath) return "output" + ext;
    return inputPath.replace(/\.[^.\\/]+$/, "") + ext;
  }

  // Multi-frame thumbnails use a %d pattern; the first written file is %d -> 1.
  function previewPath(outputPath) {
    return String(outputPath).replace(/%d/g, "1");
  }

  // --- Auto-fill output path: input + per-op suffix so "output required" isn't a
  // manual step. Each tab maps to a short tag (in.mp4 -> in.<tag>.<ext>); a few
  // ops change the output type (gif/image/video), so they override the extension.
  // Tabs not listed fall back to a tag derived from the tab name + the input's ext.
  const OUTPUT_SPECS = {
    convert: { tag: "out" },
    trim: { tag: "trim" },
    concat: { tag: "joined" },
    thumbnail: { tag: "thumb", ext: ".png" },
    compress: { tag: "small" },
    gif: { tag: "anim", ext: ".gif" },
    speed: { tag: "speed" },
    transform: { tag: "rot" },
    crop: { tag: "crop" },
    mute: { tag: "mute" },
    replace_audio: { tag: "dub" },
    pad: { tag: "pad" },
    loop: { tag: "loop" },
    frames: { tag: "frame_%04d", ext: ".png" },
    reverse: { tag: "rev" },
    volume: { tag: "vol" },
    fade: { tag: "fade" },
    grayscale: { tag: "gray" },
    invert: { tag: "invert" },
    loudnorm: { tag: "loud" },
    boomerang: { tag: "boom" },
    eq: { tag: "eq" },
    fps: { tag: "fps" },
    crop_aspect: { tag: "aspect" },
    mono: { tag: "mono" },
    title: { tag: "titled" },
    waveform: { tag: "wave", ext: ".png" },
    sample_rate: { tag: "resample" },
    hstack: { tag: "hstack" },
    vstack: { tag: "vstack" },
    blur_pad: { tag: "blurpad" },
    image_to_video: { tag: "clip", ext: ".mp4" },
    autocrop: { tag: "autocrop" },
  };

  // The lowercase extension of a path (incl. the dot), or "" if none.
  function extOf(path) {
    const m = /(\.[^.\\/]+)$/.exec(String(path));
    return m ? m[1].toLowerCase() : "";
  }

  // Suggest an output path for a tab from its input path. Keeps the input's
  // extension unless the op changes the output type. Returns "" without an input.
  function suggestOutputForTab(inputPath, tab) {
    const input = String(inputPath || "").trim();
    if (!input) return "";
    const spec = OUTPUT_SPECS[tab] || { tag: String(tab || "out").replace(/_/g, "") };
    const ext = spec.ext || extOf(input) || ".mp4";
    const base = input.replace(/\.[^.\\/]+$/, "");
    return spec.tag ? base + "." + spec.tag + ext : base + ext;
  }

  // Split a textarea/blob of paths into a trimmed, non-empty list.
  function parseLines(text) {
    return String(text)
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // Strip the op prefix from a field id for human-friendly messages
  // ("compress-crf" -> "crf").
  function fieldLabel(id) {
    return id.replace(/^[a-z]+-/, "");
  }

  // Incrementally parse Server-Sent Events from an accumulating buffer.
  // Returns the complete events parsed and the unconsumed remainder.
  function parseSseBuffer(buffer) {
    const blocks = String(buffer).split("\n\n");
    const remainder = blocks.pop();
    const events = [];
    for (const block of blocks) {
      const line = block.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        events.push(JSON.parse(line.slice("data:".length).trim()));
      } catch (_) {
        // ignore malformed block
      }
    }
    return { events, remainder };
  }

  // Which input field a dropped file should populate for the active tab.
  // Concat collects multiple paths (append); the two-input stack tabs drop into
  // the first slot; every other tab uses a single `{tab}-input` field.
  function inputTargetForTab(tab) {
    if (!tab) return null;
    if (tab === "concat") return { id: "concat-inputs", append: true };
    if (tab === "hstack" || tab === "vstack") return { id: tab + "-input-a", append: false };
    return { id: tab + "-input", append: false };
  }

  // Compute the field update for a drop: returns { id, value } or null.
  // For concat, dropped paths are appended to whatever's already listed.
  function dropUpdate(paths, tab, currentConcatValue = "") {
    const target = inputTargetForTab(tab);
    if (!target || !paths || !paths.length) return null;
    if (target.append) {
      const merged = parseLines(currentConcatValue).concat(paths);
      return { id: target.id, value: merged.join("\n") };
    }
    return { id: target.id, value: paths[0] };
  }

  // Search aliases per tab — extra keywords so the tool filter finds a tool by
  // what it *does*, not just its visible label ("rotate" -> Transform, etc.).
  const TOOL_ALIASES = {
    convert: "transcode container codec extract audio format change",
    trim: "cut clip split start end duration",
    concat: "join merge combine append stitch",
    thumbnail: "screenshot poster still snapshot contact sheet montage frame grab",
    compress: "resize scale shrink smaller size crf bitrate target quality",
    gif: "animated giphy meme loop palette",
    speed: "fast slow timelapse slowmo retime tempo",
    transform: "rotate flip mirror turn orientation cw ccw",
    crop: "cut rectangle trim edges region",
    mute: "silent remove strip audio no sound",
    replace_audio: "swap dub soundtrack music bed external audio track add sound voiceover",
    pad: "letterbox bars frame fit border",
    loop: "repeat times duplicate",
    frames: "extract images sequence export png every nth",
    reverse: "backwards rewind",
    volume: "gain loud quiet db amplify boost attenuate",
    fade: "in out dissolve intro outro",
    grayscale: "black white desaturate mono color monochrome",
    invert: "negate negative invert colors photo negative inverse opposite",
    loudnorm: "loudness normalize lufs ebu r128 level",
    boomerang: "forward back bounce pingpong instagram",
    eq: "adjust brightness contrast saturation color levels",
    fps: "frame rate resample smooth",
    crop_aspect: "aspect ratio square vertical wide 16 9 1 reframe",
    mono: "downmix single channel audio",
    title: "metadata tag name rename",
    waveform: "audio visual spectrum showwaves wave png",
    sample_rate: "audio hz khz resample rate 44100 48000",
    hstack: "side by side horizontal compare two videos",
    vstack: "stacked vertical top bottom two videos",
    blur_pad: "blurred fill background letterbox frame fit no bars",
    image_to_video: "still photo png jpg slideshow loop clip make movie from picture",
  };

  // Filter a list of tools by a search query. Pure & order-preserving.
  // tools: [{ tab, label, keywords }]. Returns the matching `tab` ids in order.
  // Empty/whitespace query returns every tab. Multi-word queries are AND-matched:
  // each whitespace-separated token must appear as a substring of the tool's
  // haystack (label + tab + keywords), so "rotate left" still finds Transform.
  function filterTools(query, tools) {
    const list = Array.isArray(tools) ? tools : [];
    const tokens = String(query || "")
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    if (tokens.length === 0) return list.map((t) => t.tab);
    return list
      .filter((t) => {
        const hay = `${t.label || ""} ${t.tab || ""} ${t.keywords || ""}`.toLowerCase();
        return tokens.every((tok) => hay.includes(tok));
      })
      .map((t) => t.tab);
  }

  // --- Source probe summary (turn ffprobe JSON into friendly chips) ---

  // Human-readable byte size: 1536 -> "1.5 KB". Returns null for non-finite.
  function formatBytes(bytes) {
    if (bytes == null || bytes === "") return null;
    const n = Number(bytes);
    if (!isFinite(n) || n < 0) return null;
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
  }

  // Seconds -> "M:SS" (or "H:MM:SS" past an hour). Returns null if not finite.
  function formatDuration(seconds) {
    if (seconds == null || seconds === "") return null;
    const s = Number(seconds);
    if (!isFinite(s) || s < 0) return null;
    const total = Math.round(s);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const sec = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }

  // Parse an ffprobe frame-rate ("30/1", "30000/1001") into fps, or null.
  function parseFrameRate(rate) {
    if (rate == null) return null;
    const str = String(rate);
    if (str.includes("/")) {
      const [num, den] = str.split("/").map(Number);
      if (!den || !isFinite(num) || !isFinite(den)) return null;
      return num / den;
    }
    const n = Number(str);
    return isFinite(n) && n > 0 ? n : null;
  }

  // Round an fps to a tidy label: 29.97, 30, 23.976 -> "29.97", "30", "23.98".
  function formatFps(fps) {
    if (fps == null) return null;
    const rounded = Math.round(fps * 100) / 100;
    return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(2)} fps`;
  }

  function channelLabel(channels) {
    const c = Number(channels);
    if (!c) return null;
    if (c === 1) return "mono";
    if (c === 2) return "stereo";
    return `${c} ch`;
  }

  // Summarize parsed ffprobe JSON ({format, streams}) into ordered display chips:
  // [{ label, value }]. Skips anything missing so the card only shows real facts.
  function summarizeProbe(data) {
    const d = data || {};
    const fmt = d.format || {};
    const streams = Array.isArray(d.streams) ? d.streams : [];
    const video = streams.find((s) => s.codec_type === "video");
    const audio = streams.find((s) => s.codec_type === "audio");
    const chips = [];
    const push = (label, value) => {
      if (value != null && value !== "") chips.push({ label, value: String(value) });
    };

    push("Duration", formatDuration(fmt.duration));
    if (video) {
      if (video.width && video.height) push("Size", `${video.width}×${video.height}`);
      push("FPS", formatFps(parseFrameRate(video.avg_frame_rate || video.r_frame_rate)));
      push("Video", video.codec_name);
    }
    if (audio) {
      const sr = Number(audio.sample_rate);
      push("Audio", audio.codec_name);
      push("Channels", channelLabel(audio.channels));
      if (isFinite(sr) && sr > 0) push("Rate", `${Math.round(sr / 100) / 10} kHz`);
    }
    push("File", formatBytes(fmt.size));
    return chips;
  }

  // --- Clickable probe chips: map a chip to the active tab's fields ("use source") ---

  // Tabs with width/height fields the Size chip can fill (h omitted = width-only).
  const DIMENSION_FIELDS = {
    crop: { w: "crop-width", h: "crop-height" },
    pad: { w: "pad-width", h: "pad-height" },
    blur_pad: { w: "blur_pad-width", h: "blur_pad-height" },
    compress: { w: "compress-width", h: "compress-height" },
    thumbnail: { w: "thumbnail-width" },
    gif: { w: "gif-width" },
    waveform: { w: "waveform-width", h: "waveform-height" },
  };
  // Tabs whose FPS field the FPS chip can fill.
  const FPS_FIELDS = { fps: "fps-fps" };

  // Given the active tab + parsed probe data, return which chips are clickable and
  // what fields they fill: { [chipLabel]: [{ id, value }] }. Order-independent;
  // only includes a chip when both the tab has the field(s) and the data exists.
  function sourceFillActions(tab, data) {
    const d = data || {};
    const streams = Array.isArray(d.streams) ? d.streams : [];
    const video = streams.find((s) => s.codec_type === "video") || {};
    const w = Number(video.width);
    const h = Number(video.height);
    const fps = parseFrameRate(video.avg_frame_rate || video.r_frame_rate);
    const actions = {};

    const dim = DIMENSION_FIELDS[tab];
    if (dim && w > 0 && h > 0) {
      const targets = [{ id: dim.w, value: String(w) }];
      if (dim.h) targets.push({ id: dim.h, value: String(h) });
      actions.Size = targets;
    }
    const fpsField = FPS_FIELDS[tab];
    if (fpsField && fps) {
      const tidy = Math.round(fps * 100) / 100;
      actions.FPS = [{ id: fpsField, value: String(tidy) }];
    }
    return actions;
  }

  // --- Dimension presets: one-click frame sizes for width/height fields ---

  // Round to the nearest even integer (x264 needs even dims), with a floor of 2.
  function evenRound(n) {
    const v = Math.max(2, Math.round(Number(n) || 0));
    return v % 2 === 0 ? v : v + 1;
  }

  // The preset chips offered on tabs that have both a width *and* a height field.
  // Fixed-resolution presets carry concrete dims; ratio presets derive the height
  // from a base width; "match" copies the probed source dims.
  const DIMENSION_PRESETS = [
    { key: "480p", label: "480p", width: 854, height: 480 },
    { key: "720p", label: "720p", width: 1280, height: 720 },
    { key: "1080p", label: "1080p", width: 1920, height: 1080 },
    { key: "1440p", label: "1440p", width: 2560, height: 1440 },
    { key: "2160p", label: "4K", width: 3840, height: 2160 },
    { key: "16:9", label: "16:9", ratio: [16, 9] },
    { key: "9:16", label: "9:16", ratio: [9, 16] },
    { key: "1:1", label: "1:1", ratio: [1, 1] },
    { key: "4:3", label: "4:3", ratio: [4, 3] },
    { key: "match", label: "Match source", match: true },
  ];

  // Tabs that get the dimension-preset chip row: those whose Size chip fills both
  // a width and a height field (single-width tabs like gif/thumbnail are skipped).
  function dimensionPresetTabs() {
    return Object.keys(DIMENSION_FIELDS).filter((t) => DIMENSION_FIELDS[t] && DIMENSION_FIELDS[t].h);
  }

  // Resolve a preset to concrete { width, height }, or null when it can't apply.
  // Ratio presets keep the current width (falling back to the source width, then
  // 1280) and compute an even matching height. "Match source" copies the probed
  // source dims verbatim; it needs them, returning null otherwise.
  function presetDimensions(preset, ctx) {
    const c = ctx || {};
    if (!preset) return null;
    if (preset.match) {
      const w = Number(c.sourceWidth);
      const h = Number(c.sourceHeight);
      return w > 0 && h > 0 ? { width: w, height: h } : null;
    }
    if (preset.width && preset.height) {
      return { width: preset.width, height: preset.height };
    }
    if (preset.ratio) {
      const base =
        Number(c.width) > 0 ? Number(c.width)
        : Number(c.sourceWidth) > 0 ? Number(c.sourceWidth)
        : 1280;
      const [rw, rh] = preset.ratio;
      return { width: evenRound(base), height: evenRound((base * rh) / rw) };
    }
    return null;
  }

  // --- Multi-input compatibility (hstack/vstack/concat) ---

  // Pull {w,h} of the first video stream from parsed ffprobe data, or null.
  function videoDims(data) {
    const streams = data && Array.isArray(data.streams) ? data.streams : [];
    const v = streams.find((s) => s.codec_type === "video");
    if (!v || !v.width || !v.height) return null;
    const w = Number(v.width);
    const h = Number(v.height);
    return w > 0 && h > 0 ? { w, h } : null;
  }

  // Check whether the inputs for a multi-input op are compatible, given each
  // input's dims ({w,h}|null) in order. Returns { ok, message } or null when the
  // check doesn't apply (not a multi-input tab, or fewer than two probed inputs).
  // hstack needs equal heights, vstack equal widths, concat matching size.
  function compatReport(tab, dimsList) {
    if (tab !== "hstack" && tab !== "vstack" && tab !== "concat") return null;
    const valid = (dimsList || []).filter(Boolean);
    if (valid.length < 2) return null;
    if (tab === "hstack") {
      const hs = valid.map((d) => d.h);
      if (new Set(hs).size > 1) {
        return { ok: false, message: `Heights differ (${hs.join(" vs ")}px). Side-by-side needs equal heights — pad or scale one first.` };
      }
      return { ok: true, message: `Heights match (${hs[0]}px) — ready to combine.` };
    }
    if (tab === "vstack") {
      const ws = valid.map((d) => d.w);
      if (new Set(ws).size > 1) {
        return { ok: false, message: `Widths differ (${ws.join(" vs ")}px). Stacking needs equal widths — pad or scale one first.` };
      }
      return { ok: true, message: `Widths match (${ws[0]}px) — ready to stack.` };
    }
    const sizes = valid.map((d) => `${d.w}×${d.h}`);
    const uniq = [...new Set(sizes)];
    if (uniq.length > 1) {
      return { ok: false, message: `Inputs differ in size (${uniq.join(", ")}). Concat needs matching size/codecs — re-encode first.` };
    }
    return { ok: true, message: `All inputs are ${uniq[0]} — ready to concat.` };
  }

  // --- Scrub-to-set-time: read the source player's playhead into time fields ---

  // Seconds -> "HH:MM:SS.mmm" (ffmpeg-accepted everywhere). Carries ms rounding
  // correctly (1.9999 -> "00:00:02.000") and clamps negatives to zero.
  function formatTimecode(seconds) {
    const totalMs = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
    const ms = totalMs % 1000;
    const totalSec = Math.floor(totalMs / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const sec = totalSec % 60;
    const pad = (n, w = 2) => String(n).padStart(w, "0");
    return `${pad(h)}:${pad(m)}:${pad(sec)}.${pad(ms, 3)}`;
  }

  // Which time fields the "set from playhead" buttons fill, per tab. [] when the
  // tab has no time field the source player's current time maps to.
  function timeTargetsForTab(tab) {
    if (tab === "trim") return [{ id: "trim-start", label: "start" }, { id: "trim-end", label: "end" }];
    if (tab === "gif") return [{ id: "gif-start", label: "start" }];
    if (tab === "thumbnail") return [{ id: "thumbnail-time", label: "time" }];
    return [];
  }

  // --- Overwrite confirmation: warn before clobbering an existing output ---

  // The confirm() prompt shown when an op's output path already exists.
  function overwriteMessage(path) {
    return `"${path}" already exists.\n\nOverwrite it with the new output?`;
  }

  // --- Presets: save/load named option-field profiles per tool ---

  // A field id is a per-file path (input/output) rather than a reusable option,
  // so presets skip it — a preset captures settings, not which file you picked.
  function isPathFieldId(id) {
    return /-(input|output|inputs|input-a|input-b)$/.test(String(id));
  }

  // Saved preset names for a tab, sorted for stable display. Pure.
  function presetNames(presets, tab) {
    const t = (presets && presets[tab]) || {};
    return Object.keys(t).sort((a, b) => a.localeCompare(b));
  }

  // The stored values for one preset, or null if absent. Pure.
  function getPreset(presets, tab, name) {
    const t = (presets && presets[tab]) || {};
    return Object.prototype.hasOwnProperty.call(t, name) ? t[name] : null;
  }

  // Return a new presets object with presets[tab][name] = values (immutable).
  function withPreset(presets, tab, name, values) {
    const base = presets && typeof presets === "object" ? presets : {};
    return { ...base, [tab]: { ...(base[tab] || {}), [name]: values } };
  }

  // Return a new presets object without presets[tab][name] (immutable).
  function withoutPreset(presets, tab, name) {
    const base = presets && typeof presets === "object" ? presets : {};
    const t = { ...(base[tab] || {}) };
    delete t[name];
    return { ...base, [tab]: t };
  }

  // --- Estimated-output readout: predict output duration/size from settings ---

  // Parse an ffmpeg-style time ("5", "1:05", "00:00:01.500") to seconds, or null.
  function parseTimeToSeconds(t) {
    if (t == null || String(t).trim() === "") return null;
    const parts = String(t).trim().split(":").map(Number);
    if (parts.some((n) => !isFinite(n) || n < 0)) return null;
    let secs;
    if (parts.length === 1) secs = parts[0];
    else if (parts.length === 2) secs = parts[0] * 60 + parts[1];
    else if (parts.length === 3) secs = parts[0] * 3600 + parts[1] * 60 + parts[2];
    else return null;
    return secs;
  }

  // Parse a bitrate ("2M", "500k", "800000", "2.5M") to bits/sec (decimal), or null.
  function parseBitrateBps(s) {
    if (s == null) return null;
    const m = String(s).trim().match(/^([\d.]+)\s*([kKmMgG]?)$/);
    if (!m) return null;
    const n = Number(m[1]);
    if (!isFinite(n) || n <= 0) return null;
    const mult = { "": 1, k: 1e3, m: 1e6, g: 1e9 }[m[2].toLowerCase()];
    return n * mult;
  }

  // Estimate an op's output as a short "~…" string, or null when not predictable.
  // Duration is exact for length-changing ops (trim/speed/loop/boomerang); size is
  // shown only for compress when an explicit target-MB or bitrate is given (CRF
  // size isn't predictable). `inputSeconds` is the probed source duration.
  function estimateOutput(tab, inputSeconds, fields) {
    const f = fields || {};
    const inDur = Number(inputSeconds);
    const haveDur = isFinite(inDur) && inDur > 0;

    if (tab === "compress") {
      const target = Number(f.target);
      if (isFinite(target) && target > 0) return `~${formatBytes(target * 1024 * 1024)}`;
      const bps = parseBitrateBps(f.bitrate);
      if (bps && haveDur) return `~${formatBytes((bps * inDur) / 8)}`;
      return null; // CRF / default → size not predictable
    }

    if (!haveDur) return null;
    let out = null;
    if (tab === "trim") {
      const start = parseTimeToSeconds(f.start);
      const end = parseTimeToSeconds(f.end);
      const dur = parseTimeToSeconds(f.duration);
      if (dur != null) out = dur;
      else if (end != null) out = Math.max(0, end - (start || 0));
      else if (start != null) out = Math.max(0, inDur - start);
      else out = inDur;
    } else if (tab === "speed") {
      const factor = Number(f.factor);
      if (isFinite(factor) && factor > 0) out = inDur / factor;
    } else if (tab === "loop") {
      const count = Number(f.count);
      if (isFinite(count) && count >= 1) out = inDur * count;
    } else if (tab === "boomerang") {
      out = inDur * 2;
    } else {
      return null;
    }
    if (out == null || !isFinite(out)) return null;
    return `~${formatDuration(out)}`;
  }

  // --- Visual crop selector: drag a rectangle over the source frame ---

  // Clamp a point {x,y} to the [0,w]×[0,h] box (displayed-pixel coords). Pure.
  function clampPoint(pt, size) {
    const w = Number(size && size.width) || 0;
    const h = Number(size && size.height) || 0;
    const x = Math.max(0, Math.min(Number(pt && pt.x) || 0, w));
    const y = Math.max(0, Math.min(Number(pt && pt.y) || 0, h));
    return { x, y };
  }

  // Two drag points -> a normalized rectangle {left,top,width,height} (handles a
  // drag in any direction). Pure.
  function normalizeDragRect(a, b) {
    const ax = Number(a && a.x) || 0, ay = Number(a && a.y) || 0;
    const bx = Number(b && b.x) || 0, by = Number(b && b.y) || 0;
    return {
      left: Math.min(ax, bx),
      top: Math.min(ay, by),
      width: Math.abs(ax - bx),
      height: Math.abs(ay - by),
    };
  }

  // Round to the nearest even integer toward zero-safe bounds (helper).
  function even(n) {
    return 2 * Math.round((Number(n) || 0) / 2);
  }

  // Convert a selection rectangle drawn over the displayed media (in displayed CSS
  // pixels, origin at the media's top-left) into source-pixel crop values. Scales
  // by sourceSize/displaySize, clamps to the source frame, and rounds to even
  // numbers (x264 needs even W/H; even offsets keep 4:2:0 chroma happy). Returns
  // {x,y,width,height} or null when the rect is degenerate or inputs are missing.
  function rectToCrop(rect, displaySize, sourceSize) {
    const dw = Number(displaySize && displaySize.width);
    const dh = Number(displaySize && displaySize.height);
    const sw = Number(sourceSize && sourceSize.width);
    const sh = Number(sourceSize && sourceSize.height);
    if (!(dw > 0 && dh > 0 && sw > 0 && sh > 0)) return null;
    if (!rect || !(Number(rect.width) > 0) || !(Number(rect.height) > 0)) return null;
    const sx = sw / dw, sy = sh / dh;
    // displayed px -> source px
    let x = Math.max(0, Math.min(rect.left * sx, sw));
    let y = Math.max(0, Math.min(rect.top * sy, sh));
    let w = Math.min(rect.width * sx, sw - x);
    let h = Math.min(rect.height * sy, sh - y);
    // floor offsets to even, round sizes to even, then re-clamp in-bounds
    x = Math.max(0, 2 * Math.floor(x / 2));
    y = Math.max(0, 2 * Math.floor(y / 2));
    w = even(w);
    h = even(h);
    if (x + w > sw) w = 2 * Math.floor((sw - x) / 2);
    if (y + h > sh) h = 2 * Math.floor((sh - y) / 2);
    if (w < 2 || h < 2) return null;
    return { x, y, width: w, height: h };
  }

  // The inverse: position an overlay rectangle (displayed CSS px) from crop field
  // values, so the drawn box reflects what's typed/filled. Returns
  // {left,top,width,height} clamped to the display box, or null when not drawable.
  function cropToRect(crop, displaySize, sourceSize) {
    const dw = Number(displaySize && displaySize.width);
    const dh = Number(displaySize && displaySize.height);
    const sw = Number(sourceSize && sourceSize.width);
    const sh = Number(sourceSize && sourceSize.height);
    if (!(dw > 0 && dh > 0 && sw > 0 && sh > 0)) return null;
    const w = Number(crop && crop.width), h = Number(crop && crop.height);
    if (!(w > 0 && h > 0)) return null;
    const x = Number(crop && crop.x) || 0, y = Number(crop && crop.y) || 0;
    const sx = dw / sw, sy = dh / sh;
    let left = Math.max(0, Math.min(x * sx, dw));
    let top = Math.max(0, Math.min(y * sy, dh));
    let width = Math.min(w * sx, dw - left);
    let height = Math.min(h * sy, dh - top);
    return { left, top, width, height };
  }

  // --- Friendly error hints: map common ffmpeg stderr to a one-line explanation ---

  // Ordered [pattern, hint] rules; the first whose regex matches the raw error
  // text wins, so put specific causes before generic ones ("Conversion failed!"
  // is printed alongside the real cause, so it stays last as a soft fallback).
  const ERROR_HINTS = [
    [/no such file or directory|cannot find the (file|path)/i,
      "A path doesn't exist — check the input file path and that the output folder exists."],
    [/permission denied|access is denied/i,
      "Permission denied — the file may be read-only or open in another program."],
    [/not divisible by 2/i,
      "Width and height must be even numbers for this codec — round them to even values."],
    [/unknown encoder|encoder.*not found|unknown decoder|automatic encoder selection failed/i,
      "Unrecognized codec — check the video/audio codec name."],
    [/unable to find a suitable output format|requested output format.*is not|invalid argument.*output|unknown.*format/i,
      "Unrecognized output format — check the output file's extension."],
    [/moov atom not found/i,
      "This MP4 is incomplete or corrupt (its 'moov atom' is missing)."],
    [/invalid data found when processing input/i,
      "The input doesn't look like a valid media file (it may be corrupt or the wrong type)."],
    [/matches no streams|does not contain any stream|stream specifier.*matches no/i,
      "A required stream is missing — the input may have no audio (or no video) for this operation."],
    [/output file (is empty|#0 does not contain)|nothing was encoded/i,
      "Nothing was encoded — check the trim range or filter settings."],
    [/no space left on device/i,
      "The disk is full — free up space or pick another output folder."],
    [/conversion failed/i,
      "ffmpeg couldn't complete the operation — see the details below."],
  ];

  // Map raw ffmpeg/ffprobe error text to a short, human-friendly hint, or null
  // when nothing recognizable matched (the caller then shows just the raw text).
  // Pure & order-defined.
  function friendlyError(text) {
    const s = String(text || "");
    for (const [re, hint] of ERROR_HINTS) {
      if (re.test(s)) return hint;
    }
    return null;
  }

  // --- Even-dimension guard: warn before an odd width/height fails the encode ---

  // Tabs whose output is re-encoded to H.264 (yuv420p), where a typed odd width or
  // height makes ffmpeg fail with "height/width not divisible by 2". They reuse the
  // DIMENSION_FIELDS field ids. PNG-output tabs (waveform/thumbnail) and palette
  // GIF tolerate odd sizes, so they're deliberately excluded.
  const EVEN_DIM_TABS = ["compress", "crop", "pad", "blur_pad"];

  // Inspect the active tab's width/height fields and warn when either is a
  // positive odd integer (x264 needs even dims). `fields` maps field id -> raw
  // string value. Returns a one-line warning naming the offending field(s) and
  // the nearest even value, or null when the tab isn't size-sensitive or both
  // dims are even / blank / non-integer (those don't reliably fail the encode).
  function oddDimensionWarning(tab, fields) {
    if (!EVEN_DIM_TABS.includes(tab)) return null;
    const dim = DIMENSION_FIELDS[tab];
    if (!dim) return null;
    const f = fields || {};
    const offenders = [];
    for (const [key, label] of [["w", "width"], ["h", "height"]]) {
      const id = dim[key];
      if (!id) continue;
      const raw = f[id];
      if (raw == null || String(raw).trim() === "") continue;
      const n = Number(raw);
      if (!Number.isInteger(n) || n <= 0) continue; // ignore blanks / non-integers
      if (n % 2 !== 0) offenders.push(`${label} ${n} → ${n + 1}`);
    }
    if (!offenders.length) return null;
    const noun = offenders.length > 1 ? "dimensions" : "dimension";
    return `Odd ${noun} — most video codecs need even numbers. Round ${offenders.join(" and ")}.`;
  }

  // --- Result summary: before/after size + duration once an op finishes ---

  // Pull {size, duration} (positive numbers, or null) from parsed ffprobe data.
  function probeSizeDuration(data) {
    const fmt = (data && data.format) || {};
    const size = Number(fmt.size);
    const duration = Number(fmt.duration);
    return {
      size: isFinite(size) && size > 0 ? size : null,
      duration: isFinite(duration) && duration > 0 ? duration : null,
    };
  }

  // Summarize an op's effect from the input vs output probe data: a short line
  // like "12.3 MB → 4.1 MB (−67%) · 0:30 → 0:12". The size delta needs both
  // sizes (input + output); the duration segment is shown only when both
  // durations are known and differ (most ops preserve duration, and images have
  // none). Returns null when there's nothing meaningful to report.
  function summarizeBeforeAfter(before, after) {
    const b = probeSizeDuration(before);
    const a = probeSizeDuration(after);
    const parts = [];
    if (a.size != null) {
      if (b.size != null) {
        const pct = Math.round(((a.size - b.size) / b.size) * 100);
        const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±";
        parts.push(`${formatBytes(b.size)} → ${formatBytes(a.size)} (${sign}${Math.abs(pct)}%)`);
      } else {
        parts.push(formatBytes(a.size));
      }
    }
    if (a.duration != null && b.duration != null) {
      const bd = formatDuration(b.duration);
      const ad = formatDuration(a.duration);
      if (bd !== ad) parts.push(`${bd} → ${ad}`);
    }
    return parts.length ? parts.join(" · ") : null;
  }

  const api = {
    IMAGE_EXTS,
    VIDEO_EXTS,
    TOOL_ALIASES,
    ERROR_HINTS,
    friendlyError,
    summarizeBeforeAfter,
    parseTimeToSeconds,
    parseBitrateBps,
    estimateOutput,
    EVEN_DIM_TABS,
    oddDimensionWarning,
    filterTools,
    DIMENSION_FIELDS,
    FPS_FIELDS,
    sourceFillActions,
    DIMENSION_PRESETS,
    dimensionPresetTabs,
    presetDimensions,
    videoDims,
    compatReport,
    formatTimecode,
    timeTargetsForTab,
    clampPoint,
    normalizeDragRect,
    rectToCrop,
    cropToRect,
    overwriteMessage,
    isPathFieldId,
    presetNames,
    getPreset,
    withPreset,
    withoutPreset,
    formatBytes,
    formatDuration,
    parseFrameRate,
    formatFps,
    channelLabel,
    summarizeProbe,
    isImagePath,
    isVideoPath,
    previewKind,
    suggestOutput,
    suggestOutputForTab,
    OUTPUT_SPECS,
    extOf,
    previewPath,
    parseLines,
    fieldLabel,
    parseSseBuffer,
    inputTargetForTab,
    dropUpdate,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.FfuLogic = api;
})();
