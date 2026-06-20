# User guide

## 1. Install and verify

```bash
nanoleaf-kde-sync-init-config --mode full-real
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

If doctor reports USB permission issues, follow [Hardware setup](HARDWARE_SETUP.md).

Launch from the desktop entry or tray app (not a bare shell) for reliable KWin ScreenShot2 authorization on Wayland.

## 2. First-run wizard

1. Start `nanoleaf-kde-sync`.
2. Complete the three-step setup wizard:
   - **Calibration** — assign corner anchors on your physical strip
   - **Display preset** — SDR, HDR, or Auto
   - **Look & feel** — color style, motion, edge locality
3. Click **Finish** to save.

**Save draft & close** keeps in-progress wizard choices without marking setup complete.

## 3. Daily use

- **Start / Stop** from the tray menu controls mirroring.
- **Settings** — Save applies changes while keeping the dialog open; Close exits.
- **Advanced → Diagnostics** — live pipeline view when troubleshooting.

## 4. Calibration

Use the wizard or Settings → Calibration:

1. Send a test pattern.
2. Step through LEDs with Previous/Next.
3. Assign TL, TR, BR, BL to match your physical layout.
4. Use **Reverse direction** if the strip runs the wrong way.

The strip diagram in the calibration panel shows corner layout.

## 5. When something goes wrong

1. Tray → **Run Doctor**
2. Tray → **Run Smoke Test**
3. Open [Troubleshooting](TROUBLESHOOTING.md) from the tray or `/usr/share/doc/nanoleaf-kde-sync/TROUBLESHOOTING.md`

## 6. Reset paths

| Goal | Command |
|------|---------|
| Full config reset | `nanoleaf-kde-sync-reset app-config --stop-runtime` |
| Calibration only | `nanoleaf-kde-sync-reset calibration --stop-runtime` |
| Probe/wizard cache | `nanoleaf-kde-sync-reset diagnostics --stop-runtime` |
