# Exact acknowledged short updates

16 October 2026. Implementation and actual response/recovery evidence following
[the short-payload hardware checks](USB_SHORT_PAYLOAD_RESEARCH.md).

## Behaviour and fallback

The runtime enables shortening only for the tested **NL82K2, firmware0x15
(1.5), hardware ASCII11 (1.1), manual48 zones**. Other models, counts, versions,
malformed replies or failed identity queries retain full-length output. The vendor
hardware query is issued only after the exact researched firmware reply. The
reported strip count remains diagnostic and never changes manual geometry.

The device handle keeps a private complete RGB state from its last successful
ACK. After normal calibration and per-ACK temporal quantization, it finds the
last zone whose **actual encoded RGB values** differ. It sends every zone from0
through that zone. Unchanged trailing zones retain the acknowledged values.
There is no tolerance, chroma approximation, averaging or colour transform.

Even an entirely identical target sends one zone and receives a real ACK. Unlike
the separate OFF-default repeat-suppression experiment, this does not skip ACKs
or dither phases. The service counts exactly one successful output transaction
per update and returns the **complete** acknowledged colour vector to capture/
temporal processing. If a fractional tail's dither value changes, it is included,
up to a full frame when the final zone changes. Global zone indices/channel order
are unchanged; the short command does not change the handle's manual count.

The normal full-frame encoder validates the complete input first. Preview,
inferred/prediction-enabled output and cleanup are full length. Start, settings,
ownership/session transitions, any direct controller query/command, uncertain
writes, errors and reopen invalidate retained state. A new/recovered connection
starts with a full frame. Ready unexpected reports invalidate state before prefix
selection; unexpected traffic during the transaction prevents caching its result.
The next update is then full. Every250ms of healthy output a full refresh is sent;
this is a conservative policy, not a claimed firmware idle timeout.

Transport remains serial, with its original exact TLV/report framing and bounded
ACK/progress handling. There is no write overlap, speculative ACK, silent retry,
new thread priority, privileged access or firmware operation. The cache contains
only one manual-count colour vector and is not serialized in diagnostics.

Advanced / Troubleshooting displays payload size and shortened-update count.
To force the original full-frame policy, quit the tray and launch:

```bash
NANOLEAF_SHORT_UPDATES=0 nanoleaf-native --run
```

No saved calibration/configuration field is added or rewritten. Previous native
versions and the preserved Python app remain available. Normal automatic capture
is still KWin ScreenShot2; the user's explicitly selected portal/Vulkan backend
and Target60 are preserved.

## Real application response benchmark

The actual native tray/service actor drove the physical strip through the same
HID implementation. A separate **generated worker fixture**, not screen capture,
supplied raw downstream colours at60Hz and changed its generated state about
every137ms. This keeps source events available independently of blocking USB.
It deliberately does not apply saved calibration; all real calibration is left
unchanged. The fixture is under `tools/`, used only beside a copied app in a
private directory. **Never install the fixture as the capture helper.**

For each of three source families, eight-second runs used full/short/short/full
order with the **same app binary**. Full mode set the process-only fallback flag;
all other transport/ACK/dither policies stayed the same. Requested brightness10
read16. Every run completed restoration and independent controller readback.
The real config and thirteen preserved user paths stayed unchanged.

Private `strace` read/write records identify the first complete HID write of
each new generated state and its actual matching ACK read. One second of startup
and the final half-second are excluded. All remaining events must match before
the next source change, with the opposite prior state and <=2ms clock drift.
All records are checked for complete writes, first full state, valid prefixes,
ACK accounting and final full black cleanup. Instrumentation overhead is included
in both policies; this is not an uninstrumented optical benchmark.

The12 ACK-traced runs yielded **537 matched source changes** and **5,103 exact
complete-strip state comparisons**. Traces reconstruct the retained suffix after
every acknowledged write and compare it to the full reference, including an
independent eight-phase fractional-tail oracle. Per-run results and all matched
response timings are in [the evidence](../perf/short-updates-2026-10-16/README.md).

Pooled software timings,89–90 matched changes per policy/source family:

| Generated source | Event→write median, full→short | Event→ACK median, full→short | Event→ACK p95, full→short |
| --- | ---: | ---: | ---: |
| First12 zones change; stable integer tail | 14.021→0.827 ms | 29.396→5.860 ms | 37.788→8.289 ms |
| Same, one fractional dithered final zone | 14.070→2.611 ms | 29.416→8.197 ms | 37.450→19.001 ms |
| Whole-strip steps with static intervals | 11.611→2.879 ms | 28.214→18.348 ms | 38.378→20.310 ms |

The last row still sends full frames for actual whole-strip changes. Its gain
comes from shortened repeats between changes, leaving the receiver available.
Continuous full-strip motion can still require full payloads every time. A short
frame's ACK time is not a measurement of when the LEDs emit its light. These
results exclude compositor/display latency, real capture/colour work, gaming
contention and power. The small controlled source families do not establish
long-term tails or universal desktop gains. A separate initial write-only ABBA
series is retained privately as preliminary evidence, not pooled with these runs.

## Recovery and colour verification

- Independent report-I/O tests reconstruct full output for all256 neutral code
  levels and every changed-prefix extent, six channel orders and a fractional
  tail. Failed/missing ACKs, uncertain writes, invalid counts, full-refresh age,
  unsolicited traffic and state invalidation require full recovery. The existing
  full-count encoder still rejects short application inputs.
- Synthetic-worker/actual-HID lifecycle tests exercise shortening, Stop while the
  tray stays alive, exclusive full-frame preview, restart, killed/frozen-worker
  recovery, reap and controller restoration. All five initial/reopened first
  writes and preview were full48. This fixture performs no capture or GPU work.
- Separate **real portal/Vulkan capture plus USB** lifecycle tests passed those
  same paths, with CPU colour parity enabled. All five first writes after reopen
  and preview were full48. A capture-only check with the actual Vulkan validation
  flag enabled is separate from that lifecycle run.
- In the physical unplug/reconnect check, initial and reconnected first writes
  were full48 in both the saved app samples and independent wire audit. The user
  reported **“Reconnected; colours resumed correctly”**. A ten-second
  reconnect window was allowed before cleanup/restoration. This is an
  emitted-colour/recovery observation, not a colorimeter or latency measurement.

A preflight attempt requested a60-second live probe, which its existing30-second
limit rejected before output; that failure is retained. The corrected bounded
run performed the actual reconnect. Its post-run audit initially attempted to
read missing timing from an expected failed-USB sample; successful ACK samples
were reanalysed and independently cross-checked against the saved wire trace.
Neither bookkeeping failure is presented as a hardware success on its own.

129 ordinary native-app tests pass (two operator tests excluded); the private
D-Bus signal/recovery test passes separately. Rust1.77 core26, all-target/gui
warnings-denied Clippy, formatting, Ruff and six offline response-trace tests pass.
Relocated bundle install/upgrade/rollback preserves configuration and fallback.
No new physical suspend, lock/unlock, NL82K1 or photometric verification is claimed.

## Final-binary confirmation and installed delivery

The shipping binary adds Advanced labels and fail-closed identity/ACK/unsolicited
traffic guards since the three-family benchmark. A separate final full/short/
short/full series matched176 source events and reconstructed1,698 complete wire
states exactly. Its integer-tail median event→write was 14.066→0.899ms;
event→ACK 29.825→5.930ms, p95 ACK 37.871→8.519ms. This confirmation is retained
separately rather than pooling measurements from different binaries.

The final app/helper pair is installed, retaining prior native versions and the
Python fallback. An eight-second installed default-policy run completed 385 ACKs,
including 247 shortened updates, with independent controller restoration.
A separate installed capture-only run verified 300 exact complete CPU/GPU outputs
with Vulkan validation enabled and empty stderr. Of13 preserved paths, only the
managed native command and desktop launcher changed. Config/calibration remain
byte-identical, including Target60 and the selected monitor/backend. No autostart
was enabled; the app was left closed.
