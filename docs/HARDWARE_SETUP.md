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
