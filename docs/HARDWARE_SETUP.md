# Hardware Setup (Nanoleaf USB)

## Supported USB IDs

- VID `0x37fa`
- PID `0x8201` (`NL82K1`)
- PID `0x8202` (`NL82K2`)

## Linux permissions

Use the provided installer script (canonical path) to install the udev rule and reload rules:

```bash
./scripts/setup_udev.sh
```

On Arch/CachyOS, if needed:

```bash
getent group plugdev || sudo groupadd plugdev
sudo usermod -aG plugdev "$USER"
```

Then log out and back in, and reconnect the device.

## If permissions are correct but `--device` still fails

If `nanoleaf-kde-sync-doctor` reports `hid-device: PASS` but `nanoleaf-kde-sync-doctor --device` still fails to open:

1. Run doctor again and inspect the `hid-device` line. It now prints each matching HID path/interface:
   - `path=/dev/hidrawN`
   - `interface=<number>`
   - `usage_page` / `usage`
2. In the `device-probe` failure text, review `Attempt results`:
   - `open_path(...) failed ...` entries show exact per-path failures.
   - `open(vid, pid) failed ...` shows fallback failure by VID/PID.
3. Use this to distinguish:
   - permission error (for example `access denied`, `permission denied`)
   - busy handle (`resource busy`, `device or resource busy`)
   - backend mismatch / wrong interface selection (path opens all fail despite correct ACLs)

Why this matters: some Nanoleaf hardware exposes multiple HID interfaces. Opening by only VID/PID can be ambiguous on Linux; opening the enumerated path is deterministic and gives actionable per-interface errors.
