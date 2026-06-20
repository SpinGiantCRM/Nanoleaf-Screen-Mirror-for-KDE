# Security

## Reporting issues

Report security concerns privately via GitHub Security Advisories on this repository, or open a minimal public issue if private reporting is unavailable. Do not include secrets, tokens, or full diagnostic dumps with personal paths in public reports.

## Threat model (summary)

This app:

- Writes colors to a **single USB HID device** after VID/PID validation
- Reads screen content via **KWin DBus** or portal/kmsgrab fallbacks
- Stores config under the user config directory
- Exports diagnostics to a private temp subdirectory (`0o700`)

It does **not** expose a network service or load untrusted Qt Designer `.ui` files.

## Dependency scan triage

Third-party supply-chain scanners may flag upstream packages. Current accepted findings:

| Package | Finding | Exposure in this app |
|---------|---------|----------------------|
| PyQt6 | `loadUi` / widget-plugin `exec` | **None** — UI is built programmatically; no `.ui` files |
| mypy | dmypy `pickle.loads` | **Dev-only** CI tool, not a runtime dependency |
| numpy | vendored meson test artifacts | **Not executed** at runtime |
| ruff | install script patterns in tests | **Dev-only** |

Re-scan cadence: every push (pip-audit, bandit), weekly CI, Dependabot PRs.

## CI security gates

- Gitleaks (secrets)
- bandit (Python SAST)
- Semgrep (`p/python`)
- CodeQL (`security-and-quality`)
- pip-audit (known CVEs in dependencies)
- GitHub dependency review on pull requests

Local pre-release check:

```bash
./scripts/release_gate.sh
```

## Manual release checklist (KDE integration)

Automated CI cannot exercise real KWin + USB on every runner. Before tagging a release:

1. `nanoleaf-kde-sync-doctor` — no blocking errors
2. `nanoleaf-kde-sync-smoke-test` — pass from desktop-entry launch context
3. Start mirroring for one session; verify LEDs track screen edges
4. Settings → Save while mirroring → Close — single restart only
5. Tray → Troubleshooting guide opens local or online doc

## Hardening in application code

- HID opens only after VID/PID match (`0x37fa:0x8201` / `0x8202`)
- Protocol responses validated for length before parsing
- User doc paths sanitized (no `..` traversal)
- Diagnostic export directories created with restrictive permissions
