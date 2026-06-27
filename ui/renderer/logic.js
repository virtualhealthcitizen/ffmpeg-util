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

  const api = {
    IMAGE_EXTS,
    VIDEO_EXTS,
    TOOL_ALIASES,
    filterTools,
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
