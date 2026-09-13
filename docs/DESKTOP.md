# Desktop and Pi integration

**English** | [日本語](DESKTOP.ja.md) · [Documentation](README.md)

The React renderer provides the settings editor and persistent right-hand chat
sidebar. Electron owns dialogs and temporary GUI subprocesses:

- Python `-m logilocal.service`: an independent process owns the Engine and tray.
  It remains alive when the GUI exits. The GUI's temporary Python relay connects
  through a Windows named pipe authenticated with a random per-user key in
  `%LOCALAPPDATA%/LogiLocal/pipe.key`. Only bounded JSON bytes are accepted, never
  pickle objects. No TCP/HTTP port is opened. Request IDs are scoped to each
  connection so an old GUI response cannot satisfy a new GUI request.
- `electron/pi-worker.mjs`: the pinned Pi SDK runs in Electron's Node runtime.
  The renderer receives model labels, text deltas and setting proposals only.

`contextIsolation`, renderer sandbox and a narrow preload IPC interface are
enabled. Renderer Node access, navigation, popups and network connections are
disabled. External model requests originate in the Pi process. The main process
validates IPC sender/frame and routes only supported operation names.

Pi uses the user's existing authentication and model configuration through
`ModelRuntime`. We disable extensions, context-file discovery, skills, prompt
templates and built-in coding tools. Scoped tools cover reading, targeted profile /
button / macro edits, proposal application, runtime selection, startup, onboard
confirmation and read-only firmware checks. Every proposed JSON config is validated by Python. Applying a
proposal uses a compare-and-save operation on the HID owner queue to avoid stale
configuration overwrites. When the user requests an actual change, Pi can apply
the proposal itself. It separately applies runtime settings and checks hardware
DPI/rate readback before reporting device application. Mere consultation should
stop at a proposal. Firmware flashing remains unavailable to the agent.
The renderer receives applied-config events. An unsaved draft is preserved and a
reload/overwrite conflict is shown rather than silently discarding user edits.

The firmware workflow retains its experimental status. The main process presents
a native confirmation dialog, blocks exit during the operation, and the backend
uses the existing version/identity/hash checks. Pi cannot start a firmware update.
If Electron closes or crashes during an update, the independent HID owner
continues the operation. The service tray refuses exit during firmware transfer.
Forced OS termination remains outside this guarantee.

The source launcher uses `desktop/node_modules/electron/dist/electron.exe` and
the existing `.venv`. This is a local source installation, not a new self-contained
portable EXE. `Install-LogiLocal.ps1` installs this layout under
`%LOCALAPPDATA%/Programs/LogiLocal`, creates shortcuts, migrates initial settings
and backups, and registers service-only startup. It uses the existing Python
installation; it is not a standalone binary installer. Reinstallation preserves
the installed settings. `LogiLocal.exe` remains the old Tkinter build.
Closing the window exits Electron, Pi and the temporary relay. The lightweight
Python HID/tray service remains, retaining runtime selection, macros and app
switching. The tray's settings action or the launcher reconnects a new GUI.
Unsaved settings prompt before closing. Chat display is reset when reopening.
Use the tray's `マウス制御を終了` to stop control and return to onboard settings.
Startup registration launches `launch-service.py --enable` using pythonw, with
no GUI or Pi; existing startup settings migrate on first GUI initialization.

## Validation

- Python: 59 tests, including actual authenticated named-pipe disconnect/reconnect,
  response isolation, tray shutdown, existing device/firmware tests and atomic setting
  application / unsupported bridge operation rejection.
- Node: real Pi SDK against an isolated loopback OpenAI-compatible model fixture.
  Streaming, read-settings, targeted proposal, atomic saving, runtime application
  and reset are exercised. The actual Python config validator is used with
  in-memory test persistence and simulated hardware. Assertions
  verify that no coding tools are exposed. No cloud model is contacted by this test.
- Proposal tests cover no write before approval, invalid JSON configuration and
  stale base rejection.
- Electron UI smoke test opens the real app and checks tabs, unsaved macro editing,
  firmware read-only state, model list and right sidebar placement. Captures at
  1450x920 and 1080x700 are stored in ignored `research/`. No settings are saved.
- Actual local Pi authentication was discovered and available models were listed.
  A live paid/cloud model prompt was not sent during implementation verification.
- A separate headless Edge renderer fixture verifies that Pi changes update the
  editor, unsaved drafts survive concurrent agent updates, conflict reload works,
  and official-catalog state is rendered. It does not use the running user app.
- `npm run test:lifecycle` opens and closes the real Electron GUI twice, loads
  the Pi model list, waits for GUI process exit, and checks that the independent
  service preserves enabled state, profile and device DPI. Verified on the local
  G703 at 1100 DPI. After closing, no Logi Local Electron/Pi processes remained;
  the Python service plus virtualenv launcher used about 40 MB working set.

Run `npm test` in `desktop` for the isolated Pi/proposal tests. `npm run test:ui`
requires the development environment and the currently tested G703 HERO 22.02.15
device. Exit existing Logi Local instances first. Run Python tests from repository
root with `.venv\Scripts\python.exe -m unittest discover -s tests`.
