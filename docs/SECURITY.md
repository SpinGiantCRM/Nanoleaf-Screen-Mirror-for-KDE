# Security

## Reporting issues

Report security concerns privately via GitHub Security Advisories on this repository, or open a minimal public issue if private reporting is unavailable. Do not include secrets, tokens, or full diagnostic dumps with personal paths in public reports.

## Threat model (summary)

This app:

- Writes colors to a **single USB HID device** after VID/PID validation
- Reads screen content via **KWin DBus** or explicitly selected portal/PipeWire/Vulkan
- Stores config under the user config directory
- Exports diagnostics to a private temp subdirectory (`0o700`)

It does **not** expose a network service or require privileged DRM access.

## CI security gates

Cargo audit checks every retained Rust lockfile. Gitleaks checks secrets;
Semgrep and CodeQL scan retained Python operator/build scripts. GitHub dependency
review covers dependency changes. The retired Python runtime and C DRM helper
are absent; their historical dependency triage is available in Git history.

## Manual release checklist (KDE integration)

1. Run `nanoleaf-native --doctor` without output.
2. Start from the KDE launcher and verify selected-monitor capture and colours.
3. Verify Stop, Save / Apply, sharing revocation and explicit restart.
4. Test physical USB recovery with an operator, preserving controller state.
5. Verify paired bundle install/rollback in isolated user directories.

## Hardening in application code

- HID opens only after VID/PID match (`0x37fa:0x8201` / `0x8202`)
- Protocol responses validated for length before parsing
- User doc paths sanitized (no `..` traversal)
- Diagnostic export directories created with restrictive permissions
