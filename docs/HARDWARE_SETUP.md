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

## Workflow: `hid-device PASS` + `device-probe FAIL`

Use this short workflow when enumeration succeeds but open fails.

1. Run both views:

   ```bash
   nanoleaf-kde-sync-doctor
   nanoleaf-kde-sync-doctor --device
   ```

2. Read `hid-device` per-interface/per-path details:
   - `path=/dev/hidrawN`
   - `interface=<number>`
   - `usage_page` and `usage`

3. Read `device-probe` `Attempt results`:
   - `open_path(...) failed ...` = result for a specific HID path/interface.
   - `open(vid, pid) failed ...` = fallback attempt by VID/PID only.

4. Interpret open failures:
   - permission/ACL issue: `permission denied`, `access denied`
   - busy handle: `resource busy`, `device or resource busy`
   - backend/interface mismatch: all path opens fail with non-permission errors even when ACLs look correct

Why this matters: some Nanoleaf units expose multiple HID interfaces. Path-based opens are deterministic; VID/PID fallback can be ambiguous on Linux.
