// SPDX-License-Identifier: GPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import {
  applyMutations,
  handleSettingsTool,
} from "../electron/settings-tools.mjs";
import { BASE, settingsFixture } from "./settings-fixture.mjs";

test("targeted settings preserve unrelated profiles and keys", () => {
  const changed = applyMutations(BASE, [
    { op: "set_profile", name: "Desktop", dpi: 1650, rate: 500 },
    { op: "set_button", profile: "Desktop", button: "4", action: "key:ctrl+c" },
  ]);
  assert.equal(BASE.profiles[0].dpi, 1600);
  assert.deepEqual(changed.profiles[0].dpi_levels, [400, 800, 1650, 3200]);
  assert.equal(changed.profiles[0].buttons["1"], "mouse:1");
  assert.equal(changed.profiles[0].buttons["4"], "key:ctrl+c");
});
test("chat tool saves configuration only after apply, then separately verifies runtime", async () => {
  const context = settingsFixture();
  const proposal = await handleSettingsTool(
    "preview-changes",
    [
      {
        summary: "800 DPI",
        operations: [{ op: "set_profile", name: "Desktop", dpi: 800 }],
      },
    ],
    context,
  );
  assert.equal(context.writes.length, 0);
  const applied = await handleSettingsTool(
    "apply-settings",
    [{ proposal_id: proposal.id }],
    context,
  );
  assert.equal(applied.saved, true);
  assert.equal(applied.device_applied, false);
  assert.equal(context.config().profiles[0].dpi, 800);
  const runtime = await handleSettingsTool(
    "set-runtime",
    [{ enabled: true }],
    context,
  );
  assert.equal(runtime.device_applied, true);
  assert.equal(runtime.device.dpi, 800);
  assert.ok(
    context.events.some((event) => event.event === "pi-config-applied"),
  );
});
test("macro and app profile creation validate through the real Python schema", async () => {
  const context = settingsFixture();
  const proposal = await handleSettingsTool(
    "preview-changes",
    [
      {
        summary: "Game macro",
        operations: [
          { op: "create_profile", name: "Game", apps: ["game.exe"], dpi: 800 },
          {
            op: "put_macro",
            name: "Copy",
            mode: "once",
            steps: [
              { key: "ctrl+c", down: true },
              { wait: 20 },
              { key: "ctrl+c", down: false },
            ],
          },
          {
            op: "set_button",
            profile: "Game",
            button: "4",
            action: "macro:Copy",
          },
        ],
      },
    ],
    context,
  );
  await handleSettingsTool(
    "apply-settings",
    [{ proposal_id: proposal.id }],
    context,
  );
  assert.equal(context.config().profiles[1].buttons["4"], "macro:Copy");
  assert.deepEqual(context.config().profiles[0], BASE.profiles[0]);
});
test("invalid settings do not produce a proposal or mutate the saved configuration", async () => {
  const context = settingsFixture();
  await assert.rejects(
    handleSettingsTool(
      "preview-changes",
      [
        {
          summary: "Invalid",
          operations: [{ op: "set_profile", name: "Desktop", dpi: 123 }],
        },
      ],
      context,
    ),
  );
  assert.equal(context.writes.length, 0);
  assert.equal(context.proposals.items.size, 0);
});
test("onboard cancellation is returned and firmware write is not an agent operation", async () => {
  const context = settingsFixture();
  assert.deepEqual(
    await handleSettingsTool("save-onboard", [{ profile: "Desktop" }], context),
    { saved: false, cancelled: true },
  );
  await assert.rejects(handleSettingsTool("firmware-update", [], context));
  assert.deepEqual(
    await handleSettingsTool("set-autostart", [{ enabled: false }], context),
    { enabled: false },
  );
});
