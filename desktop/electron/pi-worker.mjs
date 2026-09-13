// SPDX-License-Identifier: GPL-3.0-or-later
import { Type } from "@sinclair/typebox";
import { changesSchema } from "./settings-tools.mjs";
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
  return runtime.getModels().map((m) => ({
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
設定操作はpreview_changesで対象項目だけを変更して提案を作成できます。説明・相談だけなら提案までにします。
ユーザーが「変更して」「反映して」など実行を指示した場合は、提案IDをapply_settingsに渡して保存してください。
現在のマウスへの変更を依頼された場合は、保存後にset_runtimeでローカル制御を有効化・適用し、device_applied=trueを確認します。
アプリ用プロファイルの作成だけなら、勝手にそのプロファイルを固定しません。保存だけと本体反映済みを区別して返答します。
各ツールの失敗は成功と報告しないでください。本体保存はsave_onboardで確認画面を開きます。
設定形式: version:1, profiles:[{name,apps:exe名の配列,dpi,dpi_levels,rate,buttons:{"1":action,...,"6":action}}],macros:{name:{mode,steps}}。
appsが空の既定プロファイルは1個。DPIは100〜25600の50刻み、dpi_levelsは現在値を含む1〜5個、rateは125/250/500/1000。
actionはmouse:1〜5、key:ctrl+cなど、macro:名前、dpi-cycle、none。
マクロmodeはonce/hold/toggle。stepsは{key:"ctrl+c",down:true}と対応するdown:false、{wait:100}、{mouse:1,down:true/false}。
ファームウェア情報はget_firmware_statusで確認できます。候補は固定ではなく公式カタログで照合します。
実機への転送・復旧は未検証です。ファームウェア書き込みは専用画面でのみ開始できます。
任意コマンド実行やファイル探索機能はありません。モデル提供元への送信はユーザーが選んだ接続先の設定に従います。`,
  });
  await loader.reload();
  const customTools = [
    {
      name: "preview_changes",
      label: "設定項目を変更",
      description:
        "Create a validated settings proposal using targeted operations. No write yet.",
      parameters: changesSchema,
      execute: async (_id, params) =>
        toolResult(await host("preview-changes", [params])),
    },
    {
      name: "apply_settings",
      label: "設定を保存・反映",
      description:
        "Apply a proposal when the user requested a change. Returns saved/runtime status; use set_runtime to apply to hardware.",
      parameters: Type.Object({ proposal_id: Type.String() }),
      execute: async (_id, params) =>
        toolResult(await host("apply-settings", [params])),
    },
    {
      name: "get_runtime",
      label: "本体と適用状態を確認",
      description:
        "Read hardware DPI, rate, battery and current runtime selection.",
      parameters: Type.Object({}),
      execute: async () => toolResult(await host("get-runtime")),
    },
    {
      name: "set_runtime",
      label: "ローカル制御とプロファイルを適用",
      description:
        "Enable/disable local control and optionally force a named profile (null restores automatic app switching). Verify DPI/rate readback.",
      parameters: Type.Object({
        enabled: Type.Optional(Type.Boolean()),
        profile: Type.Optional(Type.Union([Type.String(), Type.Null()])),
      }),
      execute: async (_id, params) =>
        toolResult(await host("set-runtime", [params])),
    },
    {
      name: "get_firmware_status",
      label: "純正ファームウェア情報を確認",
      description:
        "Read firmware status. Optionally fetch official public catalog. Never writes firmware.",
      parameters: Type.Object({
        refresh_catalog: Type.Optional(Type.Boolean()),
      }),
      execute: async (_id, params) =>
        toolResult(await host("get-firmware", [params])),
    },
    {
      name: "set_autostart",
      label: "Windows自動起動を設定",
      description:
        "Enable or disable Logi Local startup when explicitly requested.",
      parameters: Type.Object({ enabled: Type.Boolean() }),
      execute: async (_id, params) =>
        toolResult(await host("set-autostart", [params])),
    },
    {
      name: "save_onboard",
      label: "本体スロットへ保存",
      description:
        "Open a confirmation dialog to save a named saved profile to onboard slot 1. Returns cancelled or saved.",
      parameters: Type.Object({ profile: Type.String() }),
      execute: async (_id, params) =>
        toolResult(await host("save-onboard", [params])),
    },
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
        const text = message.selectedProfile
          ? `参考情報（UIで選択中のプロファイル名）: ${JSON.stringify(message.selectedProfile)}\n\n${message.text}`
          : message.text;
        await session.prompt(text, { expandPromptTemplates: false });
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
