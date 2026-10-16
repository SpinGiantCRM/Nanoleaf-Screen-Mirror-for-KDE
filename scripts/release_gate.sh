#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$repo_root"
ruff check scripts/ tools/
ruff format --check scripts/ tools/
python3 -m unittest discover -s scripts -p 'test_*response_trace.py' -v
node --test scripts/cleanup_artifacts.test.cjs
receiver_analysis_scripts=(
  perf/receiver-encoding-2026-10-16/crc_constraints.py
  perf/ack-path-2026-10-16/summarise_shape.py
  perf/firmware-models-2026-10-16/analyse_models.py
  perf/firmware-models-2026-10-16/padded_tail.py
)
ruff check "${receiver_analysis_scripts[@]}"
ruff format --check "${receiver_analysis_scripts[@]}"
python3 perf/receiver-encoding-2026-10-16/crc_constraints.py --self-test
python3 perf/ack-path-2026-10-16/summarise_shape.py --check
python3 perf/firmware-models-2026-10-16/analyse_models.py --self-test
python3 perf/firmware-models-2026-10-16/padded_tail.py --self-test
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
