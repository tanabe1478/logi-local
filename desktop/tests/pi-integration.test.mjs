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

test(
  "Pi streams a response and uses only the two setting tools",
  { timeout: 90000 },
  async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "logi-pi-test-"));
    const requests = [];
    let worker;
    const events = [];
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
                name: "propose_settings",
                arguments: JSON.stringify({
                  summary: "800 DPIに変更",
                  configJson: '{"dpi":800}',
                }),
              },
            },
          ],
        });
      else
        chunk({
          role: "assistant",
          content: "800 DPIの変更案を作りました。画面で確認してください。",
        });
      res.write(
        `data: ${JSON.stringify({ id: "test", object: "chat.completion.chunk", created: 1, model: "fixture", choices: [{ index: 0, delta: {}, finish_reason: count < 3 ? "tool_calls" : "stop" }], usage: { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 } })}\n\n`,
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
      worker.on("message", (message) => {
        if (message.tool) {
          events.push(message.op);
          worker.send({
            toolReply: message.tool,
            result:
              message.op === "get-settings"
                ? { dpi: 1600 }
                : { proposed: true, applied: false },
          });
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
      assert.equal(requests.length, 3);
      assert.deepEqual(requests[0].tools.map((t) => t.function.name).sort(), [
        "get_settings",
        "propose_settings",
      ]);
      assert.ok(events.includes("get-settings"));
      assert.ok(events.includes("propose-settings"));
      assert.match(
        events
          .filter((e) => e.event === "pi-delta")
          .map((e) => e.value)
          .join(""),
        /変更案/,
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
