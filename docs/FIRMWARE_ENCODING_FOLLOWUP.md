# Firmware encoding and raw-level follow-up

2026-10-15. Extends [vendor software reverse engineering](VENDOR_SOFTWARE_REVERSE_ENGINEERING.md)
and [closed-case recovery research](CLOSED_CASE_FIRMWARE_RESEARCH.md).

The earlier host software contains a write-only colour path, but this does not
establish a safe shortcut for current firmware. Additional image analysis has
not identified the MCU, cipher, key or a unique checksum. Two acknowledged
physical comparisons produced repeatable USB timings, but the visual report
does not establish a black threshold. Daily encoding and calibration remain
unchanged. No firmware, reset, DFU or unknown command was sent.

## Historical Desktop 2.1.0

The official [Desktop 2.1.0 installer](https://desktop-app-prod-1.s3.us-west-2.amazonaws.com/Nanoleaf%20Desktop%20Setup%202.1.0.exe)
is 129,237,120 bytes, SHA-256
`c2b9dc2a36d01a042818478dfc1b294ae762117863ea913b0aadab448a37bbcb`.
It was extracted as data, never installed or launched. The inspected ASAR member
is `minified/server.js`, SHA-256
`a1606cd70ce0e9a9cd901766cfd2cb079c912eabae937ac561919893ba10ed26`.
Acorn 8.19.0 indexed the relevant classes; offsets use UTF-16 code units.

Unlike the inspected 2.2.4/3.0.1 path, its `setLedColours` method:

- Packs GRB channels after division by two, truncated through `Uint8Array`.
- Serializes the HID **writes**, without a colour-reply read/wait in that class.
- Updates its saved colour state after the writes complete.

The selected class was exercised with fake HID and a substitute serial queue.
Three full 48-zone cases completed without any supplied ACK or read call: black
stayed zero, RGB `[3,5,7]` became wire GRB `[2,1,3]`, and white became
`[127,127,127]`. All used reports of 65/65/20 bytes. The startup initializer's
separate zone-count read was not exercised. Constructor timers were stubbed;
caller cadence and the complete application were not executed. This is a
software trace, not a physical timing or firmware-compatibility measurement.

Its enumerator includes both production VID/PIDs `37fa:8201` / `37fa:8202` and
the historical demo `5131:2007`. This connects the old demo support with this host
driver family, but does not identify the retail MCU. The inspected server and
archive listing exposed no bootloader source, firmware image, chip-specific
decoder or independent recovery procedure. This does not rule out such material
in other releases or private resources.

**Decision:** retain current acknowledged transactions. Historical write-only
code does not overrule the earlier real overlap failure or provide missing
per-frame reply correlation. Halving colour values is also not evidence of
better reproduction on the current strip.

## Image structure: stronger pattern tests, no decoder

The five pinned stock images contain 870 records. Each 56-byte data field was
split into seven eight-byte symbols. Equal symbols recur within records and at
different positions. These counts are pairs of occurrences, not independent
cipher observations:

| Image | Equal-symbol pairs | Same record, different position | Different full data fields | Both non-first, unequal preceding symbols |
| --- | ---: | ---: | ---: | ---: |
| 1.1.0 | 96 | 29 | 67 | 44 |
| 1.2.0 | 81 | 24 | 57 | 34 |
| 1.3.0 | 91 | 22 | 69 | 41 |
| 1.4.0 | 86 | 22 | 64 | 35 |
| 1.5.0 | 113 | 40 | 73 | 36 |

**Inference:** an independent eight-byte transform remains worth investigating.
This does not identify ECB, TEA, a key or an instruction set. Repeated output
alone does not reveal whether its input was repeated plaintext or structured
encoding, and does not exclude other constructions.

To seek checksum constraints beyond identical whole records, a GF(2) elimination
test represents every `(position, encoded symbol)` as a column. An extra constant
column restricts relations to an even number of records, allowing arbitrary CRC
initial/final constants to cancel for equal-length records. This is conditional
on equal encoded symbols decoding equally at each position across versions, and
on a linear CRC covering the decoded data and the clear header. Neither premise
is established for this container.

Across **5,428 symbol-position columns**, the row nullspace has **32 independent
relations**, all two-record pairs. Header XORs have rank **two**: `030000` maps to
trailer XOR `03f0`, and `070000` to `06b0`. Therefore this broader cancellation
search adds no independent constraints to the earlier equal-data comparison.
The eight earlier polynomial hypotheses remain ambiguous; no complete image's
checksum has been verified. This result applies to this model and corpus, not
all checksum or encoding schemes.

Synthetic controls include a four-record rectangle with no duplicate rows,
a duplicate pair, independent rows, rejection of an odd three-record relation
and a binary-rank check. The reproducible script reads only bounded local files
with the five pinned hashes; no firmware bytes or vendor code are published.

## Independent driver comparison

Nanoleaf's [Developer Forum post](https://support.nanoleaf.me/hc/en-us/community/posts/54225062144788-Automatic-white-monitor-backlighting-for-macOS)
links an independent [Swift driver](https://github.com/sashusha/nanoleaf/tree/b483d5d16b8ebc388c73c5d81e80e149ee806c74).
Its source was inspected at that pinned commit, without building or running it.
Its [calibration notes](https://github.com/sashusha/nanoleaf/blob/b483d5d16b8ebc388c73c5d81e80e149ee806c74/CALIBRATION.md)
report NL82K2 hardware 1.1.0 / firmware 1.5.0 testing and use the same minimum-15
mapping found in later Desktop software. They describe code `[15,15,15]` as black.
Its [verification notes](https://github.com/sashusha/nanoleaf/blob/b483d5d16b8ebc388c73c5d81e80e149ee806c74/VERIFICATION.md)
report vendor-frame comparisons and physical ordinary-command checks on the
author's unit. Those are the author's findings, not our hardware verification;
matching vendor codes is not colorimeter calibration. The inspected HID path
also waits for command-type acknowledgements. No chip, decryption key or
closed-case recovery implementation was found in the inspected source.

## Physical raw-neutral comparison

A new developer-only `usb_levels CONFIG [--run]` binary defaults to printing a
hardware-free plan. Explicit `--run` obtains the existing exclusive output lease,
uses the saved manual count/channel order, and sends only known power/colour
commands with acknowledgements. It reads the controller's original power and
brightness first. Success and returned-error paths attempt black cleanup and
restore both original values with readback. Disconnect or process termination
can prevent restoration; unsuccessful readback is reported as failure.
Prior frame colours cannot be read back and are not restored.

The operator explicitly authorized two 18-second runs on the existing 48-zone
NL82K2. Each held codes **0 → 15 → 16 → 24 → 0 → 24 → 16 → 15 → 0** for two
seconds per step at a 30 Hz target. All RGB channels were equal. The probe
bypasses host calibration only for these generated frames. It does not change
the controller's brightness for the experiment; the raw-code cap of 24 is not
an assertion of optical brightness. Original brightness was not logged in these
two runs, limiting cross-session comparison. Future probe JSON records it.

Both runs completed **540 frame transactions**, with every ACK received, black
cleanup acknowledged, and original power/brightness restoration verified.

| Raw RGB code | Samples/run | Median ACK wait, run 1 / run 2 | Median whole transaction, run 1 / run 2 |
| --- | ---: | ---: | ---: |
| 0 | 180 | 3.033 / 3.031 ms | 5.842 / 5.626 ms |
| 15 | 120 | 15.038 / 15.035 ms | 17.744 / 17.761 ms |
| 16 | 120 | 17.038 / 17.036 ms | 19.618 / 19.609 ms |
| 24 | 120 | 18.039 / 18.035 ms | 20.722 / 20.762 ms |

The operator requested a retry after the first run. After the second, they
reported that the **third timed step was dark and the others produced light**;
the third step was code 16. This unexpected, non-monotonic observation does not
validate either black candidate or a transfer curve. Brief unlabelled steps,
human timing and the controller's output state remain confounding factors.
Do not silently reassign the report to code 0 or 15. The subsequent separately
announced held observations below address this ambiguity. No further unattended
repeat is justified by the earlier sequence.

ACK delay is repeatable and level-dependent, but **ACK is not emitted-light
timing**. No photodiode, colorimeter, throughput improvement or physical colour
accuracy claim follows from this test. The normal encoder remains unchanged.

### Prepared follow-up: one announced level at a time

`usb_levels CONFIG --level 0` now prints a plan for one ten-second observation;
only an additional `--run` opens HID. Reviewed codes are limited to 0, 15, 16 and
24. This single-level mode temporarily sets controller brightness to 10 and
restores the original power/brightness with readback; it retains manual geometry,
channel order and serial ACKs. The original nine-step mode is unchanged.

Announce the selected code before starting, wait for the observer's result, and
only then start another held code. This avoids asking someone to identify a
brief third step after the sequence has ended. No high-speed camera is required
to report whether a held code emits light, although that still cannot establish
colour accuracy or optical latency. Do not run the held comparison unattended
or derive a black-floor change from the earlier ambiguous report.

CLI tests verify plan-only operation without a desktop runtime, the manual
count, fixed duration/brightness, unchanged configuration and rejection of
unreviewed/invalid arguments before HID. Injected failure tests verify original
brightness restoration after the test-brightness command or observation fails.
It is a separate operator tool, not a daily colour-mapping change or a packaged
runtime component. Physical observations followed on 16 October, below.

### 16 October: separately confirmed level 0 and level 16

The user requested one check at a time. Each code was announced before its
ten-second hold, at controller brightness 10 with the authoritative manual count
of 48. The user's response was collected before starting the next code.

| Raw neutral code | Acknowledged frames | User observation | Median ACK wait |
| --- | ---: | --- | ---: |
| 0 | 300 | Completely dark | 3.027 ms |
| 16 | 300 | LEDs turned on, too dim to illuminate the wall behind the monitor | 17.029 ms |

Both runs acknowledged cleanup black and verified original controller power and
brightness restoration by readback. The real configuration remained byte-identical;
calibration, daily encoding and firmware were unchanged. No third phase ran.

At this tested brightness, code 0 was off and code 16 emitted light. The earlier
report of a dark third step was **not reproduced**. These observations support
retaining the existing zero-black encoding; they do not establish a black floor
of 15, a 16-code offset, a complete transfer curve, neutral colour accuracy or
screen-to-light latency. Wall illumination is not a measured luminance threshold.
The level-dependent ACK delay remains a separate software/protocol observation.

Sanitized results: [perf/held-levels-2026-10-16](../perf/held-levels-2026-10-16/results.json).

## Manufacturer contact and remaining gates

The earlier support email produced an automated notice that incoming mail is
unmonitored. The approved chip/recovery/factory-data/image-format/ACK questions
were submitted through the official [technical support form](https://support.nanoleaf.me/hc/en-us/requests/new)
instead. Both the website success message and a request-number email confirmed
delivery. Only an automated acknowledgement has arrived, not an engineering
answer. Private correspondence, contact details and confirmation screenshots
are excluded from repository evidence.

The public protocol page's attachment and child-page listings, plus scoped
public API-documentation attachment searches, exposed no additional bootloader
source. These searches do not establish what private documentation exists.

Custom firmware still requires exact MCU identification, understood image
acceptance and factory-data preservation, and a documented independent recovery
route with the enclosure closed. There is no safe-to-flash result. No opening,
boot shorts, generic programmer, loader entry, erase or firmware write occurred.

Evidence and reproduction: [perf/deeper-firmware-2026-10-15](../perf/deeper-firmware-2026-10-15/README.md).
The app was already closed and remains closed. Configuration is byte-identical;
manual 48 zones, calibration, installed app/helper and native/Python fallbacks
are preserved. The new operator tool is not included in the daily package.
