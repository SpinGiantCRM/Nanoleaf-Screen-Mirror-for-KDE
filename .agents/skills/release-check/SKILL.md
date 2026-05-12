# release-check

## Description

Use this skill for release, packaging, install, desktop-entry, udev, version, or CI gate tasks.

## When to use it

- Arch/CachyOS packaging or dependency metadata changes.
- Release/version checks or GitHub workflow changes.
- Desktop entry, udev rule, autostart, reinstall, or uninstall behavior is involved.
- The prompt asks whether a build is releasable.

## Constraints

- Do not change runtime behavior unless required by the release/install bug.
- Keep packaging changes aligned with `pyproject.toml`, `README.md`, and `packaging/arch/`.
- Preserve KDE/Wayland desktop-entry authorization expectations.
- Do not claim AUR/runtime readiness without noting hardware/session limits.

## Verification expectations

- Run relevant release/package scripts such as `python scripts/check_release_versions.py` when touched.
- Run targeted tests for desktop entry, packaging helpers, or tooling when touched.
- Run `git diff --check`.
