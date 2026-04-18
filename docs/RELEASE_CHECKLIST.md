# Release checklist (first public RC)

## Version and changelog

- [ ] `docs/CHANGELOG.md` updated with release notes under `## Unreleased` (automation will stamp release heading/version from tag).
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

- [ ] RC matrix executed and signed off (`docs/RC_TEST_MATRIX.md`) across Arch + CachyOS and KDE Wayland/X11 where supported.
- [ ] RC run result artifact updated (table in release PR description via `.github/PULL_REQUEST_TEMPLATE/release.md` or in `docs/RC_TEST_MATRIX.md`).
- [ ] `nanoleaf-kde-sync-doctor` and `nanoleaf-kde-sync-smoke-test` run in target environment.
- [ ] Tray Start/Stop/Status verified.
- [ ] Tray doctor/smoke actions run without freezing UI.
- [ ] Issue templates present and point users to troubleshooting guidance.

## Documentation quality

- [ ] README reflects current RC scope and quick-start.
- [ ] Legal artifact present in expected repo contents (`LICENSE` at repository root).
- [ ] License wording/metadata is consistent across `README.md`, `LICENSE`, `packaging/arch/PKGBUILD`, `pyproject.toml`, and published release/install artifacts.
- [ ] Install and troubleshooting docs are separated and consistent.
- [ ] Hardware + smoke docs match current commands and behavior.

## How to cut a release

1. Update `docs/CHANGELOG.md` with release notes under `## Unreleased`.
2. (Optional but recommended) Dry-run metadata sync locally: `python3 ./scripts/sync_release_version.py --git-tag vX.Y.Z`.
3. Run metadata validation locally: `python3 ./scripts/validate_release_metadata.py --git-tag vX.Y.Z`.
4. Open a release PR using `.github/PULL_REQUEST_TEMPLATE/release.md`, complete RC matrix sign-off, and attach run evidence.
5. Create and push the signed release tag using the exact same version (for example, `v0.1.0`) **only after** matrix sign-off is complete.
6. Confirm GitHub Actions **CI / Release metadata validation** and **Release / Validate release metadata** steps pass before trusting published artifacts.
