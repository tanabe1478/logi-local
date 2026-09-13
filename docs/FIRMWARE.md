# G703 HERO firmware investigation

**English** | [日本語](FIRMWARE.ja.md) · [Documentation](README.md)

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

## Official catalog discovery

The public endpoint was subsequently established and fetched directly, without
G HUB execution or authentication:
<https://updates.ghub.logitechg.com/pipeline/v2/update/ghub13/win/public/details.json>.
It matched build 824196, version 2026.5.939708, and the same G703 HERO depot/hash.
The companion summary is
<https://updates.ghub.logitechg.com/pipeline/v2/update/ghub13/win/public/update.json>.

The app now fetches this specific official public channel on demand, selects only
`g703_hero_dfu`, checks origin/path/size/hash, then validates `dfu.json` target IDs,
manifest image mapping, image hash and signed image header. New versions in this
format can be discovered without updating constants. A vendor channel/layout
change will require a code update. Catalog identity is authenticated by HTTPS;
the catalog's separate signature field is not independently verified. Device
firmware signature enforcement remains delegated to the signed DFU path.

Packages use content-addressed local cache paths; candidate metadata is published
only after the corresponding file has been validated. A failed refresh retains
the old candidate and reports the error, rather than claiming a latest check.
No vendor firmware, binaries, private device IDs or user settings are committed.

## Completion criteria and remaining hardware gate

- Implemented/tested: official discovery, download validation, offline cache,
  target/version guards, transfer state machine, error handling, journal,
  post-reboot verification, no-op refusal, and read-only journal reconciliation.
- Observed on real hardware: normal wired runtime identity/version/DFU-availability
  reads. Current firmware equals the official candidate (22.02.15).
- **Not observed:** transition to AAF6, boot-side unit-ID behavior, real signed image
  transfer, successful old-to-new reboot, and recovery after an interrupted write.

A separate G703 HERO with older firmware is needed for the intended upgrade test.
Do not describe synthetic tests as proof of real G703 write/recovery compatibility,
or call the requested fully validated updater complete while this gate is open.

"Recheck update result" never enters DFU or sends image bytes. It can reconcile a
matching unit running the target version, or close a recorded pre-transfer failure
when that unit runs its original version. A partial-transfer failure is retained;
bootloader recovery/reflashing is not implemented or promised.
