// SPDX-License-Identifier: GPL-3.0-or-later
import { randomUUID } from "node:crypto";
export class Proposals {
  constructor(bridge) {
    this.bridge = bridge;
    this.items = new Map();
    this.base = null;
  }
  async read() {
    const config = await this.bridge.request("config-get");
    this.base = JSON.stringify(config);
    return config;
  }
  async propose({ summary, configJson }) {
    if (!this.base) throw new Error("先に現在の設定を読み取ってください。");
    const config = await this.bridge.request("config-validate", [
      JSON.parse(configJson),
    ]);
    const value = {
      id: randomUUID(),
      summary,
      config,
      before: JSON.parse(this.base),
    };
    this.items.set(value.id, { ...value, base: this.base });
    return value;
  }
  async apply(id) {
    const proposal = this.items.get(id);
    if (!proposal) throw new Error("変更案が見つかりません。");
    const current = await this.bridge.request("config-get");
    if (JSON.stringify(current) !== proposal.base)
      throw new Error(
        "提案後に設定が変わりました。変更案を作り直してください。",
      );
    const saved = await this.bridge.request("config-save-expected", [
      proposal.config,
      JSON.parse(proposal.base),
    ]);
    this.items.delete(id);
    this.base = JSON.stringify(saved);
    return saved;
  }
}
