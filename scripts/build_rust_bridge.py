"""Build a Linux-only development bridge for this interpreter, without installation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if sys.platform != "linux":
        raise SystemExit("This development build helper supports Linux only")
    environment = dict(
        os.environ,
        PYO3_PYTHON=sys.executable,
        PYO3_BUILD_EXTENSION_MODULE="1",
        CARGO_TARGET_DIR=str(ROOT / "native/python-bridge/target"),
    )
    subprocess.run(
        [
            "cargo",
            "build",
            "--manifest-path",
            str(ROOT / "native/python-bridge/Cargo.toml"),
            "--release",
            "--locked",
        ],
        env=environment,
        check=True,
    )
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not isinstance(suffix, str):
        raise SystemExit("Interpreter has no native extension suffix")
    destination = ROOT / "native/target/bridge" / f"_nanoleaf_core{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "native/python-bridge/target/release/lib_nanoleaf_core.so", destination)
    shutil.copy2(
        ROOT / "native/THIRD_PARTY_NOTICES.md", destination.parent / "THIRD_PARTY_NOTICES.md"
    )
    print(destination)


if __name__ == "__main__":
    main()
