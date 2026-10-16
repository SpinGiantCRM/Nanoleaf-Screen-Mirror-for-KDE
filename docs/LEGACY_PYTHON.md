# Python application retired — 2026-10-16

The user explicitly requested removal of the old Python application after the
Rust migration. The Python/PyQt6 runtime, Rust-to-Python bridge, privileged C DRM
helper, wheel/AUR packaging, legacy tests and release/CI jobs have been removed
from the active tree. The installed pipx application and its obsolete launchers
were removed on the development host. A second Pacman-owned 1.9.1 installation
was also removed with the user's administrator session. One unowned helper from
an older manual install was found afterward and removed separately. Both elevated
DRM helper copies and the legacy import/commands are verified absent. The existing
unowned `/etc/udev/rules.d/60-nanoleaf-kde-sync.rules` remains for native HID access.
The system Python interpreter and operator
scripts are unrelated to the retired application and remain available.

`~/.config/nanoleaf-kde-sync/config.toml` is still the native configuration path.
Its calibration profiles, manual mapping and unknown settings are preserved.
Do not delete or rename that directory as part of retirement. Narrow Nanoleaf
HID udev permissions remain necessary for the native application.

Use [native installation and rollback](NATIVE_INSTALL.md). Previous immutable
native app/helper pairs remain installed. The native installer does not uninstall
other software or delete calibration; retiring Python on another machine is a
separate user-directed operation (`pipx uninstall nanoleaf-kde-sync` for pipx installs).

The last complete pre-retirement source is Git commit
`85f59888d373667f48651f8cbb2333b8605bfbc5`. Historical research and `perf/` results
retain their original claims and scopes; their Python instructions describe an
older state. Shared native fixtures under `native/fixtures/` remain unchanged,
including complete processing, calibration, geometry and protocol reference
vectors. Their original generators are recoverable from that commit. Native
regression tests continue to assert those results without importing Python.

This change does not claim improved optical response or reduced running-app CPU:
the native application already had no Python runtime dependency.
