# Release checklist (first public RC)

## Version and changelog

- [ ] `pyproject.toml` version updated.
- [ ] `docs/CHANGELOG.md` updated with release notes.
- [ ] Tag plan prepared (`vX.Y.Z`).

## Test and CI gates

- [ ] **CI / Unit and integration tests (Ubuntu)** job passes (`.github/workflows/ci.yml`, job id: `unit-integration-tests`).
- [ ] **CI / Unit and integration tests (Arch Linux)** job passes (`.github/workflows/ci.yml`, job id: `unit-integration-tests-arch`).
- [ ] **CI / Release/install regression tests (Ubuntu)** job passes (`.github/workflows/ci.yml`, job id: `release-install-regression-tests`).
- [ ] **CI / Release/install regression tests (Arch Linux)** job passes (`.github/workflows/ci.yml`, job id: `release-install-regression-tests-arch`).
- [ ] **CI / Arch package metadata sanity** job passes (`.github/workflows/ci.yml`, job id: `arch-package-metadata-sanity`).
- [ ] **Pre-release gates / Unit and integration tests (Ubuntu)** job passes on candidate tag (`.github/workflows/pre-release.yml`, job id: `unit-integration-tests`).
- [ ] **Pre-release gates / Unit and integration tests (Arch Linux)** job passes on candidate tag (`.github/workflows/pre-release.yml`, job id: `unit-integration-tests-arch`).
- [ ] **Pre-release gates / Release/install regression tests (Ubuntu)** job passes on candidate tag (`.github/workflows/pre-release.yml`, job id: `release-install-regression-tests`).
- [ ] **Pre-release gates / Release/install regression tests (Arch Linux)** job passes on candidate tag (`.github/workflows/pre-release.yml`, job id: `release-install-regression-tests-arch`).
- [ ] **Pre-release gates / Arch package metadata sanity** job passes on candidate tag (`.github/workflows/pre-release.yml`, job id: `arch-package-metadata-sanity`).

## Build/release artifacts

- [ ] **Release / Build AppImage** and **Release / Validate release artifacts exist** steps pass (`.github/workflows/release.yml`, job id: `publish`).
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

## How to cut a release

1. Update `pyproject.toml` with the target release version (`X.Y.Z`) and add the matching section to `docs/CHANGELOG.md`.
2. Run metadata validation locally: `python3 ./scripts/validate_release_metadata.py --git-tag vX.Y.Z`.
3. Create and push the signed release tag using the exact same version (for example, `v0.1.0`).
4. Confirm GitHub Actions **CI / Release metadata validation** and **Release / Validate release metadata** steps pass before trusting published artifacts.
