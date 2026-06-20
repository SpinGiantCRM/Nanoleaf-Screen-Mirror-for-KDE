# Arch / AUR packaging

## User install (recommended on Arch / CachyOS)

```bash
paru -S --needed python-dacite nanoleaf-kde-sync
```

Future updates:

```bash
paru -Syu
```

Post-install once:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
nanoleaf-kde-sync-doctor
```

## Local checkout build (before AUR publish or for dev)

From the repository root:

```bash
./scripts/build_arch_package.sh
```

This creates `packaging/arch/nanoleaf-kde-sync-$pkgver.tar.gz` from the current git tree and runs `makepkg -si`.

Reinstall helper:

```bash
./scripts/reinstall_local.sh
```

## Maintainer: publish to AUR

1. Ensure [`VERSION`](../VERSION) matches [`packaging/arch/PKGBUILD`](../packaging/arch/PKGBUILD) `pkgver`.
2. Cut a GitHub release tag `vX.Y.Z` and confirm release tarball checksum matches PKGBUILD `sha256sums`.
3. In `packaging/arch/`:
   ```bash
   makepkg --printsrcinfo > .SRCINFO
   updpkgsums   # when bumping pkgver from a new release tarball
   ```
4. Clone AUR package repo and copy `PKGBUILD`, `.SRCINFO`, `nanoleaf-kde-sync.install`.
5. Commit and push to AUR; verify with `paru -S nanoleaf-kde-sync`.

### pkgrel vs pkgver

- **pkgver**: bump when releasing a new upstream version (GitHub tag).
- **pkgrel**: bump for packaging-only fixes (dependency changes, desktop/udev file updates) without upstream version change.

### Dependencies

- `python-dacite` is on AUR; other runtime deps are in official Arch repos.
- Document `paru -S --needed python-dacite` for first-time installs.
