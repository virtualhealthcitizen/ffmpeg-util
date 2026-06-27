// Headless, dialog-safe E2E smoke harness for the ffmpeg-util Electron UI.
//
// It runs fully offscreen and NEVER pops a native error dialog or steals focus:
// crash guards are installed before anything else (including project requires),
// so any failure — even a bad require — is written to the results file and the
// process exits quietly instead of reaching Electron's default handler (which
// shows the "A JavaScript error occurred in the main process" dialog and grabs
// focus). Prefer this over writing ad-hoc Electron scripts for local checks.
//
// Usage:  electron ui/e2e/smoke.js
// Env:    FFU_SMOKE_RESULTS   path to write JSON results (default: a temp file)
//         FFMPEG_UTIL_PYTHON  python interpreter override (else auto-resolved)
// Exit:   0 if every check passed, 1 otherwise.

const path = require("path");
const fs = require("fs");
const os = require("os");

const RESULTS_FILE =
  process.env.FFU_SMOKE_RESULTS || path.join(os.tmpdir(), "ffu_smoke_results.json");

function writeResults(obj) {
  try {
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(obj, null, 2));
  } catch (_) {
    /* best effort */
  }
}

// Crash guards FIRST — before any project require — so nothing ever reaches
// Electron's default uncaught-exception handler (which pops a GUI dialog).
function bail(stage, err) {
  writeResults({ ok: false, stage, error: String((err && err.stack) || err) });
  try {
    require("electron").app.exit(1);
  } catch (_) {
    process.exit(1);
  }
}
process.on("uncaughtException", (e) => bail("uncaughtException", e));
process.on("unhandledRejection", (e) => bail("unhandledRejection", e));

const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");
const net = require("net");

// Stay invisible: no GPU, no dock icon, nothing that could steal focus.
app.disableHardwareAcceleration();
app.setName("ffmpeg-util-smoke");
if (app.dock && app.dock.hide) app.dock.hide();

// This file lives at ui/e2e/smoke.js, so the UI dir is always one level up —
// resolved from __dirname, never from a fragile path out of a temp directory.
const UI_DIR = path.resolve(__dirname, "..");
const { resolvePython } = require(path.join(UI_DIR, "python"));
const TOKEN = crypto.randomBytes(24).toString("hex");

// The renderer calls these over IPC; stub them so it loads without the real app.
ipcMain.handle("settings:get", () => ({}));
ipcMain.handle("settings:set", () => true);
app.on("window-all-closed", () => {});

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}

async function waitForHealth(port, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`);
      if (res.ok) return true;
    } catch (_) {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

async function run() {
  const results = { ok: false, checks: [] };
  let sidecar = null;
  let win = null;
  const cleanup = () => {
    try {
      if (win && !win.isDestroyed()) win.destroy();
    } catch (_) {}
    try {
      if (sidecar && !sidecar.killed) sidecar.kill();
    } catch (_) {}
  };
  const finish = () => {
    results.ok = results.checks.every((c) => c.ok);
    writeResults(results);
    cleanup();
    app.exit(results.ok ? 0 : 1);
  };

  // 1. Start the sidecar on a free port.
  const port = await getFreePort();
  const py =
    resolvePython() || { cmd: process.env.FFMPEG_UTIL_PYTHON || "python", args: [] };
  sidecar = spawn(py.cmd, [...py.args, path.join(UI_DIR, "sidecar", "server.py")], {
    env: { ...process.env, SIDECAR_PORT: String(port), SIDECAR_TOKEN: TOKEN },
    stdio: ["ignore", "pipe", "pipe"],
  });

  const healthy = await waitForHealth(port);
  results.checks.push({ name: "sidecar /health reachable", ok: healthy });
  if (!healthy) return finish();

  // 2. Load the renderer fully offscreen.
  win = new BrowserWindow({
    width: 1024,
    height: 768,
    show: false,
    webPreferences: {
      preload: path.join(UI_DIR, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      offscreen: true,
      additionalArguments: [`--sidecar-port=${port}`, `--sidecar-token=${TOKEN}`],
    },
  });
  await win.loadFile(path.join(UI_DIR, "renderer", "index.html"));
  await new Promise((r) => setTimeout(r, 1000)); // let it render

  // 3. The nav renders with the expected tools.
  const tabCount = await win.webContents.executeJavaScript(
    `document.querySelectorAll('.tabs button[data-tab]').length`
  );
  results.checks.push({ name: "nav tabs rendered (>= 10)", ok: tabCount >= 10, detail: tabCount });
  const convertVisible = await win.webContents.executeJavaScript(
    `!!document.querySelector('.tabs button[data-tab="convert"]')`
  );
  results.checks.push({ name: "convert tab present", ok: convertVisible });

  // 4. End-to-end compress: generate a clip, drive the UI, confirm output.
  const tmpDir = os.tmpdir();
  const testClip = path.join(tmpDir, "ffu_smoke_in.mp4");
  const testOut = path.join(tmpDir, "ffu_smoke_out.mp4");
  try {
    execFileSync("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
      "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
      "-c:v", "libx264", "-c:a", "aac", "-shortest", testClip,
    ]);
    results.checks.push({ name: "ffmpeg test clip generated", ok: true });
  } catch (e) {
    results.checks.push({ name: "ffmpeg test clip generated", ok: false, detail: String(e) });
    return finish();
  }

  await win.webContents.executeJavaScript(`
    document.querySelector('.tabs button[data-tab="compress"]').click();
    document.querySelector('#compress-input').value = ${JSON.stringify(testClip)};
    document.querySelector('#compress-output').value = ${JSON.stringify(testOut)};
    document.querySelector('#compress-crf').value = '35';
    document.querySelector('#compress-width').value = '160';
    document.querySelector('#run-compress').click();
  `);

  let produced = false;
  for (let i = 0; i < 150 && !produced; i++) {
    await new Promise((r) => setTimeout(r, 200));
    if (fs.existsSync(testOut)) produced = true;
  }
  results.checks.push({ name: "compress output produced", ok: produced });

  try { fs.unlinkSync(testClip); } catch (_) {}
  try { fs.unlinkSync(testOut); } catch (_) {}
  finish();
}

app.whenReady().then(run);
