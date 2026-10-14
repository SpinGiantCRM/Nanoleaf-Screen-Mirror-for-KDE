# Response delay: findings and fast-response settings

Current user order: time to colour recreation > colour reproduction > FPS >
system performance. This supersedes the earlier colour-first ordering.

## The delay hidden by per-frame timings

The saved configuration has responsiveness 0.5 and, through its default,
temporal sample accumulation enabled. Accumulation starts at a coefficient of
0.05, with motion adaptation, then final smoothing filters that result again.
Capture-to-USB timings describe one processed update; they do not measure how
long these filters take to settle on a new colour.

The `response_bench` tool runs generated uniform SDR scene steps through the
actual pipeline with a copy of the user's calibrated configuration. A fresh,
unfiltered pipeline supplies the calibrated target. The error metric uses RGB
after undoing the configured device-gamma transfer. These are **synthetic source
clock** settling results at 60 updates/s, not wall-clock capture-to-light timings.

| Scene change | Saved settings: 90% settled | Accumulation off: 90% settled | Fast response |
| --- | ---: | ---: | --- |
| Grey 64 → 192 | 483 ms | 67 ms | First update |
| Grey 192 → 64 | 517 ms | 67 ms | First update |
| Grey 128 → 132 | 983 ms | 100 ms | First update |
| Grey 100 → 120 | 767 ms | 67 ms | First update |
| Red → blue | 533 ms | 67 ms | First update |
| Black → grey | 300 ms | 67 ms | First update |
| Grey → black | First update | First update | First update |

The model places the first update one configured frame period after the switch:
16.7 ms at 60 Hz. Fast response adds no settling across subsequent input updates;
this does not mean the LEDs emit the target light after 16.7 ms. Increasing the
responsiveness control alone leaves the accumulator active: grey rise still
takes 450 ms to reach 90%, and a small grey change takes 750 ms in this model.

## Implemented controls and safeguards

Settings now offers **Use fast response**, using existing settings only:
`smoothing=1.0` and `zone_temporal_accumulation=false`. It keeps colour style,
calibration, HDR/SDR profiles, selected monitor, mapping, manual strip count,
sampling quality, dithering, Target FPS and scheduling preferences unchanged.
The draft applies through the normal Save / Apply flow, which keeps Settings open.
The daily UI also warns when additional temporal averaging is active.

For operator use, `nanoleaf-native --fast-response [existing-config-path]` stores
the same two values through the existing transactional writer, retaining an exact
backup. It preserves inline comments, unknown options and both calibration
profiles. It does not reload, start or otherwise alter an active service; reload
or restart separately. This allows private trial configurations without changing
the live application. No new FPS, priority or queue-depth setting was introduced.

Tests establish that the recipe changes only those two controls, preserves the
calibrated target on the first changed reference-mode update at 30/60/120 Hz and
gamma 1.0/2.2, and preserves configuration comments, unknown fields and exact
backups. Reapplying it is idempotent. Existing native app tests total 74 and pass,
as do Clippy, format and isolated install/upgrade/rollback/uninstall package checks.
The underlying colour and USB algorithms are unchanged by this shortcut.

This removes intentional temporal blending; small variations can become more
visible. Other colour styles can still apply palette stabilisation or appearance
policies. The first-update guarantee is tested for the user's reference mode,
not asserted for every artistic sampling policy.

## Live comparison and what remains

A bounded low-brightness comparison used the same portal/Vulkan backend for
10 seconds with saved settings, then 20 seconds with fast response. It produced
448 and 953 acknowledged packets respectively. Median capture-to-ACK times were
41.028 and 41.068 ms, and median USB transaction times were approximately 21 ms
in both phases. The healthy capture/transport path is not where this large
settling delay was removed. These are short desktop observations, not a controlled
optical latency or FPS comparison.

Each phase verified original controller power/brightness restoration. The
original installed KWin application resumed with normal process priority, and the
real configuration/installed binary remained unchanged during the comparison.
The user's perceived responsiveness/colour-stability assessment is the remaining
gate before adopting these settings for daily use. Actual emitted-light latency,
sustained gaming cadence and the firmware presentation/ACK relationship remain
unmeasured; do not equate an ACK timestamp with visible LED presentation.
