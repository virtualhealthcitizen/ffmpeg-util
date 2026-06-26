// Renderer: thin client over the sidecar HTTP API exposed via window.sidecar.
// Pure helpers live in logic.js (window.FfuLogic) and are unit-tested separately.
const { baseUrl, token, pickFile, saveFile, getSettings, setSettings, getPathForFile } =
  window.sidecar;
const { suggestOutput, isImagePath, previewPath, parseLines, fieldLabel, parseSseBuffer, dropUpdate } =
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
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
}

async function showPreview(outputPath) {
  // For multi-frame thumbnails (name has %d), preview the first one.
  const path = previewPath(outputPath);
  if (!isImagePath(path)) return hidePreview();
  try {
    const res = await fetch(baseUrl + "/file?path=" + encodeURIComponent(path), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return hidePreview();
    const blob = await res.blob();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob);
    $("#preview-img").src = previewUrl;
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
  run("Extracting thumbnail", "thumbnail", {
    input: val("thumbnail-input"),
    output: val("thumbnail-output"),
    time: val("thumbnail-time") || "00:00:01",
    count: numOrNull("thumbnail-count") || 1,
    width: numOrNull("thumbnail-width"),
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
