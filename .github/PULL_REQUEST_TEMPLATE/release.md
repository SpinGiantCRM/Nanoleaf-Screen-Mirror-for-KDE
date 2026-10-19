## Native release

- Native version / tag: `native-vX.Y.Z` (must match `native/app/Cargo.toml`)
- Bundle artifact/checksum and exact source revision:
- Supported KDE/Wayland colour contract:

## Validation

- [ ] Rust application, core and capture contracts, Clippy and format checks pass.
- [ ] Cargo audit and repository security checks pass.
- [ ] Isolated paired install/upgrade/rollback/uninstall smoke passes.
- [ ] Selected-monitor capture, faithful colours and Stop/tray verified on real KDE.
- [ ] Sharing revocation, explicit restart and USB reconnect evidence recorded.
- [ ] Manual count/calibration and unknown configuration fields preserved.
- [ ] Hardware not tested, optical latency, colourimeter accuracy and power limits stated.

No Python/PyPI/AUR release is produced. Retain previous native app/helper pairs.
Do not substitute software ACK timing for emitted-light latency.
