# Vendor support clarifications — 4 November 2026

Source: a Nanoleaf Technical Support reply received on 4 November 2026 ACDT
(sent 3 November UTC), following an earlier 21 October reply. This is a
paraphrase of private support correspondence, not an independently verified
hardware specification or a published engineering recovery procedure. Personal
information, mail headers and the original correspondence are not reproduced.

## Colour acknowledgements

Support says a successful ACK confirms receipt, parsing and acceptance of the
payload into the controller's internal processing buffer. It does not confirm
that the LEDs emitted the frame. Their explanation is that individual LED driver
ICs provide no closed-loop display telemetry back to the controller or host.

The earlier reply described colour command `0x02` and response `0x82`, with a
one-byte success/failure code. The latest reply resolves the previously open
accepted-versus-displayed distinction at the support-documentation level.

Keep USB transactions serial and acknowledged. Host ACK timings remain useful
transport measurements, but cannot establish optical latency, LED presentation
time, or the controller's internal scheduling. This correspondence supplies no
new frame-rate or timing guarantee and does not justify skipping ACKs.

## Recovery and internal design

Support states there is no documented or supported external recovery method if
the application firmware cannot boot or initialize USB. They describe the product
as having no hardware reset mechanism or external fallback capable of restoring
factory data or re-entering the bootloader in that failure case, and recommend
continuing to hold off on modified firmware.

They decline to share the MCU architecture, board revisions, firmware formats,
source code or development toolchains because these are proprietary. The exact
chip/board and an independent recovery route therefore remain unestablished.

This confirms the existing decision to keep firmware work closed-case research.
It is not permission for loader entry, reset, erase, flashing, electrical probing
or vendor-updater execution. A stock update remains an update file, not a backup
of factory data. The support statement does not independently prove that every
undocumented or enclosure-open hardware route is impossible.

## Relation to the Warframe investigation

These replies concern the USB controller and firmware. They provide no explanation
or remedy for the NVIDIA GPU timeouts observed with Warframe. See the separate
[capture investigation](WARFRAME_CAPTURE_INVESTIGATION.md).
