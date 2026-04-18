# Arch/CachyOS install options

## Primary user path (recommended)
Use the Arch package build/install path:

```bash
cd packaging/arch
makepkg -si
```

This is the recommended end-user path on Arch/CachyOS KDE.
It tracks repo tags via `PKGBUILD` `pkgver`, so keep package metadata in sync with `pyproject.toml` before release.

## Secondary path: standalone AppImage installer (experimental on Arch/CachyOS)

```bash
bash ./install-nanoleaf-kde-sync.sh ./nanoleaf-kde-sync.AppImage
```

Use this only if you explicitly want the release AppImage flow. The AppImage now bundles its own pinned CPython 3.11 runtime and does not require a host `python3.11`.

## Verify downloaded release assets

Download the checksum files from the same GitHub Release and run:

```bash
sha256sum -c nanoleaf-kde-sync.AppImage.sha256
sha256sum -c install-nanoleaf-kde-sync.sh.sha256
```

If that release also includes Python package artifacts, verify those too:

```bash
sha256sum -c nanoleaf_kde_sync-*.whl.sha256
sha256sum -c nanoleaf_kde_sync-*.tar.gz.sha256
```

## Sigstore verification (when `.sig` and `.pem` are provided)

If signature assets are present in the release, verify the AppImage (or other artifact) with:

```bash
cosign verify-blob nanoleaf-kde-sync.AppImage \
  --signature nanoleaf-kde-sync.AppImage.sig \
  --certificate nanoleaf-kde-sync.AppImage.pem \
  --certificate-identity-regexp 'https://github.com/.+/.+/.github/workflows/release.yml@refs/tags/.+' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Install `cosign` from Sigstore before verification if it is not already installed.

## Package install provides
- Python package + CLI commands
- Desktop entry: `/usr/share/applications/nanoleaf-kde-sync.desktop`
- Icon: `/usr/share/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg`
- udev rule: `/usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules`

## Advanced path: pip/source install (secondary)

```bash
pip install -r docs/requirements.txt
pip install .
./scripts/setup_udev.sh
```

Use this path only for development and debugging workflows.


## AppImage runtime architecture

- `scripts/build-appimage.sh` downloads pinned `appimagetool` and pinned `python-build-standalone` artifacts, then verifies SHA256 for both before build proceeds.
- The standalone interpreter and stdlib are unpacked to `AppDir/usr/python` and launcher scripts run `AppDir/usr/python/bin/python3` directly.
- Python package wheels are installed into the bundled interpreter site-packages, so runtime imports resolve from inside the AppImage.
- Launchers set `PYTHONHOME` and `PYTHONPATH` relative to the extracted AppImage mountpoint (`HERE`) for relocatable execution.
