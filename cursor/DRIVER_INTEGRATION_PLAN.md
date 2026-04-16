# Proprietary Driver Integration Plan

## Required contract
The proprietary driver must implement:
- `initialize()`
- `send_frame(colors)` where `colors` are RGB tuples in device-zone order
- `close()`

## Acceptance criteria
- Driver satisfies `DeviceDriver` protocol.
- Service can stream for 10 minutes at configured FPS with no unbounded error loop.
- Fallback to mock driver remains functional when proprietary driver initialization fails.
- Replay capture test path can exercise full pipeline without real hardware.

## Rollout
1. Add proprietary driver behind config flag.
2. Validate with replay backend and mock-mode parity checks.
3. Hardware smoke test with diagnostics enabled.
4. Enable as preferred backend after stability confirmation.
