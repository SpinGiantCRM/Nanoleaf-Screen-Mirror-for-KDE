# Session interruption and restoration — 2026-10-16

Implementation and reproduction: [session recovery](../../docs/SESSION_RECOVERY.md).

- `mocked-session-real-usb.json`: private D-Bus session events with real,
  acknowledged, low-brightness previews. Capture failure, locked Start/preview
  rejection, resume without the earlier prepare signal, owner loss/recovery,
  no automatic restart and independent controller restoration/readback pass.
  Initial brightness differed from the test limit, so final readback tests
  restoration rather than a coincidentally unchanged test brightness.
- `lifecycle.json`: selected portal/Vulkan capture, Stop/tray, preview ownership,
  restart, worker termination/stall/reap and recovery pass. Stall detection
  approximately 2.06 seconds. Not another physical USB unplug test.
- `real-lock.json`: actual KDE lock/unlock stopped capture/output at frame 710,
  kept the same frame count through unlock, stayed stopped another second, then
  resumed after an explicit operator Start. Tenth ACK arrived about 0.46 seconds
  after Start, and the test immediately quit. User reported no light after login;
  that brief phase does **not** verify sustained visible same-process recovery.
- `installed.json`: installed pair smoke plus a separate twenty-second fresh
  service run after login; user confirmed **“Lit and following correctly”**.
  Controller restoration and config/fallback preservation checks pass. This
  subsequent run does not retrospectively verify the brief first observation.
- `package.json`: relocated binaries and isolated install/upgrade/rollback,
  active-service exclusion, autostart tracking and retained fallback checks pass.

Native application suite: 113 passed, two operator tests ignored in the normal
run. The private-bus operator test was separately run and passed. App all-target
Clippy and formatting pass. Independent Rust 1.77 core: 26 passed. Stream-probe,
linux-gpu and gpu-probe tests (19/7/1 including the subsequent metadata audit),
all-target Clippy and formatting pass.
The selected 240-target colour oracle separately checked 610 exact outputs with
Vulkan validation clean; see [freshness evidence](../controlled-response-2026-10-16).

No real suspend/resume or new physical unplug verification occurred. Without a
delay inhibitor, pre-suspend cleanup cannot be guaranteed. No optical latency,
photometric colour accuracy, firmware modification or recovery claim is made.
Raw traces/config copies and exact original config backup remain private.
