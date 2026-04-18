# Release checklist (first public RC)

## Version and changelog

- [ ] `pyproject.toml` version updated.
- [ ] `docs/CHANGELOG.md` updated with release notes.
- [ ] Tag plan prepared (`vX.Y.Z`).

## Test and CI gates

- [ ] Local tests pass: `pytest -q`.
- [ ] Packaging metadata sanity check passes locally (`cd packaging/arch && makepkg --printsrcinfo >/dev/null`).
- [ ] Version metadata check passes locally (`pytest -q tests/test_release_install_regressions.py`).

## Build/release artifacts

- [ ] Build artifacts generated locally (`python -m build`).
- [ ] Arch package source tarball URL resolves for planned tag (`vX.Y.Z`).

## Arch/CachyOS packaging

- [ ] `cd packaging/arch && makepkg -sf` succeeds.
- [ ] Installed package exposes expected commands.
- [ ] Desktop entry and icon install at expected paths.
- [ ] udev rule installs and reload guidance is correct.

## Runtime and supportability

- [ ] `nanoleaf-kde-sync-doctor` and `nanoleaf-kde-sync-smoke-test` run in target environment.
- [ ] Tray Start/Stop/Status verified.
- [ ] Tray doctor/smoke actions run without freezing UI.
- [ ] Issue templates present and point users to troubleshooting guidance.

## Documentation quality

- [ ] README reflects current RC scope and quick-start.
- [ ] Install and troubleshooting docs are separated and consistent.
- [ ] Hardware + smoke docs match current commands and behavior.
