# Release Toolchain Pins

This project pins release tooling versions and verifies their integrity to ensure reproducible release artifacts.

## AppImage tooling

- Tool: `appimagetool-x86_64.AppImage`
- Upstream project: `AppImage/AppImageKit`
- Pinned version: `13`
- Download URL: `https://github.com/AppImage/AppImageKit/releases/download/13/appimagetool-x86_64.AppImage`
- SHA256: `df3baf5ca5facbecfc2f3fa6713c29ab9cefa8fd8c1eac5d283b79cab33e4acb`

## Verification

- Local/CI verifier: `scripts/build-appimage.sh --verify-appimagetool`
- Behavior: downloads fail closed (`curl --fail`) and the build aborts if any pinned SHA256 does not match.


## Bundled Python runtime tooling

- Tooling source: `python-build-standalone`
- Pinned archive: `cpython-3.11.8+20240224-x86_64-unknown-linux-gnu-install_only.tar.gz`
- Download URL: `https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.11.8%2B20240224-x86_64-unknown-linux-gnu-install_only.tar.gz`
- SHA256: `94e13d0e5ad417035b80580f3e893a72e094b0900d5d64e7e34ab08e95439987`
- Install location in AppImage: `AppDir/usr/python`
