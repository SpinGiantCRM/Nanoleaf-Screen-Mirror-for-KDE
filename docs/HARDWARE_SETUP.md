# Hardware setup

The Rust application supports one Nanoleaf NL82K1/NL82K2 USB strip. Use a reliable
USB data cable and manually configure its zone count; reported count never
automatically changes your mapping.

Run `nanoleaf-native --doctor` for read-only USB/configuration readiness. On a
permission failure, use the narrow rule supplied as
`assets/udev/60-nanoleaf-kde-sync.rules`; an administrator can install it under
`/etc/udev/rules.d/` and reload udev, then reconnect the strip. Native capture and
output require no root privileges or DRM capabilities.

Use [native install](NATIVE_INSTALL.md), then configure monitor, corner anchors,
channel order and calibration in Settings. Do not run two clients against the
strip. USB reconnect begins with a full frame before safe shorter updates can
resume. Firmware work remains closed-case research: no flashing, erasing,
resetting or loader entry without an independent recovery route and factory-data
preservation. Stock update files are not full-device backups.
