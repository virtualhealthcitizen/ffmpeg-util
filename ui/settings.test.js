// Unit tests for the JSON settings store (pure, no Electron). Run via `npm test`.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const store = require("./settings");

function tmpFile() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "ffu-settings-"));
  return path.join(d, "settings.json");
}

test("save merges with existing settings so writers don't clobber each other", () => {
  const f = tmpFile();
  store.save(f, { "convert-vcodec": "libx264" });
  store.save(f, { window: { width: 800, height: 600 } }); // a different writer
  const s = store.load(f);
  assert.equal(s["convert-vcodec"], "libx264");
  assert.deepEqual(s.window, { width: 800, height: 600 });
});

test("save overwrites a repeated key but keeps the rest", () => {
  const f = tmpFile();
  store.save(f, { activeTab: "convert", "gif-fps": "10" });
  store.save(f, { activeTab: "compress" });
  const s = store.load(f);
  assert.equal(s.activeTab, "compress");
  assert.equal(s["gif-fps"], "10");
});

test("load returns {} for a missing or corrupt file", () => {
  assert.deepEqual(store.load(path.join(os.tmpdir(), "nope-" + process.pid + ".json")), {});
  const f = tmpFile();
  fs.writeFileSync(f, "{ not json");
  assert.deepEqual(store.load(f), {});
});

test("windowOptions falls back to defaults and ignores implausible values", () => {
  assert.deepEqual(store.windowOptions({}), { width: 920, height: 760 });
  assert.deepEqual(store.windowOptions(null), { width: 920, height: 760 });
  // too small -> defaults
  assert.deepEqual(store.windowOptions({ window: { width: 100, height: 100 } }), { width: 920, height: 760 });
  // valid size, no position
  assert.deepEqual(store.windowOptions({ window: { width: 1000, height: 700 } }), { width: 1000, height: 700 });
  // valid size + position
  assert.deepEqual(
    store.windowOptions({ window: { width: 1000, height: 700, x: 50, y: 60 } }),
    { width: 1000, height: 700, x: 50, y: 60 }
  );
  // partial position is ignored
  assert.deepEqual(store.windowOptions({ window: { width: 1000, height: 700, x: 50 } }), { width: 1000, height: 700 });
});
