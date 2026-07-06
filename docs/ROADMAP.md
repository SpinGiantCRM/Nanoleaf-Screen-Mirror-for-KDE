# Roadmap

Explicit scope for Nanoleaf Screen Mirror for KDE. This is a single-strip, single-capture-source product.

## Supported today

- One Nanoleaf USB Edge Strip (NL82K1 / NL82K2)
- KDE Plasma 6 + Wayland (X11 may work but is not the primary target)
- Choosing **one** capture monitor via Settings → Advanced → Capture monitor
- Real-time edge mirroring with calibration, HDR/SDR presets, diagnostics

## Experimental

- **kmsgrab** DRM zone-patch capture — advanced/debug; requires DRM helper capabilities
- **Scene-adaptive profiles** — internal pipeline tuning; not exposed in Settings
- **Capture monitor** by KWin output name — works for picking a non-primary display; not multi-monitor mirroring

## Planned

- Custom display gamut chromaticity editor in Settings (config/API exists today)
- Click-and-drag privacy zone overlay picker (numeric editor exists today)
- Richer “safe support summary” copy button in diagnostics

## Not planned

- Simultaneous multi-monitor mirroring (all displays at once)
- Multiple USB strips / zone splitting across devices
- Non-KDE desktops as a supported primary platform
- Generic LED controller / plugin architecture

## How to request scope changes

Open a feature request and label it appropriately:

- Multi-monitor: use the **multi-monitor** issue template
- Multiple strips: use the **multiple-strips** issue template
- Other desktops: use the **non-KDE desktop** issue template

See [Feature matrix](FEATURE_MATRIX.md) for implementation status of existing features.
