# Arch / AUR packaging

## User install

### Published on AUR (future)

When the AUR package is live:

```bash
paru -S --needed python-dacite nanoleaf-kde-sync
paru -Syu
```

### Pre-AUR — local build (current)

AUR account creation is currently blocked. Build and install from this repository:

```bash
paru -S --needed python-dacite
./scripts/build_arch_package.sh
```

Post-install once:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
nanoleaf-kde-sync-doctor
```

User docs install to `/usr/share/doc/nanoleaf-kde-sync/`.

## Local checkout build

From the repository root:

```bash
./scripts/build_arch_package.sh
```

Reinstall helper:

```bash
./scripts/reinstall_local.sh
```

## Maintainer: publish to AUR

1. Ensure [`VERSION`](../VERSION) matches [`packaging/arch/PKGBUILD`](../packaging/arch/PKGBUILD) `pkgver`.
2. Cut a GitHub release tag `vX.Y.Z` and publish release assets.
3. In `packaging/arch/`:
   ```bash
   updpkgsums   # pin sha256sums against the published tarball
   makepkg --printsrcinfo > .SRCINFO
   ```
4. Clone AUR package repo and copy `PKGBUILD`, `.SRCINFO`, `nanoleaf-kde-sync.install`.
5. Commit and push to AUR; verify with `paru -S nanoleaf-kde-sync`.

**v1.0.0 note:** `sha256sums` remains `SKIP` until the `v1.0.0` GitHub release tarball exists; run `updpkgsums` immediately after publishing the tag.

### pkgrel vs pkgver

- **pkgver**: bump when releasing a new upstream version (GitHub tag).
- **pkgrel**: bump for packaging-only fixes (dependency changes, desktop/udev/doc file updates) without upstream version change.

### Dependencies

- `python-dacite` is on AUR; other runtime deps are in official Arch repos.
- Document `paru -S --needed python-dacite` for first-time installs.
