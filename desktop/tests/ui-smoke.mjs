// SPDX-License-Identifier: GPL-3.0-or-later
import { _electron as electron, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";
const app = await electron.launch({ args: ["."], cwd: process.cwd() });
try {
  const page = await app.firstWindow();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await expect(
    page.getByRole("heading", { name: "マウス設定", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("DPI", { exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(
    page.getByText("Pi アシスタント", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "マクロ", exact: true }).click();
  await page.getByRole("button", { name: "＋ 作成", exact: true }).click();
  await page
    .getByLabel("マクロ名", { exact: true })
    .fill("UI 検証用（未保存）");
  await page.getByRole("button", { name: "作成", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "UI 検証用（未保存）", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "＋ ステップ", exact: true }).click();
  await expect(page.locator(".step")).toHaveCount(2);
  await page.getByRole("button", { name: "本体と設定", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "本体のオンボードメモリ" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "ファームウェア", exact: true })
    .click();
  await page.getByRole("button", { name: "本体を確認", exact: true }).click();
  await expect(page.locator(".firmware-versions")).toContainText("22.02.15");
  await expect(
    page.getByRole("button", { name: "更新内容を確認して実行" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "マウス設定", exact: true }).click();
  await page.getByRole("button", { name: "現在の設定を説明して" }).click();
  await expect(page.getByLabel("Piへのメッセージ")).toHaveValue(
    "現在の設定を説明して",
  );
  await expect(page.getByLabel("Pi モデル").locator("option")).not.toHaveCount(
    1,
    { timeout: 30000 },
  );
  const sidebar = await page.locator(".chat-sidebar").boundingBox(),
    main = await page.locator("main").boundingBox();
  if (sidebar.x < main.x + main.width - 1)
    throw new Error("Sidebar overlaps main content");
  await fs.mkdir(path.resolve("../research"), { recursive: true });
  await page.screenshot({ path: path.resolve("../research/desktop-ui.png") });
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(1080, 700),
  );
  await page.screenshot({
    path: path.resolve("../research/desktop-ui-small.png"),
  });
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "Electron UI passed: tabs, macro editing, wired firmware read-only, right sidebar, model list. No settings saved or model prompt sent.",
  );
} finally {
  await app.evaluate(({ app }) => app.quit());
  await app.close();
}
