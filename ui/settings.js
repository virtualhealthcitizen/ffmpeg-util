// Tiny JSON-file settings store (pure, no Electron deps so it's unit-testable).

const fs = require("fs");
const path = require("path");

function load(file) {
  try {
    // Strip a leading UTF-8 BOM — editors/PowerShell may add one, and JSON.parse
    // rejects it.
    return JSON.parse(fs.readFileSync(file, "utf-8").replace(/^﻿/, ""));
  } catch (_) {
    return {}; // missing or corrupt -> empty settings
  }
}

// Shallow-merge into the existing file so independent writers don't clobber each
// other's keys: the renderer persists its sticky option fields + active tab, the
// main process persists window bounds — all into one settings.json.
function save(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const merged = { ...load(file), ...(data || {}) };
  fs.writeFileSync(file, JSON.stringify(merged, null, 2), "utf-8");
}

// Compute BrowserWindow size/position from persisted settings, falling back to
// defaults and ignoring implausibly small/non-numeric values. Pure (no Electron)
// so it can be unit-tested. x/y are only returned when both are present.
function windowOptions(saved, defaults = { width: 920, height: 760 }) {
  const w = (saved && saved.window) || {};
  const ok = (v) => typeof v === "number" && Number.isFinite(v);
  const opts = {
    width: ok(w.width) && w.width >= 400 ? w.width : defaults.width,
    height: ok(w.height) && w.height >= 300 ? w.height : defaults.height,
  };
  if (ok(w.x) && ok(w.y)) {
    opts.x = w.x;
    opts.y = w.y;
  }
  return opts;
}

module.exports = { load, save, windowOptions };
