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

function save(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data || {}, null, 2), "utf-8");
}

module.exports = { load, save };
