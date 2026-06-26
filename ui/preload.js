// Preload: expose the sidecar's loopback URL + per-launch token and the native
// file dialogs to the renderer. The renderer does the actual fetch() calls (it has
// the full web fetch API); the token is loopback-only so exposing it here is safe.

const { contextBridge, ipcRenderer } = require("electron");

function readArg(name) {
  const prefix = `--${name}=`;
  const found = process.argv.find((a) => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : "";
}

contextBridge.exposeInMainWorld("sidecar", {
  baseUrl: `http://127.0.0.1:${readArg("sidecar-port")}`,
  token: readArg("sidecar-token"),
  pickFile: () => ipcRenderer.invoke("dialog:openFile"),
  saveFile: (defaultPath) => ipcRenderer.invoke("dialog:saveFile", defaultPath),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (data) => ipcRenderer.invoke("settings:set", data),
});
