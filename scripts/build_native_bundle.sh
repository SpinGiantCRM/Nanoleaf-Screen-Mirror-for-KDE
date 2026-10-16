#!/usr/bin/env bash
# Package the Rust application and matching capture worker together.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
bundle_root=${1:-"$repo_root/dist/native"}
case "$bundle_root" in /*) ;; *) bundle_root="$PWD/$bundle_root";; esac
if [[ -e "$bundle_root" ]]; then
  echo "Bundle destination already exists; choose a fresh directory." >&2
  exit 1
fi
cargo +1.95.0 build --locked --release --manifest-path "$repo_root/native/app/Cargo.toml" --features gui --bin nanoleaf-native
cargo +1.95.0 build --locked --release --manifest-path "$repo_root/native/stream-probe/Cargo.toml" --bin nanoleaf-stream-probe
mkdir -p -- "$bundle_root/bin"
install -m755 "$repo_root/native/app/target/release/nanoleaf-native" "$bundle_root/bin/nanoleaf-native"
install -m755 "$repo_root/native/stream-probe/target/release/nanoleaf-stream-probe" "$bundle_root/bin/nanoleaf-native-capture"
install -m644 "$repo_root/LICENSE" "$bundle_root/LICENSE"
install -m644 "$repo_root/docs/NATIVE_INSTALL.md" "$bundle_root/README.md"
install -m644 "$repo_root/assets/udev/60-nanoleaf-kde-sync.rules" "$bundle_root/60-nanoleaf-kde-sync.rules"
python3 "$repo_root/scripts/generate_native_notices.py" --output "$bundle_root/THIRD_PARTY_NOTICES.txt"
(cd -- "$bundle_root" && sha256sum bin/nanoleaf-native bin/nanoleaf-native-capture LICENSE README.md 60-nanoleaf-kde-sync.rules THIRD_PARTY_NOTICES.txt > SHA256SUMS)
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH:-0}" --owner=0 --group=0 --numeric-owner -czf "$bundle_root.tar.gz" -C "$(dirname -- "$bundle_root")" "$(basename -- "$bundle_root")"
echo "Bundle: $bundle_root.tar.gz"
