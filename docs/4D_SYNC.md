# 4D sync

4D sync (`sync_mode = 4d`) is a low-latency mirroring mode for fast motion (games, rapid UI changes). Enable it on **Settings → Everyday** with **4D sync (120fps edge mirroring + prediction)**.

## What changes

| Area | Standard | 4D sync |
|------|----------|---------|
| HID output pacing | Default pacing | Faster send cadence, tighter USB drain |
| Edge locality | Your setting | Often tightened by the 4D preset bundle |
| Colour prediction | Off | Lookahead based on recent zone motion |
| DRM zone patch | Per config | May enable zone-patch capture when capable |

4D sync does **not** force 120 FPS screen capture. Capture rate still follows your **Target FPS** setting. The label refers to edge-response tuning, not a guaranteed capture frame rate.

## When to use it

- Fast games or high-motion content where edge lag is noticeable
- Single-monitor setups with stable capture backend (prefer **Auto** backend)

## When to avoid it

- Video/desktop use where smooth fades matter more than latency
- Setups that already flicker with high smoothing off and **Dynamic** motion
- HDR + `kwin-dbus` capture where colour accuracy is already fragile

## Trade-offs

- **CPU/GPU:** Slightly higher processing and USB traffic; predictive path adds per-frame work
- **Flicker:** Tighter response can shimmer on low-FPS capture or unstable backends — increase smoothing or disable 4D sync
- **Interaction with smoothing:** High smoothing fights prediction; try lower smoothing or **Responsive** motion preset
- **Interaction with latency:** 4D reduces perceived lag but cannot fix slow capture backends — run **Measure active backend latency** in Advanced

## Related settings

- **Motion preset** and **Edge locality** still apply; 4D preset may override edge locality to a tighter value
- **Predictive sync strength** is config-only today (default 0.35)

## Diagnostics

Live diagnostics show `predictive_sync_active`, lookahead frames, and scene-cut suppression when 4D sync is enabled.

See also [Performance](PERFORMANCE.md) for benchmark comparisons.
