# Lock, sleep and session-monitor recovery

The native tray now stops its existing output session when KDE reports a screen
lock, logind reports a sleep/resume transition, or a previously working session
monitor becomes unavailable. Unlock, resume and monitor reconnection leave the
tray stopped. Choose **Start** to establish a new capture session. Setup previews
are stopped too, and Start/preview are rejected while locked, preparing for
sleep, or unable to determine session state. Calibration is never rewritten.

This addresses the lock/resume part of A4 in the
[improvement report](IMPROVEMENT_RESEARCH_2026-10-14.md). It does not establish
monitor hotplug or physical suspend correctness.

## Boundaries and implementation

The guard subscribes to KDE's `org.freedesktop.ScreenSaver.ActiveChanged` and
logind's `PrepareForSleep` before reading their initial state. Independent
queries refresh state every two seconds, with two-second method timeouts;
logind's `PreparingForSleep` property does not emit property-change signals.
Connections retry after failure. Initial setup waits at most three seconds;
missing services leave the tray running and output blocked until recovery.
Readiness updates the stopped message without enqueuing a Start command.

Interruption uses the existing Stop cleanup. During a USB acknowledgement wait,
the bounded control-progress check drops capture immediately, retains the sole
in-flight transaction until ACK/timeout, then performs normal cleanup black and
releases output ownership. It does not overlap USB commands. A restart creates
fresh capture/temporal state rather than retaining a pre-lock image or silently
switching capture backends. The user's selected backend remains authoritative.

There is **no suspend inhibitor, privileged operation, desktop Lock call or
automatic unlock**. Pre-suspend cleanup is best effort: without a delay inhibitor
the process can be suspended before it handles the notification or finishes USB
cleanup. The resume signal therefore independently stops the old session even
if the earlier prepare signal was missed. This is not a guarantee that LEDs are
off before physical sleep or that every kernel-induced suspend is reported.
[systemd documents these timing and notification limits](https://systemd.io/INHIBITOR_LOCKS/).
The KDE boolean signal/method contract comes from
[KScreenLocker’s interface](https://github.com/KDE/kscreenlocker/blob/master/dbus/org.freedesktop.ScreenSaver.xml).

Two existing transitive dependencies (`async-io` and `futures-lite`) are direct
dependencies at their already locked versions. No new package version, output
setting, FPS knob or colour processing was introduced by the guard.

## Probe restoration regression

The bounded live probe can restore power/brightness after capture permission
failure, then reopen the strip for a subsequent preview/restart. That reopening
now marks the controller dirty **before** the test brightness write. Otherwise,
an earlier successful restoration could remain recorded after later output,
and Quit while stopped could skip the final restoration. The read-only
`usb_info` operator now also queries power/brightness, allowing an independent
comparison after the probe exits rather than trusting its status flag alone.
Normal mirroring brightness policy is unchanged.

## Reproduction and evidence

Headless tests cover unknown/locked/sleep states, missed prepare notifications,
monitor failure/reconnection, internal-only events and Stop deferral during ACK.
The stopped-service regression uses nonexistent bus addresses and verifies that
missing session monitoring rejects preview before capture/USB while preserving
normal invalid-configuration diagnostics and exact config bytes.

The optional private-bus test exercises real zbus subscriptions, initial queries,
lock/unlock and sleep/resume signals, owner loss/recovery and watcher shutdown:

```bash
cargo +1.95.0 test --manifest-path native/app/Cargo.toml --features gui \
  --lib --locked --offline private_bus_signals_owner_loss_and_recovery \
  -- --ignored --nocapture
```

`scripts/profile_session_recovery.py` additionally drives two brief exclusive,
low-brightness zone previews through the real acknowledged USB path while a
private bus supplies session events. Its capture service is deliberately absent,
so it exercises capture failure/restoration before reopening for preview. It
checks blocked Start/preview, no automatic restart, Quit while stopped, and
independent final controller readback. It defaults to a plan; `--run` is explicit.
This operator script needs `dbus-next` and `dbus-daemon`, neither of which is a
runtime requirement for the Rust application.

Results: [session recovery evidence](../perf/session-recovery-2026-10-16/README.md).
A subsequent real KDE lock/unlock test verified stop, no automatic restart and
ACK recovery after explicit Start. Its resumed phase ended after the tenth ACK,
less than half a second after Start. The user reported no light after login;
that observation is retained and sustained same-process visible recovery is not
claimed. A separate twenty-second fresh-service run after login was confirmed
by the user as lit and following correctly. Physical sleep and a new USB unplug
test remain unverified. No emitted-light timing is inferred from acknowledgements.
