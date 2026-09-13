// SPDX-License-Identifier: GPL-3.0-or-later
import {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  Tray,
  Menu,
  nativeImage,
} from "electron";
import { fork } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import { PythonBridge } from "./bridge.mjs";
import { Proposals } from "./proposals.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const startupArgs = [path.resolve(here, ".."), "--tray", "--enable"];
let window,
  tray,
  bridge,
  proposals,
  worker,
  quitting = false,
  flashRequested = false;
let counter = 0;
const pending = new Map();
let recent = new Map();
const preferences = path.join(root, "local/pi-ui.json");
const emit = (message) => {
  if (
    ["status", "enabled", "profile", "firmware-info", "fatal"].includes(
      message.event,
    )
  )
    recent.set(message.event, message.value);
  if (window && !window.isDestroyed())
    window.webContents.send("logi:event", message);
};
function pi() {
  if (worker) return worker;
  worker = fork(path.join(here, "pi-worker.mjs"), [], {
    cwd: root,
    windowsHide: true,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
    stdio: ["ignore", "ignore", "ignore", "ipc"],
  });
  worker.on("message", async (message) => {
    if (message.tool) {
      try {
        let result;
        if (message.op === "get-settings") result = await proposals.read();
        else if (message.op === "propose-settings") {
          const proposal = await proposals.propose(message.args[0]);
          emit({ event: "pi-proposal", value: proposal });
          result = { proposed: true, id: proposal.id, applied: false };
        } else throw new Error("未対応のPi操作です。");
        worker?.send({ toolReply: message.tool, result });
      } catch (error) {
        worker?.send({ toolReply: message.tool, error: error.message });
      }
    } else if (message.event) emit(message);
    else {
      const entry = pending.get(message.id);
      if (!entry) return;
      pending.delete(message.id);
      message.error
        ? entry.reject(new Error(message.error))
        : entry.resolve(message.result);
    }
  });
  const failed = () => {
    worker = undefined;
    for (const entry of pending.values())
      entry.reject(
        new Error("Piプロセスが終了しました。再送信で再起動できます。"),
      );
    pending.clear();
    emit({ event: "pi-done", value: true });
  };
  worker.on("exit", failed);
  worker.on("error", failed);
  return worker;
}
function piCall(op, fields = {}) {
  return new Promise((resolve, reject) => {
    const child = pi(),
      id = String(++counter);
    pending.set(id, { resolve, reject });
    child.send({ id, op, ...fields });
  });
}
async function quit() {
  if (flashRequested || bridge?.busy) {
    window.show();
    emit({ event: "error", value: "ファームウェア更新中は終了できません。" });
    return;
  }
  try {
    if (bridge && !bridge.dead) await bridge.request("shutdown");
  } catch (error) {
    emit({ event: "error", value: error.message });
    return;
  }
  worker?.kill();
  quitting = true;
  app.quit();
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    window?.show();
    window?.focus();
  });
  app.on("before-quit", (event) => {
    if (!quitting) {
      event.preventDefault();
      void quit();
    }
  });
  app
    .whenReady()
    .then(async () => {
      bridge = new PythonBridge(root);
      proposals = new Proposals(bridge);
      bridge.on("event", emit);
      window = new BrowserWindow({
        width: 1450,
        height: 920,
        minWidth: 1080,
        minHeight: 700,
        backgroundColor: "#101418",
        title: "Logi Local",
        autoHideMenuBar: true,
        webPreferences: {
          preload: path.join(here, "preload.cjs"),
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: true,
        },
      });
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event) => event.preventDefault());
      window.on("close", (event) => {
        if (!quitting) {
          event.preventDefault();
          window.hide();
        }
      });
      const icon = nativeImage.createFromDataURL(
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVQ4T2Nk+P+/HgY8gHFUw6gGo2E4DAAAufUf4Sk68KQAAAAASUVORK5CYII=",
      );
      tray = new Tray(icon);
      tray.setToolTip("Logi Local");
      tray.setContextMenu(
        Menu.buildFromTemplate([
          { label: "設定を開く", click: () => window.show() },
          { label: "終了", click: () => void quit() },
        ]),
      );
      tray.on("double-click", () => window.show());
      ipcMain.handle("logi:call", async (event, op, args) => {
        if (
          event.sender !== window.webContents ||
          event.senderFrame !== window.webContents.mainFrame
        )
          throw new Error("不正な呼び出し元です。");
        if (!Array.isArray(args) || typeof op !== "string")
          throw new Error("不正な操作です。");
        if (op === "init") {
          let settings = {};
          try {
            settings = JSON.parse(await fs.readFile(preferences, "utf8"));
          } catch {}
          return {
            config: await bridge.request("config-get"),
            settings,
            events: [...recent].map(([event, value]) => ({ event, value })),
            autostart:
              app.getLoginItemSettings({
                path: process.execPath,
                args: startupArgs,
              }).openAtLogin || (await bridge.request("legacy-autostart-get")),
          };
        }
        if (op === "pi-models") return piCall("models");
        if (op === "pi-abort") return piCall("abort");
        if (op === "pi-reset") {
          await piCall("reset");
          proposals.items.clear();
          return true;
        }
        if (op === "pi-prompt") {
          const { text, provider, model } = args[0];
          if (typeof text !== "string" || !text.trim() || text.length > 20000)
            throw new Error("メッセージは1〜20000文字です。");
          await fs.mkdir(path.dirname(preferences), { recursive: true });
          await fs.writeFile(preferences, JSON.stringify({ provider, model }));
          return piCall("prompt", { text, provider, model });
        }
        if (op === "pi-apply") return proposals.apply(args[0]);
        if (op === "autostart") {
          await bridge.request("legacy-autostart-disable");
          app.setLoginItemSettings({
            openAtLogin: Boolean(args[0]),
            path: process.execPath,
            args: startupArgs,
          });
          return true;
        }
        if (op === "config-export") {
          await bridge.request("config-validate", [args[0]]);
          const result = await dialog.showSaveDialog(window, {
            defaultPath: "logi-local.json",
            filters: [{ name: "設定", extensions: ["json"] }],
          });
          if (!result.canceled)
            await fs.writeFile(
              result.filePath,
              JSON.stringify(args[0], null, 2),
            );
          return !result.canceled;
        }
        if (["config-import", "restore", "firmware-import"].includes(op)) {
          const result = await dialog.showOpenDialog(window, {
            properties: ["openFile"],
            filters: [
              {
                name: "ファイル",
                extensions: op === "firmware-import" ? ["depot"] : ["json"],
              },
            ],
          });
          if (result.canceled) return null;
          if (op === "config-import")
            return bridge.request("config-validate", [
              JSON.parse(await fs.readFile(result.filePaths[0], "utf8")),
            ]);
          return bridge.request(op, [result.filePaths[0]]);
        }
        if (op === "firmware-update") {
          if (flashRequested) throw new Error("更新処理中です。");
          const result = await dialog.showMessageBox(window, {
            type: "warning",
            buttons: ["キャンセル", "更新を開始"],
            defaultId: 0,
            cancelId: 0,
            message: "G703 HERO の純正ファームウェアを更新しますか？",
            detail:
              "転送・復旧は実機未検証です。G HUBを終了し、完了までケーブルを抜かず、PCの電源を切らないでください。本体が候補より古い場合のみ実行します。",
          });
          if (result.response !== 1) return false;
          flashRequested = true;
          try {
            return await bridge.request(op);
          } finally {
            flashRequested = false;
          }
        }
        if (
          [
            "config-save",
            "config-validate",
            "status",
            "enable",
            "force",
            "backup",
            "onboard",
            "ghub-stop",
            "ghub-import",
            "firmware-check",
            "firmware-download",
          ].includes(op)
        ) {
          if (flashRequested) throw new Error("ファームウェア更新中です。");
          if (op === "onboard") {
            const result = await dialog.showMessageBox(window, {
              type: "question",
              buttons: ["キャンセル", "本体に保存"],
              defaultId: 0,
              cancelId: 0,
              message: "選択中の設定で本体スロット1を上書きしますか？",
              detail: "書き込み前に本体設定をバックアップします。",
            });
            if (result.response !== 1) return false;
          }
          return bridge.request(op, args);
        }
        throw new Error("未対応の操作です。");
      });
      await window.loadFile(path.resolve(here, "../dist/index.html"));
      if (process.argv.includes("--tray")) window.hide();
      if (process.argv.includes("--enable"))
        await bridge.request("enable", [true]);
    })
    .catch((error) => {
      dialog.showErrorBox("Logi Local", error.message);
      quitting = true;
      app.quit();
    });
}
