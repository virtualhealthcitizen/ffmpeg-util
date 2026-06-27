// Renderer: thin client over the sidecar HTTP API exposed via window.sidecar.
// Pure helpers live in logic.js (window.FfuLogic) and are unit-tested separately.
const { baseUrl, token, pickFile, saveFile, getSettings, setSettings, getPathForFile } =
  window.sidecar;
const { suggestOutput, suggestOutputForTab, parseLines, fieldLabel, parseSseBuffer, dropUpdate, previewKind,
  filterTools, TOOL_ALIASES, summarizeProbe, sourceFillActions,
  DIMENSION_FIELDS, DIMENSION_PRESETS, presetDimensions,
  videoDims, compatReport, formatTimecode, timeTargetsForTab,
  clampPoint, normalizeDragRect, rectToCrop, cropToRect,
  overwriteMessage, isPathFieldId, presetNames, getPreset, withPreset,
  withoutPreset, estimateOutput, oddDimensionWarning, friendlyError, summarizeBeforeAfter,
  buildCliCommand, previewPath, keyboardAction, nextVisibleTab,
  TOOL_CATEGORIES, groupTabs } = window.FfuLogic;
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

// Show a friendly one-line hint above the raw error text for recognized ffmpeg
// failures; hide it for unrecognized errors (and clear it on the next run).
function showErrorHint(rawMessage) {
  const el = $("#error-hint");
  if (!el) return;
  const hint = friendlyError(rawMessage);
  if (hint) {
    el.textContent = hint;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}
function clearErrorHint() {
  const el = $("#error-hint");
  if (el) {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

// --- Tabs ---
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + tab));
    refreshInputs(); // show the new tab's input + multi-input compat (if any)
    refreshPresetSelect(); // show this tab's saved presets
    refreshDimPresets(); // show frame-size presets when the tab has W/H fields
    renderCropOverlay(); // show/hide the visual crop selector for this tab
    setSettings({ activeTab: tab }).catch(() => {}); // remember across launches
  });
});

function currentTab() {
  const btn = document.querySelector(".tabs button.active");
  return btn ? btn.dataset.tab : "convert";
}

// Lay the flat list of tab buttons out into labeled category rows so the ~30-tab
// nav scans in seconds. The order comes straight from the (unit-tested) data in
// logic.js: each label is a full-width divider that wraps the buttons after it
// onto their own rows. Buttons are moved (not cloned), so the click/search/
// keyboard wiring queried elsewhere keeps working on the same nodes.
function layoutNavGroups() {
  const nav = document.querySelector(".tabs");
  if (!nav) return;
  const byTab = new Map(
    Array.from(nav.querySelectorAll("button")).map((b) => [b.dataset.tab, b])
  );
  const groups = groupTabs(Array.from(byTab.keys()), TOOL_CATEGORIES);
  for (const g of groups) {
    const label = document.createElement("span");
    label.className = "tab-group-label";
    label.dataset.group = g.name;
    label.textContent = g.name;
    nav.appendChild(label);
    for (const tab of g.tabs) nav.appendChild(byTab.get(tab));
  }
}
layoutNavGroups();

// Hide a category label when search has filtered away every tool under it, so an
// empty heading never floats over a blank row. `visible` is the set of tab ids
// the search currently shows.
function updateNavGroupLabels(visible) {
  const present = new Set(groupTabs(visible, TOOL_CATEGORIES).map((g) => g.name));
  document.querySelectorAll(".tabs .tab-group-label").forEach((label) => {
    label.classList.toggle("hidden", !present.has(label.dataset.group));
  });
}

// --- Tool search / command palette: narrow the 30 tabs by name + alias ---
(function setupToolSearch() {
  const search = $("#tool-search");
  const clearBtn = $("#tool-search-clear");
  const noTools = $("#no-tools");
  const buttons = Array.from(document.querySelectorAll(".tabs button"));
  // Build the (tab, label, keywords) list once from the DOM + alias table.
  const tools = buttons.map((b) => ({
    tab: b.dataset.tab,
    label: b.textContent.trim(),
    keywords: (TOOL_ALIASES && TOOL_ALIASES[b.dataset.tab]) || "",
  }));

  function applyFilter() {
    const q = search.value;
    const matches = new Set(filterTools(q, tools));
    buttons.forEach((b) => b.classList.toggle("hidden", !matches.has(b.dataset.tab)));
    updateNavGroupLabels(matches);
    noTools.classList.toggle("hidden", matches.size > 0);
    clearBtn.hidden = q.trim() === "";
  }

  search.addEventListener("input", applyFilter);
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = buttons.find((b) => !b.classList.contains("hidden"));
      if (first) first.click();
    } else if (e.key === "Escape") {
      search.value = "";
      applyFilter();
    }
  });
  clearBtn.addEventListener("click", () => {
    search.value = "";
    applyFilter();
    search.focus();
  });
  // Ctrl/Cmd+K focuses and selects the search box from anywhere.
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      search.focus();
      search.select();
    }
  });
})();

// --- Keyboard shortcuts: run the active tab, cycle between (visible) tabs ---
// Ctrl/Cmd+Enter runs the active tab's primary action; Ctrl/Cmd+]/[ (or ./,)
// step to the next/previous tab that the search filter currently shows.
(function () {
  function visibleTabIds() {
    return Array.from(document.querySelectorAll(".tabs button"))
      .filter((b) => !b.classList.contains("hidden"))
      .map((b) => b.dataset.tab);
  }
  document.addEventListener("keydown", (e) => {
    const action = keyboardAction(e);
    if (!action) return;
    if (action.type === "run") {
      const btn = document.getElementById("run-" + currentTab());
      if (btn && !btn.disabled) {
        e.preventDefault();
        btn.click();
      }
      return;
    }
    if (action.type === "switch") {
      const next = nextVisibleTab(visibleTabIds(), currentTab(), action.dir);
      const btn = next && document.querySelector('.tabs button[data-tab="' + next + '"]');
      if (btn) {
        e.preventDefault();
        btn.click();
      }
    }
  });
})();

// --- Source card: auto-preview + friendly probe summary for the active input ---
// The primary input path for the current tab (concat/stacks read their first slot).
function activeInputPath() {
  const tab = currentTab();
  if (tab === "concat") return parseLines($("#concat-inputs").value)[0] || "";
  if (tab === "hstack" || tab === "vstack") return val(tab + "-input-a");
  const el = $("#" + tab + "-input");
  return el ? el.value.trim() : "";
}

let sourceUrl = null;
let lastSourcePath = null;
let sourceDims = null; // {w,h} of the active input's video, for the "Match source" preset
let lastSourceDuration = null; // probed source duration (s), for the output estimate

function hideSource() {
  lastSourcePath = null;
  sourceDims = null;
  refreshDimPresets(); // drop the "Match source" chip once there's no source
  lastSourceDuration = null;
  refreshEstimate();
  $("#source").classList.add("hidden");
  const img = $("#source-img");
  const vid = $("#source-video");
  vid.pause();
  img.classList.add("hidden");
  vid.classList.add("hidden");
  img.removeAttribute("src");
  vid.removeAttribute("src");
  $("#source-actions").classList.add("hidden");
  $("#crop-overlay").classList.add("hidden");
  $("#crop-rect").classList.add("hidden");
  if (sourceUrl) {
    URL.revokeObjectURL(sourceUrl);
    sourceUrl = null;
  }
}

// "Set from playhead" buttons: read the source <video> currentTime into the
// active tab's time field(s). Shown only when the tab has time fields and a
// video preview is loaded.
function renderSourceActions() {
  const box = $("#source-actions");
  box.textContent = "";
  const vid = $("#source-video");
  const targets = timeTargetsForTab(currentTab());
  const hasVideo = !vid.classList.contains("hidden") && vid.getAttribute("src");
  if (!targets.length || !hasVideo) {
    box.classList.add("hidden");
    return;
  }
  const label = document.createElement("span");
  label.className = "sa-label";
  label.textContent = "Set from playhead:";
  box.appendChild(label);
  for (const t of targets) {
    const btn = document.createElement("button");
    btn.className = "secondary sa-btn";
    btn.textContent = "→ " + t.label;
    btn.addEventListener("click", () => {
      const tc = formatTimecode(vid.currentTime);
      const field = $("#" + t.id);
      if (field) field.value = tc;
      setStatus(`Set ${t.label} to ${tc} (from preview).`);
    });
    box.appendChild(btn);
  }
  box.classList.remove("hidden");
}

async function showSourceMedia(path) {
  const { kind } = previewKind(path); // input is a real file, no %d to resolve
  const img = $("#source-img");
  const vid = $("#source-video");
  if (!kind) {
    img.classList.add("hidden");
    vid.classList.add("hidden");
    return;
  }
  try {
    const res = await fetch(baseUrl + "/file?path=" + encodeURIComponent(path), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const blob = await res.blob();
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = URL.createObjectURL(blob);
    if (kind === "image") {
      img.src = sourceUrl;
      img.classList.remove("hidden");
      vid.classList.add("hidden");
    } else {
      vid.src = sourceUrl;
      vid.classList.remove("hidden");
      img.classList.add("hidden");
    }
  } catch (_) {
    /* preview is best-effort */
  }
}

function renderChips(chips, actions = {}) {
  const box = $("#source-chips");
  box.textContent = "";
  if (!chips.length) {
    const msg = document.createElement("span");
    msg.className = "chips-msg";
    msg.textContent = "Couldn't read media info for this file.";
    box.appendChild(msg);
    return;
  }
  for (const { label, value } of chips) {
    const chip = document.createElement("div");
    chip.className = "chip";
    const l = document.createElement("span");
    l.className = "chip-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "chip-value";
    v.textContent = value;
    chip.append(l, v);

    const targets = actions[label];
    if (targets && targets.length) {
      chip.classList.add("clickable");
      chip.title = `Use source ${label.toLowerCase()} →  ` +
        targets.map((t) => fieldLabel(t.id)).join(", ");
      chip.addEventListener("click", () => {
        for (const { id, value: v2 } of targets) {
          const field = $("#" + id);
          if (field) field.value = v2;
        }
        const names = targets.map((t) => fieldLabel(t.id)).join(" & ");
        setStatus(`Filled ${names} from source ${label.toLowerCase()}.`);
        renderCropOverlay(); // reflect a Size-chip fill in the crop marquee
        refreshDimWarning(); // a filled source size could itself be odd
      });
    }
    box.appendChild(chip);
  }
}

async function refreshSource() {
  const path = activeInputPath();
  if (!path) return hideSource();
  if (path === lastSourcePath) { renderSourceActions(); renderCropOverlay(); return refreshEstimate(); } // re-target for this tab
  lastSourcePath = path;
  $("#source").classList.remove("hidden");
  renderChips([]); // clear stale chips while loading
  await showSourceMedia(path);
  renderSourceActions();
  renderCropOverlay();
  try {
    const { result } = await api("/probe", { input: path, as_json: true });
    if (path !== lastSourcePath) return; // a newer input superseded this one
    const data = typeof result === "string" ? JSON.parse(result) : result;
    renderChips(summarizeProbe(data), sourceFillActions(currentTab(), data));
    sourceDims = videoDims(data); // feeds the "Match source" frame-size preset
    refreshDimPresets();
    lastSourceDuration = Number((data.format || {}).duration) || null;
    refreshEstimate();
  } catch (_) {
    renderChips([]); // shows the soft "couldn't read" message
    sourceDims = null;
    refreshDimPresets();
    lastSourceDuration = null;
    refreshEstimate();
  }
}

// --- Estimated-output readout (predicted duration/size from current settings) ---
// The estimate-relevant fields per tab (only tabs whose output is predictable).
function estimateFields(tab) {
  const v = (id) => { const el = $("#" + id); return el ? el.value.trim() : ""; };
  if (tab === "trim") return { start: v("trim-start"), end: v("trim-end"), duration: v("trim-duration") };
  if (tab === "speed") return { factor: v("speed-factor") };
  if (tab === "loop") return { count: v("loop-count") };
  if (tab === "boomerang") return {};
  if (tab === "compress") return { bitrate: v("compress-bitrate"), target: v("compress-target"), crf: v("compress-crf") };
  return null;
}

function refreshEstimate() {
  const el = $("#estimate");
  if (!el) return;
  const fields = estimateFields(currentTab());
  const text = fields ? estimateOutput(currentTab(), lastSourceDuration, fields) : null;
  if (!text) {
    el.classList.add("hidden");
    return;
  }
  el.innerHTML = "Estimated output: ";
  const b = document.createElement("b");
  b.textContent = text;
  el.appendChild(b);
  el.classList.remove("hidden");
}

// Live-update the estimate as the user edits the relevant option fields.
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (!id) return;
  if (/^(trim-(start|end|duration)|speed-factor|loop-count|compress-(bitrate|target|crf))$/.test(id)) {
    refreshEstimate();
  }
});

// --- Multi-input compatibility banner (hstack/vstack/concat) ---
function multiInputPaths(tab) {
  if (tab === "concat") return parseLines($("#concat-inputs").value);
  if (tab === "hstack" || tab === "vstack") {
    return [val(tab + "-input-a"), val(tab + "-input-b")].filter(Boolean);
  }
  return [];
}

async function probeDims(path) {
  try {
    const { result } = await api("/probe", { input: path, as_json: true });
    const data = typeof result === "string" ? JSON.parse(result) : result;
    return videoDims(data);
  } catch (_) {
    return null;
  }
}

let lastCompatKey = null;
async function refreshCompat() {
  const tab = currentTab();
  const el = $("#compat");
  const paths = multiInputPaths(tab);
  const key = tab + "|" + paths.join("|");
  if (paths.length < 2) {
    el.classList.add("hidden");
    lastCompatKey = null;
    return;
  }
  if (key === lastCompatKey) return; // same inputs already reported
  lastCompatKey = key;
  const dimsList = await Promise.all(paths.map(probeDims));
  if (key !== lastCompatKey) return; // a newer set of inputs superseded this run
  const report = compatReport(tab, dimsList);
  if (!report) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = (report.ok ? "✓ " : "⚠ ") + report.message;
  el.className = "compat " + (report.ok ? "ok" : "warn");
}

// --- Dimension presets: one-click frame sizes for the active tab's W/H fields ---
// Shown only on tabs that have both a width and height field (crop/pad/blur_pad/
// compress/waveform). Each chip fills both fields; ratio chips derive the height
// from the current width, and "Match source" appears once the input is probed.
function refreshDimPresets() {
  const box = $("#dim-presets");
  const tab = currentTab();
  const fields = DIMENSION_FIELDS[tab];
  box.textContent = "";
  if (!fields || !fields.h) {
    box.classList.add("hidden");
    return;
  }
  const label = document.createElement("span");
  label.className = "dim-presets-label";
  label.textContent = "Frame size";
  box.appendChild(label);
  for (const preset of DIMENSION_PRESETS) {
    if (preset.match && !sourceDims) continue; // "Match source" needs probed dims
    const btn = document.createElement("button");
    btn.className = "secondary dim-chip";
    btn.textContent = preset.label;
    btn.title = preset.match
      ? "Fill width & height from the source"
      : `Set width & height to ${preset.label}`;
    btn.addEventListener("click", () => {
      const dims = presetDimensions(preset, {
        width: Number($("#" + fields.w).value) || null,
        sourceWidth: sourceDims ? sourceDims.w : null,
        sourceHeight: sourceDims ? sourceDims.h : null,
      });
      if (!dims) {
        setStatus("Load a source first to match its size.", true);
        return;
      }
      $("#" + fields.w).value = dims.width;
      $("#" + fields.h).value = dims.height;
      setStatus(`Set frame size to ${dims.width}×${dims.height} (${preset.label}).`);
      renderCropOverlay(); // reflect a frame-size preset in the crop marquee
      refreshDimWarning(); // presets are even, but clear any stale warning
    });
    box.appendChild(btn);
  }
  box.classList.remove("hidden");
}

// --- Even-dimension warning: flag an odd typed W/H before the x264 encode fails ---
// Read the active tab's width/height field values for the pure check.
function dimWarnFields(tab) {
  const dim = DIMENSION_FIELDS[tab] || {};
  const out = {};
  for (const key of ["w", "h"]) {
    const id = dim[key];
    if (!id) continue;
    const el = $("#" + id);
    if (el) out[id] = el.value;
  }
  return out;
}

// Show/hide the warning for the active tab from its current W/H field values.
function refreshDimWarning() {
  const el = $("#dim-warn");
  if (!el) return;
  const tab = currentTab();
  const msg = oddDimensionWarning(tab, dimWarnFields(tab));
  if (msg) {
    el.textContent = "⚠ " + msg;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

// Live-update the warning as the user edits any tab's width/height field.
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (id && /-(width|height)$/.test(id)) refreshDimWarning();
});

// Refresh both the source card and the multi-input compatibility banner.
function refreshInputs() {
  refreshSource();
  refreshCompat();
  maybeFillOutput(currentTab()); // auto-suggest an output path when one isn't set yet
  refreshDimWarning(); // flag odd W/H on size-sensitive tabs
}

// Fill an empty output field from the chosen input + the tab's op suffix, so
// "output required" stops being a manual step. Never clobbers a user-set output.
function maybeFillOutput(tab) {
  const outEl = document.getElementById(tab + "-output");
  if (!outEl || outEl.value.trim() !== "") return;
  const suggestion = suggestOutputForTab(activeInputPath(), tab);
  if (suggestion) outEl.value = suggestion;
}

// --- Visual crop selector: drag a rectangle over the source frame (Crop tab) ---
// The selection lives on the shared source preview; on the Crop tab an overlay
// captures a drag and fills crop-x/y/width/height (scaled up to source pixels).

// The currently visible source media element (image or video), or null.
function visibleSourceMedia() {
  const vid = $("#source-video");
  const img = $("#source-img");
  if (!vid.classList.contains("hidden") && vid.getAttribute("src")) return vid;
  if (!img.classList.contains("hidden") && img.getAttribute("src")) return img;
  return null;
}

// Intrinsic (source) pixel size of a media element, or null until it's known.
function mediaSourceSize(el) {
  if (!el) return null;
  const w = el.tagName === "VIDEO" ? el.videoWidth : el.naturalWidth;
  const h = el.tagName === "VIDEO" ? el.videoHeight : el.naturalHeight;
  return w > 0 && h > 0 ? { width: w, height: h } : null;
}

function positionCropRect(rectEl, r) {
  rectEl.style.left = r.left + "px";
  rectEl.style.top = r.top + "px";
  rectEl.style.width = r.width + "px";
  rectEl.style.height = r.height + "px";
  rectEl.classList.remove("hidden");
}

// Project the current crop-x/y/width/height fields back onto the overlay as a
// marquee, so the box reflects what's typed or filled from a chip/preset.
function drawCropRectFromFields() {
  const rectEl = $("#crop-rect");
  const el = visibleSourceMedia();
  const source = mediaSourceSize(el);
  if (!el || !source) { rectEl.classList.add("hidden"); return; }
  const box = el.getBoundingClientRect();
  const crop = {
    x: numOrNull("crop-x") || 0,
    y: numOrNull("crop-y") || 0,
    width: numOrNull("crop-width"),
    height: numOrNull("crop-height"),
  };
  const r = cropToRect(crop, { width: box.width, height: box.height }, source);
  if (!r) { rectEl.classList.add("hidden"); return; }
  positionCropRect(rectEl, r);
}

// Show the crop overlay (Crop tab + a loaded media with known source size) and
// draw the marquee from the current crop fields; hidden everywhere else so it
// never blocks the video controls on other tabs.
function renderCropOverlay() {
  const overlay = $("#crop-overlay");
  const rectEl = $("#crop-rect");
  const source = mediaSourceSize(visibleSourceMedia());
  if (currentTab() !== "crop" || !source) {
    overlay.classList.add("hidden");
    rectEl.classList.add("hidden");
    return;
  }
  overlay.classList.remove("hidden");
  drawCropRectFromFields();
}

(function setupCropDrag() {
  const overlay = $("#crop-overlay");
  const rectEl = $("#crop-rect");
  let dragging = false, startPt = null, originRect = null, sourceSize = null;

  function localPoint(e) {
    return clampPoint(
      { x: e.clientX - originRect.left, y: e.clientY - originRect.top },
      { width: originRect.width, height: originRect.height }
    );
  }

  overlay.addEventListener("pointerdown", (e) => {
    const el = visibleSourceMedia();
    sourceSize = mediaSourceSize(el);
    if (!el || !sourceSize) return;
    originRect = el.getBoundingClientRect();
    dragging = true;
    try { overlay.setPointerCapture(e.pointerId); } catch (_) {}
    startPt = localPoint(e);
    positionCropRect(rectEl, { left: startPt.x, top: startPt.y, width: 0, height: 0 });
    e.preventDefault();
  });

  overlay.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    positionCropRect(rectEl, normalizeDragRect(startPt, localPoint(e)));
  });

  function finishDrag(e) {
    if (!dragging) return;
    dragging = false;
    try { overlay.releasePointerCapture(e.pointerId); } catch (_) {}
    const rect = normalizeDragRect(startPt, localPoint(e));
    const crop = rectToCrop(rect, { width: originRect.width, height: originRect.height }, sourceSize);
    if (!crop) { drawCropRectFromFields(); return; } // tiny / edge click → restore
    $("#crop-x").value = crop.x;
    $("#crop-y").value = crop.y;
    $("#crop-width").value = crop.width;
    $("#crop-height").value = crop.height;
    setStatus(`Crop set to ${crop.width}×${crop.height} at (${crop.x}, ${crop.y}) from the preview.`);
    drawCropRectFromFields(); // snap the marquee to the even-rounded result
  }
  overlay.addEventListener("pointerup", finishDrag);
  overlay.addEventListener("pointercancel", finishDrag);
})();

// Keep the marquee in sync when the crop fields are edited or filled by chip/preset.
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (id && /^crop-(x|y|width|height)$/.test(id)) drawCropRectFromFields();
});
// The source <video>/<img> only knows its intrinsic size once metadata loads.
$("#source-video").addEventListener("loadedmetadata", renderCropOverlay);
$("#source-img").addEventListener("load", renderCropOverlay);

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
      refreshInputs();
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
    refreshInputs();
  });
});

// Typed/edited input paths refresh the source card + compat banner (blur/Enter).
document.addEventListener("change", (e) => {
  const id = e.target && e.target.id;
  if (!id) return;
  if (id.endsWith("-input") || id.endsWith("-input-a") || id.endsWith("-input-b") || id === "concat-inputs") {
    refreshInputs();
  }
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
  "image_to_video-seconds", "image_to_video-fps",
  "autocrop-limit",
];

async function loadSettings() {
  try {
    const s = (await getSettings()) || {};
    for (const id of STICKY) {
      const el = $("#" + id);
      if (el && s[id] != null && s[id] !== "") el.value = s[id];
    }
    presetsData = s.presets && typeof s.presets === "object" ? s.presets : {};
    if (s.activeTab) {
      const tb = document.querySelector('.tabs button[data-tab="' + s.activeTab + '"]');
      if (tb && !tb.classList.contains("active")) tb.click(); // restore last tab
    }
    refreshPresetSelect();
    refreshDimPresets();
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

let presetsData = {}; // { [tab]: { [name]: { fieldId: value } } }, persisted
loadSettings();

// --- Presets: save/load named option-field profiles per tool ---

// The option fields for a tab (everything in its panel except file-path inputs).
function presetFieldEls(tab) {
  const panel = $("#panel-" + tab);
  if (!panel) return [];
  return Array.from(panel.querySelectorAll("input, select, textarea"))
    .filter((el) => el.id && !isPathFieldId(el.id));
}
function collectOptionValues(tab) {
  const out = {};
  for (const el of presetFieldEls(tab)) {
    out[el.id] = el.type === "checkbox" ? el.checked : el.value;
  }
  return out;
}
function applyOptionValues(tab, values) {
  for (const el of presetFieldEls(tab)) {
    if (!Object.prototype.hasOwnProperty.call(values, el.id)) continue;
    if (el.type === "checkbox") el.checked = !!values[el.id];
    else el.value = values[el.id];
  }
}

// Rebuild the dropdown to list the active tab's presets.
function refreshPresetSelect() {
  const sel = $("#preset-select");
  if (!sel) return;
  const names = presetNames(presetsData, currentTab());
  sel.innerHTML = '<option value="">— saved —</option>' +
    names.map((n) => `<option>${n.replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))}</option>`).join("");
}

async function persistPresets() {
  try { await setSettings({ presets: presetsData }); } catch (_) { /* non-fatal */ }
}

$("#preset-save").addEventListener("click", async () => {
  const tab = currentTab();
  const name = val("preset-name") || $("#preset-select").value;
  if (!name) { setStatus("Enter a preset name to save.", true); return; }
  presetsData = withPreset(presetsData, tab, name, collectOptionValues(tab));
  await persistPresets();
  refreshPresetSelect();
  $("#preset-select").value = name;
  $("#preset-name").value = "";
  setStatus(`Saved preset "${name}".`);
});

$("#preset-load").addEventListener("click", () => {
  const tab = currentTab();
  const name = $("#preset-select").value;
  const values = name ? getPreset(presetsData, tab, name) : null;
  if (!values) { setStatus("Pick a saved preset to load.", true); return; }
  applyOptionValues(tab, values);
  setStatus(`Loaded preset "${name}".`);
});

$("#preset-delete").addEventListener("click", async () => {
  const tab = currentTab();
  const name = $("#preset-select").value;
  if (!name) { setStatus("Pick a saved preset to delete.", true); return; }
  presetsData = withoutPreset(presetsData, tab, name);
  await persistPresets();
  refreshPresetSelect();
  setStatus(`Deleted preset "${name}".`);
});

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

// --- Before/after result summary (size + duration once an op completes) ---
function hideSummary() {
  const el = $("#summary");
  if (el) {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

// Probe parsed ffprobe data for a path, or null on any failure (best-effort).
async function probeJson(path) {
  try {
    const { result } = await api("/probe", { input: path, as_json: true });
    return typeof result === "string" ? JSON.parse(result) : result;
  } catch (_) {
    return null;
  }
}

// After a completed op, show how the output compares to the input: a size delta
// (and a duration delta when the duration changed). Best-effort — a failed probe
// on either side just hides the line.
async function showSummary(inputPath, outputPath) {
  const el = $("#summary");
  if (!el || !outputPath) return;
  const [before, after] = await Promise.all([
    inputPath ? probeJson(inputPath) : Promise.resolve(null),
    probeJson(previewPath(outputPath)), // %d -> first frame for sequences
  ]);
  const text = summarizeBeforeAfter(before, after);
  if (text) {
    el.textContent = text;
    el.classList.remove("hidden");
  } else {
    hideSummary();
  }
}

// --- "Copy as CLI": show the equivalent ffmpeg-util command for the running op ---
// Reconstructed from the op + request body, so the user can reproduce/script it.
let lastCliCommand = "";
function showCliCommand(op, body) {
  lastCliCommand = buildCliCommand(op, body);
  $("#cli-command").textContent = lastCliCommand;
  $("#cli-command-row").classList.remove("hidden");
}
async function copyCliCommand() {
  const btn = $("#copy-cli");
  try {
    await navigator.clipboard.writeText(lastCliCommand);
    btn.textContent = "Copied!";
  } catch (_) {
    // Clipboard blocked (e.g. offscreen) — fall back to selecting the text so the
    // user can copy manually.
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents($("#cli-command"));
    sel.removeAllRanges();
    sel.addRange(range);
    btn.textContent = "Selected — ⌘/Ctrl+C";
  }
  setTimeout(() => (btn.textContent = "Copy as CLI"), 1500);
}
$("#copy-cli").addEventListener("click", copyCliCommand);

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

// True while an op is streaming, so a second click can't fire the same op twice
// against the same output. Every run button is disabled for the duration.
let opInFlight = false;
let currentAbort = null; // AbortController for the in-flight /run/stream fetch
function setRunButtonsDisabled(disabled) {
  document.querySelectorAll('[id^="run-"]').forEach((b) => (b.disabled = disabled));
}
function setCancelVisible(show) {
  $("#run-actions").classList.toggle("hidden", !show);
}

// Cancel the running op: aborting the stream disconnects the client, which makes
// the sidecar stop consuming progress and kill the ffmpeg process (see
// FfmpegRunner.iter_ffmpeg_progress's finally).
function cancelOp() {
  if (currentAbort) currentAbort.abort();
}

// Ask the sidecar whether the output already exists; if so, confirm before we
// clobber it. Best-effort: a failed check never blocks the run.
async function confirmOverwrite(output) {
  if (!output) return true;
  try {
    const res = await fetch(baseUrl + "/exists?path=" + encodeURIComponent(output), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return true;
    const { exists } = await res.json();
    if (!exists) return true;
    return window.confirm(overwriteMessage(output));
  } catch (_) {
    return true;
  }
}

async function run(label, op, body) {
  if (opInFlight) return; // an op is already running — ignore the extra click
  if (!(await confirmOverwrite(body.output))) {
    setStatus("Cancelled — existing file left in place.");
    return;
  }
  opInFlight = true;
  const abort = new AbortController();
  currentAbort = abort;
  setRunButtonsDisabled(true);
  setCancelVisible(true);
  setStatus(label + "…");
  clearErrorHint();
  hideSummary();
  showCliCommand(op, body); // surface the equivalent ffmpeg-util command
  showProgress(0);
  hidePreview();
  try {
    const res = await fetch(baseUrl + "/run/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ op, ...body }),
      signal: abort.signal,
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
    if (result && result.output) {
      showPreview(result.output);
      // Compare the output back to the primary input (single-input ops, else first).
      showSummary(body.input || (body.inputs && body.inputs[0]) || null, result.output);
    }
  } catch (e) {
    hideProgress();
    if (abort.signal.aborted) {
      setStatus("Cancelled — operation stopped.");
    } else {
      showErrorHint(e.message); // friendly one-liner above the raw stderr
      setStatus("Error: " + e.message, true);
    }
  } finally {
    opInFlight = false;
    currentAbort = null;
    setCancelVisible(false);
    setRunButtonsDisabled(false);
  }
}

$("#cancel-op").addEventListener("click", cancelOp);

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

$("#run-invert").addEventListener("click", () => {
  if (!requireFields("invert-input", "invert-output")) return;
  run("Inverting colors", "invert", {
    input: val("invert-input"),
    output: val("invert-output"),
    overwrite: true,
  });
});

$("#run-blur_pad").addEventListener("click", () => {
  if (!requireFields("blur_pad-input", "blur_pad-output", "blur_pad-width", "blur_pad-height")) return;
  run("Blur padding", "blur_pad", {
    input: val("blur_pad-input"),
    output: val("blur_pad-output"),
    width: numOrNull("blur_pad-width"),
    height: numOrNull("blur_pad-height"),
    sigma: numOrNull("blur_pad-sigma") != null ? numOrNull("blur_pad-sigma") : 20,
    overwrite: true,
  });
});

$("#run-image_to_video").addEventListener("click", () => {
  if (!requireFields("image_to_video-input", "image_to_video-output", "image_to_video-seconds")) return;
  run("Making video", "image_to_video", {
    input: val("image_to_video-input"),
    output: val("image_to_video-output"),
    seconds: numOrNull("image_to_video-seconds"),
    fps: numOrNull("image_to_video-fps") || 30,
    overwrite: true,
  });
});

$("#run-vstack").addEventListener("click", () => {
  if (!requireFields("vstack-input-a", "vstack-input-b", "vstack-output")) return;
  run("Stacking vertically", "vstack", {
    inputs: [val("vstack-input-a"), val("vstack-input-b")],
    output: val("vstack-output"),
    overwrite: true,
  });
});

$("#run-hstack").addEventListener("click", () => {
  if (!requireFields("hstack-input-a", "hstack-input-b", "hstack-output")) return;
  run("Combining side by side", "hstack", {
    inputs: [val("hstack-input-a"), val("hstack-input-b")],
    output: val("hstack-output"),
    overwrite: true,
  });
});

$("#run-sample_rate").addEventListener("click", () => {
  if (!requireFields("sample_rate-input", "sample_rate-output")) return;
  run("Resampling audio", "sample_rate", {
    input: val("sample_rate-input"),
    output: val("sample_rate-output"),
    rate: Number($("#sample_rate-rate").value),
    overwrite: true,
  });
});

$("#run-waveform").addEventListener("click", () => {
  if (!requireFields("waveform-input", "waveform-output")) return;
  run("Rendering waveform", "waveform", {
    input: val("waveform-input"),
    output: val("waveform-output"),
    width: numOrNull("waveform-width") || 1000,
    height: numOrNull("waveform-height") || 200,
    overwrite: true,
  });
});

$("#run-crop_aspect").addEventListener("click", () => {
  if (!requireFields("crop_aspect-input", "crop_aspect-output")) return;
  run("Cropping to aspect", "crop_aspect", {
    input: val("crop_aspect-input"),
    output: val("crop_aspect-output"),
    aspect: $("#crop_aspect-aspect").value,
    overwrite: true,
  });
});

$("#run-fps").addEventListener("click", () => {
  if (!requireFields("fps-input", "fps-output", "fps-fps")) return;
  run("Resampling FPS", "fps", {
    input: val("fps-input"),
    output: val("fps-output"),
    fps: numOrNull("fps-fps"),
    overwrite: true,
  });
});

$("#run-eq").addEventListener("click", () => {
  if (!requireFields("eq-input", "eq-output")) return;
  const b = numOrNull("eq-brightness");
  const c = numOrNull("eq-contrast");
  const s = numOrNull("eq-saturation");
  run("Adjusting", "eq", {
    input: val("eq-input"),
    output: val("eq-output"),
    brightness: b != null ? b : 0,
    contrast: c != null ? c : 1,
    saturation: s != null ? s : 1,
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

$("#run-title").addEventListener("click", () => {
  if (!requireFields("title-input", "title-output")) return;
  run("Setting title", "title", {
    input: val("title-input"),
    output: val("title-output"),
    title: val("title-title"),
    overwrite: true,
  });
});

$("#run-mono").addEventListener("click", () => {
  if (!requireFields("mono-input", "mono-output")) return;
  run("Downmixing to mono", "mono", {
    input: val("mono-input"),
    output: val("mono-output"),
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

$("#run-replace_audio").addEventListener("click", () => {
  if (!requireFields("replace_audio-input", "replace_audio-audio", "replace_audio-output")) return;
  run("Replacing audio", "replace_audio", {
    input: val("replace_audio-input"),
    audio: val("replace_audio-audio"),
    output: val("replace_audio-output"),
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

$("#run-autocrop").addEventListener("click", () => {
  if (!requireFields("autocrop-input", "autocrop-output")) return;
  const limit = numOrNull("autocrop-limit");
  run("Auto-cropping", "autocrop", {
    input: val("autocrop-input"),
    output: val("autocrop-output"),
    limit: limit != null ? limit : 24,
    overwrite: true,
  });
});
