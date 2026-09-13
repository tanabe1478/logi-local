// SPDX-License-Identifier: GPL-3.0-or-later
import { app, BrowserWindow, ipcMain, dialog } from "electron";
import { fork } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import { PythonBridge } from "./bridge.mjs";
import { Proposals } from "./proposals.mjs";
import { handleSettingsTool } from "./settings-tools.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const startupArgs = [path.resolve(here, ".."), "--tray", "--enable"];
let window,
  bridge,
  proposals,
  worker,
  quitting = false,
  flashRequested = false;
let counter = 0;
const pending = new Map();
let recent = new Map();
let editorDirty = false,
  closing = false;
const preferences = path.join(root, "local/pi-ui.json");
async function setAutostart(enabled) {
  const actual = await bridge.request("service-autostart-set", [enabled]);
  await bridge.request("legacy-autostart-disable");
  app.setLoginItemSettings({
    openAtLogin: false,
    path: process.execPath,
    args: startupArgs,
  });
  if (actual !== enabled)
    throw new Error("自動起動設定を読み戻して確認できません。");
  emit({ event: "autostart", value: actual });
  return { enabled: actual };
}
async function saveOnboard(name) {
  const config = await bridge.request("config-get");
  const profile = config.profiles.find((p) => p.name === name);
  if (!profile) throw new Error("指定した保存済みプロファイルがありません。");
  const answer = await dialog.showMessageBox(window, {
    type: "question",
    buttons: ["キャンセル", "本体に保存"],
    defaultId: 0,
    cancelId: 0,
    message: `「${name}」を本体スロット1に保存しますか？`,
    detail: `${profile.dpi} DPI / ${profile.rate} Hz。先にバックアップを取得します。`,
  });
  if (answer.response !== 1) return { saved: false, cancelled: true };
  await bridge.request("onboard-expected", [profile]);
  return { saved: true, cancelled: false };
}
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
        if (flashRequested || bridge.busy)
          throw new Error("ファームウェア更新中です。");
        const result = await handleSettingsTool(
          message.op,
          message.args || [],
          { proposals, bridge, emit, setAutostart, saveOnboard },
        );
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
  if (closing) return;
  if (flashRequested || bridge?.busy) {
    window.show();
    emit({ event: "error", value: "ファームウェア更新中は終了できません。" });
    return;
  }
  closing = true;
  if (editorDirty) {
    const answer = await dialog.showMessageBox(window, {
      type: "question",
      buttons: ["編集を続ける", "保存せず閉じる"],
      defaultId: 0,
      cancelId: 0,
      message: "未保存の設定があります。画面を閉じますか？",
      detail: "保存済みの設定でマウス制御は続きます。",
    });
    if (answer.response !== 1) {
      closing = false;
      return;
    }
  }
  try {
    if (bridge && !bridge.dead) await bridge.request("shutdown");
  } catch (error) {
    emit({ event: "error", value: error.message });
    closing = false;
    return;
  }
  worker?.kill();
  bridge?.disconnect();
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
          void quit();
        }
      });
      ipcMain.handle("logi:call", async (event, op, args) => {
        if (
          event.sender !== window.webContents ||
          event.senderFrame !== window.webContents.mainFrame
        )
          throw new Error("不正な呼び出し元です。");
        if (!Array.isArray(args) || typeof op !== "string")
          throw new Error("不正な操作です。");
        if (op === "editor-state") {
          editorDirty = Boolean(args[0]);
          return true;
        }
        if (op === "init") {
          const oldAutostart =
            app.getLoginItemSettings({
              path: process.execPath,
              args: startupArgs,
            }).openAtLogin || (await bridge.request("legacy-autostart-get"));
          if (oldAutostart) await setAutostart(true);
          let settings = {};
          try {
            settings = JSON.parse(await fs.readFile(preferences, "utf8"));
          } catch {}
          return {
            config: await bridge.request("config-get"),
            settings,
            events: [...recent].map(([event, value]) => ({ event, value })),
            autostart: await bridge.request("service-autostart-get"),
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
          const { text, provider, model, selectedProfile } = args[0];
          if (typeof text !== "string" || !text.trim() || text.length > 20000)
            throw new Error("メッセージは1〜20000文字です。");
          await fs.mkdir(path.dirname(preferences), { recursive: true });
          await fs.writeFile(preferences, JSON.stringify({ provider, model }));
          return piCall("prompt", { text, provider, model, selectedProfile });
        }
        if (op === "pi-apply") return proposals.apply(args[0]);
        if (op === "autostart") {
          return setAutostart(Boolean(args[0]));
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
            "config-get",
            "config-validate",
            "runtime-set",
            "runtime-get",
            "status",
            "enable",
            "force",
            "backup",
            "onboard",
            "ghub-stop",
            "ghub-import",
            "firmware-check",
            "firmware-refresh",
            "firmware-reconcile",
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
      if (process.argv.includes("--enable"))
        await bridge.request("enable", [true]);
      if (process.argv.includes("--tray")) {
        await setAutostart(true);
        await quit();
      }
    })
    .catch((error) => {
      dialog.showErrorBox("Logi Local", error.message);
      quitting = true;
      app.quit();
    });
}
