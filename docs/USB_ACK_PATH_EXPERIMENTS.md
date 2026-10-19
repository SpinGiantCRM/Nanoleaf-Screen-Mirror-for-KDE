# Direct USB acknowledgement experiments

16 October 2026. The remaining USB wait was tested directly on the user's
48-zone NL82K2, firmware 1.5 / hardware 1.1. **None of these alternatives reduced
the delay.** The daily transport remains unchanged. This is receiver/transport
research, not a claimed response-time improvement.

The final retained operator binary completed **960 measured full-frame colour
commands**, each with one successful ordinary ACK, no drained stale report and
no unrelated response. Setup, queries and cleanup are additional transactions.
A separate control-read experiment exceeded its deadline; its failure is retained.
Earlier pilot results are not pooled into the final dataset.

## Same colours, different submission paths

Each pattern uses baseline/candidate/candidate/baseline order, 16 commands per
case, with the first two uniformly excluded from aggregates. Values below are
pooled medians of the remaining 28 baseline and 28 candidate commands per pattern.

| Full 48-zone pattern | Ordinary total | One-write total | Ordinary ACK wait | One-write ACK wait |
| --- | ---: | ---: | ---: | ---: |
| Black | 6.997 ms | 6.997 ms | 3.046 ms | 3.040 ms |
| Neutral code 8 | 18.996 ms | 19.000 ms | 15.059 ms | 15.057 ms |
| Neutral code 64 | 20.998 ms | 20.996 ms | 17.055 ms | 17.049 ms |
| Varied, bounded RGB | 20.998 ms | 20.998 ms | 17.053 ms | 17.045 ms |

The ordinary path writes 65/65/20 host bytes, including a zero report-ID byte
per call. The candidate writes one 148-byte buffer: one zero followed by the
identical 147-byte TLV. Linux removes the initial unnumbered report ID; the
64-byte USB endpoint packet size still divides the data. The expected endpoint
packet contents are byte-identical. A private syscall trace verifies 128 actual
148-byte writes in the final run. This is not an on-wire packet capture.
It is a Linux operator experiment, not a portable HID report guarantee.

The [Linux HID implementation](https://github.com/torvalds/linux/blob/master/drivers/hid/usbhid/hid-core.c)
passes raw output to `usb_interrupt_msg`; the
[USB message implementation](https://github.com/torvalds/linux/blob/master/drivers/usb/core/message.c)
uses a blocking URB. Submitting the frame in one call did not make this controller
complete the writes sooner: write time remained approximately 3.93 ms.

A second 256-command ABBA run used HIDAPI `send_output_report`, which invokes
`HIDIOCSOUTPUT` on this backend. Lit-code-64 totals were **20.999 ms for both
paths**; code-8 totals were 18.997/19.000 ms. All ACKs arrived.
Although HIDAPI describes a control-endpoint operation, inspected Linux source
can route output ioctls through the ordinary interrupt-output path. We did not
prove a physical endpoint change. This result rules out that API as a useful
shortcut on this host; it does not establish that every possible control-output
implementation was tested. No alternate transport was adopted.

## Does spacing the reports give the receiver processing time?

Another **256 commands** compare gaps of 250, 500, 1,000 and 2,000 microseconds
between the existing three report writes, with matched zero-gap ABBA controls.
There are eight commands per case, two excluded warmups. All report bytes,
manual zone count and ordinary ACK parsing remain identical.

| Gap between writes | Code-8 total | Code-64 total | Result |
| --- | ---: | ---: | --- |
| 0 | about 19 ms | about 21 ms | Reference |
| 250 or 500 us | about 19 ms | about 21 ms | No improvement |
| 1,000 us | 20.991 ms | 22.996 ms | About 2 ms slower |
| 2,000 us | 23.000 ms | 24.999 ms | About 4 ms slower |

The post-write ACK interval stayed about 15/17 ms. Spacing the packets did not
overlap away that interval; longer gaps just extended the writes. Requested
sleep durations are not assertions of exact USB packet spacing. The complete
command duration, rather than a shifted write/wait boundary, is the criterion.

## Does controller brightness bypass expensive receiver work?

**192 full-frame commands** use only black and raw neutral code 8, with requests
1/16/32/64/100/255 and reversed order. Eight commands per case, two excluded
warmups. Request 1 reads back **16**; the others read back their requested values.
Code-8 total medians range from **18.995 to 18.999 ms**, with ACK waits about
15.05 ms. Black remains about 7 ms. There is no useful latency bypass here.

These are raw protocol brightness values, not measured optical brightness.
No compensation curve, saved calibration, channel mapping, black threshold or
dithering policy was changed. The actual readback of 255 exposed an information
tool bug: `usb_info` incorrectly rejected values above 100. Its validation now
accepts the complete documented byte range while retaining shape/power checks.
The [official protocol](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/pages/2615574530/Nanoleaf+USB+Lightstrip+Communication+Protocol)
specifies brightness 0–255; the UI's separate percent setting is not that field.

## Can GET_REPORT retrieve the ACK earlier?

**Rejected.** An idle `HIDIOCGINPUT` returned zero bytes in about 1.96 ms.
Immediately after a complete black colour write, it instead blocked for
**5,454 ms** and returned a kernel timeout. No control response was accepted as
an ACK. The ordinary 250 ms transaction deadline necessarily expired while the
operator's control ioctl was blocking.

Crucially, the private syscall trace subsequently shows the successful ordinary
`0x82` reply drained **before** the next distinct model query. The ACK was queued;
this does **not** prove that the device lost it, or establish when it arrived.
The earlier progress update describing a missing ACK was too strong. A separate
model barrier, acknowledged black cleanup, both controller-state restorations
and subsequent ordinary queries passed. A preceding pilot also failed, but its
incomplete metadata is not used for timing aggregates. Never enable GET_REPORT
inside daily colour transactions.

## What this establishes, and what remains

### Final packet layout checks: 384 additional acknowledged commands

An additional bounded run compares the same full 147-byte TLV in ordinary
64/64/19-byte chunks against three layouts: a zero-padded final 64-byte report,
63-byte chunks, and 60-byte chunks. The latter two place fragmentation on RGB
boundaries. All use three reports, preserve the complete TLV, and wait for its
ordinary ACK before another command. Padding appears only **after** the declared
TLV, never between colours. No suffix is omitted in this experiment.

Each pattern/candidate uses ABBA order, eight commands per case, with two warmups
excluded from each case. Each table cell therefore pools 12 commands. Setup and
cleanup are additional transactions. This run uses a separately retained operator
binary; it is not pooled with the earlier 960-command binary's timings.

| Pattern | Reference / padded tail | Reference / 63-byte chunks | Reference / 60-byte chunks |
| --- | ---: | ---: | ---: |
| Black | 6.998 / 6.992 ms | 6.995 / 6.990 ms | 6.996 / 6.992 ms |
| Neutral code 8 | 19.000 / 18.997 ms | 18.994 / 18.993 ms | 19.002 / 18.988 ms |
| Neutral code 64 | 20.989 / 21.000 ms | 20.993 / 20.993 ms | 20.994 / 20.994 ms |
| Varied RGB | 20.996 / **21.997 ms** | 20.994 / 21.000 ms | 20.998 / 20.987 ms |

**No useful improvement.** For varied colours, final padding adds about 1 ms,
with the post-write ACK interval increasing from 17.061 to 18.023 ms. All 384
measured commands received one matching ACK, with no stale drained report or
unrelated reply. The independent controller-state readback and guarded restoration
passed. The unchanged daily app resumed afterward. No visual observation or
emitted-light timing was performed; an accepted TLV is not an optical parity test.
None of these layouts is selected for daily output.

An inspected independent [Python driver at a pinned commit](https://github.com/sdouf5054/nanoleaf-multi-wrap-mirror/blob/aa90aed672bf5f0b4d52f379053f5205ed2788a8/core/device.py)
also pads its reports and serializes writes, but does not validate the ACK's
contents. Its implementation was read as data, never executed or adopted. It
provides no verified faster command or justification for weakening our ACK checks.

The matching [offline firmware follow-up](RECEIVER_ENCODING_FOLLOWUP.md) narrows
conditional checksum candidates, but still supplies neither executable firmware
nor an independent closed-case recovery method.

### Receiver boundary

The tested host submission, output API, packet pacing and global-brightness
changes do not remove the content-dependent ACK wait. Together with the earlier
[active-zone experiments](USB_POSITION_AND_REPEAT_RESEARCH.md), receiver-side
work remains the leading explanation. These tests do not identify the internal
LED signalling, CPU routine, MCU, or exact optical update instant. The host's
1 ms interrupt endpoint interval alone does not explain an additional 12–14 ms
between black and fully lit requests.

The current and inspected historical/vendor command paths expose no verified
compressed, offset-addressed or low-latency colour command. Historical indicator
PWM is not a strip streaming mode. Unknown administrative commands are not safe
fast-mode probes: the same command family contains firmware operations.
The known public stock images remain opaque; there is no validated decoder or
independent recovery route. Substantial remaining receiver gains need evidence
of a supported faster path or an understood firmware implementation. No flash,
loader entry, reset, erase, overclock or unknown Nanoleaf command was performed.

The earlier [overlap failures](USB_OVERLAP_EXPERIMENT.md) remain relevant:
changing a host API does not restore missing per-frame correlation. The useful
already-shipping mitigation is [exact shortened updates](SHORT_UPDATES.md),
which reduces real receiver work when trailing quantized colours are unchanged.
It cannot guarantee a gain for full-strip motion. No colour approximation,
dither suppression or unacknowledged sending was introduced in this follow-up.

## Reproduce and preservation

Build the developer `usb_bench` binary from `native/app/Cargo.toml` using Rust
1.95.0, release mode and locked offline dependencies. With an existing config,
`--ack-path`, `--ack-output`, `--ack-pacing`, `--ack-brightness` and
`--ack-control` and `--ack-shape` print plans without opening HID. Actual hardware use requires
the explicit trailing `--run`, the exclusive output lease, the qualified
48-zone NL82K2 contract, and a stopped mirror. `--ack-control` intentionally
reproduces the rejected deadline failure and exits nonzero after restoration.
The operator binaries are absent from the managed application bundle.

Each run retains guarded black cleanup and original power/brightness restoration
with readback. Original values **1/16** were independently verified afterward.
The shared TOML remained byte-exact. The installed app/capture pair and previous
native rollback bundles were unchanged. The normal app resumed with the selected
portal/Vulkan backend, manual 48 zones and exact short updates. No foreground
game fixture, screenshots, physical reconnect, new visual colour verification or
optical latency measurement was used. Generated raw USB tests do not measure
calibrated capture, game-event response, FPS improvement or power savings.

[Per-command final evidence and aggregates](../perf/ack-path-2026-10-16/README.md)
retain failures and distinguish the five experiments. Raw syscall traces,
controller identifiers, private config and unrelated capture prototypes stay
outside the public repository.
