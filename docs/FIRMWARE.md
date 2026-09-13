# G703 HERO firmware investigation

2026-09-13. This implementation is experimental. No real firmware flashing was
performed. The connected device and the inspected official image both reported
22.02.15, so testing did not enter DFU or rewrite the same version.

## Evidence

- Wired runtime USB VID:PID: `046d:c090`, HID++ long collection ff00/2, index ff.
- Model IDs from feature 0003: `4086 c090 0000`.
- Firmware: application entity 1, `MPM 22.02.B0015`; boot `BL1 05.02.B0015`.
- Signed DFU control feature 00c2 was readable; availability bit was clear.
- Official installed G HUB depot metadata identifies wired C090 and boot AAF6,
  requires USB connection, and references `g703_hero_v22_02_15.dfu`.
- The same depot was downloaded from the official URL without running G HUB.
  The complete package hash matched installed metadata and the internal firmware
  hash matched `dfu.json`.

Official package:
<https://updates.ghub.logitechg.com/depots/58c73bea-abb7-4081-bf3a-9f4fd831ad09/g703_hero_dfu.depot>

Package SHA-256: `e6ba148ca26a38232dc9570da053fe3df13453fdac9b7db864dc63c79ebc5b82`

Image SHA-256: `16acefe9a081632d5f9a1dc69fa777eb145ea31bf085091e5ae8ca7668fc8d05`

The depot is 86404 bytes: magic 10 01 17 20, little-endian JSON length, JSON file
table, then a little-endian length and body for each file. It is parsed in memory
without extracting vendor-provided paths. The image is 78688 bytes, starts with
entity 1 and signed format 1, then `MPM22_D0`. These hashes pin the observed official
bytes; they are not an independent cryptographic signature verification by this
application. Signature acceptance is delegated to the device's signed DFU path.

## Transfer implementation and limits

Protocol sequence is adapted from
[fwupd's HID++ implementation](https://github.com/fwupd/fwupd/blob/main/plugins/logitech-hidpp/fu-logitech-hidpp-device.c).
This is protocol evidence, not proof of G703 compatibility.

1. Revalidate package, runtime identity, newer version, cable, and DFU availability.
2. Back up onboard settings and write a local update journal.
3. Enter signed DFU using 00c2 function 1, parameters `01 00 00 00 44 46 55`.
4. Open a unique AAF6 long HID collection and require its 0003 unit ID to match.
5. Transfer the entire image through 00d0 in 16-byte chunks, functions
   4, 1, 2, 3, 0, 1, 2, 3, 0, ...; wait for each response and any busy completion.
6. Send 00d0 function 5 with entity 1, then reopen runtime and verify its unit and version.

Boot enumeration, availability of boot unit IDs, asynchronous counter semantics,
actual transfer, and recovery have not been verified on a G703. The implementation
stops rather than weakening identity validation when these assumptions fail.
No automatic retry or recovery flashing is implemented. The journal is diagnostic
only. The GUI warns before any real update and blocks updates to equal/newer versions.
Windows automatic sleep is inhibited during DFU; forced shutdown/unplugging cannot
be prevented by the app.

The public latest-catalog endpoint has not been established. The known pinned
candidate must not be described as a live check of the globally latest firmware.
Adding a future release requires review of its official metadata, exact hashes,
target identities and image layout. No proprietary firmware, binaries, private
device identifiers or user settings are committed to Git.
