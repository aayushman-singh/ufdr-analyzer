/* eslint-disable @typescript-eslint/no-require-imports -- Electron preload is CommonJS */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  selectFile: () => ipcRenderer.invoke("select-file"),
});
