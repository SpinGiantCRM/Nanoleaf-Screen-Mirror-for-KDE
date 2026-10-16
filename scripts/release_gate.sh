#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$repo_root"
ruff check scripts/ tools/
ruff format --check scripts/ tools/
python3 -m unittest discover -s scripts -p 'test_*response_trace.py' -v
node --test scripts/cleanup_artifacts.test.cjs
cargo +1.77.0 fmt --manifest-path native/Cargo.toml --check
cargo +1.77.0 clippy --manifest-path native/Cargo.toml --all-targets --locked --offline -- -D warnings
cargo +1.77.0 test --manifest-path native/Cargo.toml --locked --offline
cargo +1.95.0 fmt --manifest-path native/app/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path native/app/Cargo.toml --features gui --all-targets --locked --offline -- -D warnings
cargo +1.95.0 test --manifest-path native/app/Cargo.toml --features gui --all-targets --locked --offline
for workspace in stream-probe linux-gpu gpu-probe; do
  cargo +1.95.0 fmt --manifest-path "native/$workspace/Cargo.toml" --check
  cargo +1.95.0 clippy --manifest-path "native/$workspace/Cargo.toml" --all-targets --locked --offline -- -D warnings
  cargo +1.95.0 test --manifest-path "native/$workspace/Cargo.toml" --all-targets --locked --offline
done
git diff --check
echo 'Native release contracts passed. Hardware and package checks remain separate.'
