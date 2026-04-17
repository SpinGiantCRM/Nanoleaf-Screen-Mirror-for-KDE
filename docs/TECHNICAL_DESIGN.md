# Technical Design: nanoleaf-kde-sync

## Overview
`nanoleaf-kde-sync` is a Python package that captures the current KDE desktop image, derives representative lighting colors, and sends those colors to Nanoleaf devices with low end-to-end latency. The system is organized as a linear pipeline with clean module boundaries so capture backends, color algorithms, USB transport, and device integrations can evolve independently.

## Engineering Priorities
1. Low latency (avoid blocking; prefer frame dropping over stalling).
2. Colour correctness (HDR decoding + primaries/transfer-aware conversion into device-friendly sRGB).
3. Performance (after correctness/latency, optimize allocations/conversions where it doesn’t change output).

Primary design goals:
- Maintain responsive screen-to-light synchronization.
- Sustain approximately 30 FPS under normal desktop workloads.
- Isolate platform- and transport-specific code behind narrow interfaces.
- Preserve correctness across SDR and HDR display paths.

## Architecture Overview
The system is split into four runtime stages:

1. `capture`: acquires frames from the KDE desktop.
2. `color`: converts frames into a compact device-ready color representation.
3. `usb`: transports commands through a pluggable USB-facing layer or stub.
4. `device`: translates generic color updates into Nanoleaf-specific commands and state transitions.

Supporting UI components in `ui` are responsible for configuration, status, and diagnostics, but not for core rendering or transport logic.

## Module Responsibilities
### `capture`
- Expose a common frame-source interface.
- Implement backend selection and health checks.
- Prefer `kmsgrab` for direct low-overhead capture.
- Fall back to KWin D-Bus capture when `kmsgrab` is unavailable or unstable.
- Normalize output into a predictable in-memory frame format with timestamps and display metadata.

### `color`
- Convert captured frames into one or more representative colors.
- Handle color-space normalization before sampling.
- Support HDR-aware processing so bright regions do not produce distorted output on HDR desktops.
- Provide configurable sampling strategies such as average color, zones, or weighted regions.

### `usb`
- Define a transport abstraction for packet delivery.
- Provide a modular stub implementation so the rest of the pipeline can be developed and tested without physical hardware or final transport code.
- Hide transport retries, buffering, and timing details from higher layers.

### `device`
- Map generic color updates to Nanoleaf device commands.
- Manage connection lifecycle, capability discovery, and update scheduling.
- Apply rate limiting or coalescing if device-side throughput is lower than frame production rate.

### `ui`
- Surface configuration for backend selection, performance mode, and device targeting.
- Show runtime status such as active backend, frame rate, and device connectivity.
- Remain optional so headless execution is possible.

## Data Flow
The intended runtime flow is:

`capture -> color -> usb -> device`

Detailed sequence:
1. The `capture` module acquires a frame and attaches timing and display metadata.
2. The `color` module transforms the frame into a device-oriented color payload.
3. The `usb` layer serializes and transmits the payload through a transport interface.
4. The `device` module applies the update to the target Nanoleaf device and tracks delivery state.

This pipeline should be implemented so each stage can be profiled independently. Frame dropping is acceptable under load; blocking the entire pipeline is not.

## Performance Goals
- Target end-to-end latency low enough to feel visually synchronized during interactive desktop usage.
- Sustain approximately 30 FPS on supported systems.
- Minimize frame copy count and unnecessary color-space conversions.
- Prefer non-blocking queues between stages so temporary device or transport delays do not stall capture.
- Allow adaptive degradation, such as dropping stale frames, to protect latency over throughput.

## Design Constraints
- HDR awareness is required. Capture and color processing must account for display metadata, transfer functions, and tone-mapping effects where possible.
- The USB layer must remain modular and stub-friendly so hardware integration can be deferred without blocking the rest of development.
- Backend-specific logic must not leak into color processing or device control modules.
- The system should tolerate partial capability availability, especially when running on different KDE, compositor, or graphics stack configurations.

## Fallback Strategy
Preferred backend order:

1. `kmsgrab`
2. `kwin dbus`

Fallback rules:
- Use `kmsgrab` by default because it is expected to provide lower overhead and lower latency.
- Switch to KWin D-Bus capture when `kmsgrab` is unsupported, fails initialization, or repeatedly produces invalid frames.
- Keep backend selection explicit in logs and UI so degraded capture modes are visible.
- Design capture backend selection behind a shared interface so future backends can be added without changing downstream modules.

## Initial Implementation Notes
- Start with a single-producer pipeline that prefers correctness and instrumentation over optimization.
- Introduce timing metrics at every stage from the start.
- Develop downstream modules against the USB stub first, then add real transport support once the frame and color pipeline is stable.


## Implementation Status (April 2026)
- `kwin-dbus` capture path now prioritizes modern Plasma 6 `org.kde.KWin.ScreenShot2` (with Unix FD transport) and falls back to older `org.kde.kwin.Screenshot` interfaces for compatibility.
- ScreenShot2 replies are decoded from the returned raw pipe payload plus metadata (`type`, `width`, `height`, `stride`, `format`) into RGB `numpy.uint8` frames.
- Authorization errors for restricted ScreenShot2 access are surfaced with actionable guidance (`X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`).
- `kmsgrab` backend remains the preferred low-latency path when optional DRM bindings are installed; without bindings it falls back to KWin when allowed.
- HDR conversion in `kmsgrab` now converts at native resolution before any resize step to avoid nonlinear transfer-function errors.
- Nanoleaf USB HID integration now uses the official TLV request/response protocol for PC Screen Mirror LS (`NL82K2`, PID `0x8202`) and Pegboard Desk Dock (`NL82K1`, PID `0x8201`), including model/length discovery and RGB zone updates.
- Protocol alignment details: brightness values are treated as `[0..255]`, get-length responses are parsed as `status + 1-byte strip-length`, and host-side frame policy clamps/pads zones to exact hardware length before `0x02` RGB writes.

## Public compatibility shims
- `nanoleaf_sync.ui.tray` and `nanoleaf_sync.device.nanoleaf_usb` are retained as lightweight re-export modules for import-path stability.
