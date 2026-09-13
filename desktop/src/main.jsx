// SPDX-License-Identifier: GPL-3.0-or-later
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const api = window.logi;
const labels = [
  "左クリック",
  "右クリック",
  "ホイールクリック",
  "サイド後方",
  "サイド前方",
  "DPI ボタン",
];
const clone = (value) => JSON.parse(JSON.stringify(value));
function App() {
  const [config, setConfig] = useState(null),
    [saved, setSaved] = useState("");
  const [selected, setSelected] = useState(0),
    [tab, setTab] = useState("settings");
  const [status, setStatus] = useState(null),
    [enabled, setEnabled] = useState(false),
    [active, setActive] = useState("本体設定を使用");
  const [notice, setNotice] = useState("接続を確認しています…"),
    [fatal, setFatal] = useState(false);
  const [firmware, setFirmware] = useState(null),
    [fwBusy, setFwBusy] = useState(false),
    [fwProgress, setFwProgress] = useState(0),
    [fwStage, setFwStage] = useState("本体を確認してください");
  const [autostart, setAutostart] = useState(false),
    [macroName, setMacroName] = useState("");
  const [messages, setMessages] = useState([]),
    [text, setText] = useState(""),
    [chatBusy, setChatBusy] = useState(false),
    [chatStage, setChatStage] = useState("");
  const [models, setModels] = useState([]),
    [provider, setProvider] = useState(""),
    [model, setModel] = useState(""),
    [modelError, setModelError] = useState("");
  const [proposals, setProposals] = useState([]),
    [working, setWorking] = useState(false);
  const [naming, setNaming] = useState(false),
    [newName, setNewName] = useState("");
  const [remoteConflict, setRemoteConflict] = useState(false);
  const end = useRef(null),
    prefs = useRef({});
  const editor = useRef({ config: null, saved: "" });
  editor.current = { config, saved };
  const dirty = config && JSON.stringify(config) !== saved;
  const profile = config?.profiles[selected];
  const error = (e) =>
    setNotice(
      String(e.message || e).replace(
        /^Error invoking remote method '[^']+': Error: /,
        "",
      ),
    );
  async function run(op, args = []) {
    try {
      return await api.call(op, args);
    } catch (e) {
      error(e);
      throw e;
    }
  }
  async function action(op, args = []) {
    setWorking(true);
    try {
      await run(op, args);
    } catch {
    } finally {
      setWorking(false);
    }
  }
  const edit = (fn) =>
    setConfig((previous) => {
      const next = clone(previous);
      fn(next);
      return next;
    });
  const patchProfile = (patch) =>
    edit((c) => Object.assign(c.profiles[selected], patch));
  const adopt = (value) => {
    setConfig(value);
    setSaved(JSON.stringify(value));
    setSelected(0);
  };
  function event(message) {
    const { event: kind, value } = message;
    if (kind === "status") setStatus(value);
    if (kind === "dpi")
      setStatus((previous) => previous && { ...previous, dpi: value });
    if (kind === "enabled") setEnabled(value);
    if (kind === "profile") setActive(value);
    if (kind === "error" || kind === "message" || kind === "fatal")
      setNotice(value);
    if (kind === "fatal") setFatal(true);
    if (kind === "firmware-info") {
      setFirmware(value);
      setFwStage(value.reason);
    }
    if (kind === "firmware-progress") {
      setFwStage(value[0]);
      setFwProgress(value[1]);
    }
    if (kind === "firmware-error") setFwStage(value);
    if (kind === "firmware-busy") setFwBusy(value);
    if (kind === "pi-delta")
      setMessages((previous) => {
        const next = [...previous],
          last = next.length - 1;
        if (next[last]?.role === "assistant")
          next[last] = { ...next[last], text: next[last].text + value };
        return next;
      });
    if (kind === "pi-tool")
      setChatStage(
        value === "get_settings"
          ? "現在の設定を確認しています"
          : "変更案を検証しています",
      );
    if (kind === "pi-error") setChatStage(value);
    if (kind === "pi-done") {
      setChatBusy(false);
      setChatStage("");
    }
    if (kind === "pi-proposal")
      setProposals((previous) => [...previous, value]);
    if (kind === "autostart") setAutostart(value);
    if (kind === "pi-config-applied") {
      const current = editor.current;
      if (current.config && JSON.stringify(current.config) !== current.saved) {
        setRemoteConflict(true);
        setSaved(JSON.stringify(value.config));
        setNotice(
          "Piが設定を保存しました。未保存の編集は画面に保持しています。保存するとPiの変更を上書きするため、必要なら読み直してください。",
        );
      } else {
        adopt(value.config);
        setNotice("Piが設定を保存しました。適用結果はチャットで確認できます。");
      }
      setProposals((previous) => previous.filter((p) => p.id !== value.id));
    }
  }
  useEffect(() => {
    const off = api.onEvent(event);
    api
      .call("init")
      .then((value) => {
        adopt(value.config);
        setAutostart(value.autostart);
        prefs.current = value.settings;
        value.events.forEach(event);
        setNotice("設定はこのPCに保存されます。");
        return refreshModels(value.settings);
      })
      .catch(error);
    return off;
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, proposals, chatStage]);
  async function refreshModels(settings = prefs.current) {
    setModelError("");
    try {
      const values = await api.call("pi-models");
      setModels(values);
      const choice =
        values.find(
          (m) => m.provider === settings.provider && m.id === settings.model,
        ) ||
        values.find((m) => m.available) ||
        values[0];
      if (choice) {
        setProvider(choice.provider);
        setModel(choice.id);
      } else
        setModelError(
          "モデルがありません。Piの認証・models.jsonを確認してください。",
        );
    } catch (e) {
      setModelError(e.message);
    }
  }
  async function save() {
    if (
      remoteConflict &&
      !confirm("Piが保存した設定を、現在の編集内容で上書きしますか？")
    )
      return;
    setWorking(true);
    try {
      const value = await run("config-save", [config]);
      setConfig(value);
      setSaved(JSON.stringify(value));
      setRemoteConflict(false);
      setNotice("保存しました。本体への反映を確認しています…");
      try {
        const runtime = await run("runtime-set", [{ enabled: true }]);
        setEnabled(runtime.enabled);
        setActive(runtime.active_profile);
        setStatus(runtime.device);
        setNotice(
          runtime.active_profile === profile.name
            ? `保存・反映しました。本体から ${runtime.device.dpi} DPI を確認しました。`
            : `保存しました。現在は「${runtime.active_profile}」の ${runtime.device.dpi} DPI が有効です。編集中の設定は対象アプリに切り替えるか「この設定を固定」で適用できます。`,
        );
      } catch (e) {
        setNotice(
          `設定は保存済みですが、本体への反映に失敗しました: ${String(e.message || e)}`,
        );
      }
    } catch {
    } finally {
      setWorking(false);
    }
  }
  async function send() {
    if (!text.trim() || chatBusy || !model) return;
    const prompt = text.trim();
    setText("");
    setChatBusy(true);
    setChatStage("考えています…");
    setMessages((previous) => [
      ...previous,
      { role: "user", text: prompt },
      { role: "assistant", text: "" },
    ]);
    try {
      await api.call("pi-prompt", [
        { text: prompt, provider, model, selectedProfile: profile?.name },
      ]);
    } catch (e) {
      setMessages((previous) => [
        ...previous,
        { role: "error", text: e.message },
      ]);
    } finally {
      setChatBusy(false);
      setChatStage("");
    }
  }
  async function applyProposal(proposal) {
    if (
      dirty &&
      !confirm("編集中の未保存設定を破棄し、Piの変更案を反映しますか？")
    )
      return;
    try {
      const value = await run("pi-apply", [proposal.id]);
      adopt(value);
      setProposals((p) => p.filter((v) => v.id !== proposal.id));
      setNotice("Piの変更案を保存・反映しました。");
    } catch {}
  }
  const providers = [...new Set(models.map((m) => m.provider))].sort();
  const availableModels = models.filter((m) => m.provider === provider);
  const selectedModel = models.find(
    (m) => m.provider === provider && m.id === model,
  );
  const macro = config?.macros[macroName];
  return (
    <div className="app-shell">
      {naming && (
        <div className="dialog-backdrop">
          <form
            className="dialog"
            onSubmit={(e) => {
              e.preventDefault();
              const name = newName.trim();
              if (!name || config.macros[name]) return;
              edit(
                (c) =>
                  (c.macros[name] = { mode: "once", steps: [{ wait: 100 }] }),
              );
              setMacroName(name);
              setNaming(false);
            }}
          >
            <h3>マクロを作成</h3>
            <label>
              マクロ名
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <div className="inline-actions">
              <button type="button" onClick={() => setNaming(false)}>
                キャンセル
              </button>
              <button
                className="primary"
                disabled={
                  !newName.trim() || Boolean(config?.macros[newName.trim()])
                }
              >
                作成
              </button>
            </div>
          </form>
        </div>
      )}
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">L</span>
          <strong>Logi Local</strong>
          <span className="badge">DESKTOP</span>
        </div>
        <div className="top-status">
          <i className={status && !fatal ? "dot" : "dot off"} />
          {status && !fatal ? "G703 HERO 接続済み" : "接続を確認中"}
          <span className="separator" />
          ローカル制御{" "}
          <button
            className={"switch " + (enabled ? "on" : "")}
            aria-label="ローカル制御"
            aria-pressed={enabled}
            disabled={fwBusy || fatal}
            onClick={() => action("enable", [!enabled])}
          >
            <span />
          </button>
        </div>
      </header>
      <div className="workspace">
        <nav className="navigation">
          <div className="nav-label">WORKSPACE</div>
          {[
            ["settings", "◉", "マウス設定"],
            ["macros", "⌘", "マクロ"],
            ["device", "▣", "本体と設定"],
            ["firmware", "↥", "ファームウェア"],
          ].map(([id, icon, label]) => (
            <button
              key={id}
              className={tab === id ? "nav-item selected" : "nav-item"}
              onClick={() => setTab(id)}
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </button>
          ))}
          <div className="nav-bottom">
            <i className="dot" /> G HUB 不要
            <br />
            <small>あなたのPCで、あなたの設定を。</small>
          </div>
        </nav>
        <main className="main">
          <div className="page-title">
            <div className="eyebrow">YOUR MOUSE, YOUR RULES</div>
            <h1>
              {
                {
                  settings: "マウス設定",
                  macros: "マクロ",
                  device: "本体と設定",
                  firmware: "ファームウェア",
                }[tab]
              }
            </h1>
            <p>
              {enabled
                ? `適用中 · ${active}`
                : "本体設定で動作中 · アプリ別設定はローカル制御を有効にすると動作します"}
            </p>
          </div>
          {fatal && <div className="alert">{notice}</div>}
          {!config ? (
            <div className="card">設定を読み込み中…</div>
          ) : (
            <>
              {tab === "settings" && (
                <>
                  <div className="profile-toolbar">
                    <label>
                      プロファイル
                      <select
                        value={selected}
                        onChange={(e) => setSelected(Number(e.target.value))}
                      >
                        {config.profiles.map((p, i) => (
                          <option key={i} value={i}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      onClick={() => {
                        edit((c) =>
                          c.profiles.push({
                            ...clone(profile),
                            name: `新しい設定 ${Date.now().toString().slice(-4)}`,
                            apps: ["game.exe"],
                          }),
                        );
                        setSelected(config.profiles.length);
                      }}
                    >
                      ＋ 追加
                    </button>
                  </div>
                  <div className="device-card">
                    <div>
                      <span className="badge">LIGHTSPEED</span>
                      <h2>
                        G703 <span>HERO</span>
                      </h2>
                      <p>ワイヤレス ゲーミング マウス</p>
                      <div className="device-metrics">
                        <div>
                          <strong>{status?.dpi ?? "—"}</strong>
                          <small>DPI</small>
                        </div>
                        <div>
                          <strong>
                            {status ? 1000 / status.report_rate_ms : "—"}
                          </strong>
                          <small>Hz</small>
                        </div>
                        <div>
                          <strong>
                            {status?.battery?.percent ?? "—"}
                            <em>%</em>
                          </strong>
                          <small>
                            {status?.battery?.charging
                              ? "充電中"
                              : "電池残量（目安）"}
                          </small>
                        </div>
                      </div>
                    </div>
                    <svg
                      className="mouse-drawing"
                      viewBox="0 0 160 220"
                      aria-label="G703 マウス"
                    >
                      <path
                        d="M80 10 C30 10 20 65 23 136 C25 193 43 208 80 210 C117 208 135 193 137 136 C140 65 130 10 80 10Z"
                        fill="#202b31"
                        stroke="#5e7779"
                        strokeWidth="2"
                      />
                      <path
                        d="M80 11 L80 104 M25 105 Q80 121 135 105"
                        fill="none"
                        stroke="#5e7779"
                      />
                      <rect
                        x="72"
                        y="38"
                        width="16"
                        height="34"
                        rx="7"
                        fill="#77e7cb"
                      />
                      <rect
                        x="74"
                        y="85"
                        width="12"
                        height="17"
                        rx="5"
                        fill="#4b6669"
                      />
                      <path
                        d="M31 105L29 132M30 139L32 162"
                        stroke="#77e7cb"
                        strokeWidth="5"
                        strokeLinecap="round"
                      />
                      <text
                        x="80"
                        y="170"
                        textAnchor="middle"
                        fill="#77e7cb"
                        fontSize="30"
                      >
                        G
                      </text>
                    </svg>
                  </div>
                  <section className="card">
                    <div className="section-heading">
                      <h3>感度と応答速度</h3>
                      <span className="muted">最大 25,600 DPI</span>
                    </div>
                    <div className="dpi-value">
                      {profile.dpi.toLocaleString()} <span>DPI</span>
                    </div>
                    <input
                      aria-label="DPI"
                      className="dpi-range"
                      type="range"
                      min="100"
                      max="25600"
                      step="50"
                      value={profile.dpi}
                      onChange={(e) => {
                        const dpi = Number(e.target.value);
                        const levels = [...profile.dpi_levels];
                        levels[levels.indexOf(profile.dpi)] = dpi;
                        patchProfile({ dpi, dpi_levels: [...new Set(levels)] });
                      }}
                    />
                    <div className="range-label">
                      <span>100</span>
                      <span>25,600</span>
                    </div>
                    <div className="field-grid">
                      <label>
                        DPI 切り替え段階
                        <input
                          key={`${selected}-${profile.dpi_levels.join(",")}`}
                          defaultValue={profile.dpi_levels.join(", ")}
                          onBlur={(e) =>
                            patchProfile({
                              dpi_levels: e.target.value
                                .split(",")
                                .map((v) => Number(v.trim())),
                            })
                          }
                        />
                      </label>
                      <label>
                        レポートレート
                        <select
                          value={profile.rate}
                          onChange={(e) =>
                            patchProfile({ rate: Number(e.target.value) })
                          }
                        >
                          {[125, 250, 500, 1000].map((hz) => (
                            <option key={hz} value={hz}>
                              {hz} Hz
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  </section>
                  <section className="card">
                    <div className="section-heading">
                      <h3>ボタン割り当て</h3>
                      <span className="muted">6 BUTTONS</span>
                    </div>
                    {labels.map((label, i) => {
                      const key = String(i + 1),
                        value = profile.buttons[key];
                      const type = value.startsWith("key:")
                        ? "key"
                        : value.startsWith("macro:")
                          ? "macro"
                          : value;
                      return (
                        <div className="button-row" key={key}>
                          <span className="number">{key}</span>
                          <span className="button-name">{label}</span>
                          <select
                            aria-label={`${label}の割り当て`}
                            value={type}
                            onChange={(e) => {
                              const type = e.target.value;
                              edit(
                                (c) =>
                                  (c.profiles[selected].buttons[key] =
                                    type === "key"
                                      ? "key:ctrl+c"
                                      : type === "macro"
                                        ? `macro:${Object.keys(config.macros)[0]}`
                                        : type),
                              );
                            }}
                          >
                            {labels.slice(0, 5).map((name, j) => (
                              <option key={j} value={`mouse:${j + 1}`}>
                                {name}
                              </option>
                            ))}
                            <option value="key">キー / ショートカット</option>
                            <option
                              value="macro"
                              disabled={!Object.keys(config.macros).length}
                            >
                              マクロ
                            </option>
                            <option value="dpi-cycle">
                              DPI を順に切り替え
                            </option>
                            <option value="none">無効</option>
                          </select>
                          {type === "key" && (
                            <input
                              aria-label={`${label}のキー`}
                              value={value.slice(4)}
                              onChange={(e) =>
                                edit(
                                  (c) =>
                                    (c.profiles[selected].buttons[key] =
                                      `key:${e.target.value}`),
                                )
                              }
                            />
                          )}{" "}
                          {type === "macro" && (
                            <select
                              value={value.slice(6)}
                              onChange={(e) =>
                                edit(
                                  (c) =>
                                    (c.profiles[selected].buttons[key] =
                                      `macro:${e.target.value}`),
                                )
                              }
                            >
                              {Object.keys(config.macros).map((name) => (
                                <option key={name}>{name}</option>
                              ))}
                            </select>
                          )}
                        </div>
                      );
                    })}
                  </section>
                  <section className="card">
                    <h3>アプリ別設定</h3>
                    <div className="field-grid">
                      <label>
                        プロファイル名
                        <input
                          value={profile.name}
                          onChange={(e) =>
                            patchProfile({ name: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        対象アプリ（カンマ区切り）
                        <input
                          value={profile.apps.join(", ")}
                          placeholder="空欄は既定プロファイル"
                          onChange={(e) =>
                            patchProfile({
                              apps: e.target.value
                                ? e.target.value.split(",").map((v) => v.trim())
                                : [],
                            })
                          }
                        />
                      </label>
                    </div>
                    <div className="inline-actions">
                      <button onClick={() => action("force", [profile.name])}>
                        この設定を固定
                      </button>
                      <button onClick={() => action("force", [null])}>
                        アプリに合わせて切り替え
                      </button>
                      <button
                        className="danger"
                        disabled={!profile.apps.length}
                        onClick={() => {
                          edit((c) => c.profiles.splice(selected, 1));
                          setSelected(0);
                        }}
                      >
                        削除
                      </button>
                    </div>
                  </section>
                </>
              )}
              {tab === "macros" && (
                <>
                  <section className="card">
                    <div className="section-heading">
                      <h3>マクロライブラリ</h3>
                      <button
                        onClick={() => {
                          setNewName("");
                          setNaming(true);
                        }}
                      >
                        ＋ 作成
                      </button>
                    </div>
                    <select
                      value={macroName}
                      onChange={(e) => setMacroName(e.target.value)}
                    >
                      <option value="">マクロを選択</option>
                      {Object.keys(config.macros).map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                    </select>
                  </section>
                  {macro && (
                    <section className="card">
                      <h3>{macroName}</h3>
                      <label>
                        再生方法
                        <select
                          value={macro.mode}
                          onChange={(e) =>
                            edit(
                              (c) =>
                                (c.macros[macroName].mode = e.target.value),
                            )
                          }
                        >
                          <option value="once">1回実行</option>
                          <option value="hold">押している間繰り返す</option>
                          <option value="toggle">押すたびに開始 / 停止</option>
                        </select>
                      </label>
                      <div className="macro-steps">
                        {macro.steps.map((step, i) => (
                          <div className="step" key={i}>
                            <span className="number">{i + 1}</span>
                            <select
                              value={
                                "wait" in step
                                  ? "wait"
                                  : "key" in step
                                    ? "key"
                                    : "mouse"
                              }
                              onChange={(e) =>
                                edit(
                                  (c) =>
                                    (c.macros[macroName].steps[i] =
                                      e.target.value === "wait"
                                        ? { wait: 100 }
                                        : e.target.value === "key"
                                          ? { key: "a", down: true }
                                          : { mouse: 1, down: true }),
                                )
                              }
                            >
                              <option value="wait">待機</option>
                              <option value="key">キー</option>
                              <option value="mouse">マウス</option>
                            </select>
                            {"wait" in step ? (
                              <input
                                type="number"
                                aria-label="待機ミリ秒"
                                value={step.wait}
                                onChange={(e) =>
                                  edit(
                                    (c) =>
                                      (c.macros[macroName].steps[i].wait =
                                        Number(e.target.value)),
                                  )
                                }
                              />
                            ) : (
                              <>
                                <input
                                  aria-label="入力"
                                  value={step.key ?? step.mouse}
                                  onChange={(e) =>
                                    edit((c) => {
                                      const s = c.macros[macroName].steps[i];
                                      if ("key" in s) s.key = e.target.value;
                                      else s.mouse = Number(e.target.value);
                                    })
                                  }
                                />
                                <select
                                  value={String(step.down)}
                                  onChange={(e) =>
                                    edit(
                                      (c) =>
                                        (c.macros[macroName].steps[i].down =
                                          e.target.value === "true"),
                                    )
                                  }
                                >
                                  <option value="true">押す</option>
                                  <option value="false">離す</option>
                                </select>
                              </>
                            )}
                            <button
                              aria-label="ステップを削除"
                              onClick={() =>
                                edit((c) =>
                                  c.macros[macroName].steps.splice(i, 1),
                                )
                              }
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>
                      <div className="inline-actions">
                        <button
                          onClick={() =>
                            edit((c) =>
                              c.macros[macroName].steps.push({ wait: 100 }),
                            )
                          }
                        >
                          ＋ ステップ
                        </button>
                        <button
                          className="danger"
                          onClick={() => {
                            edit((c) => delete c.macros[macroName]);
                            setMacroName("");
                          }}
                        >
                          マクロを削除
                        </button>
                      </div>
                      <p className="muted">
                        キー・ボタンには「押す」と「離す」を用意してください。保存時に整合性を検証します。
                      </p>
                    </section>
                  )}
                </>
              )}
              {tab === "device" && (
                <>
                  <section className="card">
                    <h3>本体のオンボードメモリ</h3>
                    <p>
                      選択中: <strong>{profile.name}</strong>
                      。本体に保存すると、アプリ終了後も基本設定を使えます。
                    </p>
                    <div className="inline-actions">
                      <button onClick={() => action("backup")}>
                        全設定をバックアップ
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            await run("config-validate", [config]);
                            await action("onboard", [profile]);
                          } catch {}
                        }}
                      >
                        スロット1に保存
                      </button>
                      <button onClick={() => action("restore")}>
                        バックアップから復元
                      </button>
                    </div>
                    <p className="muted">
                      マクロの本体保存は未対応です。書き込み前にバックアップし、読み戻して検証します。
                    </p>
                  </section>
                  <section className="card">
                    <h3>設定の移行</h3>
                    <div className="inline-actions">
                      <button
                        onClick={async () => {
                          try {
                            const result = await run("ghub-import");
                            setConfig(result.config);
                            setSelected(0);
                            setNotice(
                              result.warnings.join("\n") ||
                                "取り込みました。内容を確認して保存してください。",
                            );
                          } catch {}
                        }}
                      >
                        G HUB から取り込む
                      </button>
                      <button onClick={() => action("ghub-stop")}>
                        G HUB を終了
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            const value = await run("config-import");
                            if (value) {
                              setConfig(value);
                              setSelected(0);
                              setNotice(
                                "読み込みました。保存すると反映されます。",
                              );
                            }
                          } catch {}
                        }}
                      >
                        JSON を読み込む
                      </button>
                      <button onClick={() => action("config-export", [config])}>
                        JSON を書き出す
                      </button>
                    </div>
                  </section>
                  <section className="card">
                    <h3>起動と常駐</h3>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={autostart}
                        onChange={async (e) => {
                          const value = e.target.checked;
                          try {
                            await run("autostart", [value]);
                            setAutostart(value);
                          } catch {}
                        }}
                      />
                      Windows起動時にローカル制御を開始
                    </label>
                    <p className="muted">
                      ウィンドウを閉じると通知領域に移動します。完全終了は通知領域のメニューから行えます。
                    </p>
                  </section>
                </>
              )}
              {tab === "firmware" && (
                <>
                  <section className="card">
                    <div className="section-heading">
                      <h3>純正ファームウェア</h3>
                      <span className="badge">実験的</span>
                    </div>
                    <div className="firmware-versions">
                      <div>
                        <small>本体</small>
                        <strong>{firmware?.version ?? "未確認"}</strong>
                      </div>
                      <span>→</span>
                      <div>
                        <small>対応済み候補</small>
                        <strong>{firmware?.candidate ?? "未確認"}</strong>
                      </div>
                    </div>
                    <p>
                      {firmware
                        ? firmware.wired
                          ? "USB ケーブル接続"
                          : "更新にはUSBケーブルが必要"
                        : "本体を接続して確認してください。"}{" "}
                      ·{" "}
                      {firmware?.cached
                        ? "純正ファイル検証済み"
                        : "ファイル未取得"}
                    </p>
                    <div className="inline-actions">
                      <button
                        disabled={working || fwBusy}
                        onClick={() => action("firmware-refresh")}
                      >
                        公式の更新候補を確認
                      </button>
                      <button
                        disabled={working || fwBusy}
                        onClick={() => action("firmware-check")}
                      >
                        本体を確認
                      </button>
                      <button
                        disabled={working || fwBusy}
                        onClick={() => action("firmware-download")}
                      >
                        純正ファイルを取得
                      </button>
                      <button
                        disabled={working || fwBusy}
                        onClick={() => action("firmware-import")}
                      >
                        取得済みファイルを選ぶ
                      </button>
                      <button
                        disabled={working || fwBusy}
                        onClick={() => action("firmware-reconcile")}
                      >
                        更新結果を再確認
                      </button>
                    </div>
                    <p className="muted">
                      公式カタログ確認:{" "}
                      {firmware?.catalog_checked_at
                        ? new Date(firmware.catalog_checked_at).toLocaleString()
                        : "未確認（初期候補）"}
                      <br />
                      この本体の書き込み完了記録:{" "}
                      {firmware?.hardware_write_verified
                        ? "確認済み"
                        : "未検証"}
                    </p>
                    <progress value={fwProgress} max="100" />
                    <p>{fwStage}</p>
                    <button
                      className="primary"
                      disabled={!firmware?.eligible || fwBusy || working}
                      onClick={() => action("firmware-update")}
                    >
                      更新内容を確認して実行
                    </button>
                  </section>
                  <div className="alert">
                    公式公開カタログから G703 HERO
                    の更新候補を取得・照合します。本体より新しい版の場合のみ更新できます。転送・復旧は実機未検証です。
                  </div>
                </>
              )}
            </>
          )}
          <footer className="savebar">
            {remoteConflict && (
              <button
                onClick={async () => {
                  try {
                    adopt(await run("config-get"));
                    setRemoteConflict(false);
                    setNotice("Piが保存した最新設定を読み込みました。");
                  } catch {}
                }}
              >
                最新設定を読み直す
              </button>
            )}
            <div className="notice" role="status">
              {notice}
            </div>
            <button
              className="primary"
              disabled={!config || working || fwBusy || fatal}
              onClick={save}
            >
              {dirty ? "変更を保存して反映" : "保存して反映"}
            </button>
          </footer>
        </main>
        <aside className="chat-sidebar">
          <div className="chat-header">
            <div className="pi-avatar">π</div>
            <div>
              <strong>Pi アシスタント</strong>
              <small>設定を、会話で。</small>
            </div>
            <button
              className="icon-button"
              title="会話をクリア"
              disabled={chatBusy}
              onClick={async () => {
                try {
                  await run("pi-reset");
                  setMessages([]);
                  setProposals([]);
                } catch {}
              }}
            >
              ↺
            </button>
          </div>
          <div className="model-picker">
            <select
              aria-label="Pi プロバイダー"
              disabled={chatBusy}
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                setModel(
                  models.find(
                    (m) => m.provider === e.target.value && m.available,
                  )?.id ||
                    models.find((m) => m.provider === e.target.value)?.id ||
                    "",
                );
              }}
            >
              <option value="">プロバイダーを選択</option>
              {providers.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            <select
              aria-label="Pi モデル"
              disabled={chatBusy}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              <option value="">モデルを選択</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                  {m.available ? "" : " · 認証を確認"}
                </option>
              ))}
            </select>
            <div className="model-meta">
              <span>
                {selectedModel?.available
                  ? "● Pi 認証・モデル設定を利用"
                  : "Pi の認証設定を確認してください"}
              </span>
              <button
                className="text-button"
                disabled={chatBusy}
                onClick={() => refreshModels({ provider, model })}
              >
                再読込
              </button>
            </div>
            {modelError && <p className="chat-error">{modelError}</p>}
          </div>
          <div className="chat-messages">
            {!messages.length && (
              <div className="chat-welcome">
                <span className="spark">✧</span>
                <h2>どんな設定にしますか？</h2>
                <p>操作に合ったDPIやマクロを、一緒に調整できます。</p>
                {[
                  "現在の設定を説明して",
                  "ゲーム用の800 DPI設定を作って",
                  "サイドボタンにコピーを割り当てたい",
                ].map((s) => (
                  <button
                    className="suggestion"
                    key={s}
                    onClick={() => setText(s)}
                  >
                    {s}
                    <span>↗</span>
                  </button>
                ))}
                <small>
                  「変更して」と伝えると保存・反映します。相談だけなら変更案を表示します。
                </small>
              </div>
            )}
            {messages.map((message, i) => (
              <div key={i} className={`message ${message.role}`}>
                <small>
                  {message.role === "user"
                    ? "あなた"
                    : message.role === "error"
                      ? "接続エラー"
                      : "π Pi"}
                </small>
                <div>
                  {message.text || (chatBusy ? "…" : "（応答テキストなし）")}
                </div>
              </div>
            ))}
            {chatStage && (
              <div className="chat-stage">
                <i className="dot" />
                {chatStage}
              </div>
            )}
            {proposals.map((proposal) => (
              <div className="proposal" key={proposal.id}>
                <span className="badge">変更案</span>
                <h4>{proposal.summary}</h4>
                <details>
                  <summary>変更前と変更後を確認</summary>
                  <small>変更前</small>
                  <pre>{JSON.stringify(proposal.before, null, 2)}</pre>
                  <small>変更後</small>
                  <pre>{JSON.stringify(proposal.config, null, 2)}</pre>
                </details>
                <button
                  className="primary"
                  disabled={fwBusy || chatBusy}
                  onClick={() => applyProposal(proposal)}
                >
                  この変更を反映
                </button>
                <button
                  className="text-button"
                  onClick={() =>
                    setProposals((p) => p.filter((v) => v.id !== proposal.id))
                  }
                >
                  見送る
                </button>
              </div>
            ))}
            <div ref={end} />
          </div>
          <div className="chat-composer">
            <textarea
              aria-label="Piへのメッセージ"
              placeholder="Pi に設定を相談する…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="composer-actions">
              <small>Enter 送信 · Shift+Enter 改行</small>
              {chatBusy ? (
                <button onClick={() => action("pi-abort")}>■ 停止</button>
              ) : (
                <button
                  className="send"
                  aria-label="送信"
                  disabled={!model || !text.trim()}
                  onClick={send}
                >
                  ↑
                </button>
              )}
            </div>
            <p>
              会話と必要な設定は選択したモデル提供元に送信されます。既存の Pi
              認証を使用します。
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
