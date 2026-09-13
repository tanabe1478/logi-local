// SPDX-License-Identifier: GPL-3.0-or-later
// Isolated renderer fixture: no existing app or user settings are touched.
import { chromium, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { BASE } from "./settings-fixture.mjs";
const browser = await chromium.launch({ channel: "msedge", headless: true });
const staticRoot = path.resolve("dist");
const server = createServer(async (req, res) => {
  const target = path.resolve(
    staticRoot,
    "." + (req.url === "/" ? "/index.html" : req.url),
  );
  if (!target.startsWith(staticRoot + path.sep)) {
    res.writeHead(403);
    res.end();
    return;
  }
  try {
    const data = await readFile(target);
    res.setHeader(
      "Content-Type",
      target.endsWith(".js")
        ? "text/javascript"
        : target.endsWith(".css")
          ? "text/css"
          : "text/html",
    );
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
try {
  const page = await browser.newPage({
    viewport: { width: 1450, height: 920 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript((base) => {
    let config = structuredClone(base),
      listener,
      count = 0;
    window.logi = {
      onEvent: (callback) => {
        listener = callback;
        return () => {};
      },
      call: async (op, args = []) => {
        if (op === "init")
          return {
            config: structuredClone(config),
            settings: {},
            events: [],
            autostart: false,
          };
        if (op === "config-get") return structuredClone(config);
        if (op === "config-save") {
          config = structuredClone(args[0]);
          return structuredClone(config);
        }
        if (op === "runtime-set") {
          if (window.failApply) throw new Error("DPI readback mismatch");
          if (args[0].enabled !== true)
            throw new Error("Local control must be enabled");
          return {
            enabled: true,
            active_profile: config.profiles[0].name,
            device_applied: true,
            device: { dpi: config.profiles[0].dpi, report_rate_ms: 1 },
          };
        }
        if (op === "pi-models")
          return [
            {
              provider: "fixture",
              id: "fixture",
              name: "Fixture model",
              available: true,
            },
          ];
        if (op === "pi-prompt") {
          await new Promise((resolve) => setTimeout(resolve, 30));
          count++;
          config.profiles[0].dpi = count === 1 ? 800 : 3200;
          listener({
            event: "pi-config-applied",
            value: { id: "test", config: structuredClone(config) },
          });
          listener({
            event: "pi-delta",
            value: "設定を保存して適用しました。",
          });
          listener({ event: "pi-done", value: true });
          return true;
        }
        if (op === "firmware-refresh") {
          listener({
            event: "firmware-info",
            value: {
              version: "22.02.15",
              candidate: "22.02.15",
              cached: true,
              wired: true,
              eligible: false,
              catalog_checked_at: "2026-09-13T00:00:00Z",
              reason: "同じバージョンです。",
            },
          });
          return true;
        }
        throw new Error(`Unexpected renderer fixture operation: ${op}`);
      },
    };
  }, BASE);
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await expect(page.getByLabel("DPI", { exact: true })).toHaveValue("1600");
  await page.getByRole("button", { name: "保存して反映", exact: true }).click();
  await expect(
    page.getByText("保存・反映しました。本体から 1600 DPI を確認しました。"),
  ).toBeVisible();
  await page.evaluate(() => {
    window.failApply = true;
  });
  await page.getByRole("button", { name: "保存して反映", exact: true }).click();
  await expect(
    page.getByText(/設定は保存済みですが、本体への反映に失敗しました/),
  ).toBeVisible();
  await page.evaluate(() => {
    window.failApply = false;
  });
  await page.getByLabel("Piへのメッセージ").fill("DPIを800に変更して");
  await page.getByRole("button", { name: "送信", exact: true }).click();
  await expect(page.getByLabel("DPI", { exact: true })).toHaveValue("800");
  await page
    .getByLabel("プロファイル名", { exact: true })
    .fill("Unsaved draft");
  await page.getByLabel("Piへのメッセージ").fill("DPIを3200に変更して");
  await page.getByRole("button", { name: "送信", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "最新設定を読み直す" }),
  ).toBeVisible();
  await expect(page.getByLabel("プロファイル名", { exact: true })).toHaveValue(
    "Unsaved draft",
  );
  await page.getByRole("button", { name: "最新設定を読み直す" }).click();
  await expect(page.getByLabel("DPI", { exact: true })).toHaveValue("3200");
  await expect(page.getByLabel("プロファイル名", { exact: true })).toHaveValue(
    "Desktop",
  );
  await page
    .getByRole("button", { name: "ファームウェア", exact: true })
    .click();
  await page.getByRole("button", { name: "公式の更新候補を確認" }).click();
  await expect(
    page.getByRole("button", { name: "更新内容を確認して実行" }),
  ).toBeDisabled();
  await expect(page.getByText("同じバージョンです。")).toBeVisible();
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "Renderer passed: Pi saves update editor, unsaved drafts preserved, conflict reload, official catalog state.",
  );
} finally {
  await browser.close();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
}
