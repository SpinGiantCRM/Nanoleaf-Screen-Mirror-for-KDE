# Custom firmware: chip identification and recovery investigation

2026-10-15 follow-up to [firmware latency research](FIRMWARE_LATENCY_RESEARCH.md).
User requirements: **keep the enclosure closed** and **no flashing until there is a recovery method**.

Follow-up: [closed-case research and historical-image comparison](CLOSED_CASE_FIRMWARE_RESEARCH.md).
Latest: [decoder model exclusions, product declaration and conditional backup
research](FIRMWARE_MODEL_FOLLOWUP.md). Chip identity and independent recovery
remain unverified.

## Current decision

**Do not flash this controller.** We now have an official stock application
update file, but no demonstrated independent bootloader-entry/recovery method,
no confirmed MCU marking and no understood custom-image encoding.

The strongest chip lead is still WCH CH552. It is not a confirmed identification
of this unit, and its exact package/suffix is unknown. No replacement board,
programmer, shorting sequence, factory reset or bootloader entry has been tried.

## Physical and software identity

| Evidence | Observation | What it establishes |
| --- | --- | --- |
| User's exterior-label photograph | **NL82K22**, input **5 V DC / 2 A** | Printed product model and power rating; no exposed chip |
| Existing USB model query | NL82K2 | Runtime protocol family, not a silicon identifier |
| Existing identity queries | Firmware 1.5 / hardware 1.1 / manufacturer G | Controller-reported versions; vendor app formats 1.5.0 / 1.1.0 |
| Existing kernel USB attributes | 37fa:8202, full-speed 12 Mbit/s, endpoint-zero size 64, one interface | Consistent with many USB MCUs; cannot identify a CH552 |
| Old vendor demo link | Repository named `nanoleaf/ch552_testing` | A CH552 lead for that development project; not proof of the production board |
| Official update image | Numbered opaque update records | Container structure, not a readable CPU architecture or package marking |

The supplied photograph contains a serial number/barcode. Neither the photograph
nor those identifiers are committed. The printed trailing `2` in NL82K22 is not
being interpreted as a chip revision, and no runtime VID/PID or mapping changes
are needed. The app's manual 48-zone configuration remains authoritative.

Targeted searches included NL82K2, NL82K22, N7601 product identifiers, MCU/PCB/
teardown terms and public source searches. No board-specific internal photograph,
schematic, chip marking or custom firmware was located. The public Nanogrid FCC
index did not provide an NL82 entry; that absence does not establish that no
filing exists. Other Nanoleaf panel/4D teardowns concern different boards.
The vendor demo Git/raw/API remained unavailable, and the attempted archive
index returned no matching captures. These are search limits, not proof that
source or drawings do not exist privately.

## New finding: the stock update file is obtainable

The previous normal update check returned no newer image for installed 1.5.0.
That remains true. However, static inspection of official Desktop 3.0.1 revealed
a separate recovery-object request: when it sees its vendor bootloader product,
it checks availability with empty firmware/hardware version fields.

We reproduced **only that HTTPS metadata request**, with the actual unit's serial
sent to the manufacturer's firmware service. The strip stayed in application
mode. No USB command was sent for this follow-up investigation; existing kernel
attributes were read instead.

The service returned HTTP 200, `update_status: required`, `new_firmware_ver: 1.5.0`
and the following public vendor URL:

[Official NL82K2 1.5.0 application update](https://nl82k2-firmware.s3.amazonaws.com/1.5.0.firmware)

The `required` result applies to the **empty-version recovery metadata request**;
it does not mean that our running 1.5.0 installation needs an upgrade or that the
physical device entered DFU.

Downloaded file:

- Size: **10,431 bytes**.
- SHA-256: **05ae98ac932d18fb9bf1579e744401827f9ac068347cdb968426363ec45ef3de**.
- Server last-modified: 2025-09-01 02:45:34 GMT.
- Stored privately for offline research; never executed, sent to USB or flashed.
- It is a vendor application-update container, **not a byte-for-byte dump of this
  unit's complete flash, bootloader, configuration or persistent factory data**.

Availability and version match make this a recovery asset. They do not establish
compatibility with every board suffix, successful restoration, image signature
validity or preservation of factory data after an erase. The vendor's recovery
request itself omits hardware revision; board compatibility needs confirmation.

### Offline analysis

The file divides exactly into **171 records of 61 bytes**. Every record begins
with version byte `0x15` and a consecutive big-endian index from 0 through 170.
The [historical vendor protocol](https://nanoleaf.atlassian.net/wiki/pages/viewpage.action?pageId=2615574530&pageVersion=3)
assigns the remaining fields to 56 data bytes and two CRC bytes. Under that
layout, the payload totals **9,576 bytes**.

Its measured data-field entropy is about **7.9784 bits per byte**. Simple searches
found no plaintext NL82K2, CH552 or NLUSB marker. Thirty-six common CRC-16
parameter combinations over each proposed 59-byte prefix did not reproduce the
trailers. The public spec does not specify the polynomial or fully explain the
encoding. Consequently, **the CRC has not been validated**. This result does not
prove the vendor file is corrupt: the layout, calculation stage or encoding may
differ from our assumptions.

High entropy and the historical decryption-error code support an encoding/
encryption hypothesis, but identify neither a cipher nor a signing policy.
Compression or other packaging can also obscure architecture. Disassembling these
opaque bytes as 8051 instructions would not identify the chip reliably. No
cryptographic key, CPU identification or modified executable image was obtained.

The official desktop updater forwards records from the downloaded file; it does
not construct them from a user-supplied raw program. Thus its presence alone does
not give us the ability to package custom firmware.

## Recovery routes are separate questions

### 1. Nanoleaf's vendor loader

Desktop 3.0.1 recognizes `NLUSB-BL`, erases application storage, writes numbered
blocks, checks replies and reboots. This is vendor TLV/HID updating, not evidence
of USB DFU-class or WCH ISP compatibility.

Unresolved: whether the loader survives all application writes; whether reset
vectors/configuration are protected; how it starts when the application cannot
run; and whether recovery preserves serial/factory settings. An application
command that enters DFU is insufficient to recover an application that no longer
runs. A factory reset is not a demonstrated application reinstallation procedure.

### 2. WCH USB ISP, if the silicon and loader support it

The manufacturer's **CH552 datasheet V1G**, sections 6.2 and 6.6, places the loader
in flash and makes startup/read protection configurable. It says loss of the
loader requires a dedicated external programmer. Read protection can prevent
external backup; clearing it by erase destroys the data we want to preserve.
These are conditional CH552 properties, not measured settings on this unit.

[Manufacturer-authored datasheet, distributor-hosted copy](https://cdn-learn.adafruit.com/assets/assets/000/129/847/original/CH552DS1.PDF)

Do not assume an immutable ROM rescue loader. Do not change protection/startup
bits to obtain a dump. No candidate boot pin is identified for this PCB, and
keyboard-board boot straps are not a safe substitute for tracing this board.

[wchisp](https://github.com/ch32-rs/wchisp) and
[isp55e0](https://github.com/frank-zago/isp55e0) implement WCH-family ISP; neither
was installed or run against the controller. The former explicitly marks CH552
support as potentially buggy. The latter's program verification sends candidate
bytes for an internal comparison; it is not protected-code readback.

A Nanoleaf `.firmware` container must not be passed to a generic raw-image
programmer. Even a confirmed CH552 does not establish that its stock WCH loader
is present, reachable or accepts this vendor container.

### 3. External programmer

Potentially useful only after identifying the exact chip/package, circuit and
supported programmer. Before any write we need read-only protection/configuration
identification and, if permitted, repeatable matching dumps of application,
loader, persistent data and configuration. A read-protected unit may make full
backup unavailable. A public application update file does not replace those
missing regions. No pads were probed, enclosure opened, programmer connected or
protection bits changed.

## What must be established before custom flashing

| Gate | Status | Evidence needed |
| --- | --- | --- |
| Exact physical MCU/package and PCB revision | **Open** | Manufacturer confirmation, matching BOM/schematic or authenticated board-specific source |
| LED IC/protocol, power/current path and pins | **Open** | Board-specific manufacturer documentation or authenticated source; no internal probing in this investigation |
| Official application update asset | **Obtained** | Vendor URL, version, size and pinned SHA above |
| Loader/factory-data preservation | **Open** | Memory map and protected regions; backups where readable, otherwise a supported replacement route |
| Recovery entry independent of application | **Open** | Documented closed-case recovery entry that works with a broken application and a way back to normal operation |
| Safe stock restoration procedure | **Open** | Manufacturer-supported closed-case procedure with matching image/loader and factory-data preservation established |
| Custom-image format and acceptance | **Open** | Source/tooling or understood encoding/signature policy; no blind edits |
| Latency/colour justification | **Open** | Light-output timing plus byte/colour/reconnect tests after a recoverable prototype exists |

The user has explicitly ruled out opening the enclosure. Continue with public
records, offline vendor-package analysis and manufacturer documentation. Do not
ask for internal photos, probing, boot-pin shorting or a spare controller. The
external-programmer discussion above is conditional background, not a proposed
step for this closed-case investigation.

The next useful evidence is manufacturer confirmation of the exact MCU and a
closed-case recovery procedure that works when the application cannot run.
Neither stock update availability nor a bootloader product name satisfies the
no-flash requirement. A manufacturer enquiry has been sent with explicit user
approval; chip identity and recovery remain unconfirmed pending evidence.

## Reproducible inspection and preservation

An operator-only Rust binary, `firmware_inspect`, reads a bounded local regular
file and requires an independently recorded expected SHA-256. It checks record
alignment, a single version and consecutive indices and reports payload entropy.
It has no USB/network/decryption/write interface. The JSON explicitly leaves
checksum/signature verification, MCU identification, recovery and flash safety
**false**. It is not packaged as part of the daily application.

Build with Rust 1.95.0 and locked dependencies from `native/app/Cargo.toml`, then
run `firmware_inspect FILE EXPECTED_SHA256`. Re-run against the private stock file
and the SHA above. No vendor firmware bytes are included in tests or the repo.

Six synthetic tests cover malformed/truncated/oversize inputs, mixed versions,
block-order corruption, changed content against a pinned hash, malformed hashes
and the distinction between container structure and flash safety. **95 app tests
pass**, all-target GUI Clippy with warnings denied and formatting pass.

Evidence: [`perf/custom-firmware-2026-10-15`](../perf/custom-firmware-2026-10-15).
Configuration/calibration and installed app/helper hashes remain unchanged;
Python/native fallbacks and launchers are preserved. No daily code path changed.
The app was already closed and remains closed. No HID transaction, reset, DFU
entry, erase, programmer operation or flash was performed in this follow-up.
No new colour, optical, reconnect or NL82K1 hardware verification is claimed.
