// Renderer: thin client over the sidecar HTTP API exposed via window.sidecar.
// Pure helpers live in logic.js (window.FfuLogic) and are unit-tested separately.
const { baseUrl, token, pickFile, saveFile, getSettings, setSettings, getPathForFile } =
  window.sidecar;
const { suggestOutput, parseLines, fieldLabel, parseSseBuffer, dropUpdate, previewKind } =
  window.FfuLogic;
const $ = (sel) => document.querySelector(sel);
const val = (id) => $("#" + id).value.trim();
const numOrNull = (id) => (val(id) === "" ? null : Number(val(id)));
const strOrNull = (id) => (val(id) === "" ? null : val(id));

async function api(pathname, body) {
  const res = await fetch(baseUrl + pathname, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function setStatus(msg, isErr = false) {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status " + (isErr ? "err" : "ok");
}

// --- Tabs ---
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + tab));
  });
});

function currentTab() {
  const btn = document.querySelector(".tabs button.active");
  return btn ? btn.dataset.tab : "convert";
}

// --- Drag & drop: drop files anywhere to load them into the active tab ---
(function setupDragDrop() {
  const body = document.body;
  ["dragenter", "dragover"].forEach((ev) =>
    body.addEventListener(ev, (e) => {
      e.preventDefault();
      body.classList.add("drag-over");
    })
  );
  body.addEventListener("dragleave", (e) => {
    if (!e.relatedTarget) body.classList.remove("drag-over"); // left the window
  });
  body.addEventListener("drop", (e) => {
    e.preventDefault();
    body.classList.remove("drag-over");
    const paths = Array.from(e.dataTransfer.files).map((f) => getPathForFile(f)).filter(Boolean);
    const upd = dropUpdate(paths, currentTab(), $("#concat-inputs").value);
    if (upd) {
      $("#" + upd.id).value = upd.value;
      setStatus(`Loaded ${paths.length} file(s) into the ${currentTab()} tab.`);
    }
  });
})();

// --- File pickers (declarative via data attributes) ---
document.querySelectorAll(".pick-file").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const p = await pickFile();
    if (!p) return;
    if (btn.dataset.append) {
      const ta = $("#" + btn.dataset.append);
      ta.value = ta.value ? ta.value + "\n" + p : p;
    } else {
      $("#" + btn.dataset.target).value = p;
    }
  });
});

document.querySelectorAll(".pick-save").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const p = await saveFile(suggestOutput("", ""));
    if (p) $("#" + btn.dataset.target).value = p;
  });
});

document.querySelectorAll(".probe-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const input = val(btn.dataset.source);
    if (!input) return setStatus("Pick an input file first.", true);
    setStatus("Probing…");
    try {
      const { result } = await api("/probe", { input, as_json: false });
      $("#probe-out").textContent = result;
      setStatus("Probe complete.");
    } catch (e) {
      setStatus("Error: " + e.message, true);
    }
  });
});

// --- Settings persistence (sticky option fields, not per-file paths) ---
const STICKY = [
  "convert-vcodec", "convert-acodec",
  "trim-start",
  "thumbnail-time", "thumbnail-count", "thumbnail-width",
  "compress-crf", "compress-bitrate", "compress-width", "compress-height",
  "compress-vcodec", "compress-preset",
  "gif-fps", "gif-width",
];

async function loadSettings() {
  try {
    const s = (await getSettings()) || {};
    for (const id of STICKY) {
      const el = $("#" + id);
      if (el && s[id] != null && s[id] !== "") el.value = s[id];
    }
  } catch (_) {
    // first run / no store yet — ignore
  }
}

async function saveSettings() {
  const s = {};
  for (const id of STICKY) {
    const el = $("#" + id);
    if (el && el.value.trim() !== "") s[id] = el.value;
  }
  try {
    await setSettings(s);
  } catch (_) {
    // non-fatal
  }
}

loadSettings();

// --- Output preview (images) ---
let previewUrl = null;

function hidePreview() {
  $("#preview").classList.add("hidden");
  const img = $("#preview-img");
  const vid = $("#preview-video");
  vid.pause();
  img.classList.add("hidden");
  vid.classList.add("hidden");
  img.removeAttribute("src");
  vid.removeAttribute("src");
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
}

async function showPreview(outputPath) {
  // Images (incl. %d -> first frame) show inline; videos get a <video> player.
  const { kind, path } = previewKind(outputPath);
  if (!kind) return hidePreview();
  try {
    const res = await fetch(baseUrl + "/file?path=" + encodeURIComponent(path), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return hidePreview();
    const blob = await res.blob();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    const img = $("#preview-img");
    const vid = $("#preview-video");
    if (kind === "image") {
      img.src = previewUrl;
      img.classList.remove("hidden");
      vid.classList.add("hidden");
      vid.removeAttribute("src");
    } else {
      vid.src = previewUrl;
      vid.classList.remove("hidden");
      img.classList.add("hidden");
      img.removeAttribute("src");
    }
    $("#preview").classList.remove("hidden");
  } catch (_) {
    hidePreview();
  }
}

// --- Progress bar ---
function showProgress(pct) {
  $("#progress").classList.remove("hidden");
  $("#progress-bar").style.width = (pct || 0) + "%";
}
function hideProgress() {
  $("#progress").classList.add("hidden");
  $("#progress-bar").style.width = "0%";
}

// --- Operation runners (stream progress via SSE over fetch) ---
async function run(label, op, body) {
  setStatus(label + "…");
  showProgress(0);
  hidePreview();
  try {
    const res = await fetch(baseUrl + "/run/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ op, ...body }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `HTTP ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parsed = parseSseBuffer(buf);
      buf = parsed.remainder; // keep trailing partial
      for (const ev of parsed.events) {
        if (ev.type === "progress") {
          if (ev.percent != null) showProgress(ev.percent);
          setStatus(`${label}… ${ev.percent != null ? ev.percent + "%" : ""}${ev.speed ? " (" + ev.speed + ")" : ""}`);
        } else if (ev.type === "done") {
          result = ev;
        } else if (ev.type === "error") {
          throw new Error(ev.detail);
        }
      }
    }
    hideProgress();
    setStatus(result ? "Done → " + result.output : "Done.");
    saveSettings();
    if (result && result.output) showPreview(result.output);
  } catch (e) {
    hideProgress();
    setStatus("Error: " + e.message, true);
  }
}

function requireFields(...ids) {
  for (const id of ids) {
    if (!val(id)) {
      setStatus("Missing required field: " + fieldLabel(id), true);
      return false;
    }
  }
  return true;
}

$("#run-convert").addEventListener("click", () => {
  if (!requireFields("convert-input", "convert-output")) return;
  run("Converting", "convert", {
    input: val("convert-input"),
    output: val("convert-output"),
    vcodec: strOrNull("convert-vcodec"),
    acodec: strOrNull("convert-acodec"),
    extract_audio: $("#convert-extract").checked,
    overwrite: true,
  });
});

$("#run-trim").addEventListener("click", () => {
  if (!requireFields("trim-input", "trim-output")) return;
  run("Trimming", "trim", {
    input: val("trim-input"),
    output: val("trim-output"),
    start: strOrNull("trim-start"),
    end: strOrNull("trim-end"),
    duration: strOrNull("trim-duration"),
    reencode: $("#trim-reencode").checked,
    overwrite: true,
  });
});

$("#run-concat").addEventListener("click", () => {
  const inputs = parseLines(val("concat-inputs"));
  if (inputs.length < 2) return setStatus("Concat needs at least two input files.", true);
  if (!requireFields("concat-output")) return;
  run("Concatenating", "concat", { inputs, output: val("concat-output"), overwrite: true });
});

$("#run-thumbnail").addEventListener("click", () => {
  if (!requireFields("thumbnail-input", "thumbnail-output")) return;
  const cols = numOrNull("thumbnail-cols");
  const rows = numOrNull("thumbnail-rows");
  if (cols && rows) {
    run("Building contact sheet", "contact_sheet", {
      input: val("thumbnail-input"),
      output: val("thumbnail-output"),
      cols,
      rows,
      width: numOrNull("thumbnail-width") || 320,
      overwrite: true,
    });
    return;
  }
  run("Extracting thumbnail", "thumbnail", {
    input: val("thumbnail-input"),
    output: val("thumbnail-output"),
    time: val("thumbnail-time") || "00:00:01",
    count: numOrNull("thumbnail-count") || 1,
    width: numOrNull("thumbnail-width"),
    overwrite: true,
  });
});

$("#run-grayscale").addEventListener("click", () => {
  if (!requireFields("grayscale-input", "grayscale-output")) return;
  run("Converting to grayscale", "grayscale", {
    input: val("grayscale-input"),
    output: val("grayscale-output"),
    overwrite: true,
  });
});

$("#run-boomerang").addEventListener("click", () => {
  if (!requireFields("boomerang-input", "boomerang-output")) return;
  run("Making boomerang", "boomerang", {
    input: val("boomerang-input"),
    output: val("boomerang-output"),
    overwrite: true,
  });
});

$("#run-fade").addEventListener("click", () => {
  if (!requireFields("fade-input", "fade-output", "fade-duration")) return;
  run("Fading", "fade", {
    input: val("fade-input"),
    output: val("fade-output"),
    fade: numOrNull("fade-duration"),
    overwrite: true,
  });
});

$("#run-loudnorm").addEventListener("click", () => {
  if (!requireFields("loudnorm-input", "loudnorm-output")) return;
  run("Normalizing loudness", "loudnorm", {
    input: val("loudnorm-input"),
    output: val("loudnorm-output"),
    target_i: numOrNull("loudnorm-target") != null ? numOrNull("loudnorm-target") : -16,
    overwrite: true,
  });
});

$("#run-volume").addEventListener("click", () => {
  if (!requireFields("volume-input", "volume-output", "volume-gain")) return;
  run("Adjusting volume", "volume", {
    input: val("volume-input"),
    output: val("volume-output"),
    gain: numOrNull("volume-gain"),
    overwrite: true,
  });
});

$("#run-reverse").addEventListener("click", () => {
  if (!requireFields("reverse-input", "reverse-output")) return;
  run("Reversing", "reverse", {
    input: val("reverse-input"),
    output: val("reverse-output"),
    overwrite: true,
  });
});

$("#run-frames").addEventListener("click", () => {
  if (!requireFields("frames-input", "frames-output")) return;
  run("Extracting frames", "frames", {
    input: val("frames-input"),
    output: val("frames-output"),
    every: numOrNull("frames-every") || 1,
    overwrite: true,
  });
});

$("#run-loop").addEventListener("click", () => {
  if (!requireFields("loop-input", "loop-output", "loop-count")) return;
  run("Looping", "loop", {
    input: val("loop-input"),
    output: val("loop-output"),
    count: numOrNull("loop-count"),
    overwrite: true,
  });
});

$("#run-pad").addEventListener("click", () => {
  if (!requireFields("pad-input", "pad-output", "pad-width", "pad-height")) return;
  run("Padding", "pad", {
    input: val("pad-input"),
    output: val("pad-output"),
    width: numOrNull("pad-width"),
    height: numOrNull("pad-height"),
    overwrite: true,
  });
});

$("#run-mute").addEventListener("click", () => {
  if (!requireFields("mute-input", "mute-output")) return;
  run("Stripping audio", "mute", {
    input: val("mute-input"),
    output: val("mute-output"),
    overwrite: true,
  });
});

$("#run-crop").addEventListener("click", () => {
  if (!requireFields("crop-input", "crop-output", "crop-width", "crop-height")) return;
  run("Cropping", "crop", {
    input: val("crop-input"),
    output: val("crop-output"),
    width: numOrNull("crop-width"),
    height: numOrNull("crop-height"),
    x: numOrNull("crop-x") || 0,
    y: numOrNull("crop-y") || 0,
    overwrite: true,
  });
});

$("#run-transform").addEventListener("click", () => {
  if (!requireFields("transform-input", "transform-output")) return;
  run("Transforming", "transform", {
    input: val("transform-input"),
    output: val("transform-output"),
    transform: $("#transform-op").value,
    overwrite: true,
  });
});

$("#run-speed").addEventListener("click", () => {
  if (!requireFields("speed-input", "speed-output", "speed-factor")) return;
  run("Changing speed", "speed", {
    input: val("speed-input"),
    output: val("speed-output"),
    factor: numOrNull("speed-factor"),
    overwrite: true,
  });
});

$("#run-gif").addEventListener("click", () => {
  if (!requireFields("gif-input", "gif-output")) return;
  run("Making GIF", "gif", {
    input: val("gif-input"),
    output: val("gif-output"),
    fps: numOrNull("gif-fps") || 12,
    width: numOrNull("gif-width") || 480,
    start: strOrNull("gif-start"),
    duration: strOrNull("gif-duration"),
    overwrite: true,
  });
});

$("#run-compress").addEventListener("click", () => {
  if (!requireFields("compress-input", "compress-output")) return;
  run("Compressing", "compress", {
    input: val("compress-input"),
    output: val("compress-output"),
    crf: numOrNull("compress-crf"),
    bitrate: strOrNull("compress-bitrate"),
    target_size: numOrNull("compress-target"),
    width: numOrNull("compress-width"),
    height: numOrNull("compress-height"),
    vcodec: val("compress-vcodec") || "libx264",
    preset: val("compress-preset") || "medium",
    overwrite: true,
  });
});
