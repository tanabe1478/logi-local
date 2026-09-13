// SPDX-License-Identifier: GPL-3.0-or-later
import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import path from "node:path";

export class PythonBridge extends EventEmitter {
  constructor(root) {
    super();
    this.pending = new Map();
    this.counter = 0;
    this.busy = false;
    this.child = spawn(
      path.join(root, ".venv/Scripts/python.exe"),
      ["-u", "-m", "logilocal.service", "--relay"],
      {
        cwd: root,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      },
    );
    let buffer = "";
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => {
      buffer += chunk;
      let boundary;
      while ((boundary = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 1);
        try {
          const message = JSON.parse(line);
          if (message.event) {
            if (message.event === "firmware-busy") this.busy = message.value;
            this.emit("event", message);
          } else {
            const call = this.pending.get(message.id);
            if (!call) continue;
            clearTimeout(call.timer);
            this.pending.delete(message.id);
            message.error
              ? call.reject(new Error(message.error))
              : call.resolve(message.result);
          }
        } catch {
          this.emit("event", {
            event: "error",
            value: "制御プロセスから不正な応答がありました。",
          });
        }
      }
    });
    this.child.stderr.on("data", () => {});
    this.child.on("error", (error) => this.failed(error.message));
    this.child.on("exit", () =>
      this.failed(
        "マウス制御プロセスが終了しました。アプリを再起動してください。",
      ),
    );
  }
  failed(message) {
    this.dead = true;
    for (const call of this.pending.values()) {
      clearTimeout(call.timer);
      call.reject(new Error(message));
    }
    this.pending.clear();
    this.emit("event", { event: "fatal", value: message });
  }
  request(op, args = []) {
    if (this.dead)
      return Promise.reject(new Error("制御プロセスに接続できません。"));
    const id = String(++this.counter);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => {
          this.pending.delete(id);
          reject(
            new Error("処理がタイムアウトしました。状態を確認してください。"),
          );
        },
        op === "firmware-update" ? 1800000 : 90000,
      );
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(
        JSON.stringify({ id, op, args }) + "\n",
        (error) => {
          if (error) {
            clearTimeout(timer);
            this.pending.delete(id);
            reject(error);
          }
        },
      );
    });
  }
  disconnect() {
    this.child.stdin.end();
  }
}
