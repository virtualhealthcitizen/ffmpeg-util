// Preload: expose the sidecar's loopback URL + per-launch token and the native
// file dialogs to the renderer. The renderer does the actual fetch() calls (it has
// the full web fetch API); the token is loopback-only so exposing it here is safe.

const { contextBridge, ipcRenderer, webUtils } = require("electron");

function readArg(name) {
  const prefix = `--${name}=`;
  const found = process.argv.find((a) => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : "";
}

contextBridge.exposeInMainWorld("sidecar", {
  baseUrl: `http://127.0.0.1:${readArg("sidecar-port")}`,
  token: readArg("sidecar-token"),
  pickFile: (defaultPath) => ipcRenderer.invoke("dialog:openFile", defaultPath),
  saveFile: (defaultPath) => ipcRenderer.invoke("dialog:saveFile", defaultPath),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (data) => ipcRenderer.invoke("settings:set", data),
  // Resolve the absolute path of a dropped File (Electron 32+ removed File.path).
  getPathForFile: (file) => webUtils.getPathForFile(file),
});
