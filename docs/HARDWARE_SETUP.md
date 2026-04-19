# Hardware Setup (Nanoleaf USB)

## Supported USB IDs

- VID `0x37fa`
- PID `0x8201` (`NL82K1`)
- PID `0x8202` (`NL82K2`)

## Linux permissions

Install the provided udev rule and reload rules:

```bash
sudo install -Dm0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=add
```

On Arch/CachyOS, if needed:

```bash
getent group plugdev || sudo groupadd plugdev
sudo usermod -aG plugdev "$USER"
```

Then log out and back in, and reconnect the device.
