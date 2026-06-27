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
    pad: "letterbox bars frame fit border",
    loop: "repeat times duplicate",
    frames: "extract images sequence export png every nth",
    reverse: "backwards rewind",
    volume: "gain loud quiet db amplify boost attenuate",
    fade: "in out dissolve intro outro",
    grayscale: "black white desaturate mono color monochrome",
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

  const api = {
    IMAGE_EXTS,
    VIDEO_EXTS,
    TOOL_ALIASES,
    filterTools,
    DIMENSION_FIELDS,
    FPS_FIELDS,
    sourceFillActions,
    videoDims,
    compatReport,
    formatTimecode,
    timeTargetsForTab,
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
