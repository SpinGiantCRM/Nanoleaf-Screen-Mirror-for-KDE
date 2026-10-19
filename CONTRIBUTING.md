# Contributing

Build the Rust application and matching capture worker using [native installation](docs/NATIVE_INSTALL.md).
See [the user guide](docs/USER_GUIDE.md) and
[native release verification](docs/RELEASE_RC_MATRIX.md) for scope, colour,
calibration and hardware guardrails.
One selected monitor, one manually configured strip and acknowledged serial USB
remain the product contract. Do not introduce new FPS or priority controls.

Run `bash scripts/release_gate.sh` for Rust core/application/capture tests, Clippy,
formatting and operator-script contracts. Python is used only for developer and
operator scripts and the native PyPI installer/exec launcher; install Ruff
for their lint/format checks. Hardware Vulkan
oracles, live colour parity, permissions and physical USB/session recovery are
separate from headless CI and must be reported accurately.

## Monthly maintenance

[Monthly maintenance](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/monthly-maintenance.yml)
runs on the first day of each month at 04:17 UTC and supports **Run workflow**.
It reuses the full CI suite (including fresh Rust advisory checks) and native
bundle build/install/rollback checks, without publishing a release. Independently,
Ubuntu 24.04 and the current Ubuntu runner download the latest public PyPI wheel,
require matching stable GitHub/PyPI versions and checksum pins, and exercise the
published installer using real HTTPS GitHub downloads. Isolated installation,
custom-prefix upgrade, read-only doctor, uninstall and configuration preservation
are checked. CI stubs only KDE's desktop-cache refresh; no capture/output starts.
The run retains JSON evidence and a summary. Failed jobs make the run fail;
GitHub Actions notification preferences control delivery of GitHub alerts.

GitHub may disable public-repository schedules after 60 days without repository
activity. A separate monthly Codex follow-up checks for a recent completed run,
reports failures, and dispatches a missing run. That follow-up depends on the
Codex host/account remaining available; GitHub scheduling and manual dispatch
remain usable independently. Check the Actions page if notifications stop.
These automated checks do not replace physical display/strip and sleep/wake tests.

Run the same public-network installation check locally with:

```bash
python3 scripts/verify_public_install.py --output dist/public-install.json
```

It uses disposable HOME/XDG directories and never updates the daily installation.
Expect failures while a new release is published to only one of GitHub/PyPI;
rerun after both channels finish publishing. Do not suppress version mismatches.

Keep calibration and unknown configuration fields compatible. Changes to mapping,
colour or schemas require meaningful regression tests under `native/app/tests/`
and `native/core/tests/`. The immutable native bundle must preserve user data and
keep earlier paired binaries for rollback. Validate package changes with
`scripts/verify_native_bundle.py` in isolated user directories.

Native distribution supports three routes: the immutable GitHub bundle, a
pure-Python PyPI installer and the AUR `nanoleaf-kde-sync-bin` recipe. The PyPI
wheel contains no ELF binaries and uses `py3-none-any` truthfully. Only explicit
`--install-native` downloads the version-pinned archive/checksum; verify its
embedded release SHA-256, archive safety and internal manifest before invoking
the native installer. Help/version/default and ordinary forwarded commands must
never download. The native app remains Linux x86_64 with glibc 2.39+; a pure
installer tag does not widen native compatibility. Do not introduce Python
capture, processing, output or UI logic, or claim unverified manylinux support.

For packaging changes, run the standard-library packaging tests and Ruff:

```bash
python3 -m unittest discover -s scripts -p 'test_*native*.py'
ruff check scripts
ruff format --check scripts
```

`test_build_native_wheel.py` covers pure installer-wheel metadata, pinned download
verification, archive guards and launcher forwarding.
`test_native_arch_package.py` checks system staging,
permissions, pair integrity and Arch metadata. Build a wheel with
`python3 scripts/build_native_wheel.py --archive dist/native.tar.gz --output dist/wheels`
after producing a fresh native archive and its `native.tar.gz.sha256` companion. Inspect the archive/wheel and verify
installation in isolated user directories. Check wheel purity, explicit-only
downloads, native exec forwarding, manifest integrity, version metadata and
preserved configuration. For AUR changes, run
`makepkg --printsrcinfo`, compare the generated `.SRCINFO`, and build the package
without installing it on the developer's real desktop. Match the release archive
checksum; do not use `SKIP`. A published registry listing and authenticated
maintainer setup require separate verification from a local build. See
[distribution guidance](docs/PACKAGING_AUR.md).

The Python/PyQt6 app, C DRM helper, bridge and historical Python wheel/AUR recipes
remain retired. Historical evidence and native golden fixtures remain. Do not
reintroduce their processing, capture, output or GUI logic as runtime dependencies.
Keep public PR descriptions concise, include measured
benefits and verification limits, and never commit secrets or captured pixels.
