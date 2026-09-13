// SPDX-License-Identifier: GPL-3.0-or-later
// Real Pi SDK, isolated temporary credentials, loopback model fixture. No cloud calls.
import test from "node:test";
import assert from "node:assert/strict";
import { fork } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { handleSettingsTool } from "../electron/settings-tools.mjs";
import { settingsFixture } from "./settings-fixture.mjs";

test(
  "Pi reads, proposes, saves and applies through scoped tools and real config validation",
  { timeout: 90000 },
  async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "logi-pi-test-"));
    const requests = [];
    let worker;
    const events = [];
    const context = settingsFixture();
    let proposalId;
    const server = createServer(async (req, res) => {
      let body = "";
      for await (const chunk of req) body += chunk;
      const request = JSON.parse(body);
      requests.push(request);
      const count = requests.length;
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      const chunk = (delta) =>
        res.write(
          `data: ${JSON.stringify({ id: "test", object: "chat.completion.chunk", created: 1, model: "fixture", choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`,
        );
      if (count === 1)
        chunk({
          role: "assistant",
          tool_calls: [
            {
              index: 0,
              id: "read-1",
              type: "function",
              function: { name: "get_settings", arguments: "{}" },
            },
          ],
        });
      else if (count === 2)
        chunk({
          role: "assistant",
          tool_calls: [
            {
              index: 0,
              id: "propose-1",
              type: "function",
              function: {
                name: "preview_changes",
                arguments: JSON.stringify({
                  summary: "800 DPIに変更",
                  operations: [
                    { op: "set_profile", name: "Desktop", dpi: 800 },
                  ],
                }),
              },
            },
          ],
        });
      else if (count === 3 || count === 4)
        chunk({
          role: "assistant",
          tool_calls: [
            {
              index: 0,
              id: `action-${count}`,
              type: "function",
              function: {
                name: count === 3 ? "apply_settings" : "set_runtime",
                arguments: JSON.stringify(
                  count === 3 ? { proposal_id: proposalId } : { enabled: true },
                ),
              },
            },
          ],
        });
      else
        chunk({
          role: "assistant",
          content: "800 DPIを保存し、本体への適用結果を確認しました。",
        });
      res.write(
        `data: ${JSON.stringify({ id: "test", object: "chat.completion.chunk", created: 1, model: "fixture", choices: [{ index: 0, delta: {}, finish_reason: count < 5 ? "tool_calls" : "stop" }], usage: { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 } })}\n\n`,
      );
      res.end("data: [DONE]\n\n");
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      await writeFile(
        path.join(directory, "models.json"),
        JSON.stringify({
          providers: {
            fixture: {
              baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
              api: "openai-completions",
              apiKey: "fixture",
              models: [
                {
                  id: "fixture",
                  name: "Fixture",
                  reasoning: false,
                  contextWindow: 32000,
                  maxTokens: 1000,
                },
              ],
            },
          },
        }),
      );
      worker = fork(
        fileURLToPath(new URL("../electron/pi-worker.mjs", import.meta.url)),
        [],
        {
          cwd: directory,
          execArgv: [],
          silent: true,
          env: {
            ...process.env,
            PI_CODING_AGENT_DIR: directory,
            PI_OFFLINE: "1",
          },
        },
      );
      const pending = new Map();
      let next = 0,
        stderr = "";
      worker.stderr.on("data", (data) => (stderr += data));
      worker.on("message", async (message) => {
        if (message.tool) {
          events.push(message.op);
          try {
            const result = await handleSettingsTool(
              message.op,
              message.args || [],
              context,
            );
            if (result?.proposed) proposalId = result.id;
            worker.send({ toolReply: message.tool, result });
          } catch (error) {
            worker.send({ toolReply: message.tool, error: error.message });
          }
        } else if (message.event) events.push(message);
        else {
          const p = pending.get(message.id);
          pending.delete(message.id);
          if (p)
            message.error
              ? p.reject(new Error(message.error))
              : p.resolve(message.result);
        }
      });
      worker.on("exit", () => {
        for (const p of pending.values())
          p.reject(new Error(stderr || "worker exited"));
      });
      const call = (op, fields = {}) =>
        new Promise((resolve, reject) => {
          const id = String(++next);
          pending.set(id, { resolve, reject });
          worker.send({ id, op, ...fields });
        });
      const models = await call("models");
      assert.ok(models.some((m) => m.provider === "fixture" && m.available));
      await call("prompt", {
        provider: "fixture",
        model: "fixture",
        text: "800 DPIにしてください",
      });
      assert.equal(requests.length, 5);
      assert.deepEqual(requests[0].tools.map((t) => t.function.name).sort(), [
        "apply_settings",
        "get_firmware_status",
        "get_runtime",
        "get_settings",
        "preview_changes",
        "propose_settings",
        "save_onboard",
        "set_autostart",
        "set_runtime",
      ]);
      assert.ok(events.includes("get-settings"));
      assert.ok(events.includes("apply-settings"));
      assert.equal(context.config().profiles[0].dpi, 800);
      assert.equal(context.writes.length, 1);
      assert.match(
        events
          .filter((e) => e.event === "pi-delta")
          .map((e) => e.value)
          .join(""),
        /適用結果/,
      );
      await call("reset");
    } finally {
      worker?.kill();
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
      assert.equal(
        path.dirname(path.resolve(directory)),
        path.resolve(os.tmpdir()),
      );
      assert.ok(path.basename(directory).startsWith("logi-pi-test-"));
      await rm(directory, { recursive: true, force: true });
    }
  },
);
