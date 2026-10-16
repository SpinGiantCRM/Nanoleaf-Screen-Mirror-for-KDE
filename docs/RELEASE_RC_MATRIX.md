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
