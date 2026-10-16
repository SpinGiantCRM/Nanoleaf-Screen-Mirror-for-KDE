# Capture freshness comparisons — 2026-10-16

See [method, results and limitations](../../docs/CAPTURE_FRESHNESS.md).

- `60-120.json`: focus/fullscreen-checked ABBA runs, 12-second probes, every
  fresh ACK from frame 75 onward; all four restored controller state and kept
  the real config byte-identical during comparison.
- `120-240.json`: separate ABBA run at the existing higher targets, same method.
- `colour-parity.json`: separate slower correctness run, 610 exact outputs at
  requested target 240, Vulkan validation stderr empty. Not a throughput test.

App SHA-256 `e4d12cd9d2a72c70780b4f4a061d6330a79e2e85a807c2a4f5f5d8668160b619`;
helper SHA-256 `4ca79a9b49555461e10534fabba9cdaf10f31eba63b7888570b6efef835eaf1c`.
Scene hash is included per comparison. Preliminary exploratory/throttled runs
and the rejected overly strict maximum-gap trial remain private and are not
included as validated comparisons. Successful runs retain occasional paint
hitches; the scene is not a panel-presentation or optical timestamp oracle.

These are software timing and process-resource aggregates. No images, colour
values, calibration, serial, firmware binaries or support correspondence are
included. No measured optical, whole-system power or gaming-contention benefit
is claimed. Target 240 was tested temporarily, then the exact original config (Target FPS
60) was restored pending a valid static-to-change comparison. The first traced
static trial lost focus and was discarded; the user deferred its repeat.
Global defaults remain unchanged.
