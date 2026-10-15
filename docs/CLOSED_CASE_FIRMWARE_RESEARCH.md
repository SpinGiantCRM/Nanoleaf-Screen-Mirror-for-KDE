# Closed-case firmware research

2026-10-15. Follow-up to [recovery investigation](CUSTOM_FIRMWARE_RECOVERY.md).

The enclosure stays closed. No flash, reset, bootloader entry, unknown HID command
or programmer operation was performed. This work changes no daily application
code, installed binary, calibration or configuration.

## What the additional research establishes

We obtained five historical official application-update containers and inspected
two official Windows desktop updaters as archive data, without executing them.
This provides useful encoding and updater evidence, but **does not identify the
MCU, produce a custom executable image or establish recoverability**. WCH CH552
remains a lead from the old vendor demo repository name, not a confirmed part.

The [historical vendor protocol](https://nanoleaf.atlassian.net/wiki/pages/viewpage.action?pageId=2615574530&pageVersion=1)
describes application-triggered updating and numbered records with CRC-16. It
does not supply an application-independent closed-case rescue procedure or the
encoding tools needed to build a custom image.

## Historical images: measurements, not compatibility claims

Public vendor URLs follow `https://nl82k2-firmware.s3.amazonaws.com/VERSION.firmware`.
Versions below returned HTTP 200 and were downloaded only to private local storage.
The 1.5.0 URL had previously been returned by vendor recovery metadata; earlier
filenames were bounded public-path hypotheses, not vendor recommendations for
this physical unit. No serial-specific metadata request was needed in this pass.

| Version | Bytes | 61-byte records | Data bytes under historical layout |
| --- | ---: | ---: | ---: |
| [1.1.0](https://nl82k2-firmware.s3.amazonaws.com/1.1.0.firmware) | 10,736 | 176 | 9,856 |
| [1.2.0](https://nl82k2-firmware.s3.amazonaws.com/1.2.0.firmware) | 10,736 | 176 | 9,856 |
| [1.3.0](https://nl82k2-firmware.s3.amazonaws.com/1.3.0.firmware) | 10,797 | 177 | 9,912 |
| [1.4.0](https://nl82k2-firmware.s3.amazonaws.com/1.4.0.firmware) | 10,370 | 170 | 9,520 |
| [1.5.0](https://nl82k2-firmware.s3.amazonaws.com/1.5.0.firmware) | 10,431 | 171 | 9,576 |

Pinned SHA-256 values, in the same order:

```text
1.1.0  1ffcf5900dee6ae70f49623fd1ed047b0d923754bc9a4224a99c193a37b71ffa
1.2.0  1a50962b641d9ba8a4c5f5a0c2fb82e55924700b45b030bc020d43e28a5f274c
1.3.0  9a5f84be343e57238c95ca7d6acac1ddf6364bd59c39e646df8519c4e9419518
1.4.0  de7f11f76c9ad8ac6bb6e2595c89d5ce8da39a9ace7155cc4fd6d5e61c99f3a2
1.5.0  05ae98ac932d18fb9bf1579e744401827f9ac068347cdb968426363ec45ef3de
```

Every file has a consistent version byte and consecutive big-endian indices.
Data-field entropy ranges from 7.9741 to 7.9802 bits/byte; simple plaintext searches
found no NL82K2, CH552 or NLUSB marker. File size is not flash capacity or a memory
map. An update container is not a backup of the bootloader or factory storage.
Earlier images have **not** been established as compatible downgrade targets.
The guessed 1.0.0 path and bucket listing returned 403; this does not prove absence.

## Encoding evidence and limits

Concatenate bytes 3..58 of each record and split the result into aligned eight-byte
blocks. Version 1.5.0 has 1,197 blocks, 1,143 unique values and 54 repeated
occurrences beyond their first occurrence. There are 113 equal-block pairs; 52
have unequal following blocks, so repetition is not solely identical 16-byte pairs.
Adjacent versions share 444, 57, 192 and 102 unique eight-byte values respectively.

**Inference:** this supports investigating a shared deterministic block encoding.
It does not identify TEA, an encryption key, compression, CPU architecture or a
signature policy. High entropy alone is not proof of encryption. Unrelated CH552
community loaders using eight-byte TEA blocks do not establish Nanoleaf's format.
Disassembling the opaque stored bytes as 8051 code would not identify the chip.

### Checksum constraints, not a solved checksum

Earlier tests of 36 common CRC variants did not validate the stored records.
Additional polynomial codeword analysis across all 171 records of 1.5.0 found no
common degree-16 factor in 12 tested layouts: start byte 0/1/3, trailer-byte swap
on/off and per-byte bit reflection on/off. Synthetic CRC-CCITT codewords with an
arbitrary seed and final XOR passed the positive control. This constrains those
conventional stored-codeword interpretations; it does not prove corruption or
rule out a checksum calculated before encoding.

There are 26 equal 56-byte data fields at matching indices across 1.1.0/1.2.0;
their trailer XOR is always `0x03f0`. Six equal fields across 1.3.0/1.4.0 have
trailer XOR `0x06b0`. Under the **unproven** assumption that equal encoded data
means equal decoded data under a shared encoding, these differences constrain a
checksum over the clear version/index plus decoded data.

An exhaustive search of nonzero 16-bit polynomials, reflected/non-reflected update
and both trailer byte orders leaves **eight** candidates, all reflected with
big-endian trailers: `07b1`, `07e7`, `0828`, `27e4`, `6000`, `682d`, `a001`, `b876`.
All match the 32 equal-data pairs, but those pairs contain only **two independent
header differences**. Therefore `a001` is not uniquely identified and this is not
a validated Modbus CRC, seed/XOR, decoder or firmware builder. The image's actual
checksum remains unverified. No key or modified image was produced.

## Older desktop updater comparison

The official [Desktop 2.2.4 installer](https://desktop-app-prod-1.s3.us-west-2.amazonaws.com/Nanoleaf%20Desktop%20Setup%202.2.4.exe)
is 107,684,928 bytes, SHA-256
`7c9d180eac31949c66d032cb042d6b00946fca6f1aaccdacc2f1148a515a6038`.
The server reports 2025-07-02 19:09:46 GMT. Only known archive members were
extracted; no installer, bundled JavaScript or vendor executable was run.

Both 2.2.4 and previously inspected 3.0.1 consume the vendor's prepared 61-byte
records and recognize `NLUSB-BL`. Neither inspected USB updater constructs or
decrypts custom firmware. Crypto code elsewhere in bundled ZIP dependencies is
not evidence of USB-firmware decryption. No source maps or named MCU/bootloader
binary archive members were found in 2.2.4.

Static comparison also found weaker recovery handling in 2.2.4: its enumeration
wait is unbounded, erase/reboot reply error codes are not checked, and block
acceptance lacks the newer returned-index and exhausted-retry failure handling.
Version 3.0.1 has a 60-second enumeration bound and stronger block failure checks.
These are inspected source paths, not exercised firmware-update tests. An older
app is not being recommended as a safer recovery tool. Automatic updating of an
already-enumerated loader does not show how to reach it with a broken application.

## Other closed-case source checks

Targeted manufacturer documentation searches found the known USB protocol, but
no chip or application-independent recovery description. The accessible public
Bitbucket workspace listing returned no repositories; the linked demo raw/API
paths were unavailable. Nanoleaf's public GitHub organization exposed older Aurora
SDK repositories, not strip controller firmware. Public support documentation
did not establish a closed-case recovery sequence. These are search limits, not
proof that private source or recovery documentation does not exist.

Useful manufacturer questions are now specific: exact MCU/board revision for
NL82K22 reporting NL82K2 hardware 1.1; closed-case recovery when the application
cannot start; bootloader/factory-data preservation; supported image encoding and
development tools; and whether colour acknowledgements mean accepted or emitted.
A manufacturer enquiry was sent with explicit user approval, requesting these
points without serial identifiers or attachments. No internal photographs, opening, pad probing
or spare-controller purchase are requested.

## Reproduction and preservation

Aggregate evidence is in [perf/closed-firmware-2026-10-15](../perf/closed-firmware-2026-10-15/README.md).
Use the existing offline `firmware_inspect FILE EXPECTED_SHA256` with the pinned
hashes above. Structural success must still report checksum/signature validation,
MCU identification, recovery and flash safety as false. The independent checksum
difference search is included with instructions; it needs no firmware or hardware.
Vendor installers, firmware bytes, proprietary updater source, serial identifiers,
mail and the original photograph are excluded from the public evidence.

No USB transactions, firmware writes, live colour tests or new latency benchmarks
were performed in this follow-up. Calibration/configuration and installed native
application hashes are unchanged; Python/native fallbacks remain available. The
tray app remains closed. No colour or response-time improvement is claimed from
this research. Safe custom firmware remains contingent on documented recovery,
board identification and understood image acceptance.
