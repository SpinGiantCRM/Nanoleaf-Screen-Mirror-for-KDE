# Troubleshooting

Start with `nanoleaf-native --doctor`. It reads configuration and detects USB
identity without requesting screen capture or driving LEDs. `nanoleaf-native
--status` queries a running tray. Run `nanoleaf-native --run` in a terminal to
see startup failures; do not start a second copy against the strip.

## App does not open

Check the native bundle's system-library requirements and use its matched
capture helper. Quit the tray before upgrading; follow [native install and
rollback](NATIVE_INSTALL.md). Old pipx/PyQt launchers are retired.

## No HID device found or permission denied

Reconnect the USB cable and check `lsusb`, then rerun the doctor. The supplied
`assets/udev/60-nanoleaf-kde-sync.rules` grants narrow access to supported strips.
If permissions are missing, have an administrator install that rule and reconnect.
Native mirroring needs no root access, DRM helper or capabilities. The reported
strip size is diagnostic; your manual count remains authoritative.

## Screen sharing stopped

Use Start to request sharing again and select the configured monitor. Permission
revocation intentionally stops capture. No silent backend switching or automatic
reacquisition occurs. Lock/session interruption stops output; use Start after
unlock if requested. Keep portal/Vulkan on its validated KDE colour contract;
unsupported versions or colour formats fail explicitly.

## Delay, flicker or incorrect colours

Check Advanced for capture, processing, latest-slot queue and USB timings, as
well as full/shortened payload counters. The receiver's acknowledged transaction
can limit delivered FPS below Target. Do not overlap USB requests or skip ACKs.
Keep calibration and channel order intact; confirm anchors/manual count and
neutral white/grey before tuning colour. Black should turn off promptly. Captured
SDR pixels are not raw HDR and must not be PQ/HLG-decoded.

To diagnose retained trailing-zone updates, quit the tray and run
`NANOLEAF_SHORT_UPDATES=0 nanoleaf-native --run`. This forces full frames without
changing calibration. Previous native bundles remain available for rollback.

## Recovery and reporting

Stop releases mirroring while preserving the tray; Quit closes it. Reconnect
should reopen the strip and start with a full frame. Use a bounded live probe only
when no other application owns output. Include version, selected backend, manual
count, doctor and timing metadata in reports. Do not publish screen pixels,
raw screen-derived HID payloads, full calibration files or personal paths.
