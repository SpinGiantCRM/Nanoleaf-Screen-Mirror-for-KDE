# AMD / Intel DRM validation checklist

Use this checklist when validating on non-NVIDIA hardware. CI does not run these checks.

## AMD (amdgpu)

1. `nanoleaf-kde-sync-setup-permissions` — udev + setcap guidance
2. `nanoleaf-kde-sync-doctor --capture` — expect `kmsgrab`, vendor `amd`, tier `unvalidated`
3. HDR desktop: 10-bit scanout if available; grey test pattern channel spread ≤4
4. Fallback: force `prefer_backend = "kwin-dbus"` if DRM fails

## Intel (i915 / Xe)

Same steps as AMD with vendor `intel`.

## Report

File issues with: GPU model, kernel, Plasma version, doctor `--capture` output, and `last_capture_path`.
