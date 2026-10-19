# Native smoke checks

Run `nanoleaf-native --doctor` first; this is read-only. Launch the tray from KDE,
open Settings and confirm the selected monitor, manual mapping and calibration.
Start mirroring and visually check neutral, dark and changing scenes. Stop should
end mirroring while keeping the tray available. Permission revocation requires
explicit Start; a USB reconnect must reopen with a full output frame.

Use [native packaging](NATIVE_INSTALL.md) and `scripts/verify_native_bundle.py`
with isolated directories for install/upgrade/rollback/uninstall checks. Automated
Rust contracts do not establish optical latency, measured colour accuracy or
physical suspend/USB recovery. Report actual user observations separately.

The old `nanoleaf-kde-sync-smoke-test` command is retired with the Python app.
