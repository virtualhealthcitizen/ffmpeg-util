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

  // Multi-frame thumbnails use %d or zero-padded %04d patterns; resolve to the
  // first frame (%04d -> "0001", %d -> "1") so a preview can be loaded.
  function previewPath(outputPath) {
    return String(outputPath).replace(/%(\d*)d/g, (_, w) =>
      String(1).padStart(w ? parseInt(w, 10) : 1, "0")
    );
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
    scene_thumbs: { tag: "scene_%04d", ext: ".png" },
    reverse: { tag: "rev" },
    volume: { tag: "vol" },
    fade: { tag: "fade" },
    grayscale: { tag: "gray" },
    invert: { tag: "invert" },
    timecode: { tag: "tc" },
    deinterlace: { tag: "deint" },
    sharpen: { tag: "sharp" },
    denoise: { tag: "denoise" },
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
    blur_region: { tag: "blurred" },
    blur_pad: { tag: "blurpad" },
    image_to_video: { tag: "clip", ext: ".mp4" },
    autocrop: { tag: "autocrop" },
    trim_silence: { tag: "trimmed" },
    remux: { tag: "remux" },
    preview_clip: { tag: "preview" },
    poster_frame: { tag: "poster", ext: ".png" },
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

  // Split a path into { dir (incl. trailing separator), name (no extension) }.
  // Handles both \ and / so it works on Windows and POSIX paths.
  function splitPath(p) {
    const s = String(p || "");
    const idx = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    const dir = idx >= 0 ? s.slice(0, idx + 1) : "";
    const file = idx >= 0 ? s.slice(idx + 1) : s;
    const dot = file.lastIndexOf(".");
    const name = dot > 0 ? file.slice(0, dot) : file;
    return { dir, name };
  }

  // Substitute output-name tokens into a template. Known tokens: {name} {op}
  // {w} {h} {wxh} {date}. Missing values resolve to "" ({wxh} only when both
  // w and h are present); unknown {tokens} are left literally in place.
  function applyOutputTemplate(template, ctx) {
    const c = ctx || {};
    const has = (v) => v != null && v !== "";
    const map = {
      name: has(c.name) ? String(c.name) : "",
      op: has(c.op) ? String(c.op) : "",
      w: has(c.w) ? String(c.w) : "",
      h: has(c.h) ? String(c.h) : "",
      wxh: has(c.w) && has(c.h) ? String(c.w) + "x" + String(c.h) : "",
      date: has(c.date) ? String(c.date) : "",
    };
    return String(template || "").replace(/\{(\w+)\}/g, (m, key) =>
      Object.prototype.hasOwnProperty.call(map, key) ? map[key] : m
    );
  }

  // Build an output path for a tab from a name template (the opt-in alternative
  // to suggestOutputForTab's fixed op suffix). Keeps the input's directory and
  // the op's extension; fills {name}/{op}/{w}/{h}/{wxh}/{date} from the input,
  // tab, probed dims and date. `dims` may be {w,h} (videoDims) or {width,height}.
  // Returns "" (caller falls back) without an input or template, or if the
  // template resolves to an empty filename.
  function templatedOutputForTab(inputPath, tab, template, dims, dateStr) {
    const input = String(inputPath || "").trim();
    const tmpl = String(template || "").trim();
    if (!input || !tmpl) return "";
    const { dir, name } = splitPath(input);
    const spec = OUTPUT_SPECS[tab] || {};
    const ext = spec.ext || extOf(input) || ".mp4";
    const w = dims && (dims.width != null ? dims.width : dims.w);
    const h = dims && (dims.height != null ? dims.height : dims.h);
    let stem = applyOutputTemplate(tmpl, { name, op: tab, w, h, date: dateStr });
    // Keep the result a single filename segment: drop path separators + chars
    // that are illegal in Windows filenames, then tidy whitespace.
    stem = stem.replace(/[<>:"/\\|?*]/g, "").replace(/\s+/g, " ").trim();
    if (!stem) return "";
    return dir + stem + ext;
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

  // --- Recent files: a most-recent-first list of input paths the user has loaded,
  // persisted in settings.json so a dropdown/picker can offer them again next
  // launch. Windows paths are case-insensitive, so dedup ignores case (keeping
  // the newest casing) and the list is capped so it can't grow without bound.
  function addRecentFile(list, path, max = 12) {
    const arr = (Array.isArray(list) ? list : []).filter(
      (x) => typeof x === "string" && x.trim()
    );
    const p = String(path || "").trim();
    if (!p) return arr.slice(0, max);
    const lower = p.toLowerCase();
    return [p].concat(arr.filter((x) => x.toLowerCase() !== lower)).slice(0, max);
  }

  // The display label for a recent entry — its filename (with extension).
  function recentFileLabel(path) {
    const s = String(path || "");
    const idx = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    return idx >= 0 ? s.slice(idx + 1) : s;
  }

  // The directory of the most-recent input (no trailing separator), for seeding
  // a file picker's defaultPath; "" when there's no history.
  function recentDir(list) {
    const arr = Array.isArray(list) ? list : [];
    if (!arr.length) return "";
    return splitPath(arr[0]).dir.replace(/[\\/]+$/, "");
  }

  // Move the item at index `from` to index `to`, returning a NEW array (the
  // input is untouched). Out-of-range or equal indices yield a plain copy, so a
  // drag that lands on itself or off the ends can never corrupt the list. Used
  // by the concat tab's drag-to-reorder rows (the textarea stays the store).
  function reorderList(list, from, to) {
    const arr = Array.isArray(list) ? list.slice() : [];
    const n = arr.length;
    if (from < 0 || from >= n || to < 0 || to >= n || from === to) return arr;
    const [item] = arr.splice(from, 1);
    arr.splice(to, 0, item);
    return arr;
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
    scene_thumbs: "scene change detection cut transition thumbnail keyframe shot boundary",
    reverse: "backwards rewind",
    volume: "gain loud quiet db amplify boost attenuate",
    fade: "in out dissolve intro outro",
    grayscale: "black white desaturate mono color monochrome",
    invert: "negate negative invert colors photo negative inverse opposite",
    timecode: "timestamp timecode burned text overlay drawtext clock time counter",
    deinterlace: "interlaced yadif deinterlace combing comb fields progressive fix",
    sharpen: "sharpen unsharp mask crisp edges detail acuity soften blur",
    denoise: "denoise noise grain hqdn3d smooth reduce filter clean",
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
    blur_region: "blur region area face censor pixelate rectangle mosaic privacy redact",
    blur_pad: "blurred fill background letterbox frame fit no bars",
    image_to_video: "still photo png jpg slideshow loop clip make movie from picture",
    trim_silence: "silence strip trim audio ends start trailing leading remove quiet padding",
    remux: "container format change mkv mp4 mov avi webm repackage rewrap copy codec",
    preview_clip: "short preview sample quick look downscale first seconds thumbnail clip small",
    poster_frame: "poster frame still grab percentage midpoint cover art representative image",
  };

  // Group the operation tabs into labeled categories so the ~30-tab nav scans in
  // seconds instead of reading as one undifferentiated wall. Ordered; every tab
  // belongs to exactly one category. Pure data + a grouping helper, consumed by
  // renderer.js to lay the nav out into rows and to hide a category label when
  // search has filtered all of its tools away. A new tab not listed here is never
  // silently dropped — groupTabs() collects any strays into a trailing "Other".
  const TOOL_CATEGORIES = [
    { name: "Convert", tabs: ["convert", "remux"] },
    { name: "Trim & Frames", tabs: ["trim", "preview_clip", "thumbnail", "poster_frame", "frames", "scene_thumbs", "gif"] },
    { name: "Resize & Frame", tabs: ["compress", "crop", "crop_aspect", "autocrop", "pad", "blur_pad"] },
    { name: "Video FX", tabs: ["transform", "speed", "fps", "loop", "reverse", "boomerang", "fade", "image_to_video", "timecode", "blur_region"] },
    { name: "Color", tabs: ["grayscale", "invert", "deinterlace", "sharpen", "denoise", "eq"] },
    { name: "Audio", tabs: ["volume", "mute", "replace_audio", "loudnorm", "mono", "sample_rate", "trim_silence", "waveform"] },
    { name: "Combine", tabs: ["concat", "hstack", "vstack"] },
    { name: "Metadata", tabs: ["title"] },
  ];

  // Lay the given tab ids out under their categories, in category order, keeping
  // each category's tab order and dropping categories with no present tab. `present`
  // is the set of tab ids to show (an array or a Set) — pass every tab to build the
  // full nav, or just the search-visible tabs to decide which labels to show. Any
  // present tab not in TOOL_CATEGORIES lands in a trailing "Other" group so an
  // unlisted tab is never hidden.
  function groupTabs(present, categories) {
    const cats = Array.isArray(categories) ? categories : TOOL_CATEGORIES;
    const show = present instanceof Set ? present : new Set(present || []);
    const seen = new Set();
    const groups = [];
    for (const cat of cats) {
      const tabs = cat.tabs.filter((t) => show.has(t));
      tabs.forEach((t) => seen.add(t));
      if (tabs.length) groups.push({ name: cat.name, tabs });
    }
    const leftover = [...show].filter((t) => !seen.has(t));
    if (leftover.length) groups.push({ name: "Other", tabs: leftover });
    return groups;
  }

  // --- Per-tab help: a one-line "what it does + a concrete example" for the
  // active tool, shown above its panel. With ~30 near-identical input/output/run
  // tabs, the tab name alone doesn't say what the fields mean or what good values
  // look like; this gives each tool a plain-English sentence and a worked example.
  // Pure data + a lookup so the renderer just prints helpForTab(tab). Every tab in
  // the nav has an entry — a stray/unknown id returns "" (the renderer hides it).
  const TOOL_HELP = {
    convert: "Change container or codec (or extract audio). Example: in.mov → in.mp4, or tick Extract audio for in.mp3.",
    trim: "Cut a section by start + end/duration. Example: Start 00:00:05, Duration 10 keeps 5s–15s.",
    concat: "Join clips end-to-end (one path per line, in order). They must share codec/size — re-encode first if not.",
    thumbnail: "Grab a still (or N stills, or a contact sheet). Example: Time 00:00:03 → one frame; Count 5 → 5 frames.",
    compress: "Shrink with CRF/bitrate, optionally resizing. Example: CRF 28 + Width 1280 for a smaller 720p file.",
    gif: "Make an animated GIF (palette two-pass). Example: Width 480, FPS 12, Duration 3; Dither = High quality; Loop 0 = infinite.",
    speed: "Speed up or slow down (keeps pitch sane). Example: 2.0 plays twice as fast; 0.5 is half speed.",
    transform: "Rotate or flip. Example: op = rotate-cw turns 320×240 into 240×320; flip-h mirrors left↔right.",
    crop: "Cut a rectangle (drag on the preview or type x/y/w/h). Example: 160×120 at 80,60 keeps the centre.",
    mute: "Strip the audio track — output is silent video, copied without re-encoding.",
    replace_audio: "Swap in an external audio file (video copied, audio re-encoded, trimmed to the shorter). Pick a new track.",
    pad: "Letterbox to a target frame with solid bars (no cropping). Example: 320×240 → 640×640 centred.",
    loop: "Repeat the whole clip N times. Example: Count 3 makes the output ~3× as long.",
    frames: "Export every Nth frame as images. Example: Every 30 on a 30fps clip writes one PNG per second (use %d).",
    scene_thumbs: "Extract one thumbnail at each scene cut (score > threshold). Example: Threshold 0.3 on a 5-min film → one PNG per shot (use %04d).",
    reverse: "Play the clip backwards (video and audio). Duration is unchanged.",
    volume: "Adjust loudness by decibels. Example: -6 halves perceived volume; +6 boosts it.",
    fade: "Fade in and out at the ends. Example: Duration 1 gives a 1s fade-in and 1s fade-out.",
    grayscale: "Desaturate to black & white (hue=s=0). No options to set — just run.",
    invert: "Invert colours (photo negative). No options to set — just run.",
    timecode: "Burn a running HH:MM:SS.ms timecode into the video (drawtext). Example: Font 24, top-left, white.",
    deinterlace: "Remove interlacing artefacts via yadif. Safe on progressive sources — no options needed, just run.",
    sharpen: "Sharpen edges with the unsharp mask filter. Example: Amount 1.5 for moderate sharpening; negative values soften instead.",
    denoise: "Reduce film grain / sensor noise via hqdn3d. Example: Strength 4 for moderate noise reduction; 8–10 for heavy smoothing.",
    loudnorm: "Normalize loudness to a broadcast target (EBU R128). Example: -16 LUFS for web/podcast levels.",
    boomerang: "Play forward then reversed so it bounces. Output duration is ~2× the input.",
    eq: "Tweak brightness/contrast/saturation (eq filter). Example: Brightness +0.1, Saturation 1.3 for a punchier look.",
    fps: "Change frame rate without changing speed. Example: 30 → 15 drops/duplicates frames, same duration.",
    crop_aspect: "Auto-crop to an aspect ratio. Example: 16:9 turns 320×240 into 320×180 (sides kept, top/bottom trimmed).",
    mono: "Downmix audio to a single channel (-ac 1). No options to set — just run.",
    title: "Set or clear the metadata title tag. Example: type a Title, or leave it blank to clear.",
    waveform: "Render the audio as a waveform PNG. Example: 640×120 for a compact strip.",
    sample_rate: "Resample audio. Example: Rate 22050 down-samples a 44100 Hz track.",
    hstack: "Place two videos side by side (equal heights). Output width is the sum of both.",
    vstack: "Stack two videos top-and-bottom (equal widths). Output height is the sum of both.",
    blur_region: "Blur a rectangle within the video — blur faces, plates, or sensitive text. Example: X=40 Y=10 W=80 H=60 blurs the top-left corner region.",
    blur_pad: "Pad to a target frame, filling the bars with a blurred copy of the video (no solid bars). Example: 320×240 → 480×480.",
    image_to_video: "Loop a still image into a fixed-length clip. Example: photo.png + Seconds 3 → a 3s video.",
    autocrop: "Detect and remove black bars automatically (cropdetect → crop). Example: letterboxed 320×240 → 320×180.",
    trim_silence: "Strip leading and trailing silence (silenceremove). Example: Threshold -50 dB, Min 0.5s removes quiet pads from recordings.",
    remux: "Change the container without re-encoding (-c copy). Example: in.mkv → in.mp4 — fast and lossless when the codecs are container-compatible.",
    preview_clip: "Export the first N seconds at a reduced width — quick sanity-check for long recordings. Example: 5 s · 320 px wide.",
    poster_frame: "Grab one representative frame at a % of the clip's duration. Example: 10% for a near-start cover; 50% for the midpoint; 90% for near the end.",
  };

  // The one-line help for a tab, or "" for an unknown id (renderer hides it). Pure.
  function helpForTab(tab) {
    return Object.prototype.hasOwnProperty.call(TOOL_HELP, tab) ? TOOL_HELP[tab] : "";
  }

  // --- Favorites: pin tools into a leading quick-access row, persisted ---

  // The label of the synthetic group that leads the nav with the pinned tabs.
  const FAVORITES_GROUP = "★ Favorites";

  // Normalize a stored favorites value into a clean ordered list of unique,
  // truthy tab ids (drops blanks + duplicates; a non-array yields []). Pure, so a
  // corrupt/missing settings value can't break the nav layout.
  function normalizeFavorites(favorites) {
    if (!Array.isArray(favorites)) return [];
    const seen = new Set();
    const out = [];
    for (const t of favorites) {
      const id = String(t == null ? "" : t);
      if (id && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    }
    return out;
  }

  // Whether a tab is currently pinned. Pure.
  function isFavorite(favorites, tab) {
    return normalizeFavorites(favorites).includes(tab);
  }

  // Toggle a tab's pinned state, returning a new ordered list (immutable). A newly
  // pinned tab appends to the end so the favorites row order stays stable; the
  // input list is never mutated. A blank tab is a no-op.
  function toggleFavorite(favorites, tab) {
    const list = normalizeFavorites(favorites);
    if (!tab) return list;
    return list.includes(tab) ? list.filter((t) => t !== tab) : [...list, tab];
  }

  // Like groupTabs, but pulls the pinned tabs into a leading "★ Favorites" group
  // and removes them from their normal category, so frequently-used tools sit in
  // one quick-access row at the top. `favorites` is the ordered favorite tab-id
  // list; only favorites that are also `present` appear, in favorites order. The
  // remaining present tabs group by category exactly as groupTabs does, so every
  // present tab still appears exactly once.
  function groupTabsWithFavorites(present, favorites, categories) {
    const show = present instanceof Set ? present : new Set(present || []);
    const favs = normalizeFavorites(favorites).filter((t) => show.has(t));
    const favSet = new Set(favs);
    const rest = [...show].filter((t) => !favSet.has(t));
    const groups = groupTabs(rest, categories);
    return favs.length ? [{ name: FAVORITES_GROUP, tabs: favs }].concat(groups) : groups;
  }

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
    } else if (tab === "preview_clip") {
      const secs = Number(f.seconds);
      if (isFinite(secs) && secs > 0) out = Math.min(inDur, secs);
    } else {
      return null;
    }
    if (out == null || !isFinite(out)) return null;
    return `~${formatDuration(out)}`;
  }

  // --- Live ETA: remaining time for an in-flight op from a progress event ---

  // Parse ffmpeg's `speed` field ("1.05x", "0.5x", "N/A") into a positive number
  // (output seconds encoded per wall-clock second), or null when unusable.
  function parseSpeed(speed) {
    if (speed == null) return null;
    const m = String(speed).match(/([\d.]+)\s*x?/i);
    if (!m) return null;
    const n = Number(m[1]);
    return isFinite(n) && n > 0 ? n : null;
  }

  // Estimate remaining seconds for an in-flight op from a `/run/stream` progress
  // event ({speed, out_time, total}). ETA = remaining output seconds / speed.
  // Returns null until the inputs are usable (no total, no speed, or 0×).
  function etaSeconds(ev) {
    if (!ev) return null;
    const speed = parseSpeed(ev.speed);
    const total = Number(ev.total);
    const out = Number(ev.out_time);
    if (!speed || !isFinite(total) || total <= 0) return null;
    if (!isFinite(out) || out < 0) return null;
    const remaining = Math.max(0, total - out);
    return remaining / speed;
  }

  // "ETA ~0:42" label for a progress event, or null when not yet predictable.
  function etaLabel(ev) {
    const secs = etaSeconds(ev);
    if (secs == null) return null;
    return `ETA ~${formatDuration(secs)}`;
  }

  // --- Console buffer: append a streamed ffmpeg log line, capped to the last
  // `max` lines so a chatty run can't grow the panel without bound. Pure. ---
  function appendConsoleLines(existing, line, max = 500) {
    const lines = Array.isArray(existing) ? existing.slice() : [];
    const incoming = String(line == null ? "" : line).split("\n");
    for (const l of incoming) lines.push(l);
    return lines.length > max ? lines.slice(lines.length - max) : lines;
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

  // --- "Copy as CLI": the equivalent ffmpeg-util command for an op + request body ---

  // The renderer POSTs {op, ...body} to the sidecar's /run/stream; the same values
  // map 1:1 to the CLI, so we can reconstruct the command the user could have typed.
  // A few sidecar body fields carry a different name than their CLI flag — those are
  // the only special cases; every other key becomes --kebab-case.
  const CLI_FLAG_OVERRIDES = {
    fade: "duration", // Fade tab sends `fade`; the CLI flag is --duration
    transform: "op", // Transform tab sends `transform`; the CLI flag is --op
    target_i: "target", // Loudnorm sends `target_i`; the CLI flag is --target
    threshold_db: "threshold", // Trim-silence sends `threshold_db`; the CLI flag is --threshold
  };
  // Body keys that aren't CLI options (positionals or transport-only).
  const CLI_SKIP_KEYS = new Set(["input", "output", "inputs", "overwrite", "op"]);

  function cliSubcommand(op) {
    return String(op || "").replace(/_/g, "-");
  }

  function cliFlagName(key) {
    return "--" + (CLI_FLAG_OVERRIDES[key] || key.replace(/_/g, "-"));
  }

  // Quote a single shell token if it's empty or contains whitespace (paths with
  // spaces are common); embedded double-quotes are backslash-escaped.
  function cliQuote(value) {
    const s = String(value);
    if (s === "" || /\s/.test(s)) return '"' + s.replace(/"/g, '\\"') + '"';
    return s;
  }

  // Build the `ffmpeg-util <subcommand> …` command equivalent to an op + body.
  // Positionals: an `inputs` array (concat/hstack/vstack, joined with `-o output`)
  // or `input` then `output`. Remaining keys become flags in body order: a `true`
  // boolean is a bare flag, null/""/false are dropped, and negative numbers use the
  // `--flag=value` form so argparse doesn't mistake them for another option.
  function buildCliCommand(op, body) {
    body = body || {};
    const parts = ["ffmpeg-util", cliSubcommand(op)];
    if (Array.isArray(body.inputs)) {
      for (const f of body.inputs) parts.push(cliQuote(f));
      if (body.output != null && body.output !== "") parts.push("-o", cliQuote(body.output));
    } else {
      if (body.input != null && body.input !== "") parts.push(cliQuote(body.input));
      if (body.output != null && body.output !== "") parts.push(cliQuote(body.output));
    }
    for (const key of Object.keys(body)) {
      if (CLI_SKIP_KEYS.has(key)) continue;
      const v = body[key];
      if (v == null || v === "" || v === false) continue;
      if (v === true) {
        parts.push(cliFlagName(key));
        continue;
      }
      const s = String(v);
      if (s[0] === "-") parts.push(cliFlagName(key) + "=" + cliQuote(s));
      else parts.push(cliFlagName(key), cliQuote(s));
    }
    if (body.overwrite) parts.push("-y");
    return parts.join(" ");
  }

  // --- Keyboard shortcuts (run the active tab, cycle tabs) ---
  // Pure mapping from a keydown to an app action, so the renderer just dispatches.
  // Modifier (Ctrl/Cmd) gates every shortcut so plain typing in fields is untouched:
  //   Ctrl/Cmd+Enter            → run the active tab's primary action
  //   Ctrl/Cmd+] or Ctrl+Cmd+. → next tab; Ctrl/Cmd+[ or Ctrl/Cmd+, → previous tab
  // `event` only needs {key, ctrlKey, metaKey}. Returns null for anything else.
  function keyboardAction(event) {
    if (!event || (!event.ctrlKey && !event.metaKey)) return null;
    switch (event.key) {
      case "Enter":
        return { type: "run" };
      case "]":
      case ".":
        return { type: "switch", dir: 1 };
      case "[":
      case ",":
        return { type: "switch", dir: -1 };
      default:
        return null;
    }
  }

  // Pure neighbor lookup over the *visible* tab ids (search may hide some), wrapping
  // around. dir is +1 (next) / -1 (previous). Returns null when there are no tabs;
  // if `current` isn't visible, lands on the first (next) or last (previous) tab.
  function nextVisibleTab(visibleTabs, current, dir) {
    if (!visibleTabs || !visibleTabs.length) return null;
    const i = visibleTabs.indexOf(current);
    if (i === -1) return dir > 0 ? visibleTabs[0] : visibleTabs[visibleTabs.length - 1];
    const n = (i + dir + visibleTabs.length) % visibleTabs.length;
    return visibleTabs[n];
  }

  // --- Sliders with live readouts ---
  // Configuration for each slider: id (the number input's id), range, step,
  // default value when the field is empty, and unit suffix for the readout.
  const SLIDER_SPECS = [
    { id: "volume-gain",     min: -60, max: 30,  step: 0.5, def: 0,   unit: " dB" },
    { id: "speed-factor",    min: 0.1, max: 4,   step: 0.1, def: 1,   unit: "×" },
    { id: "eq-brightness",   min: -1,  max: 1,   step: 0.1, def: 0,   unit: "" },
    { id: "eq-contrast",     min: 0,   max: 3,   step: 0.1, def: 1,   unit: "" },
    { id: "eq-saturation",   min: 0,   max: 3,   step: 0.1, def: 1,   unit: "" },
    { id: "fade-duration",   min: 0.1, max: 10,  step: 0.1, def: 1,   unit: "s" },
    { id: "loudnorm-target", min: -70, max: -5,  step: 0.5, def: -16, unit: " LUFS" },
    { id: "sharpen-amount",  min: -1.5, max: 5,  step: 0.1, def: 1.5, unit: "" },
    { id: "denoise-strength",   min: 1,  max: 10,  step: 0.5, def: 4,   unit: "" },
    { id: "timecode-font-size",         min: 6,   max: 72,  step: 2,   def: 24,   unit: " pt" },
    { id: "trim_silence-threshold",     min: -80, max: -20, step: 1,   def: -50,  unit: " dB" },
    { id: "trim_silence-min-duration",  min: 0.1, max: 3.0, step: 0.1, def: 0.5,  unit: "s" },
  ];

  // Format a (already-valid, finite) slider value for its live readout label.
  // Removes floating-point noise then appends the unit suffix.
  function formatSliderOut(spec, value) {
    const v = parseFloat(value);
    if (!isFinite(v)) return "";
    return parseFloat(v.toFixed(10)) + spec.unit;
  }

  // --- Pre-run path validation helpers ---

  // [path, fieldId] pairs for every input of a run body so the renderer can
  // check each exists and highlight the right field on failure. Empty paths are
  // omitted — requireFields already catches missing values before the run starts.
  function runInputEntries(tab, body) {
    const b = body || {};
    if (tab === "hstack" || tab === "vstack") {
      const arr = Array.isArray(b.inputs) ? b.inputs : [];
      return [
        [String(arr[0] || "").trim(), tab + "-input-a"],
        [String(arr[1] || "").trim(), tab + "-input-b"],
      ].filter(([p]) => p);
    }
    if (Array.isArray(b.inputs)) {
      const fieldId = tab + "-inputs"; // e.g. "concat-inputs"
      return b.inputs
        .map((p) => String(p || "").trim())
        .filter(Boolean)
        .map((p) => [p, fieldId]);
    }
    if (tab === "replace_audio") {
      const entries = [];
      const vid = String(b.input || "").trim();
      if (vid) entries.push([vid, "replace_audio-input"]);
      const aud = String(b.audio || "").trim();
      if (aud) entries.push([aud, "replace_audio-audio"]);
      return entries;
    }
    const p = String(b.input || "").trim();
    return p ? [[p, tab + "-input"]] : [];
  }

  // [dir, fieldId] for the output-directory existence check, or null when the
  // output path has no directory component (current dir — always present).
  function runOutputDirEntry(tab, body) {
    const out = String((body && body.output) || "").trim();
    if (!out) return null;
    const dir = splitPath(out).dir;
    return dir ? [dir, tab + "-output"] : null;
  }

  // --- Completion actions: Open + Reveal in file manager after a run ---

  // Platform-appropriate label for the "reveal in file manager" button.
  function revealLabel(platform) {
    if (platform === "darwin") return "Reveal in Finder";
    if (platform === "linux") return "Reveal in Files";
    return "Reveal in Explorer";
  }

  // Extract just the filename from a path (handles both / and \ separators).
  // Returns null for empty/null inputs; falls back to the original string when
  // there is no separator so callers always get a displayable value or null.
  function outputBaseName(outputPath) {
    if (!outputPath) return null;
    return String(outputPath).replace(/\\/g, "/").split("/").pop() || String(outputPath);
  }

  // --- Light/dark theme toggle ---
  // The renderer carries a `data-theme` attribute on <html>; styles.css supplies a
  // `:root[data-theme="light"]` palette override (dark is the default :root). Pure
  // helpers so the renderer just resolves, cycles, and labels — no logic in the DOM.
  const THEMES = ["dark", "light"];

  // Normalize any stored value to a known theme; anything unknown falls back to dark.
  function resolveTheme(value) {
    return THEMES.includes(value) ? value : "dark";
  }

  // Cycle to the next theme (dark <-> light), tolerant of a bad current value.
  function nextTheme(current) {
    const i = THEMES.indexOf(resolveTheme(current));
    return THEMES[(i + 1) % THEMES.length];
  }

  // Label for the toggle button: it advertises the theme a click switches *to*.
  function themeToggleLabel(current) {
    return resolveTheme(current) === "dark" ? "☀ Light" : "☾ Dark";
  }

  // --- Per-field "?" tooltips: short help blurbs for non-obvious form fields ---
  // Maps input/select element ids to a one-line explanation — what the field does
  // and what values make sense. Covers the ~40 fields users most often mis-set or
  // wonder about; obvious labels and path fields are intentionally omitted. Pure
  // data + a lookup, consumed by setupFieldTooltips() in renderer.js which inserts
  // a small ? badge next to each covered label at startup.
  const FIELD_TOOLTIPS = {
    // Convert
    "convert-vcodec":  "Video codec: 'copy' to stream-copy without re-encoding, or a name like libx264 (H.264) or libx265 (HEVC).",
    "convert-acodec":  "Audio codec: 'copy' to stream-copy, or a name like aac, mp3, or opus.",
    // Trim
    "trim-start":      "Start time: HH:MM:SS, MM:SS, or bare seconds (e.g. 5 or 1:30). Defaults to the beginning.",
    "trim-end":        "End time — use End or Duration, not both. Defaults to the end of the clip.",
    "trim-duration":   "How long to keep — use End or Duration, not both.",
    // Thumbnail
    "thumbnail-time":  "Timestamp for a single frame: HH:MM:SS or bare seconds. Ignored when Count > 1.",
    "thumbnail-count": "Number of evenly-spaced frames to extract. Include %d in the output filename.",
    "thumbnail-width": "Output image width in pixels; height scales proportionally. Leave blank for the source width.",
    "thumbnail-cols":  "Columns in a contact-sheet montage — set both Cols and Rows to make a grid.",
    "thumbnail-rows":  "Rows in a contact-sheet montage — set both Cols and Rows to make a grid.",
    // Compress
    "compress-crf":    "Constant Rate Factor: lower = better quality / larger file. 0 = lossless, 51 = worst; 18–28 is the useful range (default 23).",
    "compress-bitrate":"Target average bitrate, e.g. '2M' for 2 Mbps or '500k'. Overridden by Target MB if set.",
    "compress-target": "Target output file size in megabytes — uses a two-pass encode. Overrides CRF and Bitrate.",
    "compress-vcodec": "Video codec: libx264 (H.264), libx265 (H.265/HEVC), libvpx-vp9 (VP9). Defaults to libx264.",
    "compress-preset": "Encoding speed vs compression: ultrafast → veryslow. Slower = smaller file at the same CRF, but takes longer.",
    // GIF
    "gif-fps":         "Frames per second for the GIF. Lower = smaller file; 10–15 fps is a good range.",
    "gif-width":       "Output width in pixels; height scales proportionally.",
    "gif-start":       "Start time within the source clip: HH:MM:SS or bare seconds.",
    "gif-duration":    "Length of the GIF in seconds.",
    "gif-loop":        "Loop count: 0 = infinite loop, -1 = play once, N > 0 = play N times.",
    // Speed
    "speed-factor":    "Speed multiplier: 2.0 = twice as fast, 0.5 = half speed. Audio pitch is corrected automatically.",
    // Crop
    "crop-width":      "Crop rectangle width in source pixels. Must be even for H.264.",
    "crop-height":     "Crop rectangle height in source pixels. Must be even for H.264.",
    "crop-x":          "Left edge of the crop rectangle, in source pixels (0 = left edge of the frame).",
    "crop-y":          "Top edge of the crop rectangle, in source pixels (0 = top of the frame).",
    // Pad
    "pad-width":       "Target frame width in pixels. The source is centred; solid bars fill the gaps.",
    "pad-height":      "Target frame height in pixels.",
    // Loop
    "loop-count":      "Total number of plays: 1 = no loop, 2 = play twice, 3 = three times, etc.",
    // Frames
    "frames-every":    "Extract one frame every N frames (e.g. 30 on a 30 fps clip = one frame per second). Use %04d in the output path.",
    // Scene thumbs
    "scene-thumbs-threshold": "Scene-change score threshold (0–1). Lower values catch more cuts: 0.1 for soft transitions, 0.3 for typical cuts, 0.4 for hard cuts only.",
    "scene-thumbs-width":     "Scale each thumbnail to this width in pixels; height scales proportionally. Leave blank to keep the source resolution.",
    // Volume
    "volume-gain":     "Gain in decibels: +6 dB ≈ double loudness, -6 dB ≈ half. Typical adjustments are ±3–12 dB.",
    // Fade
    "fade-duration":   "Length of the fade-in and fade-out in seconds. Both ends fade; trim first to fade only one end.",
    // Loudnorm
    "loudnorm-target": "Integrated loudness target in LUFS: -16 for web/podcast, -14 for Spotify/YouTube, -23 for broadcast.",
    // EQ
    "eq-brightness":   "Brightness offset: -1 = black, 0 = unchanged, +1 = white.",
    "eq-contrast":     "Contrast multiplier: 0 = flat grey, 1 = unchanged, >1 = higher contrast.",
    "eq-saturation":   "Saturation multiplier: 0 = greyscale, 1 = unchanged, >1 = more vivid.",
    // FPS
    "fps-fps":         "Output frame rate in fps. Frames are dropped or duplicated to hit this rate; clip duration is unchanged.",
    // Waveform
    "waveform-width":  "Output PNG width in pixels. The waveform spans the full width.",
    "waveform-height": "Output PNG height in pixels.",
    // Blur region
    "blur_region-x":      "Left edge of the blur rectangle in pixels (from the left of the frame). Default 0.",
    "blur_region-y":      "Top edge of the blur rectangle in pixels (from the top of the frame). Default 0.",
    "blur_region-width":  "Width of the blur rectangle in pixels.",
    "blur_region-height": "Height of the blur rectangle in pixels.",
    "blur_region-sigma":  "Gaussian blur strength. Higher = more blurred. Default 10; use 20+ for heavy redaction.",
    // Blur pad
    "blur_pad-width":  "Target frame width in pixels. The source is scaled to fit; the gap is filled with a blurred copy.",
    "blur_pad-height": "Target frame height in pixels.",
    "blur_pad-sigma":  "Blur strength for the background fill (Gaussian sigma). Higher = softer. Default 20 works for most clips.",
    // Image to video
    "image_to_video-seconds": "Length of the output clip in seconds.",
    "image_to_video-fps":     "Frames per second for the output clip. 30 is standard.",
    // Autocrop
    "autocrop-limit":  "Black level threshold (0–255): pixels at or below this brightness count as 'bar' pixels. Default 24 suits most clips.",
    // Title
    "title-title":     "Metadata title tag to embed in the output file. Leave blank to clear the existing title.",
    // Sharpen
    "sharpen-amount":  "Unsharp mask luma amount: >0 sharpens (1.5 = moderate, 5 = heavy), <0 softens, 0 = no-op.",
    // Denoise
    "denoise-strength": "hqdn3d noise reduction strength: 1–3 light, 4–6 moderate, 7–10 heavy smoothing.",
    // Timecode
    "timecode-font-size": "Font size in points for the timecode overlay (6–72). Default 24 suits 720p+; use 36+ for 1080p.",
    "timecode-position":  "Corner of the frame to place the timecode: top-left, top-right, bottom-left, bottom-right.",
    "timecode-color":     "Text colour: white/yellow are most legible on dark subjects; black works on bright backgrounds.",
    // Trim silence
    "trim_silence-threshold":    "Audio below this level is treated as silence. -50 dB is a safe default; try -40 for noisy rooms, -60 for very quiet pads.",
    "trim_silence-min-duration": "Minimum run of silence (seconds) before it is removed. 0.5 trims any half-second or longer quiet section.",
    // Preview clip
    "preview_clip-seconds": "How many seconds to keep from the start of the file. Example: 5 for a 5-second preview; 30 for a 30-second sample.",
    "preview_clip-width":   "Output width in pixels; height scales proportionally (rounded to even). Example: 320 for a small preview, 640 for medium.",
    // Poster frame
    "poster_frame-percent": "Position in the clip as a percentage of its total duration (0–100). Example: 10 grabs a frame near the start; 50 the midpoint; 90 near the end.",
  };

  // The help blurb for a form field id, or "" when none is configured. Pure.
  function fieldTooltip(id) {
    return Object.prototype.hasOwnProperty.call(FIELD_TOOLTIPS, id) ? FIELD_TOOLTIPS[id] : "";
  }

  // --- Completion notification payload ---
  // Returns { title, body } to show a desktop notification when an op finishes,
  // or null when notifications are disabled. Pure so it's unit-testable.
  function notifyComplete(basename, enabled) {
    if (!enabled) return null;
    return {
      title: "ffmpeg-util",
      body: basename ? "Done — " + basename : "Done.",
    };
  }

  const api = {
    THEMES,
    resolveTheme,
    nextTheme,
    themeToggleLabel,
    keyboardAction,
    nextVisibleTab,
    IMAGE_EXTS,
    VIDEO_EXTS,
    TOOL_ALIASES,
    ERROR_HINTS,
    friendlyError,
    summarizeBeforeAfter,
    buildCliCommand,
    parseTimeToSeconds,
    parseBitrateBps,
    estimateOutput,
    parseSpeed,
    etaSeconds,
    etaLabel,
    appendConsoleLines,
    EVEN_DIM_TABS,
    oddDimensionWarning,
    filterTools,
    TOOL_CATEGORIES,
    groupTabs,
    TOOL_HELP,
    helpForTab,
    FAVORITES_GROUP,
    normalizeFavorites,
    isFavorite,
    toggleFavorite,
    groupTabsWithFavorites,
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
    applyOutputTemplate,
    templatedOutputForTab,
    splitPath,
    OUTPUT_SPECS,
    extOf,
    previewPath,
    parseLines,
    fieldLabel,
    parseSseBuffer,
    inputTargetForTab,
    dropUpdate,
    addRecentFile,
    recentFileLabel,
    recentDir,
    reorderList,
    SLIDER_SPECS,
    formatSliderOut,
    revealLabel,
    outputBaseName,
    runInputEntries,
    runOutputDirEntry,
    FIELD_TOOLTIPS,
    fieldTooltip,
    notifyComplete,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.FfuLogic = api;
})();
