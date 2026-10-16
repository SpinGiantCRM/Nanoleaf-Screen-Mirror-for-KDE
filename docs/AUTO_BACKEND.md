# Native automatic capture

`capture_backend = "auto"` selects KWin ScreenShot2 on KDE Wayland. It does not
benchmark and silently promote another backend. Explicit `kwin-dbus` is also
supported. Advanced allows explicitly selecting `xdg-portal` for the validated
PipeWire/Vulkan colour path; the user's choice is preserved across restarts.

Portal permissions are requested through KDE. Sharing denial/revocation stops
mirroring and requires explicit Start. No automatic permission reacquisition or
privileged DRM fallback occurs. Captured display-referred SDR is not raw HDR;
unknown colour formats and unverified desktop contracts fail explicitly.

Use `nanoleaf-native --doctor` for read-only readiness and `--status` for actual
backend/timing metadata. Historical Python auto-probe behaviour is retired.
