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

## Socket vs pip-audit

- **pip-audit** checks installed packages against a database of **known CVEs**. CI uses
  [`scripts/pip_audit_runtime.sh`](../scripts/pip_audit_runtime.sh) against a production-only
  install (`pip install .`, no `[test]` extras).
- **Socket** (and similar supply-chain scanners) statically analyze **upstream package source
  trees**, including example files, test fixtures, and vendored build tooling. That produces
  heuristic alerts that are not CVEs and may not reflect runtime exposure.

When triaging Socket alerts, prefer the exposure column below over alert severity alone.

## Dependency scan triage

Third-party supply-chain scanners may flag upstream packages. Current accepted findings (as of
Socket export 2026-07-06):

| Package | Version | Alert type | Upstream path | Exposure in this app |
|---------|---------|------------|---------------|----------------------|
| bandit | 1.9.4 | gptSecurity | `examples/nosec.py` | **Dev-only** — SAST tool example; never imported |
| bandit | 1.9.4 | gptSecurity | `examples/wildcard-injection.py` | **Dev-only** — SAST tool example; never imported |
| bandit | 1.9.4 | gptSecurity | `examples/eval.py` | **Dev-only** — SAST tool example; never imported |
| PyQt6 | 6.11.0 | potentialVulnerability | `uic/objcreator.py` (`load_plugin` exec) | **None** — UI built programmatically; no widget-plugin dirs |
| PyQt6 | 6.11.0 | potentialVulnerability | `uic/load_ui.py` (`loadUiType` exec) | **None** — no `.ui` files loaded |
| mypy | 2.1.0 | gptSecurity | `mypy/dmypy/client.py` (pickle.loads) | **Dev-only** — CI type checker, not a runtime dependency |
| ruff | 0.15.20 | gptSecurity | `crates/ruff_python_formatter/.../preview_long_strings__regression.py` | **Dev-only** — Black regression fixture inside formatter tests |
| ruff | 0.15.20 | installScripts | `crates/ruff_annotate_snippets/tests/formatter.rs` | **Dev-only** — Rust test resource, not executed at install |
| numpy | 2.5.1 | potentialVulnerability | `numpy/f2py/capi_maps.py` (eval) | **Not executed** — f2py build path only; mirroring does not run f2py |
| numpy | 2.5.1 | gptSecurity | `vendored-meson/meson/ci/run.ps1` | **Not executed** — vendored meson CI bootstrap script |
| numpy | 2.5.1 | potentialVulnerability | `vendored-meson/meson/mesonbuild/scripts/regen_checker.py` | **Not executed** — meson build helper |
| numpy | 2.5.1 | obfuscatedFile | `vendored-meson/meson/test cases/.../foo-1.0.tar.xz` | **Not executed** — meson test-case archive |
| numpy | 2.5.1 | gptMalware | `vendored-meson/meson/mesonbuild/scripts/pickle_env.py` | **Not executed** — meson build helper; no runtime pickle of env |

**Runtime dependencies with accepted alerts:** PyQt6, numpy (upstream internals only).

**Dev-only dependencies with accepted alerts:** bandit, mypy, ruff (from `[project.optional-dependencies] test`).

Re-scan cadence: every push (bandit, runtime pip-audit), weekly CI, Dependabot PRs, Socket on PRs.

For future PRs that re-trigger the same accepted finding after a version bump, use Socket bot
commands documented at https://docs.socket.dev/docs/ignoring-pull-request-alerts (e.g.
`@SocketSecurity ignore bandit@1.9.4`).

## CI security gates

- Gitleaks (secrets)
- bandit (Python SAST on `src/` only)
- Semgrep (`p/python`)
- CodeQL (`security-and-quality`)
- pip-audit on **production** dependencies only (`scripts/pip_audit_runtime.sh`)
- GitHub dependency review on pull requests

Local pre-release check:

```bash
./scripts/release_gate.sh
```

Runtime-only dependency audit:

```bash
./scripts/pip_audit_runtime.sh
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
