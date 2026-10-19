# Moving from the retired Python application

Use the [native Rust installation](NATIVE_INSTALL.md) for current releases.
The Python/PyQt6 application, Rust-to-Python bridge, privileged C DRM helper,
historical wheel/AUR recipes and Python application release jobs are retired.
Native PyPI/AUR distribution is authorised. The pure-Python PyPI installer
downloads and verifies a pinned Rust app/helper release only on explicit
`--install-native`; subsequent commands execute the installed native app. Developer/operator Python scripts remain
supported.

## Which download is current?

| Route | What it contains |
| --- | --- |
| GitHub **native-v2.0.0** release, `native.tar.gz` | Native Rust app and matching capture helper; follow the [native guide](NATIVE_INSTALL.md). |
| PyPI **nanoleaf-kde-sync 1.9.3** | Retained Python application. Explicit 1.x versions remain historical. |
| PyPI **nanoleaf-kde-sync 2.0.0** | Pure-Python installer for the pinned native Rust release, once published; explicit `--install-native` downloads/verifies it. |
| GitHub **v1.9.3** release and Python wheel/source assets | Historical Python release retained for reference. |
| AUR **nanoleaf-kde-sync-bin** | Native binary recipe; registry publication is separate. See [package instructions](PACKAGING_AUR.md). |

The [PyPI project](https://pypi.org/project/nanoleaf-kde-sync/) showed only the old
1.9.3 release in the 19 October audit before native publication. Updating this
repository does not change an existing PyPI artifact or its description; a native
2.0.0 upload is a separate release. Use the explicit native release tag
when choosing GitHub downloads; older release pages and search results may still
point to Python commands.

## Preserve your settings

The native app continues to use
`~/.config/nanoleaf-kde-sync/config.toml`. Keep that directory: it contains your
calibration profiles, manual mapping and other settings. The native app preserves
unknown fields and creates private backups when saving. Narrow Nanoleaf HID udev
permissions remain relevant; native capture does not need DRM capabilities.

Quit the Python tray/service and disable its login startup before starting native
mirroring. Install and launch the native bundle, then review the saved monitor,
manual zone count, four corner anchors and channel order in **Strip setup**.
Existing calibration profiles remain available under **Colour calibration**.

The native installer manages only its own command, launcher and login entry.
Use the original package manager to upgrade or retire an old installation.
After native PyPI 2.0.0 is available, pipx users can upgrade to that version;
otherwise `pipx uninstall nanoleaf-kde-sync` removes the old pipx app. A
Pacman-owned installation should be managed through Pacman. Preserve configuration
and avoid manually deleting package-owned files. Do not run two strip-control
applications together.

Previous immutable native app/helper pairs provide binary rollback. Rollback does
not restore earlier settings; retain a known-good configuration copy separately.

## Historical source and evidence

The last complete pre-retirement source is Git commit
`85f59888d373667f48651f8cbb2333b8605bfbc5`. Historical reports and `perf/` results
retain their original scope; their Python instructions describe an earlier state.
Generated fixtures under `native/fixtures/` retain colour, calibration, geometry
and protocol reference vectors. Native tests consume those fixtures without
importing the old app; their original generators remain recoverable from history.

Retirement does not establish an optical-response or running-app CPU improvement:
the native application already had no Python runtime dependency.
