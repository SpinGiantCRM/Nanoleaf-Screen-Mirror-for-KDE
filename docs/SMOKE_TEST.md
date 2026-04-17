# Manual smoke test checklist

Run this after first install or when changing capture/device settings.

1. **Doctor pass**
   ```bash
   nanoleaf-kde-sync-doctor
   ```
2. **Capture validation**
   ```bash
   nanoleaf-kde-sync-smoke-test
   ```
   Expected: reports a valid frame shape from the active capture backend.
3. **Real device probe** (only if `use_mock_device=false`)
   ```bash
   nanoleaf-kde-sync-doctor --device
   ```
   Expected: model + zone count are printed.
4. **Safe LED write test** (optional but recommended)
   ```bash
   nanoleaf-kde-sync-smoke-test --send-test-frame
   ```
   Expected: one low-brightness RGB test frame reaches the strip.
5. **Tray runtime check**
   - Launch `nanoleaf-kde-sync`
   - Start service from tray
   - Open **Status** in tray and confirm:
     - capture backend/mode
     - device mode
     - device discovered true (for real mode)
     - last_error is empty

If any step fails, use troubleshooting in README.
