// SPDX-License-Identifier: GPL-3.0-or-later
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("logi", {
  call: (op, args = []) => ipcRenderer.invoke("logi:call", op, args),
  onEvent: (callback) => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on("logi:event", listener);
    return () => ipcRenderer.removeListener("logi:event", listener);
  },
});
