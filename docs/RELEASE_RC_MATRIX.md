# Native release verification matrix

Record exact source/bundle hashes, KDE version, selected backend, manual count
and device model. CI evidence is separate from physical observations.

| Check | Evidence required |
| --- | --- |
| Rust core/app/capture | Tests, Clippy, formatting and lockfile audit |
| Bundle | Isolated install, upgrade, paired rollback and uninstall; calibration unchanged |
| Selected monitor | KWin automatic and explicitly selected supported portal path |
| Colour | Neutral/black, calibrated mapping, exact CPU/GPU replay/parity |
| Lifecycle | Stop keeps tray; previews exclusive; sharing stop requires explicit Start |
| USB | Full first frame and recovery after a real unplug/reconnect |
| Desktop session | Lock/unlock and suspend separately labelled; never infer either |
| Performance | Actual workload, stage clocks and benchmark instrumentation stated |

NL82K1 and NL82K2 hardware results must be reported separately. Unavailable
hardware tests remain unverified. A software ACK is not an optical measurement.
No X11 or privileged DRM backend is promised by the native application. Historical
Python RC matrices and publishing instructions are available in Git history.

## 2.0.0 local release validation — 19 October 2026

The release gate passed 200 Rust tests across the five workspaces, all-target
Clippy and formatting. The normally ignored private D-Bus session-recovery test
also passed when run explicitly. The operator timing benchmark remains excluded
from ordinary tests. Repository/script tests include archive integrity, immutable
publication, native installer extraction, wheel metadata and Arch staging controls.

An isolated KDE session exercised fresh tray launch into onboarding, saving a
manual count and four corner anchors, finishing setup without Start, and restarting
a configured tray without reopening onboarding. The stopped service retained zero
output frames throughout; no physical colour or optical claim follows. Every
Settings page and onboarding step also renders without mutating calibration in
headless regression checks.

Real binaries passed isolated relocated install, upgrade, paired rollback,
corrupted-helper refusal and uninstall while preserving configuration and unrelated
files. The pure installer wheel passed both venv and pipx flows, including a custom
prefix and uninstall. That pre-publication bootstrap smoke substitutes the exact
local archive for HTTPS transport; public download and registry publication must
be checked separately. Arch package staging and a local makepkg build passed;
its final release checksum and metadata are verified before publication.

CI and registry status must be checked on the final release revision. The physical
limits above remain unchanged; local software checks do not certify every strip,
desktop, emitted colour or suspend/resume path.
