# User guide

## 1. Install and verify

```bash
pipx install nanoleaf-kde-sync
nanoleaf-kde-sync-setup-permissions
nanoleaf-kde-sync-init-config --mode full-real
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

After setup-permissions, log out and back in, then reconnect the strip.

If doctor reports USB permission issues, follow [Hardware setup](HARDWARE_SETUP.md).

Launch from the desktop entry or tray app (not a bare shell) for reliable KWin ScreenShot2 authorization on Wayland.

## 2. What success looks like

You are set up correctly when:

- The tray icon appears after `nanoleaf-kde-sync`
- **Check app/device health** (or `nanoleaf-kde-sync-doctor`) shows no blocking errors
- The setup wizard test pattern lights the strip
- **Start** makes LEDs follow your screen edges within a second or two
- Tray tooltip shows **Running** with your device model

## 3. First-run wizard

1. Start `nanoleaf-kde-sync`.
2. Open tray → **Set up strip…**
3. Complete the three-step setup wizard:
   - **Calibration** — assign corner anchors on your physical strip
   - **Display preset** — SDR, HDR, or Auto
   - **Look & feel** — color style, motion, edge locality
4. Click **Finish** to save.

**Save draft & close** keeps in-progress wizard choices without marking setup complete.

A zone is one controllable lighting segment on the strip. If unsure, keep the detected value or use the count from your Nanoleaf app/device specs. You can change this later.

## 4. Which settings should I pick?

Recommended defaults for most users:

| Setting | Recommended | When to change |
| ------- | ------------- | -------------- |
| Display mode | **Auto** | Use **SDR** if HDR colours look wrong |
| Motion | **Responsive** | **Calm** for movies; **Dynamic** for fast action |
| Colour style | **Ambient** | **Reference** for accuracy; **Vivid** for punch |
| Edge locality | **Balanced** | **Tight** if colours bleed; **Wide** for softer glow |
| Quality | **Balanced** | **High** on powerful PCs; **Low** if CPU is stressed |

Not sure? You can change any of these later in **Settings**.

## 5. Daily use

- **Start / Stop** from the tray menu controls mirroring.
- **Settings** — Save applies changes while keeping the dialog open; Close exits.
- **Advanced → Help & Diagnostics** — structured overview when troubleshooting.

## 6. Calibration

Use the wizard or Settings → Strip setup:

1. Send a test pattern.
2. Step through LEDs with Previous/Next.
3. Assign TL, TR, BR, BL to match your physical layout.
4. Use **Reverse direction** if the strip runs the wrong way.

You cannot damage anything by testing. If the wrong LED lights up, keep pressing Next and assign the lit LED to the screen corner it sits closest to.

The strip diagram in the calibration panel shows corner layout.

## 7. Common problems

### Nothing lights up

1. Tray → **Help & Diagnostics** → Refresh
2. Run **Check app/device health**
3. Confirm `nanoleaf-kde-sync-setup-permissions` was run and you logged out/in
4. See [No HID device found](TROUBLESHOOTING.md#no-hid-device-found)

### Wrong LEDs light up

1. Open **Set up strip…** or Settings → Strip setup
2. Use **Reverse direction** if the strip walks the wrong way
3. Re-assign corner anchors (TL/TR/BR/BL)
4. Verify strip LED count matches your hardware

### Colours too bright, too dull, or tinted

- Too bright: lower **Brightness** on the Everyday settings page
- Too dull: try **Ambient** or **Vivid** colour style; use **Colours too dull** quick fix on Colour page
- Whites tinted: check Display preset (try **Auto** or **SDR**); see HDR section in [Troubleshooting](TROUBLESHOOTING.md#colors-look-wrong-on-an-hdr-display)

### Flicker or lag

- Flicker: tray → **Help & Diagnostics** → Colour & flicker tab
- Lag: lower smoothing on Fine-tuning page; enable **4D sync** for fast games
- See [Slow path diagnosis](TROUBLESHOOTING.md#slow-path-diagnosis)

## 8. When something goes wrong

1. Tray → **Help & Diagnostics** → Refresh
2. Tray → Advanced → **Check app/device health**
3. Tray → Advanced → **Run quick test**
4. Open [Troubleshooting](TROUBLESHOOTING.md) from the tray or `/usr/share/doc/nanoleaf-kde-sync/TROUBLESHOOTING.md`

## 9. Reset paths

| Goal | Command |
|------|---------|
| Full config reset | `nanoleaf-kde-sync-reset app-config --stop-runtime` |
| Calibration only | `nanoleaf-kde-sync-reset calibration --stop-runtime` |
| Probe/wizard cache | `nanoleaf-kde-sync-reset diagnostics --stop-runtime` |

Use reset only when calibration or config is clearly broken. You can change most settings without a full reset.
