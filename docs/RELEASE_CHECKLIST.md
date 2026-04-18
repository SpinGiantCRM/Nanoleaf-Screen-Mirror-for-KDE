# Release checklist

## Version and changelog

- [ ] `docs/CHANGELOG.md` updated with release notes under `## Unreleased`.
- [ ] Tag plan prepared (`vX.Y.Z`, or pre-release tag such as `vX.Y.Z-rc1`).

## CI gates

- [ ] **CI / Validate release metadata** passes on the release commit (`.github/workflows/ci.yml`, job: `validate-release-metadata`).
- [ ] **CI / Run test suite** passes on the release commit (`.github/workflows/ci.yml`, job: `tests`).

## Build/release artifacts

- [ ] **Release / Build and publish release assets** passes for the release tag (`.github/workflows/release.yml`, job: `publish`).
- [ ] AppImage and installer are attached to the GitHub release.
- [ ] Wheel and source distribution (`sdist`) are attached to the GitHub release.
- [ ] SHA256 checksum files are attached for all released artifacts.

## Arch/CachyOS packaging

- [ ] `cd packaging/arch && makepkg -sf` succeeds.
- [ ] Installed package exposes expected commands.
- [ ] Desktop entry and icon install at expected paths.
- [ ] udev rule installs and reload guidance is correct.

## Runtime and supportability

- [ ] RC matrix executed and signed off (`docs/RC_TEST_MATRIX.md`) across Arch + CachyOS and KDE Wayland/X11 where supported.
- [ ] `nanoleaf-kde-sync-doctor` and `nanoleaf-kde-sync-smoke-test` run in target environment.
- [ ] Tray Start/Stop/Status verified.
- [ ] Tray doctor/smoke actions run without freezing UI.

## Documentation quality

- [ ] README reflects current release scope and quick-start.
- [ ] Legal artifact present in expected repo contents (`LICENSE` at repository root).
- [ ] License wording/metadata is consistent across `README.md`, `LICENSE`, `packaging/arch/PKGBUILD`, `pyproject.toml`, and published release/install artifacts.
- [ ] Install and troubleshooting docs are separated and consistent.
- [ ] Hardware + smoke docs match current commands and behavior.

## How to cut a release

1. Update `docs/CHANGELOG.md` with release notes under `## Unreleased`.
2. (Optional but recommended) Dry-run metadata sync locally: `python3 ./scripts/sync_release_version.py --git-tag vX.Y.Z`.
3. Run metadata validation locally: `python3 ./scripts/validate_release_metadata.py --git-tag vX.Y.Z`.
4. Make sure `CI` is green on the exact commit you plan to tag.
5. Create and push the signed release tag using the exact same version (for example, `v0.1.0`).
6. Confirm the `Release` workflow completed and published all expected assets.
