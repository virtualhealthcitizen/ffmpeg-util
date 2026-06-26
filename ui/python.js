// Resolve a Python interpreter that can actually run the sidecar.
//
// On Windows, `spawn('python')` often hits the Microsoft Store stub (a 0-byte app
// execution alias) which fails with exit 9009, and Node's spawn can't use pyenv's
// `python.bat` shim. So instead of trusting PATH, we probe concrete candidates and
// keep the first one that can `import ffmpeg_util, fastapi, uvicorn`. That import
// check doubles as a dependency check and naturally rejects the Store stub (it
// exits non-zero whenever it's run with arguments).

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

function candidates() {
  const list = [];
  if (process.env.FFMPEG_UTIL_PYTHON) {
    list.push({ cmd: process.env.FFMPEG_UTIL_PYTHON, args: [] });
  }
  // pyenv-win installed versions, by their real python.exe (skips the .bat shim).
  const root = process.env.PYENV_ROOT || path.join(os.homedir(), ".pyenv", "pyenv-win");
  try {
    const versions = fs.readdirSync(path.join(root, "versions")).sort().reverse();
    for (const v of versions) {
      list.push({ cmd: path.join(root, "versions", v, "python.exe"), args: [] });
    }
  } catch (_) {
    // no pyenv-win install — fine
  }
  // Windows launcher, then generic names (the latter may be Store stubs; the
  // import probe below filters those out).
  list.push({ cmd: "py", args: ["-3"] });
  list.push({ cmd: "python3", args: [] });
  list.push({ cmd: "python", args: [] });
  return list;
}

// Returns { cmd, args } for the first usable interpreter, or null if none work.
function resolvePython() {
  for (const c of candidates()) {
    try {
      const res = spawnSync(c.cmd, [...c.args, "-c", "import ffmpeg_util, fastapi, uvicorn"], {
        stdio: "ignore",
      });
      if (res.status === 0) return c;
    } catch (_) {
      // candidate not runnable — try the next
    }
  }
  return null;
}

module.exports = { resolvePython };
