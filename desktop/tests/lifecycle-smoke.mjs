// SPDX-License-Identifier: GPL-3.0-or-later
// Real local service/device test. Does not save or modify user configuration.
import { _electron as electron, expect } from "@playwright/test";
import path from "node:path";
import { PythonBridge } from "../electron/bridge.mjs";
const root = path.resolve("..");
async function state() {
  const bridge = new PythonBridge(root);
  try {
    return await bridge.request("runtime-get");
  } finally {
    bridge.disconnect();
  }
}
const before = await state();
for (let i = 0; i < 2; i++) {
  const app = await electron.launch({ args: ["."], cwd: process.cwd() });
  const child = app.process();
  try {
    const page = await app.firstWindow();
    await expect(page.getByLabel("DPI", { exact: true })).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByLabel("Pi モデル")).not.toHaveValue("", {
      timeout: 20000,
    });
    const exit = new Promise((resolve) => child.once("exit", resolve));
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await Promise.race([
      exit,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("GUI did not exit")), 10000).unref(),
      ),
    ]);
    const after = await state();
    expect(after.enabled).toBe(before.enabled);
    expect(after.active_profile).toBe(before.active_profile);
    expect(after.device.dpi).toBe(before.device.dpi);
    console.log(
      `GUI close/reopen ${i + 1}: control=${after.enabled}, DPI=${after.device.dpi}`,
    );
  } finally {
    if (child.exitCode === null) await app.close();
  }
}
