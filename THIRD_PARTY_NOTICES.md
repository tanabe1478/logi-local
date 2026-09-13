# Licensing and third-party notices

Logi Local project code is licensed under **GPL-3.0-or-later**.
Copyright (C) 2026 Logi Local contributors. See [LICENSE](LICENSE).
Third-party works retain their original copyrights and licenses.

This project is an independent, unofficial utility. It is not affiliated with,
endorsed by, or sponsored by Logitech / Logicool. Product names identify compatible
hardware; no vendor logos, firmware, executables, SDKs or G HUB database contents
are included in this source distribution.

## Electron desktop dependencies

The optional desktop frontend uses React / React DOM 19.2.4 (MIT; Copyright Meta
Platforms, Inc. and affiliates), Electron 44.3.0 (MIT; Copyright Electron contributors
and GitHub Inc.), Pi coding-agent 0.85.1 (MIT; Copyright 2025 Mario Zechner), and
TypeBox 0.34.48 (MIT; Copyright 2017–2026 Haydn Paterson).
License texts are included in `licenses/react-MIT.txt`, `licenses/electron-MIT.txt`,
`licenses/pi-MIT.txt` and `licenses/typebox-MIT.txt`.

Pi source corresponding to the pinned npm release:
<https://github.com/earendil-works/pi/tree/d981de1229ef899957bbe968bc8dcda02a21f477>.
The SDK is used as a dependency; we do not copy its agent implementation into
project code. The project remains GPL-3.0-or-later. These dependency licenses do
not license provider accounts, model weights or firmware.

`desktop/package-lock.json` pins transitive dependencies. Their own license files
remain in the installed packages. Electron includes additional Chromium/Node/V8
notices in its distribution (`LICENSE` and `LICENSES.chromium.html`). Preserve
those notices and review all bundled dependencies when producing a redistributable
binary; this repository does not publish a desktop binary bundle. Vite and
Playwright are development/test dependencies, not renderer runtime libraries.

## Adapted material and protocol research

### fwupd — LGPL-2.1-or-later

Copyright 2017 Richard Hughes.
Source: <https://github.com/fwupd/fwupd/blob/main/plugins/logitech-hidpp/fu-logitech-hidpp-device.c>
and <https://github.com/fwupd/fwupd/blob/main/plugins/logitech-hidpp/fu-logitech-hidpp.rs>.

`logilocal/firmware.py` adapts the signed HID++ DFU entry sequence, status handling,
16-byte transfer function rotation, and restart command into a Windows Python
transport. Changes include pinned G703 HERO package validation, strict device
identity checks, immediate asynchronous error handling, a local journal, and
post-reboot version verification. Adapted in September 2026 and distributed as
GPL-3.0-or-later. The upstream LGPL-2.1 text is included in
[licenses/fwupd-LGPL-2.1.txt](licenses/fwupd-LGPL-2.1.txt); the GPLv3 text is in LICENSE.
Upstream fwupd support does not establish that this G703 implementation works.

Official Logitech firmware is not included or relicensed. The optional downloader
retrieves a pinned package directly from Logitech for the user's own device.
Project GPL licensing does not grant rights to redistribute that vendor firmware.

### Solaar — GPL-2.0-or-later

Copyright (C) 2012–2013 Daniel Pavel.
Copyright (C) 2014–2024 Solaar Contributors.

Source: <https://github.com/pwr-Solaar/Solaar/blob/master/lib/logitech_receiver/hidpp20.py>

`logilocal/device.py` uses Solaar's battery voltage/percentage table and draws on
its onboard profile parsing and sector-tail handling. This is acknowledged as
adapted material, not claimed as a clean-room implementation. Modifications include
a Windows hidapi transport, standalone CRC checks, a compact linear interpolation
function, preservation of unmodified profile bytes, and guarded profile writes.
The code was adapted in September 2026. We exercise upstream's option to use a later
GPL version and distribute these adaptations as GPL-3.0-or-later. The full GPLv3
text is included in LICENSE; this does not change the upstream project's license.

### libratbag — MIT

Copyright 2015 Benjamin Tissoires.
Copyright 2015 Red Hat, Inc.

Source: <https://github.com/libratbag/libratbag/blob/master/src/hidpp20.c>

Used to establish HID++ command numbers, profile layout and read/write sequencing.
The applicable source-file copyright and permission text is retained in
[licenses/libratbag-MIT.txt](licenses/libratbag-MIT.txt).

### Other protocol references

Logitech cpg-docs, G403HID and MouseButtonSpy research are linked in
[docs/PROTOCOL.md](docs/PROTOCOL.md). They were consulted for interoperability
information. Their source files, documentation text and proprietary resources
are not redistributed here. G403HID had no license file in the inspected checkout;
it is not a dependency and its C# source is not incorporated in this project.

## Runtime dependencies

| Component | Version | License / included notice | Source |
|---|---|---|---|
| cython-hidapi | 0.15.0 | BSD option selected; [BSD](licenses/cython-hidapi-BSD.txt), [original notice](licenses/cython-hidapi-original.txt) | https://github.com/trezor/cython-hidapi |
| pystray | 0.19.5 | LGPL-3.0; [LGPL](licenses/LGPL-3.0.txt) and [GPL](LICENSE) | https://github.com/moses-palmer/pystray/tree/v0.19.5 |
| Pillow | 11.3.0 | MIT-CMU and notices contained in [Pillow license](licenses/Pillow.txt) | https://github.com/python-pillow/Pillow/tree/11.3.0 |
| six | 1.17.0 | [MIT](licenses/six.txt) | https://github.com/benjaminp/six/tree/1.17.0 |

These dependencies are installed by setup.ps1; their implementation files are not
vendored in the Git source tree. The cython-hidapi wheel also contains native HIDAPI;
its upstream licensing must be preserved when distributing that binary.

## Build tool

PyInstaller 6.16.0 is GPL-2.0-or-later with its bootloader/distribution exception.
The exception permits distributing the generated application under its own license;
it does not remove the licenses of bundled dependencies.
See [licenses/PyInstaller.txt](licenses/PyInstaller.txt) and
<https://github.com/pyinstaller/pyinstaller/tree/v6.16.0>.

## Source publication versus executable releases

This repository publishes source code, license notices and build instructions.
The locally built LogiLocal.exe, local settings, original G HUB databases and
research checkouts are deliberately excluded. No executable release is supplied
by the initial source publication.

Anyone distributing a bundled executable must also preserve notices for the
actual bundled components (including Python, Tcl/Tk, native HIDAPI and any Pillow
native libraries). Supply the corresponding application source and required
dependency source/build materials, with the executable version clearly tied to
its source revision. In particular, LGPL compliance requires an appropriate way
to rebuild/recombine with a modified pystray, not merely a link to this repository.
Use the GPL/LGPL texts for the complete terms; a standalone exe without the
necessary accompanying materials is not the intended public distribution format.
