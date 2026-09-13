// SPDX-License-Identifier: GPL-3.0-or-later
import { Type } from "@sinclair/typebox";
import {
  createAgentSession,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  DefaultResourceLoader,
  getAgentDir,
} from "@earendil-works/pi-coding-agent";

let runtime,
  session,
  busy = false;
const toolsPending = new Map();
let nextTool = 0;
const send = (message) => process.send?.(message);
const toolResult = (value) => ({
  content: [{ type: "text", text: JSON.stringify(value) }],
  details: {},
});
function host(op, args = []) {
  const id = String(++nextTool);
  return new Promise((resolve, reject) => {
    toolsPending.set(id, { resolve, reject });
    send({ tool: id, op, args });
  });
}
async function models() {
  if (runtime) await runtime.refresh({ allowNetwork: false });
  else runtime = await ModelRuntime.create({ allowModelNetwork: false });
  const available = new Set(
    (await runtime.getAvailable()).map((m) => `${m.provider}/${m.id}`),
  );
  return runtime
    .getModels()
    .map((m) => ({
      provider: m.provider,
      id: m.id,
      name: m.name,
      available: available.has(`${m.provider}/${m.id}`),
    }));
}
async function start(provider, modelId) {
  if (!runtime) await models();
  const model = runtime.getModel(provider, modelId);
  if (!model) throw new Error("プロバイダーとモデルを選択してください。");
  if (session) {
    await session.setModel(model);
    return;
  }
  const settingsManager = SettingsManager.inMemory();
  const loader = new DefaultResourceLoader({
    cwd: process.cwd(),
    agentDir: getAgentDir(),
    settingsManager,
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPrompt: `あなたはLogi Localの設定アシスタントPiです。日本語で簡潔に応答します。
G703 HEROのDPI・6ボタン・アプリ別プロファイル・マクロを支援します。
変更前にget_settingsで現在の設定を読み、既存設定を保持した完全な設定JSONをpropose_settingsへ渡してください。
propose_settingsは変更案を表示するだけで保存しません。ユーザーが画面の反映ボタンを押すまで変更済みと言わないでください。
設定形式: version:1, profiles:[{name,apps:exe名の配列,dpi,dpi_levels,rate,buttons:{"1":action,...,"6":action}}],macros:{name:{mode,steps}}。
appsが空の既定プロファイルは1個。DPIは100〜25600の50刻み、dpi_levelsは現在値を含む1〜5個、rateは125/250/500/1000。
actionはmouse:1〜5、key:ctrl+cなど、macro:名前、dpi-cycle、none。
マクロmodeはonce/hold/toggle。stepsは{key:"ctrl+c",down:true}と対応するdown:false、{wait:100}、{mouse:1,down:true/false}。
ファームウェアは専用画面で扱います。実機への転送・復旧は未検証で、対応済み候補は22.02.15です。
任意コマンド実行やファイル探索機能はありません。モデル提供元への送信はユーザーが選んだ接続先の設定に従います。`,
  });
  await loader.reload();
  const customTools = [
    {
      name: "get_settings",
      label: "現在の設定を確認",
      description: "Read current saved mouse settings.",
      parameters: Type.Object({}),
      execute: async () => toolResult(await host("get-settings")),
    },
    {
      name: "propose_settings",
      label: "設定の変更案を作成",
      description:
        "Validate and propose a complete config; does not save or apply.",
      parameters: Type.Object({
        summary: Type.String({ maxLength: 1000 }),
        configJson: Type.String({ maxLength: 200000 }),
      }),
      execute: async (_id, params) =>
        toolResult(await host("propose-settings", [params])),
    },
  ];
  ({ session } = await createAgentSession({
    cwd: process.cwd(),
    modelRuntime: runtime,
    model,
    settingsManager,
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(),
    tools: customTools.map((t) => t.name),
    customTools,
  }));
  session.subscribe((event) => {
    if (
      event.type === "message_update" &&
      event.assistantMessageEvent.type === "text_delta"
    )
      send({ event: "pi-delta", value: event.assistantMessageEvent.delta });
    if (event.type === "tool_execution_start")
      send({ event: "pi-tool", value: event.toolName });
    if (
      event.type === "message_end" &&
      event.message.role === "assistant" &&
      event.message.errorMessage
    )
      send({ event: "pi-error", value: event.message.errorMessage });
  });
}
process.on("message", async (message) => {
  if (message.toolReply) {
    const entry = toolsPending.get(message.toolReply);
    if (!entry) return;
    toolsPending.delete(message.toolReply);
    message.error
      ? entry.reject(new Error(message.error))
      : entry.resolve(message.result);
    return;
  }
  try {
    if (message.op === "models")
      send({ id: message.id, result: await models() });
    else if (message.op === "abort") {
      await session?.abort();
      send({ id: message.id, result: true });
    } else if (message.op === "reset") {
      if (busy) throw new Error("応答を停止してから会話をクリアしてください。");
      session?.dispose();
      session = undefined;
      send({ id: message.id, result: true });
    } else if (message.op === "prompt") {
      if (busy) throw new Error("応答中です。停止してから送信してください。");
      busy = true;
      try {
        await start(message.provider, message.model);
        await session.prompt(message.text, { expandPromptTemplates: false });
        send({ id: message.id, result: true });
      } finally {
        busy = false;
        send({ event: "pi-done", value: true });
      }
    }
  } catch (error) {
    send({ id: message.id, error: error.message });
  }
});
process.on("disconnect", () => {
  session?.dispose();
  process.exit(0);
});
