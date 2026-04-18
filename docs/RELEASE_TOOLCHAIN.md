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
- Behavior: download fails closed (`curl --fail`) and the build aborts if SHA256 does not match.
