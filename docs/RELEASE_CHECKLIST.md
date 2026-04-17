# Release candidate checklist

- [ ] `pytest` passes on Python 3.11+.
- [ ] `nanoleaf-kde-sync-doctor` runs without crashes in KDE session.
- [ ] `nanoleaf-kde-sync-smoke-test` validates capture path.
- [ ] `nanoleaf-kde-sync-init-config` mode presets verified.
- [ ] Arch package builds (`cd packaging/arch && makepkg -sf`).
- [ ] Desktop file launches tray app from KDE menu.
- [ ] udev rule installs and real device initializes after reconnect.
- [ ] README + hardware + smoke docs updated for current release.
