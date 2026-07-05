// Renderer: thin client over the sidecar HTTP API exposed via window.sidecar.
// Pure helpers live in logic.js (window.FfuLogic) and are unit-tested separately.
const { baseUrl, token, pickFile, pickFiles, saveFile, getSettings, setSettings, getPathForFile, notify } =
  window.sidecar;
const { suggestOutputForTab, defaultSavePath, parseLines, fieldLabel, parseSseBuffer, sseIncompleteError, dropUpdate, previewKind,
  filterTools, TOOL_ALIASES, summarizeProbe, sourceFillActions,
  DIMENSION_FIELDS, DIMENSION_PRESETS, presetDimensions,
  videoDims, compatReport, formatTimecode, timeTargetsForTab, timeHandlesForTab, timecodeFraction,
  clampPoint, normalizeDragRect, rectToCrop, cropToRect,
  overwriteMessage, isPathFieldId, presetNames, getPreset, withPreset,
  withoutPreset, estimateOutput, compressSizeEstimateLabel, oddDimensionWarning, friendlyError, summarizeBeforeAfter,
  buildCliCommand, previewPath, keyboardAction, nextVisibleTab,
  TOOL_CATEGORIES, groupTabs, templatedOutputForTab,
  groupTabsWithFavorites, toggleFavorite, isFavorite, normalizeFavorites,
  addRecentFile, recentFileLabel, recentDir, setRecentOutput, recentOutputDir, reorderList,
  resolveTheme, nextTheme, themeToggleLabel, helpForTab, etaLabel,
  appendConsoleLines, SLIDER_SPECS, formatSliderOut,
  revealLabel, outputBaseName,
  runInputEntries, runOutputDirEntry,
  fieldTooltip, notifyComplete,
  FIELD_VALIDATORS, validateField, tabFieldValidatorIds,
  shouldShowCompare, compareSliderPercent, compareClipInset, compareDividerPos,
  COMPRESS_QUICK_PRESETS, compressQuickPreset,
  ASPECT_RATIO_PRESETS, aspectRatioPreset,
  SHARPEN_QUICK_PRESETS, sharpenQuickPreset,
  DENOISE_QUICK_PRESETS, denoiseQuickPreset,
  addJobRecord, jobHistoryLabel, chainTabOptions,
  addQueueItem, removeQueueItem, updateQueueItem, nextQueuedItem, queueItemLabel,
  batchFilePairs } = window.FfuLogic;
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
    updateTabHelp(tab); // one-line "what it does + example" for the new tab
    setSettings({ activeTab: tab }).catch(() => {}); // remember across launches
  });
});

function currentTab() {
  const btn = document.querySelector(".tabs button.active");
  return btn ? btn.dataset.tab : "convert";
}

// Show the active tab's one-line help (from logic.js) above its panel; hide the
// line for any tab without help so an empty box never floats there.
function updateTabHelp(tab) {
  const el = $("#tab-help");
  if (!el) return;
  const text = helpForTab(tab);
  el.textContent = text;
  el.classList.toggle("hidden", !text);
}

// --- Light/dark theme toggle ---
// Dark is the default (the bare :root palette); "light" sets data-theme on <html>
// so styles.css swaps the palette variables. The choice is persisted in
// settings.json (shallow-merged, so it coexists with sticky fields / window bounds).
let currentTheme = "dark";

function applyTheme(theme) {
  currentTheme = resolveTheme(theme);
  // Dark = no attribute (default palette); light = data-theme="light".
  if (currentTheme === "dark") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", currentTheme);
  const btn = $("#theme-toggle");
  if (btn) btn.textContent = themeToggleLabel(currentTheme); // advertise the next theme
}

const themeToggleBtn = $("#theme-toggle");
if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    applyTheme(nextTheme(currentTheme));
    setSettings({ theme: currentTheme }).catch(() => {}); // sticky across launches
  });
}

// --- Completion notification toggle ---
// When enabled, a native desktop notification fires after each successful run.
// The setting is persisted in settings.json (shallow-merged with other keys).
let notifyEnabled = false;

const notifyToggle = $("#notify-toggle");
if (notifyToggle) {
  notifyToggle.addEventListener("change", () => {
    notifyEnabled = notifyToggle.checked;
    setSettings({ notify: notifyEnabled }).catch(() => {});
  });
}

// --- Collapsible cards: Source and Probe can be folded to reclaim vertical space ---
// The collapsed state persists in settings.json across launches.
let sourceBodyCollapsed = false;
let probeBodyCollapsed = false;

function applySourceCollapse(collapsed) {
  sourceBodyCollapsed = !!collapsed;
  const body = $("#source-card-body");
  const btn = $("#source-collapse");
  if (body) body.classList.toggle("collapsed", sourceBodyCollapsed);
  if (btn) {
    btn.textContent = sourceBodyCollapsed ? "▼" : "▲";
    btn.title = sourceBodyCollapsed ? "Expand source preview" : "Collapse source preview";
  }
}

function applyProbeCollapse(collapsed) {
  probeBodyCollapsed = !!collapsed;
  const body = $("#probe-card-body");
  const btn = $("#probe-collapse");
  if (body) body.classList.toggle("collapsed", probeBodyCollapsed);
  if (btn) {
    btn.textContent = probeBodyCollapsed ? "▼" : "▲";
    btn.title = probeBodyCollapsed ? "Expand probe output" : "Collapse probe output";
  }
}

(function setupCollapsibles() {
  const sb = $("#source-collapse");
  if (sb) sb.addEventListener("click", () => {
    applySourceCollapse(!sourceBodyCollapsed);
    setSettings({ sourceCollapsed: sourceBodyCollapsed }).catch(() => {});
  });
  const pb = $("#probe-collapse");
  if (pb) pb.addEventListener("click", () => {
    applyProbeCollapse(!probeBodyCollapsed);
    setSettings({ probeCollapsed: probeBodyCollapsed }).catch(() => {});
  });
  const cb = $("#console-collapse");
  if (cb) cb.addEventListener("click", () => {
    const out = $("#console-out");
    const collapsed = out.classList.toggle("collapsed");
    cb.textContent = collapsed ? "▼" : "▲";
    cb.title = collapsed ? "Expand console" : "Collapse console";
  });
})();

// Pinned tools (tab ids) shown in a leading "★ Favorites" row; persisted in
// settings.json. Populated from settings on load and updated by the star toggles.
let favoritesData = [];
let reapplyToolSearch = null; // set by setupToolSearch, lets a re-layout re-filter

// Lay the flat list of tab buttons out into labeled category rows so the ~30-tab
// nav scans in seconds. The order comes straight from the (unit-tested) data in
// logic.js: each label is a full-width divider that wraps the buttons after it
// onto their own rows. Pinned tabs lead in a "★ Favorites" row. Buttons are moved
// (not cloned), so the click/search/keyboard wiring queried elsewhere keeps
// working on the same nodes. Re-callable: existing labels are cleared first so a
// favorite toggle just re-runs this.
function layoutNavGroups() {
  const nav = document.querySelector(".tabs");
  if (!nav) return;
  nav.querySelectorAll(".tab-group-label").forEach((l) => l.remove());
  const byTab = new Map(
    Array.from(nav.querySelectorAll("button")).map((b) => [b.dataset.tab, b])
  );
  const groups = groupTabsWithFavorites(Array.from(byTab.keys()), favoritesData, TOOL_CATEGORIES);
  for (const g of groups) {
    const label = document.createElement("span");
    label.className = "tab-group-label";
    label.dataset.group = g.name;
    label.textContent = g.name;
    nav.appendChild(label);
    for (const tab of g.tabs) nav.appendChild(byTab.get(tab));
  }
}

// Hide a category label when search has filtered away every tool under it, so an
// empty heading never floats over a blank row. `visible` is the set of tab ids
// the search currently shows (favorites-aware so the Favorites label hides too).
function updateNavGroupLabels(visible) {
  const present = new Set(
    groupTabsWithFavorites(visible, favoritesData, TOOL_CATEGORIES).map((g) => g.name)
  );
  document.querySelectorAll(".tabs .tab-group-label").forEach((label) => {
    label.classList.toggle("hidden", !present.has(label.dataset.group));
  });
}

// --- Favorites: a ☆/★ pin toggle on each tab moves it to the top Favorites row ---
// Toggle a tab's pinned state, persist it, and re-lay-out the nav (re-applying the
// active search so hidden/labels stay correct).
function toggleFav(tab) {
  favoritesData = toggleFavorite(favoritesData, tab);
  setSettings({ favorites: favoritesData }).catch(() => {}); // sticky across launches
  layoutNavGroups();
  refreshFavoriteStars();
  if (reapplyToolSearch) reapplyToolSearch();
}

// Reflect the current favorites in each button's star glyph + state class.
function refreshFavoriteStars() {
  document.querySelectorAll(".tabs button").forEach((btn) => {
    const star = btn.querySelector(".fav-star");
    if (!star) return;
    const fav = isFavorite(favoritesData, btn.dataset.tab);
    star.textContent = fav ? "★" : "☆";
    star.title = fav ? "Unpin from favorites" : "Pin to favorites";
    btn.classList.toggle("favorited", fav);
  });
}

// Inject the pin toggle into each tab button once. Run after the tool-search setup
// so the search's captured labels don't include the star glyph.
function setupFavoriteStars() {
  document.querySelectorAll(".tabs button").forEach((btn) => {
    const star = document.createElement("span");
    star.className = "fav-star";
    star.setAttribute("role", "button");
    star.setAttribute("aria-label", "Pin tool to favorites");
    star.addEventListener("click", (e) => {
      e.stopPropagation(); // toggling the pin must not switch tabs
      toggleFav(btn.dataset.tab);
    });
    btn.insertBefore(star, btn.firstChild);
  });
  refreshFavoriteStars();
}

layoutNavGroups();

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
  reapplyToolSearch = applyFilter; // let a favorites re-layout re-run the filter

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

// Add the ☆ pin toggles after the search has captured each tab's clean label.
setupFavoriteStars();

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
  if (tab === "hstack" || tab === "vstack" || tab === "xfade_concat") return val(tab + "-input-a");
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
  updateTimelineBar(); // video is gone — hide the scrubber
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
    updateTimelineBar();
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
  updateTimelineBar();
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
    maybeRefillTemplatedOutput(); // {w}/{h}/{wxh} are only known once probed
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
  if (tab === "preview_clip") return { seconds: v("preview_clip-seconds") };
  if (tab === "trim_pct") return { "start-pct": v("trim_pct-start-pct"), "end-pct": v("trim_pct-end-pct") };
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
  if (/^(trim-(start|end|duration)|speed-factor|loop-count|compress-(bitrate|target|crf)|preview_clip-seconds|trim_pct-(start|end)-pct)$/.test(id)) {
    refreshEstimate();
  }
});

// --- Multi-input compatibility banner (hstack/vstack/concat) ---
function multiInputPaths(tab) {
  if (tab === "concat") return parseLines($("#concat-inputs").value);
  if (tab === "hstack" || tab === "vstack" || tab === "xfade_concat") {
    return [val(tab + "-input-a"), val(tab + "-input-b")].filter(Boolean);
  }
  if (tab === "pip") return [val("pip-input"), val("pip-overlay")].filter(Boolean);
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

// Live-update the warning as the user edits any tab's width/height field, and
// run inline validation for any field that has a registered FIELD_VALIDATORS entry.
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (id && /-(width|height)$/.test(id)) refreshDimWarning();
  if (id && FIELD_VALIDATORS[id]) refreshFieldValidation(e.target);
});

// Refresh both the source card and the multi-input compatibility banner.
function refreshInputs() {
  refreshSource();
  refreshCompat();
  maybeFillOutput(currentTab()); // auto-suggest an output path when one isn't set yet
  refreshDimWarning(); // flag odd W/H on size-sensitive tabs
  renderConcatList(); // draggable reorder rows mirroring the concat textarea
}

// --- Concat: drag-to-reorder rows ---
// The textarea (#concat-inputs) stays the canonical store; this list is a
// visual mirror of it. Dragging a row reorders the lines and writes them back,
// so every existing reader (run-concat, drop/append, compat banner) is unchanged.
let concatDragIndex = null;
let concatThumbUrls = [];

function revokeConcatThumbs() {
  concatThumbUrls.forEach((u) => URL.revokeObjectURL(u));
  concatThumbUrls = [];
}

// Fetches the file once (same auth'd blob pattern as the output preview) and
// paints it into the row's thumbnail slot. Best-effort: a failed fetch just
// leaves the placeholder empty, it never blocks reordering.
async function loadConcatThumb(el, path) {
  const { kind, path: resolved } = previewKind(path);
  if (!kind) return;
  try {
    const res = await fetch(baseUrl + "/file?path=" + encodeURIComponent(resolved), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    // The list may have re-rendered (or the row been dragged away) while this
    // fetch was in flight; a detached slot means our render is stale.
    if (!el.isConnected) {
      URL.revokeObjectURL(url);
      return;
    }
    concatThumbUrls.push(url);
    if (kind === "image") {
      const img = document.createElement("img");
      img.src = url;
      el.appendChild(img);
    } else {
      const vid = document.createElement("video");
      vid.src = url;
      vid.muted = true;
      vid.preload = "metadata";
      // Some renderers leave the frame blank until a seek is requested.
      vid.addEventListener("loadedmetadata", () => { vid.currentTime = 0; }, { once: true });
      el.appendChild(vid);
    }
  } catch (_) {
    // best-effort thumbnail; leave the placeholder empty on failure
  }
}

function renderConcatList() {
  const ul = $("#concat-list");
  if (!ul) return;
  const items = parseLines($("#concat-inputs").value);
  revokeConcatThumbs();
  ul.innerHTML = "";
  // Reordering only makes sense with two or more files.
  if (items.length < 2) {
    ul.classList.add("hidden");
    return;
  }
  ul.classList.remove("hidden");
  items.forEach((path, i) => {
    const li = document.createElement("li");
    li.className = "reorder-row";
    li.draggable = true;
    li.dataset.index = String(i);
    const handle = document.createElement("span");
    handle.className = "reorder-handle";
    handle.textContent = "⠿";
    const thumb = document.createElement("span");
    thumb.className = "reorder-thumb";
    const label = document.createElement("span");
    label.className = "reorder-name";
    label.textContent = `${i + 1}. ${recentFileLabel(path)}`;
    label.title = path; // full path on hover
    li.append(handle, thumb, label);
    ul.appendChild(li);
    loadConcatThumb(thumb, path);
  });
}

// Write a reordered path list back to the textarea and re-render everything.
function applyConcatOrder(items) {
  $("#concat-inputs").value = items.join("\n");
  refreshInputs();
}

(function setupConcatReorder() {
  const ul = $("#concat-list");
  if (!ul) return;
  const rowIndex = (el) => {
    const li = el && el.closest && el.closest(".reorder-row");
    return li ? Number(li.dataset.index) : null;
  };
  ul.addEventListener("dragstart", (e) => {
    concatDragIndex = rowIndex(e.target);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
    const li = e.target.closest && e.target.closest(".reorder-row");
    if (li) li.classList.add("dragging");
  });
  ul.addEventListener("dragover", (e) => {
    e.preventDefault(); // allow the drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    ul.querySelectorAll(".drop-target").forEach((el) => el.classList.remove("drop-target"));
    const li = e.target.closest && e.target.closest(".reorder-row");
    if (li) li.classList.add("drop-target");
  });
  ul.addEventListener("drop", (e) => {
    e.preventDefault();
    const to = rowIndex(e.target);
    const from = concatDragIndex;
    if (from === null || to === null || from === to) return;
    applyConcatOrder(reorderList(parseLines($("#concat-inputs").value), from, to));
  });
  ul.addEventListener("dragend", () => {
    concatDragIndex = null;
    ul.querySelectorAll(".dragging, .drop-target").forEach((el) =>
      el.classList.remove("dragging", "drop-target")
    );
  });
})();

// Today as YYYY-MM-DD, for the {date} name-template token.
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

// The current output-name template (empty -> use the fixed op-suffix default).
function nameTemplate() {
  const el = $("#output-template");
  return el ? el.value.trim() : "";
}

// Fill an empty output field from the chosen input — either a custom name
// template (tokens) when one is set, or the tab's fixed op suffix otherwise, so
// "output required" stops being a manual step. Never clobbers a user-set output;
// the value it sets is tagged data-auto so a template change can refresh it.
function maybeFillOutput(tab) {
  const outEl = document.getElementById(tab + "-output");
  if (!outEl) return;
  // Never clobber a user-typed path; only fill if empty or still auto-generated.
  if (outEl.value.trim() !== "" && !outEl.dataset.auto) return;
  const tmpl = nameTemplate();
  const suggestion = tmpl
    ? templatedOutputForTab(activeInputPath(), tab, tmpl, sourceDims, todayStr())
    : suggestOutputForTab(activeInputPath(), tab);
  if (suggestion) {
    outEl.value = suggestion;
    outEl.dataset.auto = "1";
  }
}

// Re-fill the active tab's output from the template once the probe resolves, so
// dimension tokens ({w}/{h}/{wxh}) — unknown when the input was first set — land.
// Only touches an empty or still-auto-filled output; never clobbers a user path.
function maybeRefillTemplatedOutput() {
  if (!nameTemplate()) return; // the fixed-suffix default doesn't use probed dims
  const tab = currentTab();
  const outEl = document.getElementById(tab + "-output");
  if (!outEl) return;
  if (outEl.value.trim() === "" || outEl.dataset.auto) {
    outEl.value = ""; // clear so maybeFillOutput regenerates with dims known
    maybeFillOutput(tab);
  }
}

// Editing an output field by hand clears the auto-fill tag so a later template
// change won't overwrite the user's path. (Programmatic .value = fires no event.)
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (id && /-output$/.test(id)) delete e.target.dataset.auto;
});

// Live-apply the name template: re-fill the active tab's output when it's empty
// or still auto-filled, and persist the template across launches.
document.addEventListener("input", (e) => {
  if (!e.target || e.target.id !== "output-template") return;
  const tab = currentTab();
  const outEl = document.getElementById(tab + "-output");
  if (outEl && (outEl.value.trim() === "" || outEl.dataset.auto)) {
    outEl.value = ""; // clear so maybeFillOutput regenerates from the template
    maybeFillOutput(tab);
  }
  saveSettings();
});

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

// --- Recent files: remember inputs the user loaded and offer them again ---
// A most-recent-first list (persisted in settings.json) drives the Recent
// dropdown and seeds the file picker's defaultPath with the last-used dir.
let recentData = [];

// --- Per-tab output history: remember the last output path used on each tab ---
// A dict of tab→path persisted in settings.json. On load, empty output fields
// are seeded from this history; the save dialog also defaults to the saved path.
let recentOutputData = {};

function refreshRecentSelect() {
  const sel = $("#recent-select");
  const box = $("#recent");
  if (!sel || !box) return;
  if (!recentData.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  const esc = (s) => s.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  sel.innerHTML = '<option value="">— recent files —</option>' +
    recentData.map((p) =>
      `<option value="${esc(p)}" title="${esc(p)}">${esc(recentFileLabel(p))}</option>`
    ).join("");
}

async function persistRecent() {
  try { await setSettings({ recentFiles: recentData }); } catch (_) { /* non-fatal */ }
}

// Record the output path used on a given tab and persist to settings.
async function recordRecentOutput(tab, path) {
  if (!tab || !path) return;
  recentOutputData = setRecentOutput(recentOutputData, tab, path);
  try { await setSettings({ recentOutputs: recentOutputData }); } catch (_) { /* non-fatal */ }
}

// Record a freshly-loaded input path. No-op when it's empty or already at the
// front, so a mere tab switch doesn't churn the list.
function recordRecent(path) {
  const next = addRecentFile(recentData, path);
  if (next.length === recentData.length && next.every((v, i) => v === recentData[i])) return;
  recentData = next;
  refreshRecentSelect();
  persistRecent();
}

// Picking a recent entry loads it into the active tab (same path as a drop).
$("#recent-select").addEventListener("change", (e) => {
  const p = e.target.value;
  e.target.value = ""; // snap back to the placeholder
  if (!p) return;
  const upd = dropUpdate([p], currentTab(), $("#concat-inputs").value);
  if (!upd) return;
  $("#" + upd.id).value = upd.value;
  recordRecent(p); // move it back to the front
  setStatus(`Loaded ${recentFileLabel(p)} into the ${currentTab()} tab.`);
  refreshInputs();
});

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
      // Record in reverse so the primary (first-dropped) file ends up front.
      [...paths].reverse().forEach(recordRecent);
      setStatus(`Loaded ${paths.length} file(s) into the ${currentTab()} tab.`);
      refreshInputs();
    }
  });
})();

// --- File pickers (declarative via data attributes) ---
document.querySelectorAll(".pick-file").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const p = await pickFile(recentDir(recentData)); // open in the last-used dir
    if (!p) return;
    if (btn.dataset.append) {
      const ta = $("#" + btn.dataset.append);
      ta.value = ta.value ? ta.value + "\n" + p : p;
    } else {
      $("#" + btn.dataset.target).value = p;
    }
    recordRecent(p);
    refreshInputs();
  });
});

// Typed/edited input paths refresh the source card + compat banner (blur/Enter).
document.addEventListener("change", (e) => {
  const id = e.target && e.target.id;
  if (!id) return;
  if (id.endsWith("-input") || id.endsWith("-input-a") || id.endsWith("-input-b") || id === "concat-inputs") {
    // A typed single-file path is recent-worthy; concat holds many, so skip it.
    if (id !== "concat-inputs") recordRecent(e.target.value.trim());
    refreshInputs();
  }
});

document.querySelectorAll(".pick-save").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const tab = currentTab();
    const lastOut = recentOutputData[tab] || "";
    const p = await saveFile(defaultSavePath(lastOut, activeInputPath(), tab));
    if (p) {
      const el = $("#" + btn.dataset.target);
      if (el) { el.value = p; delete el.dataset.auto; }
    }
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
  "concat-reencode",
  "trim-start",
  "thumbnail-time", "thumbnail-count", "thumbnail-width",
  "compress-crf", "compress-bitrate", "compress-width", "compress-height",
  "compress-vcodec", "compress-preset", "compress-hwaccel",
  "gif-fps", "gif-width", "gif-dither", "gif-loop",
  "image_to_video-seconds", "image_to_video-fps",
  "autocrop-limit",
  "output-template",
  "sharpen-amount",
  "denoise-strength",
  "stabilize-shakiness",
  "stabilize-smoothing",
  "timecode-font-size",
  "watermark-font-size",
  "watermark-opacity",
  "trim_silence-threshold",
  "trim_silence-min-duration",
  "blur_region-sigma",
  "poster_frame-percent",
  "trim_pct-start-pct",
  "trim_pct-end-pct",
  "pixfmt-pix-fmt",
];

async function loadSettings() {
  try {
    const s = (await getSettings()) || {};
    applyTheme(s.theme); // restore the saved light/dark choice (defaults to dark)
    if (s.notify != null && notifyToggle) {
      notifyEnabled = !!s.notify;
      notifyToggle.checked = notifyEnabled;
    }
    if (s.sourceCollapsed) applySourceCollapse(true);
    if (s.probeCollapsed) applyProbeCollapse(true);
    for (const id of STICKY) {
      const el = $("#" + id);
      if (el && s[id] != null && s[id] !== "") el.value = s[id];
    }
    presetsData = s.presets && typeof s.presets === "object" ? s.presets : {};
    recentData = Array.isArray(s.recentFiles) ? s.recentFiles.filter((x) => typeof x === "string" && x.trim()) : [];
    refreshRecentSelect();
    recentOutputData = s.recentOutputs && typeof s.recentOutputs === "object" ? s.recentOutputs : {};
    for (const [tab, path] of Object.entries(recentOutputData)) {
      const el = document.getElementById(tab + "-output");
      if (el && !el.value.trim()) {
        el.value = path; // restore only if still empty
        el.dataset.auto = "1"; // treat like an auto-fill so loading a new input can refresh it
      }
    }
    favoritesData = normalizeFavorites(s.favorites);
    layoutNavGroups(); // re-lay-out so pinned tools lead the nav
    refreshFavoriteStars();
    if (reapplyToolSearch) reapplyToolSearch();
    if (s.activeTab) {
      const tb = document.querySelector('.tabs button[data-tab="' + s.activeTab + '"]');
      if (tb && !tb.classList.contains("active")) tb.click(); // restore last tab
    }
    refreshPresetSelect();
    refreshDimPresets();
    jobHistoryData = Array.isArray(s.jobHistory)
      ? s.jobHistory.filter((r) => r && r.outputPath)
      : [];
    renderJobHistory();
    // Restore the queue; anything still "running" was interrupted by the last
    // shutdown, so it goes back to "queued" rather than being stuck forever.
    opQueueData = Array.isArray(s.opQueue)
      ? s.opQueue.map((it) => (it && it.status === "running" ? { ...it, status: "queued" } : it)).filter(Boolean)
      : [];
    renderQueue();
  } catch (_) {
    // first run / no store yet — ignore
  }
  updateTabHelp(currentTab()); // seed help for the default/restored tab
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
    .filter((el) => el.id && !isPathFieldId(el.id) && el.type !== "range");
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
  refreshSliders(); // sync range sliders to the restored number values
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

// --- Quick (factory) presets for Compress ---
// One click fills all compress option fields from a named factory preset.
document.getElementById("compress-quick-presets").addEventListener("click", (e) => {
  const btn = e.target.closest(".qp-chip");
  if (!btn) return;
  const values = compressQuickPreset(btn.dataset.qp);
  if (!values) return;
  applyOptionValues("compress", values);
  refreshSliders();
  setStatus(`Applied "${btn.dataset.qp}" preset.`);
});

// --- Aspect-ratio presets for Compress ---
// One click forces an exact width+height pair for a common target ratio.
document.getElementById("compress-aspect-presets").addEventListener("click", (e) => {
  const btn = e.target.closest(".qp-chip");
  if (!btn) return;
  const values = aspectRatioPreset(btn.dataset.ar);
  if (!values) return;
  applyOptionValues("compress", values);
  refreshSliders();
  setStatus(`Applied ${btn.dataset.ar} aspect ratio.`);
});

// --- Quick (factory) presets for Sharpen ---
document.getElementById("sharpen-quick-presets").addEventListener("click", (e) => {
  const btn = e.target.closest(".qp-chip");
  if (!btn) return;
  const values = sharpenQuickPreset(btn.dataset.qp);
  if (!values) return;
  applyOptionValues("sharpen", values);
  refreshSliders();
  setStatus(`Applied "${btn.dataset.qp}" preset.`);
});

// --- Quick (factory) presets for Denoise ---
document.getElementById("denoise-quick-presets").addEventListener("click", (e) => {
  const btn = e.target.closest(".qp-chip");
  if (!btn) return;
  const values = denoiseQuickPreset(btn.dataset.qp);
  if (!values) return;
  applyOptionValues("denoise", values);
  refreshSliders();
  setStatus(`Applied "${btn.dataset.qp}" preset.`);
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

// --- Before/after compare: two-up grid + overlay slider after a run ---
let compareInUrl = null, compareOutUrl = null;
let compareMode = "grid"; // "grid" | "slider"

// Assign an already-loaded blob URL to an img/video pair based on its kind.
function assignCompareMedia(url, kind, imgEl, vidEl) {
  if (!imgEl || !vidEl) return;
  if (url && kind === "image") {
    imgEl.src = url; imgEl.classList.remove("hidden");
    vidEl.classList.add("hidden"); vidEl.removeAttribute("src");
  } else if (url && kind === "video") {
    vidEl.src = url; vidEl.classList.remove("hidden");
    imgEl.classList.add("hidden"); imgEl.removeAttribute("src");
  } else {
    imgEl.classList.add("hidden"); imgEl.removeAttribute("src");
    vidEl.pause && vidEl.pause(); vidEl.classList.add("hidden"); vidEl.removeAttribute("src");
  }
}

function hideCompare() {
  const panel = $("#compare-panel");
  if (panel) panel.classList.add("hidden");
  ["compare-in", "compare-out", "cs-before", "cs-after"].forEach((base) => {
    assignCompareMedia(null, null, $("#" + base + "-img"), $("#" + base + "-vid"));
  });
  if (compareInUrl) { URL.revokeObjectURL(compareInUrl); compareInUrl = null; }
  if (compareOutUrl) { URL.revokeObjectURL(compareOutUrl); compareOutUrl = null; }
}

// Fetch the file once and return its blob URL + preview kind (no DOM assignment).
async function fetchCompareMedia(filePath) {
  const { kind, path: resolved } = previewKind(filePath);
  if (!kind) return { url: null, kind: null };
  const res = await fetch(baseUrl + "/file?path=" + encodeURIComponent(resolved), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return { url: null, kind: null };
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), kind };
}

async function showCompare(inputPath, outputPath) {
  if (!shouldShowCompare(inputPath, outputPath)) return;
  const panel = $("#compare-panel");
  if (!panel) return;
  try {
    const [inMedia, outMedia] = await Promise.all([
      fetchCompareMedia(inputPath),
      fetchCompareMedia(outputPath),
    ]);
    if (compareInUrl) URL.revokeObjectURL(compareInUrl);
    if (compareOutUrl) URL.revokeObjectURL(compareOutUrl);
    compareInUrl = inMedia.url;
    compareOutUrl = outMedia.url;
    // Two-up grid.
    assignCompareMedia(inMedia.url, inMedia.kind, $("#compare-in-img"), $("#compare-in-vid"));
    assignCompareMedia(outMedia.url, outMedia.kind, $("#compare-out-img"), $("#compare-out-vid"));
    // Overlay slider (before = input, after = output), reusing the same blobs.
    assignCompareMedia(inMedia.url, inMedia.kind, $("#cs-before-img"), $("#cs-before-vid"));
    assignCompareMedia(outMedia.url, outMedia.kind, $("#cs-after-img"), $("#cs-after-vid"));
    setCompareSliderPct(50);
    if (inMedia.url || outMedia.url) panel.classList.remove("hidden");
  } catch (_) { /* best-effort */ }
}

// Position the divider + clip the "after" layer to reveal pct% from the left.
function setCompareSliderPct(pct) {
  const after = $("#cs-after"), divider = $("#cs-divider");
  if (after) after.style.clipPath = compareClipInset(pct);
  if (divider) divider.style.left = compareDividerPos(pct);
}

function setCompareMode(mode) {
  compareMode = mode === "slider" ? "slider" : "grid";
  const grid = $("#compare-grid"), slider = $("#compare-slider");
  if (grid) grid.classList.toggle("hidden", compareMode !== "grid");
  if (slider) slider.classList.toggle("hidden", compareMode !== "slider");
  const gridBtn = $("#compare-mode-grid"), sliderBtn = $("#compare-mode-slider");
  [[gridBtn, compareMode === "grid"], [sliderBtn, compareMode === "slider"]].forEach(([btn, on]) => {
    if (btn) { btn.classList.toggle("active", on); btn.setAttribute("aria-pressed", String(on)); }
  });
}

// Wire the mode toggle + drag-to-reveal on the slider box (called once at startup).
function setupCompareControls() {
  const gridBtn = $("#compare-mode-grid"), sliderBtn = $("#compare-mode-slider");
  if (gridBtn) gridBtn.addEventListener("click", () => setCompareMode("grid"));
  if (sliderBtn) sliderBtn.addEventListener("click", () => setCompareMode("slider"));
  const box = $("#compare-slider-box");
  if (!box) return;
  let dragging = false;
  const moveTo = (clientX) => {
    const r = box.getBoundingClientRect();
    setCompareSliderPct(compareSliderPercent(clientX, r.left, r.width));
  };
  box.addEventListener("pointerdown", (e) => {
    dragging = true;
    box.setPointerCapture && box.setPointerCapture(e.pointerId);
    moveTo(e.clientX);
  });
  box.addEventListener("pointermove", (e) => { if (dragging) moveTo(e.clientX); });
  const stop = (e) => {
    dragging = false;
    box.releasePointerCapture && e && box.releasePointerCapture(e.pointerId);
  };
  box.addEventListener("pointerup", stop);
  box.addEventListener("pointercancel", stop);
}

// --- Completion actions: Open and Reveal in Explorer buttons after a run ---
// Stored so the button click handlers can reference the last successful output.
let lastOutputPath = null;
// Stored so "Run again" can re-fire the exact same op with the same parameters.
let lastRunRecord = null;

function populateChainSelect() {
  const sel = $("#chain-tab-select");
  if (!sel) return;
  const allTabs = Array.from(document.querySelectorAll(".tabs button[data-tab]"))
    .map((btn) => ({ tab: btn.dataset.tab, label: btn.textContent.trim() }));
  const options = chainTabOptions(allTabs, currentTab());
  sel.innerHTML = options.map((o) => `<option value="${o.tab}">${o.label}</option>`).join("");
}

function showCompletionActions(outputPath) {
  lastOutputPath = outputPath || null;
  const el = $("#completion-actions");
  if (el) el.classList.toggle("hidden", !outputPath);
  if (outputPath) populateChainSelect();
}

function hideCompletionActions() {
  lastOutputPath = null;
  const el = $("#completion-actions");
  if (el) el.classList.add("hidden");
}

(function setupCompletionActions() {
  const revealBtn = $("#reveal-output");
  if (revealBtn) revealBtn.textContent = revealLabel(window.sidecar.platform);
  const openBtn = $("#open-output");
  if (openBtn) openBtn.addEventListener("click", () => {
    if (lastOutputPath) window.sidecar.openPath(lastOutputPath).catch(() => {});
  });
  if (revealBtn) revealBtn.addEventListener("click", () => {
    if (lastOutputPath) window.sidecar.showItemInFolder(lastOutputPath).catch(() => {});
  });
})();

// --- "Run again": re-run the last successful op with identical parameters ---
function runAgain() {
  if (!lastRunRecord || opInFlight) return;
  run(lastRunRecord.label, lastRunRecord.op, lastRunRecord.body);
}

const runAgainBtn = $("#run-again");
if (runAgainBtn) runAgainBtn.addEventListener("click", runAgain);

// --- "Chain to tab": send the last output into another tab as its input ---
const chainToBtn = $("#chain-to-btn");
if (chainToBtn) chainToBtn.addEventListener("click", () => {
  const sel = $("#chain-tab-select");
  if (!sel || !lastOutputPath) return;
  const targetTab = sel.value;
  if (!targetTab) return;

  const tabBtn = document.querySelector(`.tabs button[data-tab="${targetTab}"]`);
  if (tabBtn) tabBtn.click(); // switches tab + triggers refreshInputs / updateTabHelp

  const concatVal = ($("#concat-inputs") || {}).value || "";
  const upd = dropUpdate([lastOutputPath], targetTab, concatVal);
  if (upd) {
    const inputEl = $("#" + upd.id);
    if (inputEl) {
      inputEl.value = upd.value;
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  recordRecent(lastOutputPath);
  setStatus("Output sent to " + targetTab.replace(/_/g, "-") + " tab.");
});

// --- Job history strip: recent completed runs with re-run / reveal buttons ---
let jobHistoryData = [];

function renderJobHistory() {
  const panel = $("#job-history");
  const list = $("#job-history-list");
  if (!panel || !list) return;
  if (!jobHistoryData.length) {
    panel.classList.add("hidden");
    return;
  }
  list.innerHTML = "";
  for (const r of jobHistoryData) {
    const li = document.createElement("li");
    li.className = "job-entry";
    const lbl = document.createElement("span");
    lbl.className = "job-entry-label";
    lbl.title = r.outputPath || "";
    lbl.textContent = jobHistoryLabel(r);
    li.appendChild(lbl);
    const rerunBtn = document.createElement("button");
    rerunBtn.textContent = "Re-run";
    rerunBtn.className = "secondary";
    rerunBtn.type = "button";
    rerunBtn.addEventListener("click", () => { if (!opInFlight) run(r.label, r.op, r.body); });
    const revealBtn = document.createElement("button");
    revealBtn.textContent = "Reveal";
    revealBtn.className = "secondary";
    revealBtn.type = "button";
    revealBtn.addEventListener("click", () => {
      window.sidecar.showItemInFolder(r.outputPath).catch(() => {});
    });
    li.appendChild(rerunBtn);
    li.appendChild(revealBtn);
    list.appendChild(li);
  }
  panel.classList.remove("hidden");
}

function pushJobRecord(record) {
  jobHistoryData = addJobRecord(jobHistoryData, record);
  setSettings({ jobHistory: jobHistoryData }).catch(() => {});
  renderJobHistory();
}

(function setupJobHistory() {
  const clearBtn = $("#clear-job-history");
  if (clearBtn) clearBtn.addEventListener("click", () => {
    jobHistoryData = [];
    setSettings({ jobHistory: [] }).catch(() => {});
    renderJobHistory();
  });
})();

// --- Operation queue: line up several ops (any tab, "Queue mode" toggle above) ---
// and run them one after another. Each item captures the exact { label, op, body }
// that would otherwise be passed straight to run().
let opQueueData = [];
let queueModeEnabled = false;
let queueRunning = false;
let queueIdCounter = 0;

function renderQueue() {
  const panel = $("#op-queue");
  const list = $("#op-queue-list");
  if (!panel || !list) return;
  if (!opQueueData.length) {
    panel.classList.add("hidden");
    return;
  }
  list.innerHTML = "";
  for (const item of opQueueData) {
    const li = document.createElement("li");
    li.className = "job-entry";
    const lbl = document.createElement("span");
    lbl.className = "job-entry-label";
    lbl.textContent = queueItemLabel(item);
    li.appendChild(lbl);
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Remove";
    removeBtn.className = "secondary";
    removeBtn.type = "button";
    removeBtn.disabled = item.status === "running";
    removeBtn.addEventListener("click", () => {
      opQueueData = removeQueueItem(opQueueData, item.id);
      setSettings({ opQueue: opQueueData }).catch(() => {});
      renderQueue();
    });
    li.appendChild(removeBtn);
    list.appendChild(li);
  }
  panel.classList.remove("hidden");
}

// Called in place of run() for every tab's Run button. In Queue mode this
// captures the op instead of executing it immediately; otherwise it's a
// pass-through to run() so normal (non-queued) behavior is unchanged.
function runOrQueue(label, op, body) {
  if (!queueModeEnabled) return run(label, op, body);
  const item = { id: "q" + Date.now() + "_" + queueIdCounter++, tab: currentTab(), label, op, body, status: "queued" };
  opQueueData = addQueueItem(opQueueData, item);
  setSettings({ opQueue: opQueueData }).catch(() => {});
  setStatus("Queued: " + label + " (" + opQueueData.length + " in queue)");
  renderQueue();
}

// Run every queued item in order, updating each item's status as it goes.
// Stops early if the op it's running fails/cancels — remaining items stay queued.
async function runQueueAll() {
  if (queueRunning || opInFlight) return;
  queueRunning = true;
  try {
    let next;
    while ((next = nextQueuedItem(opQueueData))) {
      opQueueData = updateQueueItem(opQueueData, next.id, { status: "running" });
      renderQueue();
      const ok = await run(next.label, next.op, next.body, next.tab);
      opQueueData = updateQueueItem(opQueueData, next.id, { status: ok ? "done" : "error" });
      setSettings({ opQueue: opQueueData }).catch(() => {});
      renderQueue();
      if (!ok) break; // don't blow through the rest of the queue after a failure
    }
  } finally {
    queueRunning = false;
  }
}

(function setupOpQueue() {
  const modeToggle = $("#queue-mode-toggle");
  if (modeToggle) modeToggle.addEventListener("change", () => {
    queueModeEnabled = modeToggle.checked;
  });
  const runBtn = $("#run-queue");
  if (runBtn) runBtn.addEventListener("click", runQueueAll);
  const clearBtn = $("#clear-queue");
  if (clearBtn) clearBtn.addEventListener("click", () => {
    if (queueRunning) return; // don't clear out from under the runner
    opQueueData = [];
    setSettings({ opQueue: [] }).catch(() => {});
    renderQueue();
  });
})();

// --- Batch mode: apply the active tab's operation to many picked files at once ---
// Only supported on single-input tabs (id "<tab>-input" / "<tab>-output" / a
// "run-<tab>" button) — multi-input tabs like concat/hstack/vstack/xfade-concat
// use different field ids and are silently skipped with a status message.
// Reuses the tab's own Run button (and therefore its own field-gathering,
// validation, and runOrQueue call) once per file, forcing Queue mode so nothing
// runs until the user reviews the queue and clicks "Run queue".
(function setupBatchMode() {
  const batchBtn = $("#batch-files");
  if (!batchBtn) return;
  batchBtn.addEventListener("click", async () => {
    const tab = currentTab();
    const inputEl = $("#" + tab + "-input");
    const outputEl = $("#" + tab + "-output");
    const runBtn = $("#run-" + tab);
    if (!inputEl || !outputEl || !runBtn) {
      setStatus("Batch mode needs a single-input tab (not available on " + tab + ").", true);
      return;
    }
    const files = await pickFiles(recentDir(recentData));
    const pairs = batchFilePairs(files, tab);
    if (!pairs.length) return; // cancelled or picked nothing
    const label = document.querySelector(".tabs button.active")?.textContent || tab;
    const prevInput = inputEl.value;
    const prevOutput = outputEl.value;
    queueModeEnabled = true; // batch always queues, and stays on so the panel matches
    try {
      for (const pair of pairs) {
        inputEl.value = pair.input;
        outputEl.value = pair.output;
        runBtn.click();
      }
    } finally {
      inputEl.value = prevInput;
      outputEl.value = prevOutput;
    }
    const queueToggle = $("#queue-mode-toggle");
    if (queueToggle) queueToggle.checked = true; // reflect that Queue mode is now on
    setStatus("Batch: queued " + pairs.length + " file(s) for " + label + ".");
  });
})();

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
  setEta(null);
}

// --- Live console: stream ffmpeg log lines during a run ---
let consoleLines = [];
function clearConsole() {
  consoleLines = [];
  $("#console-out").textContent = "";
  $("#console-count").textContent = "";
}
function showConsole() {
  $("#console").classList.remove("hidden");
}
function appendConsole(line) {
  consoleLines = appendConsoleLines(consoleLines, line);
  const out = $("#console-out");
  out.textContent = consoleLines.join("\n");
  $("#console-count").textContent = `(${consoleLines.length})`;
  // Auto-scroll to the newest line unless the user scrolled up to read.
  const nearBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
  if (nearBottom) out.scrollTop = out.scrollHeight;
}
// Live "ETA ~0:42" readout next to the status line (cleared when empty).
function setEta(text) {
  const el = $("#eta");
  el.textContent = text || "";
  el.classList.toggle("hidden", !text);
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

// Ask the sidecar whether a path (file or directory) exists. Best-effort:
// failures always return true so a sidecar hiccup never blocks the run.
async function checkExists(path) {
  try {
    const res = await fetch(baseUrl + "/exists?path=" + encodeURIComponent(path), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return true;
    return (await res.json()).exists;
  } catch (_) {
    return true;
  }
}

// Highlight a form field as invalid; clearFieldErrors removes all highlights.
function clearFieldErrors() {
  document.querySelectorAll(".field-error").forEach((el) => {
    el.classList.remove("field-error");
    const label = el.closest("label");
    if (label) delete label.dataset.fieldErr;
  });
}
function markFieldError(fieldId) {
  const el = document.getElementById(fieldId);
  if (el) el.classList.add("field-error");
}

// Inline per-field validation: highlight a field and show a short error message
// on its parent <label> in real-time as the user types.
function markFieldInvalid(el, msg) {
  el.classList.add("field-error");
  const label = el.closest("label");
  if (label) label.dataset.fieldErr = msg;
}
function clearFieldInvalid(el) {
  el.classList.remove("field-error");
  const label = el.closest("label");
  if (label) delete label.dataset.fieldErr;
}
function refreshFieldValidation(el) {
  if (!el || !el.id) return;
  const msg = validateField(el.id, el.value);
  if (msg) markFieldInvalid(el, msg);
  else clearFieldInvalid(el);
}

// Confirm before clobbering an existing output file.
async function confirmOverwrite(output) {
  if (!output) return true;
  if (!(await checkExists(output))) return true;
  return window.confirm(overwriteMessage(output));
}

// Pre-run check: verify input files exist and the output directory exists before
// launching ffmpeg. Highlights the offending field and returns {ok, message}.
// Best-effort: a sidecar error always returns {ok: true} so the run still fires.
async function validateRunPaths(tab, body) {
  clearFieldErrors();
  // Block the run if any of THIS tab's validated fields has an invalid value.
  // Scoped to `tab` rather than DOM visibility — a queued item's tab may not
  // be the one on-screen right now (see the `tab` param note on run() below),
  // but its fields still hold their real values underneath the hidden panel.
  for (const id of tabFieldValidatorIds(tab)) {
    const el = document.getElementById(id);
    if (!el) continue;
    const msg = validateField(id, el.value);
    if (msg) {
      markFieldInvalid(el, msg);
      return { ok: false, message: (fieldLabel(id) || id) + ": " + msg };
    }
  }
  for (const [path, fieldId] of runInputEntries(tab, body)) {
    if (!(await checkExists(path))) {
      markFieldError(fieldId);
      return { ok: false, message: "Input not found: " + recentFileLabel(path) };
    }
  }
  const outEntry = runOutputDirEntry(tab, body);
  if (outEntry) {
    const [dir, fieldId] = outEntry;
    if (!(await checkExists(dir))) {
      markFieldError(fieldId);
      return { ok: false, message: "Output folder doesn't exist: " + dir };
    }
  }
  return { ok: true };
}

// Returns true once the op completes without error, false on any early-out,
// validation failure, cancel, or error — so the queue runner (below) knows
// whether to advance the item to "done" or "error".
//
// `tab` is the op's OWN tab (defaults to whatever's on-screen for a direct Run
// click); the queue runner passes the tab an item was queued from explicitly,
// since the user may have navigated elsewhere by the time that item executes —
// persisted per-tab state (recent output, job history, field highlighting)
// must follow the op, not the currently-visible tab.
async function run(label, op, body, tab = currentTab()) {
  if (opInFlight) return false; // an op is already running — ignore the extra click
  const validation = await validateRunPaths(tab, body);
  if (!validation.ok) {
    setStatus(validation.message, true);
    return false;
  }
  if (!(await confirmOverwrite(body.output))) {
    setStatus("Cancelled — existing file left in place.");
    return false;
  }
  opInFlight = true;
  const abort = new AbortController();
  currentAbort = abort;
  setRunButtonsDisabled(true);
  setCancelVisible(true);
  setStatus(label + "…");
  clearErrorHint();
  hideSummary();
  hideCompletionActions();
  showCliCommand(op, body); // surface the equivalent ffmpeg-util command
  showProgress(0);
  clearConsole();
  showConsole(); // live ffmpeg output, so a long run (e.g. GIF) isn't a black box
  hidePreview();
  hideCompare();
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
          setEta(etaLabel(ev)); // remaining time from speed + output position
        } else if (ev.type === "log") {
          appendConsole(ev.line); // live ffmpeg console output
        } else if (ev.type === "done") {
          result = ev;
        } else if (ev.type === "error") {
          throw new Error(ev.detail);
        }
      }
    }
    const incomplete = sseIncompleteError(result);
    if (incomplete) throw new Error(incomplete);
    hideProgress();
    const doneBasename = result && result.output ? outputBaseName(result.output) || result.output : null;
    setStatus(doneBasename ? "Done — " + doneBasename : "Done.");
    lastRunRecord = { label, op, body }; // enable "Run again" with the same params
    saveSettings();
    const notifyPayload = notifyComplete(doneBasename, notifyEnabled);
    if (notifyPayload) notify(notifyPayload.title, notifyPayload.body).catch(() => {});
    if (result && result.output) {
      recordRecentOutput(tab, result.output); // persist output history for this tab
      pushJobRecord({ tab, label, op, body, outputPath: result.output, ts: Date.now() });
      showPreview(result.output);
      const primaryInput = body.input || (body.inputs && body.inputs[0]) || null;
      // Compare the output back to the primary input (single-input ops, else first).
      showSummary(primaryInput, result.output);
      showCompare(primaryInput, result.output);
      showCompletionActions(result.output);
    }
    return true;
  } catch (e) {
    hideProgress();
    if (abort.signal.aborted) {
      setStatus("Cancelled — operation stopped.");
    } else {
      showErrorHint(e.message); // friendly one-liner above the raw stderr
      setStatus("Error: " + e.message, true);
    }
    return false;
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
  runOrQueue("Converting", "convert", {
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
  runOrQueue("Trimming", "trim", {
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
  const reencode = !!$("#concat-reencode")?.checked;
  runOrQueue("Concatenating", "concat", { inputs, output: val("concat-output"), reencode, overwrite: true });
});

$("#run-thumbnail").addEventListener("click", () => {
  if (!requireFields("thumbnail-input", "thumbnail-output")) return;
  const cols = numOrNull("thumbnail-cols");
  const rows = numOrNull("thumbnail-rows");
  if (cols && rows) {
    runOrQueue("Building contact sheet", "contact_sheet", {
      input: val("thumbnail-input"),
      output: val("thumbnail-output"),
      cols,
      rows,
      width: numOrNull("thumbnail-width") || 320,
      overwrite: true,
    });
    return;
  }
  runOrQueue("Extracting thumbnail", "thumbnail", {
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
  runOrQueue("Converting to grayscale", "grayscale", {
    input: val("grayscale-input"),
    output: val("grayscale-output"),
    overwrite: true,
  });
});

$("#run-invert").addEventListener("click", () => {
  if (!requireFields("invert-input", "invert-output")) return;
  runOrQueue("Inverting colors", "invert", {
    input: val("invert-input"),
    output: val("invert-output"),
    overwrite: true,
  });
});

$("#run-timecode").addEventListener("click", () => {
  if (!requireFields("timecode-input", "timecode-output")) return;
  runOrQueue("Burning timecode", "timecode", {
    input: val("timecode-input"),
    output: val("timecode-output"),
    font_size: numOrNull("timecode-font-size") ?? 24,
    position: val("timecode-position") || "top-left",
    color: val("timecode-color") || "white",
    overwrite: true,
  });
});

$("#run-watermark").addEventListener("click", () => {
  if (!requireFields("watermark-input", "watermark-output", "watermark-text")) return;
  runOrQueue("Burning watermark", "watermark", {
    input: val("watermark-input"),
    output: val("watermark-output"),
    text: val("watermark-text"),
    font_size: numOrNull("watermark-font-size") ?? 24,
    opacity: numOrNull("watermark-opacity") ?? 1.0,
    position: val("watermark-position") || "bottom-right",
    color: val("watermark-color") || "white",
    overwrite: true,
  });
});

$("#run-hardsub").addEventListener("click", () => {
  if (!requireFields("hardsub-input", "hardsub-subtitle", "hardsub-output")) return;
  runOrQueue("Burning subtitles", "hardsub", {
    input: val("hardsub-input"),
    subtitle: val("hardsub-subtitle"),
    output: val("hardsub-output"),
    overwrite: true,
  });
});

$("#run-deinterlace").addEventListener("click", () => {
  if (!requireFields("deinterlace-input", "deinterlace-output")) return;
  runOrQueue("Deinterlacing", "deinterlace", {
    input: val("deinterlace-input"),
    output: val("deinterlace-output"),
    overwrite: true,
  });
});

$("#run-sharpen").addEventListener("click", () => {
  if (!requireFields("sharpen-input", "sharpen-output")) return;
  runOrQueue("Sharpening", "sharpen", {
    input: val("sharpen-input"),
    output: val("sharpen-output"),
    amount: numOrNull("sharpen-amount") ?? 1.5,
    overwrite: true,
  });
});

$("#run-denoise").addEventListener("click", () => {
  if (!requireFields("denoise-input", "denoise-output")) return;
  runOrQueue("Denoising", "denoise", {
    input: val("denoise-input"),
    output: val("denoise-output"),
    strength: numOrNull("denoise-strength") ?? 4.0,
    overwrite: true,
  });
});

$("#run-blur_region").addEventListener("click", () => {
  if (!requireFields("blur_region-input", "blur_region-output", "blur_region-width", "blur_region-height")) return;
  runOrQueue("Blurring region", "blur_region", {
    input: val("blur_region-input"),
    output: val("blur_region-output"),
    x: numOrNull("blur_region-x") ?? 0,
    y: numOrNull("blur_region-y") ?? 0,
    width: numOrNull("blur_region-width"),
    height: numOrNull("blur_region-height"),
    sigma: numOrNull("blur_region-sigma") ?? 10,
    overwrite: true,
  });
});

$("#run-blur_pad").addEventListener("click", () => {
  if (!requireFields("blur_pad-input", "blur_pad-output", "blur_pad-width", "blur_pad-height")) return;
  runOrQueue("Blur padding", "blur_pad", {
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
  runOrQueue("Making video", "image_to_video", {
    input: val("image_to_video-input"),
    output: val("image_to_video-output"),
    seconds: numOrNull("image_to_video-seconds"),
    fps: numOrNull("image_to_video-fps") || 30,
    audio: val("image_to_video-audio") || null,
    overwrite: true,
  });
});

$("#run-vstack").addEventListener("click", () => {
  if (!requireFields("vstack-input-a", "vstack-input-b", "vstack-output")) return;
  runOrQueue("Stacking vertically", "vstack", {
    inputs: [val("vstack-input-a"), val("vstack-input-b")],
    output: val("vstack-output"),
    overwrite: true,
  });
});

$("#run-hstack").addEventListener("click", () => {
  if (!requireFields("hstack-input-a", "hstack-input-b", "hstack-output")) return;
  runOrQueue("Combining side by side", "hstack", {
    inputs: [val("hstack-input-a"), val("hstack-input-b")],
    output: val("hstack-output"),
    overwrite: true,
  });
});

$("#run-pip").addEventListener("click", () => {
  if (!requireFields("pip-input", "pip-overlay", "pip-output")) return;
  runOrQueue("Adding picture in picture", "pip", {
    input: val("pip-input"),
    overlay: val("pip-overlay"),
    output: val("pip-output"),
    pip_size: numOrNull("pip-size") || 25,
    position: $("#pip-position").value || "bottom-right",
    overwrite: true,
  });
});

$("#run-pixfmt").addEventListener("click", () => {
  if (!requireFields("pixfmt-input", "pixfmt-output")) return;
  runOrQueue("Converting pixel format", "pixfmt", {
    input: val("pixfmt-input"),
    output: val("pixfmt-output"),
    pix_fmt: $("#pixfmt-pix-fmt").value || "yuv420p",
    overwrite: true,
  });
});

$("#run-xfade_concat").addEventListener("click", () => {
  if (!requireFields("xfade_concat-input-a", "xfade_concat-input-b", "xfade_concat-output")) return;
  const dur = Number($("#xfade_concat-xfade_duration").value) || 1.0;
  // Compute the offset (transition start = end of clip 1 minus transition duration).
  // Null when the source hasn't been probed yet; the sidecar will probe as fallback.
  const offset = lastSourceDuration != null ? Math.max(0, lastSourceDuration - dur) : null;
  runOrQueue("Crossfading clips", "xfade_concat", {
    inputs: [val("xfade_concat-input-a"), val("xfade_concat-input-b")],
    output: val("xfade_concat-output"),
    transition: $("#xfade_concat-transition").value,
    xfade_duration: dur,
    xfade_offset: offset,
    overwrite: true,
  });
});

$("#run-sample_rate").addEventListener("click", () => {
  if (!requireFields("sample_rate-input", "sample_rate-output")) return;
  runOrQueue("Resampling audio", "sample_rate", {
    input: val("sample_rate-input"),
    output: val("sample_rate-output"),
    rate: Number($("#sample_rate-rate").value),
    overwrite: true,
  });
});

$("#run-waveform").addEventListener("click", () => {
  if (!requireFields("waveform-input", "waveform-output")) return;
  runOrQueue("Rendering waveform", "waveform", {
    input: val("waveform-input"),
    output: val("waveform-output"),
    width: numOrNull("waveform-width") || 1000,
    height: numOrNull("waveform-height") || 200,
    overwrite: true,
  });
});

$("#run-crop_aspect").addEventListener("click", () => {
  if (!requireFields("crop_aspect-input", "crop_aspect-output")) return;
  runOrQueue("Cropping to aspect", "crop_aspect", {
    input: val("crop_aspect-input"),
    output: val("crop_aspect-output"),
    aspect: $("#crop_aspect-aspect").value,
    overwrite: true,
  });
});

$("#run-fps").addEventListener("click", () => {
  if (!requireFields("fps-input", "fps-output", "fps-fps")) return;
  runOrQueue("Resampling FPS", "fps", {
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
  runOrQueue("Adjusting", "eq", {
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
  runOrQueue("Making boomerang", "boomerang", {
    input: val("boomerang-input"),
    output: val("boomerang-output"),
    overwrite: true,
  });
});

$("#run-fade").addEventListener("click", () => {
  if (!requireFields("fade-input", "fade-output", "fade-duration")) return;
  runOrQueue("Fading", "fade", {
    input: val("fade-input"),
    output: val("fade-output"),
    fade: numOrNull("fade-duration"),
    overwrite: true,
  });
});

$("#run-loudnorm").addEventListener("click", () => {
  if (!requireFields("loudnorm-input", "loudnorm-output")) return;
  runOrQueue("Normalizing loudness", "loudnorm", {
    input: val("loudnorm-input"),
    output: val("loudnorm-output"),
    target_i: numOrNull("loudnorm-target") != null ? numOrNull("loudnorm-target") : -16,
    overwrite: true,
  });
});

$("#run-volume").addEventListener("click", () => {
  if (!requireFields("volume-input", "volume-output", "volume-gain")) return;
  runOrQueue("Adjusting volume", "volume", {
    input: val("volume-input"),
    output: val("volume-output"),
    gain: numOrNull("volume-gain"),
    overwrite: true,
  });
});

$("#run-reverse").addEventListener("click", () => {
  if (!requireFields("reverse-input", "reverse-output")) return;
  runOrQueue("Reversing", "reverse", {
    input: val("reverse-input"),
    output: val("reverse-output"),
    overwrite: true,
  });
});

$("#run-frames").addEventListener("click", () => {
  if (!requireFields("frames-input", "frames-output")) return;
  runOrQueue("Extracting frames", "frames", {
    input: val("frames-input"),
    output: val("frames-output"),
    every: numOrNull("frames-every") || 1,
    overwrite: true,
  });
});

$("#run-scene-thumbs").addEventListener("click", () => {
  if (!requireFields("scene_thumbs-input", "scene_thumbs-output")) return;
  runOrQueue("Extracting scene thumbnails", "scene_thumbs", {
    input: val("scene_thumbs-input"),
    output: val("scene_thumbs-output"),
    threshold: numOrNull("scene_thumbs-threshold") ?? 0.3,
    width: numOrNull("scene_thumbs-width") || null,
    overwrite: true,
  });
});

$("#run-loop").addEventListener("click", () => {
  if (!requireFields("loop-input", "loop-output", "loop-count")) return;
  runOrQueue("Looping", "loop", {
    input: val("loop-input"),
    output: val("loop-output"),
    count: numOrNull("loop-count"),
    overwrite: true,
  });
});

$("#run-pad").addEventListener("click", () => {
  if (!requireFields("pad-input", "pad-output", "pad-width", "pad-height")) return;
  runOrQueue("Padding", "pad", {
    input: val("pad-input"),
    output: val("pad-output"),
    width: numOrNull("pad-width"),
    height: numOrNull("pad-height"),
    overwrite: true,
  });
});

$("#run-title").addEventListener("click", () => {
  if (!requireFields("title-input", "title-output")) return;
  runOrQueue("Setting title", "title", {
    input: val("title-input"),
    output: val("title-output"),
    title: val("title-title"),
    overwrite: true,
  });
});

$("#run-chapters").addEventListener("click", () => {
  if (!requireFields("chapters-input", "chapters-output", "chapters-chapters")) return;
  runOrQueue("Adding chapters", "chapters", {
    input: val("chapters-input"),
    output: val("chapters-output"),
    chapters_text: val("chapters-chapters"),
    overwrite: true,
  });
});

$("#run-mono").addEventListener("click", () => {
  if (!requireFields("mono-input", "mono-output")) return;
  runOrQueue("Downmixing to mono", "mono", {
    input: val("mono-input"),
    output: val("mono-output"),
    overwrite: true,
  });
});

$("#run-trim_silence").addEventListener("click", () => {
  if (!requireFields("trim_silence-input", "trim_silence-output")) return;
  runOrQueue("Trimming silence", "trim_silence", {
    input: val("trim_silence-input"),
    output: val("trim_silence-output"),
    threshold_db: numOrNull("trim_silence-threshold") != null ? numOrNull("trim_silence-threshold") : -50,
    min_duration: numOrNull("trim_silence-min-duration") != null ? numOrNull("trim_silence-min-duration") : 0.5,
    overwrite: true,
  });
});

$("#run-mute").addEventListener("click", () => {
  if (!requireFields("mute-input", "mute-output")) return;
  runOrQueue("Stripping audio", "mute", {
    input: val("mute-input"),
    output: val("mute-output"),
    overwrite: true,
  });
});

$("#run-replace_audio").addEventListener("click", () => {
  if (!requireFields("replace_audio-input", "replace_audio-audio", "replace_audio-output")) return;
  runOrQueue("Replacing audio", "replace_audio", {
    input: val("replace_audio-input"),
    audio: val("replace_audio-audio"),
    output: val("replace_audio-output"),
    overwrite: true,
  });
});

$("#run-crop").addEventListener("click", () => {
  if (!requireFields("crop-input", "crop-output", "crop-width", "crop-height")) return;
  runOrQueue("Cropping", "crop", {
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
  runOrQueue("Transforming", "transform", {
    input: val("transform-input"),
    output: val("transform-output"),
    transform: $("#transform-op").value,
    overwrite: true,
  });
});

$("#run-speed").addEventListener("click", () => {
  if (!requireFields("speed-input", "speed-output", "speed-factor")) return;
  runOrQueue("Changing speed", "speed", {
    input: val("speed-input"),
    output: val("speed-output"),
    factor: numOrNull("speed-factor"),
    overwrite: true,
  });
});

$("#run-gif").addEventListener("click", () => {
  if (!requireFields("gif-input", "gif-output")) return;
  runOrQueue("Making GIF", "gif", {
    input: val("gif-input"),
    output: val("gif-output"),
    fps: numOrNull("gif-fps") || 12,
    width: numOrNull("gif-width") || 480,
    start: strOrNull("gif-start"),
    duration: strOrNull("gif-duration"),
    dither: val("gif-dither") || "sierra2_4a",
    loop: numOrNull("gif-loop") ?? 0,
    overwrite: true,
  });
});

$("#run-compress").addEventListener("click", () => {
  if (!requireFields("compress-input", "compress-output")) return;
  runOrQueue("Compressing", "compress", {
    input: val("compress-input"),
    output: val("compress-output"),
    crf: numOrNull("compress-crf"),
    bitrate: strOrNull("compress-bitrate"),
    target_size: numOrNull("compress-target"),
    width: numOrNull("compress-width"),
    height: numOrNull("compress-height"),
    vcodec: val("compress-vcodec") || "libx264",
    preset: val("compress-preset") || "medium",
    hwaccel: val("compress-hwaccel") || "none",
    overwrite: true,
  });
});

$("#estimate-compress-size").addEventListener("click", async () => {
  if (!requireFields("compress-input")) return;
  const btn = $("#estimate-compress-size");
  const out = $("#compress-size-estimate");
  btn.disabled = true;
  out.classList.remove("hidden");
  out.textContent = "Estimating (encoding a short sample)…";
  try {
    const result = await api("/compress/estimate-size", {
      input: val("compress-input"),
      crf: numOrNull("compress-crf"),
      bitrate: strOrNull("compress-bitrate"),
      width: numOrNull("compress-width"),
      height: numOrNull("compress-height"),
      vcodec: val("compress-vcodec") || "libx264",
      preset: val("compress-preset") || "medium",
      hwaccel: val("compress-hwaccel") || "none",
    });
    out.textContent = compressSizeEstimateLabel(result) || "Could not estimate.";
  } catch (err) {
    out.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

$("#run-autocrop").addEventListener("click", () => {
  if (!requireFields("autocrop-input", "autocrop-output")) return;
  const limit = numOrNull("autocrop-limit");
  runOrQueue("Auto-cropping", "autocrop", {
    input: val("autocrop-input"),
    output: val("autocrop-output"),
    limit: limit != null ? limit : 24,
    overwrite: true,
  });
});

$("#run-remux").addEventListener("click", () => {
  if (!requireFields("remux-input", "remux-output")) return;
  runOrQueue("Remuxing", "remux", {
    input: val("remux-input"),
    output: val("remux-output"),
    overwrite: true,
  });
});

$("#run-trim_pct").addEventListener("click", () => {
  if (!requireFields("trim_pct-input", "trim_pct-output")) return;
  runOrQueue("Trimming by percentage", "trim_pct", {
    input: val("trim_pct-input"),
    output: val("trim_pct-output"),
    start_pct: numOrNull("trim_pct-start-pct") ?? 0,
    end_pct: numOrNull("trim_pct-end-pct") ?? 100,
    reencode: !!$("#trim_pct-reencode")?.checked,
    overwrite: true,
  });
});

$("#run-trim_segments").addEventListener("click", () => {
  if (!requireFields("trim_segments-input", "trim_segments-output", "trim_segments-segments")) return;
  runOrQueue("Trimming segments", "trim_segments", {
    input: val("trim_segments-input"),
    output: val("trim_segments-output"),
    segments_text: val("trim_segments-segments"),
    overwrite: true,
  });
});

$("#run-preview_clip").addEventListener("click", () => {
  if (!requireFields("preview_clip-input", "preview_clip-output")) return;
  runOrQueue("Exporting preview", "preview_clip", {
    input: val("preview_clip-input"),
    output: val("preview_clip-output"),
    seconds: numOrNull("preview_clip-seconds") ?? 5,
    width: numOrNull("preview_clip-width") ?? 320,
    overwrite: true,
  });
});

$("#run-poster_frame").addEventListener("click", () => {
  if (!requireFields("poster_frame-input", "poster_frame-output")) return;
  runOrQueue("Extracting poster frame", "poster_frame", {
    input: val("poster_frame-input"),
    output: val("poster_frame-output"),
    percent: numOrNull("poster_frame-percent") ?? 10,
    overwrite: true,
  });
});

$("#run-auto_orient").addEventListener("click", () => {
  if (!requireFields("auto_orient-input", "auto_orient-output")) return;
  runOrQueue("Auto-orienting", "auto_orient", {
    input: val("auto_orient-input"),
    output: val("auto_orient-output"),
    overwrite: true,
  });
});

$("#run-stabilize").addEventListener("click", () => {
  if (!requireFields("stabilize-input", "stabilize-output")) return;
  runOrQueue("Stabilizing", "stabilize", {
    input: val("stabilize-input"),
    output: val("stabilize-output"),
    shakiness: numOrNull("stabilize-shakiness") ?? 5,
    smoothing: numOrNull("stabilize-smoothing") ?? 10,
    overwrite: true,
  });
});

// --- Sliders with live readouts ---
// Sync all sliders from their paired number inputs (called after preset load).
function refreshSliders() {
  for (const spec of SLIDER_SPECS) {
    const sl = $("#" + spec.id + "-sl");
    const num = $("#" + spec.id);
    const out = $("#" + spec.id + "-out");
    if (!sl || !num || !out) continue;
    const v = num.value.trim() !== "" ? parseFloat(num.value) : spec.def;
    const clamped = Math.min(spec.max, Math.max(spec.min, isFinite(v) ? v : spec.def));
    sl.value = clamped;
    out.textContent = formatSliderOut(spec, clamped);
  }
}

// Wire up bidirectional slider↔number sync for each spec. Called once at init.
function setupSliders() {
  for (const spec of SLIDER_SPECS) {
    const sl = $("#" + spec.id + "-sl");
    const num = $("#" + spec.id);
    const out = $("#" + spec.id + "-out");
    if (!sl || !num || !out) continue;
    sl.addEventListener("input", () => {
      const v = parseFloat(sl.value);
      if (!isFinite(v)) return;
      const clamped = Math.min(spec.max, Math.max(spec.min, v));
      const tidy = parseFloat((Math.round(clamped / spec.step) * spec.step).toFixed(10));
      num.value = tidy;
      out.textContent = formatSliderOut(spec, tidy);
    });
    num.addEventListener("input", () => {
      const v = parseFloat(num.value);
      if (!isFinite(v)) return;
      const clamped = Math.min(spec.max, Math.max(spec.min, v));
      sl.value = clamped;
      out.textContent = formatSliderOut(spec, parseFloat(clamped.toFixed(10)));
    });
  }
  refreshSliders(); // initialize readouts and slider positions from defaults
}

setupSliders();

// --- Timeline scrubber: in/out handles on the source player for time-field tabs ---
// Shows a thin track with draggable in/out handles beneath the source video when
// the active tab has time fields (trim, gif, thumbnail). Dragging a handle seeks
// the video and fills the form field; the playhead dot tracks currentTime.

function updateTimelinePlayhead() {
  const vid = $("#source-video");
  const ph = $("#tl-playhead");
  if (!ph) return;
  const dur = vid && vid.duration;
  if (!(dur > 0)) { ph.style.display = "none"; return; }
  ph.style.display = "";
  ph.style.left = ((vid.currentTime / dur) * 100) + "%";
}

function updateTimelineBar() {
  const bar = $("#timeline-bar");
  if (!bar) return;
  const vid = $("#source-video");
  const handles = timeHandlesForTab(currentTab());
  const hasVideo = vid && !vid.classList.contains("hidden") && vid.getAttribute("src");

  if (!handles.length || !hasVideo) {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");

  const dur = (vid && vid.duration > 0) ? vid.duration : 0;
  const inHandle = handles.find((h) => h.role === "in");
  const outHandle = handles.find((h) => h.role === "out");
  const inEl = $("#tl-in");
  const outEl = $("#tl-out");

  if (inHandle) {
    const frac = timecodeFraction(($("#" + inHandle.id) || {}).value, dur) ?? 0;
    inEl.style.left = (frac * 100) + "%";
    inEl.dataset.fieldId = inHandle.id;
    inEl.classList.remove("hidden");
  } else {
    inEl.classList.add("hidden");
  }

  if (outHandle) {
    const frac = timecodeFraction(($("#" + outHandle.id) || {}).value, dur) ?? 1;
    outEl.style.left = (frac * 100) + "%";
    outEl.dataset.fieldId = outHandle.id;
    outEl.classList.remove("hidden");
  } else {
    outEl.classList.add("hidden");
  }

  const rangeEl = $("#tl-range");
  if (rangeEl) {
    const inFrac = inHandle ? (timecodeFraction(($("#" + inHandle.id) || {}).value, dur) ?? 0) : 0;
    const outFrac = outHandle ? (timecodeFraction(($("#" + outHandle.id) || {}).value, dur) ?? 1) : 1;
    rangeEl.style.left = (inFrac * 100) + "%";
    rangeEl.style.width = (Math.max(0, outFrac - inFrac) * 100) + "%";
  }

  const labelsEl = $("#tl-labels");
  if (labelsEl && dur > 0) {
    const inFrac = inHandle ? (timecodeFraction(($("#" + inHandle.id) || {}).value, dur) ?? 0) : null;
    const outFrac = outHandle ? (timecodeFraction(($("#" + outHandle.id) || {}).value, dur) ?? null) : null;
    labelsEl.textContent = "";
    if (inFrac !== null) {
      const span = document.createElement("span");
      span.textContent = formatTimecode(inFrac * dur);
      labelsEl.appendChild(span);
    }
    if (outFrac !== null) {
      const span = document.createElement("span");
      span.textContent = formatTimecode(outFrac * dur);
      labelsEl.appendChild(span);
    }
  }

  updateTimelinePlayhead();
}

(function setupTimelineDrag() {
  const track = document.querySelector(".tl-track");
  if (!track) return;

  function fractionFromX(clientX) {
    const rect = track.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  }

  function applyFraction(formFieldId, frac) {
    const vid = $("#source-video");
    const dur = vid && vid.duration > 0 ? vid.duration : 0;
    if (!dur) return;
    const field = $("#" + formFieldId);
    if (field) {
      field.value = formatTimecode(frac * dur);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    }
    vid.currentTime = frac * dur;
    updateTimelineBar();
  }

  for (const elId of ["tl-in", "tl-out"]) {
    const el = $("#" + elId);
    if (!el) continue;
    el.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
    });
    el.addEventListener("pointermove", (e) => {
      if (!el.hasPointerCapture(e.pointerId)) return;
      const fieldId = el.dataset.fieldId;
      if (fieldId) applyFraction(fieldId, fractionFromX(e.clientX));
    });
    el.addEventListener("pointerup", (e) => {
      try { el.releasePointerCapture(e.pointerId); } catch (_) {}
    });
    el.addEventListener("pointercancel", (e) => {
      try { el.releasePointerCapture(e.pointerId); } catch (_) {}
    });
    // Keyboard nudge: arrow keys move by 1% of total duration
    el.addEventListener("keydown", (e) => {
      const vid = $("#source-video");
      const dur = vid && vid.duration > 0 ? vid.duration : 0;
      const fieldId = el.dataset.fieldId;
      if (!dur || !fieldId) return;
      const field = $("#" + fieldId);
      const cur = field ? (parseFloat(field.value) || 0) : 0;
      const step = dur * 0.01;
      if (e.key === "ArrowLeft") { applyFraction(fieldId, Math.max(0, (cur - step) / dur)); e.preventDefault(); }
      if (e.key === "ArrowRight") { applyFraction(fieldId, Math.min(1, (cur + step) / dur)); e.preventDefault(); }
    });
  }

  // Click on the track background (not on a handle) to seek the video
  track.addEventListener("click", (e) => {
    const tgt = e.target;
    if (tgt === track || tgt.classList.contains("tl-range") || tgt.classList.contains("tl-playhead")) {
      const vid = $("#source-video");
      const dur = vid && vid.duration > 0 ? vid.duration : 0;
      if (!dur) return;
      vid.currentTime = fractionFromX(e.clientX) * dur;
      updateTimelinePlayhead();
    }
  });
})();

// Wire video events to keep the timeline in sync with playback and new clips
(function wireVideoToTimeline() {
  const vid = $("#source-video");
  if (!vid) return;
  vid.addEventListener("timeupdate", updateTimelinePlayhead);
  vid.addEventListener("loadedmetadata", updateTimelineBar);
})();

// Sync handle positions when time fields are edited by hand
document.addEventListener("input", (e) => {
  const id = e.target && e.target.id;
  if (id && /^(trim-start|trim-end|gif-start|thumbnail-time)$/.test(id)) updateTimelineBar();
});

// --- Per-field "?" tooltips ---
// Walk every label.inline and its child input/select; insert a small ? badge next
// to the label text for any field that has a tooltip in FIELD_TOOLTIPS. The badge
// carries a `title` attribute so the browser shows the native OS tooltip on hover.
// Called once at startup — the HTML is static so a single pass is enough.
function setupFieldTooltips() {
  document.querySelectorAll("label.inline").forEach((label) => {
    const field = label.querySelector("input[id], select[id]");
    if (!field) return;
    const tip = fieldTooltip(field.id);
    if (!tip) return;
    const badge = document.createElement("span");
    badge.className = "field-tip";
    badge.title = tip;
    badge.setAttribute("aria-label", "field help: " + tip);
    badge.textContent = "?";
    label.insertBefore(badge, field);
  });
}

setupFieldTooltips();
setupCompareControls();
