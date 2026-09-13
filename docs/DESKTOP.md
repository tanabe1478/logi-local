# Desktop and Pi integration

The React renderer provides the settings editor and persistent right-hand chat
sidebar. Electron owns dialogs, tray, startup registration and two subprocesses:

- Python `-m logilocal.bridge`: the existing Engine is the only HID owner. Private
  stdin/stdout JSONL carries commands and events. No HTTP port is opened.
- `electron/pi-worker.mjs`: the pinned Pi SDK runs in Electron's Node runtime.
  The renderer receives model labels, text deltas and setting proposals only.

`contextIsolation`, renderer sandbox and a narrow preload IPC interface are
enabled. Renderer Node access, navigation, popups and network connections are
disabled. External model requests originate in the Pi process. The main process
validates IPC sender/frame and routes only supported operation names.

Pi uses the user's existing authentication and model configuration through
`ModelRuntime`. We disable extensions, context-file discovery, skills, prompt
templates and built-in coding tools. Only `get_settings` and `propose_settings`
are available. Every proposed JSON config is validated by Python. Applying a
proposal uses a compare-and-save operation on the HID owner queue to avoid stale
configuration overwrites. The agent cannot invoke that operation itself.

The firmware workflow retains its experimental status. The main process presents
a native confirmation dialog, blocks exit during the operation, and the backend
uses the existing version/identity/hash checks. Pi cannot start a firmware update.
If the Electron pipe closes during an update, Python waits for the in-flight
operation before normal shutdown. Forced OS termination remains outside this
guarantee.

The source launcher uses `desktop/node_modules/electron/dist/electron.exe` and
the existing `.venv`. This is a local source installation, not a new self-contained
portable EXE or an installer. `LogiLocal.exe` remains the old Tkinter build.
Closing the window hides it and preserves conversation; Electron and the Pi
worker stay resident until explicit exit. Removing that overhead while retaining
the Python background engine is future work.

## Validation

- Python: 41 tests, including existing device/firmware tests and atomic setting
  application / unsupported bridge operation rejection.
- Node: real Pi SDK against an isolated loopback OpenAI-compatible model fixture.
  Streaming, read-settings tool, proposal tool and reset are exercised. Assertions
  verify that no coding tools are exposed. No cloud model is contacted by this test.
- Proposal tests cover no write before approval, invalid JSON configuration and
  stale base rejection.
- Electron UI smoke test opens the real app and checks tabs, unsaved macro editing,
  firmware read-only state, model list and right sidebar placement. Captures at
  1450x920 and 1080x700 are stored in ignored `research/`. No settings are saved.
- Actual local Pi authentication was discovered and available models were listed.
  A live paid/cloud model prompt was not sent during implementation verification.

Run `npm test` in `desktop` for the isolated Pi/proposal tests. `npm run test:ui`
requires the development environment and the currently tested G703 HERO 22.02.15
device. Exit existing Logi Local instances first. Run Python tests from repository
root with `.venv\Scripts\python.exe -m unittest discover -s tests`.
