// E2E: verify that Open + Reveal buttons appear after a successful run.
// Follows the same hardening pattern as smoke.js (crash guards first, offscreen,
// no GPU, no dock icon) so no native dialogs can steal desktop focus.

const path = require("path");
const fs = require("fs");
const os = require("os");

const RESULTS_FILE = process.env.FFU_CA_RESULTS ||
  path.join(os.tmpdir(), "ffu_ca_results.json");

function writeResults(obj) {
  try { fs.writeFileSync(RESULTS_FILE, JSON.stringify(obj, null, 2)); } catch (_) {}
}

function bail(stage, err) {
  writeResults({ ok: false, stage, error: String((err && err.stack) || err) });
  try { require("electron").app.exit(1); } catch (_) { process.exit(1); }
}
process.on("uncaughtException", (e) => bail("uncaughtException", e));
process.on("unhandledRejection", (e) => bail("unhandledRejection", e));

const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");
const net = require("net");

app.disableHardwareAcceleration();
app.setName("ffu-completion-actions-e2e");
if (app.dock && app.dock.hide) app.dock.hide();

const UI_DIR = path.resolve(__dirname, "..");
const { resolvePython } = require(path.join(UI_DIR, "python"));
const TOKEN = crypto.randomBytes(24).toString("hex");

ipcMain.handle("settings:get", () => ({}));
ipcMain.handle("settings:set", () => true);
ipcMain.handle("shell:openPath", () => "");
ipcMain.handle("shell:showItemInFolder", () => {});
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
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

async function run() {
  const results = { ok: false, checks: [] };
  let sidecar = null;
  let win = null;
  const cleanup = () => {
    try { if (win && !win.isDestroyed()) win.destroy(); } catch (_) {}
    try { if (sidecar && !sidecar.killed) sidecar.kill(); } catch (_) {}
  };
  const finish = () => {
    results.ok = results.checks.every((c) => c.ok);
    writeResults(results);
    cleanup();
    app.exit(results.ok ? 0 : 1);
  };

  const port = await getFreePort();
  const py = resolvePython() || { cmd: process.env.FFMPEG_UTIL_PYTHON || "python", args: [] };
  sidecar = spawn(py.cmd, [...py.args, path.join(UI_DIR, "sidecar", "server.py")], {
    env: { ...process.env, SIDECAR_PORT: String(port), SIDECAR_TOKEN: TOKEN },
    stdio: ["ignore", "pipe", "pipe"],
  });

  const healthy = await waitForHealth(port);
  results.checks.push({ name: "sidecar healthy", ok: healthy });
  if (!healthy) return finish();

  win = new BrowserWindow({
    width: 1024, height: 768, show: false,
    webPreferences: {
      preload: path.join(UI_DIR, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      offscreen: true,
      additionalArguments: [`--sidecar-port=${port}`, `--sidecar-token=${TOKEN}`],
    },
  });
  await win.loadFile(path.join(UI_DIR, "renderer", "index.html"));
  await new Promise((r) => setTimeout(r, 1000));

  // Completion-actions div must start hidden.
  const hiddenAtStart = await win.webContents.executeJavaScript(
    `document.querySelector('#completion-actions').classList.contains('hidden')`
  );
  results.checks.push({ name: "completion-actions hidden before any run", ok: hiddenAtStart });

  // The Reveal button label must be platform-appropriate.
  const revealText = await win.webContents.executeJavaScript(
    `document.querySelector('#reveal-output').textContent`
  );
  const validLabels = ["Reveal in Explorer", "Reveal in Finder", "Reveal in Files"];
  results.checks.push({
    name: "reveal button label is platform-appropriate",
    ok: validLabels.includes(revealText),
    detail: revealText,
  });

  // Generate a test clip and run compress.
  const tmpDir = os.tmpdir();
  const testClip = path.join(tmpDir, "ffu_ca_in.mp4");
  const testOut = path.join(tmpDir, "ffu_ca_out.mp4");
  try {
    execFileSync("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
      "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
      "-c:v", "libx264", "-c:a", "aac", "-shortest", testClip,
    ]);
    results.checks.push({ name: "test clip generated", ok: true });
  } catch (e) {
    results.checks.push({ name: "test clip generated", ok: false, detail: String(e) });
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

  // Wait for the output file to appear (up to 30s).
  let produced = false;
  for (let i = 0; i < 150 && !produced; i++) {
    await new Promise((r) => setTimeout(r, 200));
    if (fs.existsSync(testOut)) produced = true;
  }
  results.checks.push({ name: "compress output produced", ok: produced });
  if (!produced) return finish();

  // Give the renderer a moment to process the "done" event and show the buttons.
  await new Promise((r) => setTimeout(r, 500));

  // The completion-actions div must now be visible.
  const visibleAfterRun = await win.webContents.executeJavaScript(
    `!document.querySelector('#completion-actions').classList.contains('hidden')`
  );
  results.checks.push({ name: "completion-actions visible after run", ok: visibleAfterRun });

  // Both buttons must exist and be enabled.
  const buttonsOk = await win.webContents.executeJavaScript(`
    (function() {
      const open = document.querySelector('#open-output');
      const reveal = document.querySelector('#reveal-output');
      return !!(open && reveal && !open.disabled && !reveal.disabled);
    })()
  `);
  results.checks.push({ name: "Open and Reveal buttons present and enabled", ok: buttonsOk });

  // Status bar must show "Done —" with the filename.
  const statusText = await win.webContents.executeJavaScript(
    `document.querySelector('#status').textContent`
  );
  results.checks.push({
    name: "status shows 'Done -' with filename",
    ok: statusText.startsWith("Done") && statusText.includes("ffu_ca_out"),
    detail: statusText,
  });

  try { fs.unlinkSync(testClip); } catch (_) {}
  try { fs.unlinkSync(testOut); } catch (_) {}
  finish();
}

app.whenReady().then(run);
