// SPDX-License-Identifier: GPL-3.0-or-later
import { Type } from "@sinclair/typebox";
const name = Type.String({ minLength: 1, maxLength: 120 });
const apps = Type.Array(Type.String(), { maxItems: 100 });
const dpi = Type.Integer({ minimum: 100, maximum: 25600, multipleOf: 50 });
const levels = Type.Array(dpi, { minItems: 1, maxItems: 5 });
const rate = Type.Union([125, 250, 500, 1000].map((v) => Type.Literal(v)));
const mode = Type.Union(["once", "hold", "toggle"].map((v) => Type.Literal(v)));
const fields = {
  dpi: Type.Optional(dpi),
  dpi_levels: Type.Optional(levels),
  rate: Type.Optional(rate),
  apps: Type.Optional(apps),
};
const step = Type.Union([
  Type.Object(
    { wait: Type.Integer({ minimum: 0, maximum: 60000 }) },
    { additionalProperties: false },
  ),
  Type.Object(
    { key: Type.String(), down: Type.Boolean() },
    { additionalProperties: false },
  ),
  Type.Object(
    { mouse: Type.Integer({ minimum: 1, maximum: 5 }), down: Type.Boolean() },
    { additionalProperties: false },
  ),
]);
export const changesSchema = Type.Object(
  {
    summary: Type.String({ maxLength: 1000 }),
    operations: Type.Array(
      Type.Union([
        Type.Object(
          {
            op: Type.Literal("set_profile"),
            name,
            ...fields,
            new_name: Type.Optional(name),
          },
          { additionalProperties: false },
        ),
        Type.Object(
          {
            op: Type.Literal("create_profile"),
            name,
            apps,
            copy_from: Type.Optional(name),
            dpi: Type.Optional(dpi),
            dpi_levels: Type.Optional(levels),
            rate: Type.Optional(rate),
          },
          { additionalProperties: false },
        ),
        Type.Object(
          { op: Type.Literal("delete_profile"), name },
          { additionalProperties: false },
        ),
        Type.Object(
          {
            op: Type.Literal("set_button"),
            profile: name,
            button: Type.Union(
              ["1", "2", "3", "4", "5", "6"].map((v) => Type.Literal(v)),
            ),
            action: Type.String(),
          },
          { additionalProperties: false },
        ),
        Type.Object(
          {
            op: Type.Literal("put_macro"),
            name,
            mode,
            steps: Type.Array(step, { minItems: 1, maxItems: 1000 }),
          },
          { additionalProperties: false },
        ),
        Type.Object(
          { op: Type.Literal("delete_macro"), name },
          { additionalProperties: false },
        ),
      ]),
      { minItems: 1, maxItems: 100 },
    ),
  },
  { additionalProperties: false },
);

export function applyMutations(config, operations) {
  const next = structuredClone(config);
  const profile = (name) => {
    const p = next.profiles.find((p) => p.name === name);
    if (!p) throw new Error(`プロファイルがありません: ${name}`);
    return p;
  };
  function patch(target, operation) {
    const oldDpi = target.dpi;
    for (const key of ["dpi", "dpi_levels", "rate", "apps"])
      if (operation[key] !== undefined)
        target[key] = structuredClone(operation[key]);
    if (
      operation.dpi !== undefined &&
      operation.dpi_levels === undefined &&
      !target.dpi_levels.includes(operation.dpi)
    ) {
      const index = target.dpi_levels.indexOf(oldDpi);
      if (index >= 0) target.dpi_levels[index] = operation.dpi;
      else target.dpi_levels.push(operation.dpi);
    }
    if (operation.new_name !== undefined) target.name = operation.new_name;
  }
  for (const operation of operations) {
    switch (operation.op) {
      case "set_profile":
        patch(profile(operation.name), operation);
        break;
      case "create_profile": {
        if (next.profiles.some((p) => p.name === operation.name))
          throw new Error("同名のプロファイルがあります。");
        const value = structuredClone(
          operation.copy_from
            ? profile(operation.copy_from)
            : next.profiles.find((p) => !p.apps.length),
        );
        value.name = operation.name;
        patch(value, operation);
        next.profiles.push(value);
        break;
      }
      case "delete_profile":
        profile(operation.name);
        next.profiles = next.profiles.filter((p) => p.name !== operation.name);
        break;
      case "set_button":
        profile(operation.profile).buttons[operation.button] = operation.action;
        break;
      case "put_macro":
        next.macros[operation.name] = {
          mode: operation.mode,
          steps: structuredClone(operation.steps),
        };
        break;
      case "delete_macro":
        if (!Object.hasOwn(next.macros, operation.name))
          throw new Error("マクロがありません。");
        delete next.macros[operation.name];
        break;
      default:
        throw new Error("不明な設定操作です。");
    }
  }
  return next;
}

export async function handleSettingsTool(
  op,
  args,
  { proposals, bridge, emit, setAutostart, saveOnboard },
) {
  if (op === "get-settings") return proposals.read();
  if (op === "propose-settings" || op === "preview-changes") {
    let input = args[0];
    if (op === "preview-changes") {
      const config = await proposals.read();
      input = {
        summary: input.summary,
        configJson: JSON.stringify(applyMutations(config, input.operations)),
      };
    }
    const proposal = await proposals.propose(input);
    emit({ event: "pi-proposal", value: proposal });
    return { proposed: true, id: proposal.id, applied: false };
  }
  if (op === "apply-settings") {
    const id = args[0].proposal_id;
    const config = await proposals.apply(id);
    emit({ event: "pi-config-applied", value: { id, config } });
    let runtime;
    try {
      runtime = await bridge.request("runtime-get");
    } catch (error) {
      runtime = { error: error.message };
    }
    return {
      saved: true,
      config,
      runtime,
      device_applied: false,
      note: "保存済みです。現在の本体への反映・検証には set_runtime を呼び出してください。",
    };
  }
  if (op === "get-runtime") return bridge.request("runtime-get");
  if (op === "set-runtime") return bridge.request("runtime-set", [args[0]]);
  if (op === "get-firmware")
    return bridge.request("firmware-status", [
      args[0]?.refresh_catalog === true,
    ]);
  if (op === "set-autostart") return setAutostart(args[0].enabled);
  if (op === "save-onboard") return saveOnboard(args[0].profile);
  throw new Error("未対応のPi操作です。");
}
