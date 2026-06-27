// Electron main process: pick a free port, launch the Python sidecar, wait for it
// to report healthy, then open the window. The renderer talks to the sidecar over
// loopback HTTP using a per-launch bearer token (so no other local process can use it).

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const net = require("net");
const { resolveSidecarLaunch } = require("./sidecar-launcher");
const settingsStore = require("./settings");

const TOKEN = crypto.randomBytes(24).toString("hex");
let sidecar = null;
let mainWindow = null;
let port = null;

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

function startSidecar(p) {
  const launch = resolveSidecarLaunch({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    baseDir: __dirname,
  });
  if (!launch) {
    console.error("[sidecar] No bundled binary and no usable Python interpreter found.");
    return false;
  }
  console.log(`[sidecar] mode=${launch.mode}: ${launch.cmd} ${launch.args.join(" ")}`.trimEnd());
  sidecar = spawn(launch.cmd, launch.args, {
    env: { ...process.env, SIDECAR_PORT: String(p), SIDECAR_TOKEN: TOKEN },
    stdio: ["ignore", "pipe", "pipe"],
  });
  sidecar.stdout.on("data", (d) => console.log(`[sidecar] ${d}`.trimEnd()));
  sidecar.stderr.on("data", (d) => console.error(`[sidecar] ${d}`.trimEnd()));
  sidecar.on("exit", (code) => console.log(`[sidecar] exited with ${code}`));
  return true;
}

async function waitForHealth(p, timeoutMs = 20000) {
  const url = `http://127.0.0.1:${p}/health`;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch (_) {
      // sidecar not up yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

async function createWindow() {
  port = await getFreePort();
  const started = startSidecar(port);
  const healthy = started && (await waitForHealth(port));

  mainWindow = new BrowserWindow({
    width: 920,
    height: 760,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--sidecar-port=${port}`, `--sidecar-token=${TOKEN}`],
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  if (!healthy) {
    console.error("Sidecar did not become healthy in time — check Python/deps.");
    dialog.showErrorBox(
      "Sidecar failed to start",
      "Could not start the Python sidecar.\n\n" +
        "Install Python 3 with the sidecar dependencies:\n" +
        "    pip install -r sidecar/requirements.txt\n\n" +
        "Or set FFMPEG_UTIL_PYTHON to a Python that has them installed."
    );
  }
}

ipcMain.handle("dialog:openFile", async () => {
  const res = await dialog.showOpenDialog(mainWindow, { properties: ["openFile"] });
  return res.canceled ? null : res.filePaths[0];
});

ipcMain.handle("dialog:saveFile", async (_e, defaultPath) => {
  const res = await dialog.showSaveDialog(mainWindow, { defaultPath: defaultPath || undefined });
  return res.canceled ? null : res.filePath;
});

const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
ipcMain.handle("settings:get", () => settingsStore.load(settingsFile()));
ipcMain.handle("settings:set", (_e, data) => {
  settingsStore.save(settingsFile(), data);
  return true;
});

function killSidecar() {
  if (!sidecar || sidecar.killed || sidecar.pid == null) return;
  // Kill the whole tree so any ffmpeg child the sidecar spawned dies too —
  // sidecar.kill() alone would orphan an in-progress ffmpeg on Windows.
  if (process.platform === "win32") {
    try {
      execFileSync("taskkill", ["/pid", String(sidecar.pid), "/T", "/F"], { stdio: "ignore" });
    } catch (_) {
      sidecar.kill();
    }
  } else {
    sidecar.kill();
  }
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  killSidecar();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", killSidecar);
process.on("exit", killSidecar);
