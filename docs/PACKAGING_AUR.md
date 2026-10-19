# Native package distribution

The GitHub native archive is the direct installation route. Native PyPI and AUR
packaging ship the same Rust application and capture helper. The historical
Python/PyQt6 application remains retired. A package built in this repository is
not proof that its registry publication or account setup has completed.

## PyPI with pipx

The PyPI distribution is **nanoleaf-kde-sync 2.0.0**, a genuinely pure-Python
`py3-none-any` **installer** wheel with no ELF binaries. Python 3.11 or newer is
used only for standard-library installation and forwarding later commands to the
installed native app. Explicit `--install-native` downloads the version-pinned
GitHub native archive and checksum, verifies the archive against its embedded
release SHA-256, checks archive paths/internal manifest, then invokes the native
installer. Installing the wheel or using help/version/default commands does not
download the runtime.

The native runtime remains Linux x86_64, requires glibc 2.39 or newer and uses the
Ubuntu 24.04 build baseline. The Python installer’s pure tag does not imply that
the native app supports other operating systems or architectures. No legacy
Python/PyQt6 application or privileged DRM helper is restored.

After native 2.0.0 is published on [PyPI](https://pypi.org/project/nanoleaf-kde-sync/):

```bash
pipx install nanoleaf-kde-sync==2.0.0
~/.local/bin/nanoleaf-kde-sync --install-native
~/.local/bin/nanoleaf-native --version
```

Existing pipx users should Quit the old tray and disable its startup before
running `pipx upgrade nanoleaf-kde-sync`. Then run its `--install-native` command
again to download/install the new immutable native pair and refresh KDE's launcher.
Check the installed Rust version with `nanoleaf-native --version`; the wrapper
identifies the installer only before native installation; afterward it delegates
to the installed app.

The pipx command is `nanoleaf-kde-sync`; the managed native installation creates
`~/.local/bin/nanoleaf-native`. The desktop launcher uses that installed native
binary directly. For removal, Quit, run
`~/.local/bin/nanoleaf-native --uninstall-native`, then
`pipx uninstall nanoleaf-kde-sync`. Removing pipx alone leaves the separately
installed native desktop app. Configuration and recoverable native versions
remain retained. [Full setup and rollback](NATIVE_INSTALL.md) describes the shared
configuration and immutable pair.

## Arch/CachyOS and AUR

The native binary recipe is **nanoleaf-kde-sync-bin** under
`packaging/arch/nanoleaf-kde-sync-bin/`. It packages the checksum-pinned
`native-v2.0.0` GitHub archive. The `-bin` suffix follows
[Arch's prebuilt-package naming rule](https://wiki.archlinux.org/title/AUR_submission_guidelines).

Before AUR publication, use the checked-out recipe after the native release and
final archive checksum are available:

```bash
cd packaging/arch/nanoleaf-kde-sync-bin
makepkg --printsrcinfo
makepkg --cleanbuild --syncdeps --install
```

Review the recipe before installing. Once the recipe is published on AUR, an AUR
helper can install `nanoleaf-kde-sync-bin`. Its registry page and publication must
be confirmed separately; the old name `nanoleaf-kde-sync` had no listing in the
19 October 2026 audit.

The system package owns `/usr/lib/nanoleaf-native/bin/`, the
`/usr/bin/nanoleaf-native` command, desktop launcher, icon and narrow NL82K1/NL82K2
udev rule. Reconnect the strip after installing the rule. It creates no group,
sets no DRM capabilities, enables no autostart and does not modify user
configuration. Use Pacman/AUR tooling for system-package upgrades and removal;
avoid the user-prefix `--install-native`/`--uninstall-native` maintenance commands
for package-owned files. Preserve configuration before changing distribution
channels, Quit the old tray, and start only one installed copy. When switching
from a user-prefix or pipx-installed native copy to AUR, first run
`~/.local/bin/nanoleaf-native --uninstall-native` (with its custom prefix if used).
This removes the per-user command and desktop launcher that would otherwise
shadow the system package. Calibration and recoverable native versions remain.

## Maintainer publication

The GitHub native archive is verified and published before the separate PyPI
OIDC job publishes its pinned installer wheel. Existing PyPI versions fail closed
rather than being silently skipped. The PyPI project must trust
owner **SpinGiantCRM**, repository **Nanoleaf-Screen-Mirror-for-KDE** and the exact
**release.yml** workflow filename. Existing artifact provenance used that
filename, but public metadata cannot confirm the current account trust settings.
Configure the publisher through the project's Publishing page; see
[PyPI's official instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

AUR publication requires an AUR account with a registered SSH public key, a
package Git repository and tracked `PKGBUILD` plus regenerated `.SRCINFO`.
AUR accepts pushes to `master`; see
[official submission instructions](https://wiki.archlinux.org/title/AUR_submission_guidelines).
A local recipe does not establish authenticated AUR write access. Keep private
keys and registry credentials out of this repository.

## Historical audit — before native publication, 19 October 2026

| Route | Verified state |
| --- | --- |
| [PyPI metadata](https://pypi.org/pypi/nanoleaf-kde-sync/json) | Only 1.9.3, uploaded 24 June 2026; Python wheel/source files unyanked, no project URL metadata. |
| [AUR old-name lookup](https://aur.archlinux.org/rpc/v5/info?arg%5B%5D=nanoleaf-kde-sync) | Exact lookup returned zero results; the package page returned 404. |
| [GitHub releases](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases) | Only historical v1.9.3 Python assets were published. |

The old PyPI wheel declares `py3-none-any` and pure Python while containing an
x86_64 ELF DRM helper. Its entry points lack the setup-permissions command used
by later Python-era guides. The description includes relative documentation links
under PyPI's own domain and conditional AUR instructions. Those are historical
packaging/documentation inconsistencies, not native 2.0.0 behavior. The wheel was
inspected without installation or execution. The native installer wheel contains no ELF binaries and supplies absolute
documentation links; old files remain
historical. See [migration guidance](LEGACY_PYTHON.md).
