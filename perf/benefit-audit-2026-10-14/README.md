# Benefit-audit evidence

`summary.json` identifies the audited revision, current verification scope,
calibration hash, upstream source hashes and fresh replay results. Previous live
measurements are linked from the research report rather than presented as new
hardware runs.

Replay command:

```sh
.venv/bin/python scripts/benchmark_native_app.py --frames 4 --repeats 3 --no-accumulation --output /tmp/fresh-offline-replay.json
```

The existing final production replay binary was reused. Its hash is recorded;
the report explains which source files changed since its checkpoint. Processing
sources did not change. The 216 comparisons exclude capture, USB and light output.

The colour probe compiles the actual checked-in colour source without modifying
it. From the repository root:

```sh
rustc +1.95.0 --edition=2021 -Awarnings perf/benefit-audit-2026-10-14/colour-contract-probe.rs -o /tmp/colour-contract-probe
/tmp/colour-contract-probe
```

The portal probe uses `zbus::zvariant` against the application's locked zbus 5.19.0
library. It requires a matching compiler and the built dependency search path;
the isolated run used the existing stable-compiler build. Its two standard-value
conversion errors are recorded in `portal-value-probe.txt`. It does not contact
the portal or change capture permissions.

Native validation used Rust 1.95.0 with the GUI feature for app tests, Rust 1.77.0
for core tests, and Rust 1.95.0 for streaming tests, all locked and offline.
No user configuration, installed binary, autostart or controller state changed.
