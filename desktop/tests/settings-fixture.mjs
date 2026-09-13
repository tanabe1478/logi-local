// SPDX-License-Identifier: GPL-3.0-or-later
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { Proposals } from "../electron/proposals.mjs";
export const BASE = {
  version: 1,
  profiles: [
    {
      name: "Desktop",
      apps: [],
      dpi: 1600,
      dpi_levels: [400, 800, 1600, 3200],
      rate: 1000,
      buttons: {
        1: "mouse:1",
        2: "mouse:2",
        3: "mouse:3",
        4: "mouse:4",
        5: "mouse:5",
        6: "dpi-cycle",
      },
    },
  ],
  macros: {},
};
export function settingsFixture() {
  let config = structuredClone(BASE),
    runtime = { enabled: false, device: null };
  const writes = [],
    events = [];
  const root = fileURLToPath(new URL("../../", import.meta.url));
  function validate(value) {
    const result = spawnSync(
      path.join(root, ".venv/Scripts/python.exe"),
      [
        "-c",
        "import sys,json; from logilocal.config import validate; print(json.dumps(validate(json.load(sys.stdin))))",
      ],
      {
        cwd: root,
        input: JSON.stringify(value),
        encoding: "utf8",
        windowsHide: true,
      },
    );
    if (result.status !== 0)
      throw new Error(result.stderr || "Python validation failed");
    return JSON.parse(result.stdout);
  }
  const bridge = {
    request: async (op, args = []) => {
      if (op === "config-get") return structuredClone(config);
      if (op === "config-validate") return validate(args[0]);
      if (op === "config-save-expected") {
        assert.deepEqual(config, args[1]);
        config = validate(args[0]);
        writes.push(structuredClone(config));
        return config;
      }
      if (op === "runtime-get") return runtime;
      if (op === "runtime-set") {
        runtime = {
          ...args[0],
          device_applied: true,
          device: {
            dpi: config.profiles[0].dpi,
            report_rate_ms: 1000 / config.profiles[0].rate,
          },
        };
        return runtime;
      }
      throw new Error(`Unsupported fixture operation: ${op}`);
    },
  };
  return {
    bridge,
    proposals: new Proposals(bridge),
    emit: (message) => events.push(message),
    writes,
    events,
    config: () => config,
    setAutostart: async (enabled) => ({ enabled }),
    saveOnboard: async () => ({ saved: false, cancelled: true }),
  };
}
