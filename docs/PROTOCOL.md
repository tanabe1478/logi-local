# G703 HERO reverse engineering notes

**English** | [日本語](PROTOCOL.ja.md) · [Documentation](README.md)

Observed on 2026-09-11. No firmware patching or proprietary binary redistribution.
The local G HUB SQLite settings were read with SQLite in read-only mode; existing profile data was backed up and translated.
Public HID++ implementations informed framing and field offsets. Solaar-derived
profile handling and battery data are acknowledged in THIRD_PARTY_NOTICES.md;
this is not claimed as a clean-room implementation.

## Device and transport

- VID 046D, receiver PID C539, interface 2, usage page FF00, usage 2.
- Windows exposes the short and long HID++ collections separately. Open the long collection with hidapi.
- Long report: `[11, device=01, feature_index, (function<<4)|software_id, parameters padded to 16]`.
- Ping response: protocol 4.2, echoed marker 5A. Name: G703 LIGHTSPEED Wireless Gaming Mouse w/ HERO.
- Resolve feature indices dynamically through IRoot. Requests correlate device, feature and function/software ID;
  unsolicited notifications are dispatched separately.
- Device feature IDs observed: 0001, 0003, 0005, 1D4B, 0020, 1001, 8071, 8100, 8110, 8060, 2201,
  00C2 and additional manufacturer-internal features. Internal features are not
  used by normal mouse control. The later experimental updater is documented in
  [Firmware investigation](FIRMWARE.md).

## Proven operations

| Feature | Function | Meaning |
|---|---|---|
| 2201 | 1 / 2 / 3 | DPI list / current DPI / set DPI |
| 8060 | 0 / 1 / 2 | supported intervals / read / set polling interval |
| 1001 | 0 | big-endian millivolts and charging flags |
| 8110 | 0 | six physical buttons |
| 8110 | 1 / 2 | start / stop button reports |
| 8110 | 3 / 4 | get / set six-byte live mapping |
| 8100 | 0 | onboard descriptor |
| 8100 | 1 / 2 | set / get mode (1 onboard, 2 host) |
| 8100 | 3 / 4 | set / get active sector |
| 8100 | 5 | read 16 bytes: sector and offset, both big endian |
| 8100 | 6 / 7 / 8 | begin write / write chunk / finish write |
| 8100 | B / C | read / set current DPI stage |

8110 mapping read while G HUB's desktop profile was active: `01 02 03 00 00 00`.
Writing `01 02 03 04 05 00` was accepted and read back exactly. Entries map physical buttons to native mouse button numbers;
zero suppresses their normal HID output in host mode. Native mappings preserve ordinary click and drag behavior.
Only keyboard/macro/DPI actions require software handling. Event payload is a big-endian held-button bitmask.
Physical event behavior and game-side acceptance still require user verification on this installation.

## Onboard memory

Descriptor: `01 04 01 05 01 06 10 00 ff 0a 04 ...`

- Memory model 1, profile format 4, macro format 1.
- Five profile slots, six buttons, sixteen user sectors, **255 bytes per sector**.
- CRC16/CCITT-FALSE, initial FFFF, polynomial 1021, stored big endian in the last two bytes.
- Directory entries are four bytes: big-endian sector, enabled byte, reserved byte. FFFF terminates entries.
- Initial directory pointed at sectors 1–5 with only slot1 enabled. Directory CRC 4037; original profile1 CRC 2CAC.

The last read must start at offset239; append only its final15 bytes after the initial240 bytes. Reading offset240
or appending all16 duplicates/overruns the sector. This was diagnosed against the actual CRC and corrected.

Profile fields used:

| Offset | Meaning |
|---|---|
| 0 | report interval in ms |
| 1 / 2 | default DPI index / shift DPI index |
| 3–12 | five little-endian DPI values |
| 32 | six four-byte primary button bindings (remaining bank bytes preserved) |
| 160–207 | UTF-16LE profile name (preserved) |
| 253–254 | CRC for this unit's255-byte sector |

Button encodings: `80 01 mask16be` mouse, `80 02 modifiers usage` keyboard,
`80 00 ff ff` no action, `90 05 ff 00` cycle DPI.
All other profile bytes, including power-saving parameters, alternate buttons and lighting, are preserved.

A desktop profile was written to slot1 and full readback matched the write buffer.
The earlier snapshot was retained locally for restoration and is not published.
App switching never writes flash.

## Local runtime

Single HID owner thread serializes device commands, routes notifications, checks foreground process every200ms,
and reads battery/status every30s. Background macro workers use Windows SendInput with scan codes where available.
Output ownership is reference-counted; cancellation signals interrupt waits, then release outputs owned by that macro.
Normal mouse control uses no global keyboard hook, virtual driver installation,
shell-command macro, telemetry or cloud login. The desktop service uses an
authenticated local named pipe; optional Pi and firmware catalog access are
described in [Desktop and Pi integration](DESKTOP.md).

The legacy Tkinter GUI shares its process with the engine. The Electron GUI
connects to an independent Python service; closing that GUI leaves control running.
Clean service shutdown cancels macros, restores native mappings and onboard slot1.
Unplugged-device errors retry with a delay. Forced process termination and firmware-specific sleep behavior remain
operational limitations; re-enable local control after a failure, or switch the mouse off and back on.

## References

- [Logitech HID++ framing and feature list](https://github.com/Logitech/cpg-docs/blob/master/hidpp20/README.rst)
- [libratbag HID++ implementation](https://github.com/libratbag/libratbag/blob/master/src/hidpp20.c)
- [Solaar profile structures and battery-voltage estimation](https://github.com/pwr-Solaar/Solaar/blob/master/lib/logitech_receiver/hidpp20.py)
- [G403HID Windows implementation](https://github.com/clovervidia/G403HID)
- [MouseButtonSpy research](https://github.com/libratbag/libratbag/issues/1831)
- [MouseButtonSpy start/stop observations](https://gist.github.com/myaiexp/ce62498e0d702f2a3b289be58218822c)
- [Windows SendInput behavior and permission levels](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

Reference checkouts are not bundled. Adaptations and dependency licenses are
documented in THIRD_PARTY_NOTICES.md.
