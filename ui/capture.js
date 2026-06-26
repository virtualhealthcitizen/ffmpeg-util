// Dev utility: render the real UI (renderer + preload + sidecar) headlessly and
// save a PNG via Electron's capturePage(). Used to visually verify the UI without
// a visible window. Usage:
//   set CAPTURE_OUT=...png CAPTURE_INPUT=...mp4 ; electron capture.js

const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const net = require("net");
const fs = require("fs");
const { resolvePython } = require("./python");
const settingsStore = require("./settings");

// Match the real app's identity so getPath("userData") resolves to the same dir
// as `electron .` (otherwise it would default to "Electron").
app.setName("ffmpeg-util-ui");
// Allow tests to pin userData to a known dir (must be set before app is ready).
if (process.env.CAPTURE_USERDATA) {
  app.setPath("userData", process.env.CAPTURE_USERDATA);
}

const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
// Mirror main.js's settings handlers so the real load/save paths run during capture.
ipcMain.handle("settings:get", () => settingsStore.load(settingsFile()));
ipcMain.handle("settings:set", (_e, d) => {
  settingsStore.save(settingsFile(), d || {});
  return true;
});

const TOKEN = crypto.randomBytes(24).toString("hex");
const OUT = process.env.CAPTURE_OUT || path.join(__dirname, "capture.png");
const PROBE_INPUT = process.env.CAPTURE_INPUT || "";
let sidecar = null;

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

async function waitForHealth(p, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${p}/health`);
      if (res.ok) return true;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

async function run() {
  const port = await getFreePort();
  const py = resolvePython() || { cmd: process.env.FFMPEG_UTIL_PYTHON || "python", args: [] };
  sidecar = spawn(py.cmd, [...py.args, path.join(__dirname, "sidecar", "server.py")], {
    env: { ...process.env, SIDECAR_PORT: String(port), SIDECAR_TOKEN: TOKEN },
    stdio: ["ignore", "pipe", "pipe"],
  });
  await waitForHealth(port);

  const win = new BrowserWindow({
    width: 920,
    height: 760,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--sidecar-port=${port}`, `--sidecar-token=${TOKEN}`],
    },
  });

  await win.loadFile(path.join(__dirname, "renderer", "index.html"));
  await new Promise((r) => setTimeout(r, 800)); // let it paint

  const OP = process.env.CAPTURE_OP || "probe";
  const WAIT = Number(process.env.CAPTURE_WAIT || (OP === "compress" ? 700 : 2500));

  if (OP.startsWith("tab:")) {
    // Just switch to a tab and capture (used to show restored settings).
    const tab = OP.slice(4);
    await win.webContents.executeJavaScript(
      `document.querySelector('.tabs button[data-tab=${JSON.stringify(tab)}]').click();`
    );
    await new Promise((r) => setTimeout(r, WAIT));
  } else if (PROBE_INPUT && OP === "thumbnail") {
    // Generate a thumbnail and snapshot so the output preview is visible.
    const outGuess = PROBE_INPUT.replace(/\.[^.\\/]+$/, "") + ".thumb.png";
    const js = `
      (async () => {
        document.querySelector('.tabs button[data-tab="thumbnail"]').click();
        document.querySelector('#thumbnail-input').value = ${JSON.stringify(PROBE_INPUT)};
        document.querySelector('#thumbnail-output').value = ${JSON.stringify(outGuess)};
        document.querySelector('#thumbnail-time').value = "1";
        document.querySelector('#thumbnail-width').value = "320";
        document.querySelector('#run-thumbnail').click();
      })();
    `;
    await win.webContents.executeJavaScript(js);
    await new Promise((r) => setTimeout(r, WAIT));
  } else if (PROBE_INPUT && OP === "compress") {
    // Kick off a compress and snapshot mid-run so the progress bar is visible.
    const outGuess = PROBE_INPUT.replace(/\.[^.\\/]+$/, "") + ".small.mp4";
    const js = `
      (async () => {
        document.querySelector('.tabs button[data-tab="compress"]').click();
        document.querySelector('#compress-input').value = ${JSON.stringify(PROBE_INPUT)};
        document.querySelector('#compress-output').value = ${JSON.stringify(outGuess)};
        document.querySelector('#compress-crf').value = "28";
        document.querySelector('#compress-preset').value = "slow";
        document.querySelector('#run-compress').click();
      })();
    `;
    await win.webContents.executeJavaScript(js);
    await new Promise((r) => setTimeout(r, WAIT));
  } else if (PROBE_INPUT) {
    // Populate the input and run a real probe so the screenshot shows live output.
    const outGuess = PROBE_INPUT.replace(/\.[^.\\/]+$/, "") + ".out.mp4";
    const js = `
      (async () => {
        document.querySelector('#convert-input').value = ${JSON.stringify(PROBE_INPUT)};
        document.querySelector('#convert-output').value = ${JSON.stringify(outGuess)};
        document.querySelector('.probe-btn[data-source="convert-input"]').click();
      })();
    `;
    await win.webContents.executeJavaScript(js);
    await new Promise((r) => setTimeout(r, WAIT));
  }

  const image = await win.webContents.capturePage();
  fs.writeFileSync(OUT, image.toPNG());
  console.log("saved " + OUT);

  if (sidecar && !sidecar.killed) sidecar.kill();
  app.quit();
}

app.whenReady().then(run).catch((e) => {
  console.error(e);
  if (sidecar && !sidecar.killed) sidecar.kill();
  app.exit(1);
});
