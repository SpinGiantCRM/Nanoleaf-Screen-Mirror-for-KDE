# Controller firmware and latency research

Research date: 2026-10-15. Priority: visible response time, colour accuracy, FPS,
then resource use. Scope remains one manually configured USB strip.

## Conclusion

**The controller has a vendor firmware-update route. There is no verified,
ready-to-flash latency fix or custom replacement firmware in this investigation.**
The official desktop application still implements USB updating even though the
current public protocol omits the flashing commands. A device-specific check now confirms Nanoleaf offers **no update for this unit**
with firmware 1.5.0 / hardware 1.1.0 today. This does not establish that arbitrary
firmware is accepted or that a failed flash is recoverable.

No firmware, device mode, power, brightness, LED output or saved configuration was
changed for this research. The native tray was already closed and remains closed.
The installed app, capture helper, calibration and Python/native fallbacks remain
intact. The only implementation addition is an operator-only read-only identity
probe, with no updater or automatic network check.

## Follow-up: stock recovery asset obtained

[Custom firmware and recovery investigation](CUSTOM_FIRMWARE_RECOVERY.md) now
records the exterior model **NL82K22**, the official **1.5.0** application-update
file obtained through the vendor's recovery metadata request, its pinned hash
and offline structure analysis. This is an advance over the first pass below,
which obtained no image through the normal update check. The exact MCU remains
unconfirmed; CH552 is still a lead. A complete stock backup, independent recovery
entry and safe custom-image packaging remain unresolved. No flashing is authorized
or performed. The following sections retain the first-pass investigation context.

## What is measured on this unit

| Item | Verified result | Interpretation |
| --- | --- | --- |
| Model | NL82K2 | Existing PC Screen Mirror strip |
| Firmware query | `0x15` | Major 1, minor 5; vendor app formats this as `1.5.0` |
| Hardware query | ASCII `11` | Hardware 1.1; vendor app formats `1.1.0` |
| Manufacturer query | ASCII `G` | Historical protocol's manufacturer indicator |
| Manual / reported zones | 48 / 48 | Manual count remains authoritative |
| USB descriptor `bcdDevice` | 1.05 | Separate descriptor; not the firmware-version query |

Identity queries were made under the normal exclusive output lease, through the
existing HID transport. No serial number is included in public evidence.
[`perf/firmware-research-2026-10-15`](../perf/firmware-research-2026-10-15)
contains the sanitized identity and package-inspection provenance.

Earlier [USB measurements](USB_AND_BLACK_RESPONSE.md) found approximately 4 ms of
host write time for the same complete 48-zone frame size, followed by about 3 ms
of reply wait for black versus 15-17 ms for fully lit generated neutral frames.
Changing the number of lit zones changes the wait despite identical packet sizes.
This is evidence of a content-dependent device-side delay; it does not identify
its internal operation. In particular, it does **not** measure when the LEDs emit
light or prove that all of the reply wait is removable optical latency.

The [two-frame overlap experiment](USB_OVERLAP_EXPERIMENT.md) failed sustained
trains with missing replies. Keeping serial acknowledgements is justified by the
measurements. An earlier ACK alone would improve host throughput only if the
controller also accepts and presents subsequent frames correctly.

## Official update path: stronger evidence than the old specification

The [original official protocol, revision 1 (2025-05-18)](https://nanoleaf.atlassian.net/wiki/pages/viewpage.action?pageId=2615574530&pageVersion=1)
describes application-to-DFU switching, application-flash erase, indexed firmware
blocks with CRC-16, and reboot. It also lists decryption, verification and write
errors. It documents identity queries used above, but no application-flash readback
or backup procedure. A CRC does not establish that modified firmware is accepted;
image authentication/encryption details are unresolved. Its linked vendor demo
repository, `nanoleaf/ch552_testing`, was not publicly retrievable through either
Git or the Bitbucket API during this investigation.

The [current official protocol](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/pages/2615574530/Nanoleaf+USB+Lightstrip+Communication+Protocol)
was read through its public Confluence REST representation: revision 10,
2026-02-12. It and the bundled eight-page vendor PDF cover runtime commands and
firmware-version querying, but omit the former update commands. There is no
published ACK-optional or queued/latest-frame streaming mode in that document.
Omission does not establish that the old commands were removed from hardware.

### Static inspection of official Desktop 3.0.1

The [official desktop download page](https://nanoleaf.me/en-eu/pages/nanoleaf-desktop-app)
links to the vendor's latest-version endpoint. A fresh request resolved the
Windows installer to **3.0.1**, last modified 2026-10-05. It was downloaded and
inspected as archive data on Linux; it was never executed, installed or run under
Wine. Installer SHA-256:

`93af37b0112188a45bde68ebf1d4bd2e915cfcd3b4f5bd9586fe51420daf1579`

The application archive contains a USB-specific controller implementation that:

- Recognizes NL82K1 and NL82K2, including the `NLUSB-BL` bootloader product name.
- Reads firmware/hardware identity using the same encoding confirmed above.
- Checks `/smartdownload` on the vendor firmware service with app version,
  model, firmware, hardware and serial number.
- Uses the returned firmware location and advertised new version; no clearly
  named standalone controller image was found in either archive's file listing.
- Can enter DFU, erase, write sequential 61-byte blocks, check block replies,
  reboot and wait for the application device to reappear.
- Awaits the ordinary zone-frame reply. This inspection found no demonstrated
  faster alternate USB streaming command in that controller implementation.

These are static observations of this exact official package, not a supported
Linux updater, a live firmware-server result for this device, or proof that its
bootloader is currently healthy. No proprietary code or installer is committed.
The firmware blocks are consumed from the downloaded image; that does not tell
us how to construct or sign an acceptable custom image.

One metadata-only request to `https://firmware.nanoleaf.me/smartdownload` used the
confirmed model and version fields **without a serial number**. It returned
HTTP 422 with `{}`. That incomplete request did not establish availability.

A subsequent normal device-specific request included this unit's actual USB
serial, sent only to the manufacturer's HTTPS firmware endpoint. The service
returned **HTTP 404 with `update_status: "none"`, `update_interval: 720`, and
`report: 0`**. The official client accepts both HTTP 200 and 404 for this check
and branches on `update_status`. Thus **no firmware update is currently offered
for this unit and these identity fields**. This is not a claim that 1.5 is the
latest version for every production revision or region. No credentials,
calibration or screen data were sent, and the serial is excluded from retained
request metadata and public evidence. No image was returned, downloaded or flashed.
No fabricated serials or repeated polling were used.

Nanoleaf's [2026 product firmware notes](https://support.nanoleaf.me/hc/en-us/articles/45269445987092-Products-Firmware-Release-Notes-2026),
updated October 13, say PC Screen Mirror and Pegboard receive limited or no regular
updates; they do not list a latest NL82K2 version. Firmware versions for Wi-Fi
panels or Matter strips are unrelated. Desktop application version 3.0.1 is also
not the controller's firmware version.

## What a useful firmware change would actually need to do

This is an engineering proposal, **not an identified defect in Nanoleaf's code**:

1. Receive a complete frame into an inactive buffer; never expose partially
   received zones to the LEDs. Validate full length and integrity before use.
2. Swap frames at a defined presentation boundary. Keep at most one newer pending
   frame, replacing stale pending work while preserving all 48 zones exactly.
3. Service USB while preparing/outputting LEDs if the actual MCU/peripherals
   permit it. Otherwise establish a bounded scheduling budget explicitly.
4. Give acceptance and presentation distinct sequence-numbered replies, so the
   host can bound queue depth and recover without confusing an old ACK for a new
   frame. Merely returning success sooner is insufficient.
5. Preserve correct RGB ordering, brightness transfer, neutral handling, black
   off, current/thermal limits, buttons and power-on behaviour. Measure a colour
   ramp and emitted-light timing before adoption.

Content-dependent delay could involve LED-output implementation, per-channel
work, current/brightness management, supply behaviour or reply scheduling. We
cannot choose among these from host timestamps. Disabling current protection,
reducing colour depth, omitting zones or guessing future colours would not be
acceptable ways to obtain a lower number.

## Custom firmware feasibility

The old vendor demo's name suggests a **CH552-family lead**, not a verified chip
identification. The [WCH CH552 documentation](https://www.wch-ic.com/downloads/CH552DS1_PDF.html)
describes an 8051-family USB MCU. If that is the actual controller, it is a small
embedded target and needs its own suitable toolchain; migrating the Linux app to
Rust does not imply the factory MCU should use the same approach.

[ch55xduino](https://github.com/DeqingSun/ch55xduino) and
[wchisp](https://github.com/ch32-rs/wchisp) demonstrate tooling for that chip family.
They are not evidence that this board exposes a compatible programming interface,
that a vendor bootloader accepts their output, or that a factory image can be
restored. The latter project explicitly cautions about CH552 support.

Unresolved prerequisites are the exact board/MCU, LED IC and output protocol,
voltage/pinout, flash layout, image format, acceptance checks, bootloader protection
and a known-good factory image. USB DFU here is a vendor protocol; its name alone
does not imply standard `dfu-util` compatibility. No programmer was run, no hidden
USB commands were probed and no controller was opened.

Targeted searches did not locate a publicly accessible NL82K2 firmware source,
verified custom image or board-specific recovery guide. Nanoleaf panel replacement
projects and Wi-Fi firmware guides target different hardware.

## Replacing only the controller

A replacement controller could retain the existing strip and all 48 manually
mapped zones while allowing a deliberately low-latency wired protocol. It would
need a separately tested device adapter; factory USB support and fallback must
remain. This is a conditional hardware experiment, not a reason to generalize the
application into a multi-device platform.

An [RP2040](https://www.raspberrypi.com/products/rp2040/specifications/) has native
USB and programmable I/O. The official [Pico LED example](https://github.com/raspberrypi/pico-examples/blob/master/pio/ws2812/ws2812.c)
and [parallel/DMA example](https://github.com/raspberrypi/pico-examples/blob/master/pio/ws2812/ws2812_parallel.c)
show ways to separate USB service from compatible LED signalling. **The actual
Nanoleaf LED protocol has not been identified.** For a hypothetical 800 kbit/s,
24-bit RGB strip, 48 pixels require 1.44 ms of data signalling plus its reset time.
That is arithmetic for that hypothetical protocol, not a Nanoleaf measurement,
complete latency forecast or guaranteed benefit. PWM and optical response may
add delay.

WLED is not a verified drop-in image for this controller. Using a Wi-Fi controller
would also introduce a different latency/recovery tradeoff; native USB is the
more relevant experiment for this user's priority.

Before selecting parts: inspect labels/connector without damage, identify the
LED protocol and voltage, and obtain a logic trace of USB completion versus LED
data and light output. Use a reversible adapter and retain the factory controller
if feasible. Avoid any unverified power/ground or logic-level connection.
Existing calibration files remain preserved, but changing electrical drive or
brightness transfer requires new comparisons and possibly a separate copied
profile. Reusing old calibration is not proof of accuracy on a new controller.

## Effort and decision order

Estimates below are engineering time, conditional on information/equipment and
not promises or measured speedups. Vendor response and procurement time excluded.

| Route | Estimated effort | Potential actual benefit | Gate before adoption |
| --- | --- | --- | --- |
| Official device-specific update availability | Completed | Vendor currently offers none for this unit | Recheck only when new firmware information warrants it |
| Controlled official update evaluation | 1-3 days once a compatible image and recovery route exist | Could fix controller latency; may do nothing | Recoverability, baseline optical timing, colour and reconnect regression checks |
| Vendor source/protocol assistance | Days of investigation; external timing unknown | Best route to an informed stock-controller fix | Obtain source/image/recovery and ACK/presentation semantics |
| Custom factory-controller firmware | Several weeks or longer; may be blocked entirely | Potentially large if controller scheduling dominates | Confirm MCU/LED protocol, restorable factory image and programming access first |
| Reversible replacement controller prototype | Roughly 3-10 engineering days after compatible hardware is identified; longer if proprietary | More control over buffering, USB and LED scheduling | Electrical compatibility, optical/colour tests and preserved factory fallback |
| Host-side capture/preparation during serial ACK wait | Roughly 2-5 days for a measured prototype/recovery tests | Reduce stale work if profiling shows serialization | Preserve colours and one acknowledged HID transaction; no firmware risk |

The most useful next evidence is **screen-to-light timing**, together with an
LED-data trace if hardware access is available. A high-speed camera can first
show whether light changes near the USB write or its ACK; a photodiode/logic
analyser gives better precision. A 240 fps camera alone has about 4.17 ms frame
quantization, so it cannot validate a claimed 1-2 ms gain reliably. No such optical
measurement was made in this research.

With the normal updater offering nothing, a vendor inquiry should ask specifically for: latest firmware for NL82K2 hardware
1.1/manufacturer G; an image and supported recovery procedure for installed 1.5;
whether `0x82` means accepted or presented; whether there is an asynchronous or
sequence-numbered streaming mode; and whether the content-dependent 3-17 ms reply
wait is expected. No inquiry has been sent.

## Safe implementation and validation

Build the operator-only `usb_info` binary from `native/app/Cargo.toml` with Rust
1.95.0 and locked dependencies. Stop mirroring first, then run it with the existing
config path. It holds the same output lease as the app and refuses a running
Python fallback. It performs model/length and firmware/hardware/manufacturer
queries only; historical optional identity queries may be unsupported and are
reported as errors. It has no DFU/reset/erase/program path or arbitrary opcode
argument. It does not send serial numbers or make network requests.

89 app tests pass, including firmware nibble encoding and malformed-length
contracts; all-target GUI Clippy with warnings denied and formatting pass.
The read-only identity probe was run against this physical NL82K2. No new
NL82K1, capture, emitted-colour, reconnect, permission or firmware tests are claimed.
