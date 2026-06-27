// Decide how to launch the sidecar:
//   1. a bundled standalone binary (PyInstaller) if present — no Python needed, or
//   2. a resolved Python interpreter + server.py (development).
//
// Packaged builds ship the binary under resources/. In development we deliberately
// run the live server.py so newly-added ops are picked up — a locally-built
// sidecar/dist/ binary is NOT auto-used (it would shadow the source and go stale);
// set FFMPEG_UTIL_SIDECAR to use a specific binary on purpose.

const fs = require("fs");
const path = require("path");
const { resolvePython } = require("./python");

const EXE = process.platform === "win32" ? "ffmpeg-util-sidecar.exe" : "ffmpeg-util-sidecar";

function bundledCandidates({ isPackaged, resourcesPath }) {
  const list = [];
  if (process.env.FFMPEG_UTIL_SIDECAR) list.push(process.env.FFMPEG_UTIL_SIDECAR);
  if (isPackaged && resourcesPath) {
    list.push(path.join(resourcesPath, "sidecar", EXE)); // electron-builder extraResources
    list.push(path.join(resourcesPath, EXE)); // @electron/packager --extra-resource
  }
  return list;
}

// Returns { cmd, args, mode } or null if nothing can launch the sidecar.
function resolveSidecarLaunch(opts = {}) {
  const baseDir = opts.baseDir || __dirname;
  for (const exe of bundledCandidates({ ...opts, baseDir })) {
    if (exe && fs.existsSync(exe)) return { cmd: exe, args: [], mode: "bundled" };
  }
  const py = resolvePython();
  if (py) {
    const dir =
      opts.isPackaged && opts.resourcesPath
        ? path.join(opts.resourcesPath, "sidecar")
        : path.join(baseDir, "sidecar");
    return { cmd: py.cmd, args: [...py.args, path.join(dir, "server.py")], mode: "python" };
  }
  return null;
}

module.exports = { resolveSidecarLaunch, EXE };
