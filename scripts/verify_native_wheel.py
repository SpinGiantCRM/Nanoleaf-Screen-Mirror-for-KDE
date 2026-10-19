"""Isolated pip/pipx install and pinned native bootstrap smoke verification.

Only the HTTPS download transport is replaced by the exact local tested archive.
The installed wheel's digest, extraction and real native installer all run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

DRIVER = """
import hashlib
import json
import sys
from pathlib import Path
from nanoleaf_native_installer import bootstrap

archive, prefix = map(Path, sys.argv[1:])
version = json.loads(Path(bootstrap.__file__).with_name("release.json").read_text())["version"]
def local_transport(url, destination, limit):
    expected = ("https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/"
                f"releases/download/native-v{version}/native.tar.gz")
    assert url in (expected, expected + ".sha256")
    source = Path(str(archive) + ".sha256") if url.endswith(".sha256") else archive
    data = source.read_bytes()
    assert len(data) <= limit
    destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()
bootstrap.download = local_transport
sys.argv = ["nanoleaf-kde-sync", "--install-native", str(prefix)]
bootstrap.main()
"""


def verify(wheel: Path, archive: Path, output: Path, stub_cache: bool, pipx: bool):
    wheel, archive = wheel.resolve(), archive.resolve()
    with zipfile.ZipFile(wheel) as packaged:
        release = json.loads(packaged.read("nanoleaf_native_installer/release.json"))
        assert release["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
        assert all(not packaged.read(name).startswith(b"\x7fELF") for name in packaged.namelist())
    with tempfile.TemporaryDirectory(prefix="nanoleaf-wheel-smoke-") as directory:
        root = Path(directory)
        for route in ("venv", "pipx") if pipx else ("venv",):
            home = root / route
            home.mkdir()
            runtime = home / "runtime"
            runtime.mkdir(mode=0o700)
            env = dict(
                os.environ,
                HOME=str(home),
                XDG_CONFIG_HOME=str(home / "config"),
                XDG_DATA_HOME=str(home / "data"),
                XDG_CACHE_HOME=str(home / "cache"),
                XDG_STATE_HOME=str(home / "state"),
                XDG_RUNTIME_DIR=str(runtime),
                PIP_NO_INDEX="1",
                PIP_CONFIG_FILE=os.devnull,
                PIP_DISABLE_PIP_VERSION_CHECK="1",
                PIPX_HOME=str(home / "pipx"),
                PIPX_BIN_DIR=str(home / "bin"),
                PIPX_MAN_DIR=str(home / "man"),
                PIPX_DEFAULT_PYTHON=sys.executable,
                PATH=os.pathsep.join(
                    [str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]
                ),
            )
            if stub_cache:
                tools = home / "tools"
                tools.mkdir()
                cache = tools / "kbuildsycoca6"
                cache.write_text("#!/bin/sh\nexit 0\n")
                cache.chmod(0o755)
                env["PATH"] = str(tools) + os.pathsep + env["PATH"]

            def run(*command, run_env=env):
                result = subprocess.run(
                    [str(part) for part in command],
                    env=run_env,
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode:
                    raise RuntimeError(result.stderr + result.stdout)
                return result.stdout.strip()

            if route == "venv":
                environment = home / "environment"
                run(sys.executable, "-m", "venv", environment)
                python = environment / "bin/python"
                run(python, "-m", "pip", "install", "--no-index", "--no-deps", wheel)
                alias = environment / "bin/nanoleaf-kde-sync"
            else:
                # Seed pipx's private shared pip from ensurepip so this smoke
                # remains offline even on a machine with no prior pipx state.
                run(sys.executable, "-m", "venv", home / "pipx/shared")
                run(
                    shutil.which("pipx") or "pipx",
                    "install",
                    "--pip-args=--no-index --no-deps",
                    wheel,
                )
                python = home / "pipx/venvs/nanoleaf-kde-sync/bin/python"
                alias = home / "bin/nanoleaf-kde-sync"
            assert "native installer " + release["version"] in run(alias, "--version")
            assert "--install-native" in run(alias, "--help")
            config = home / "config/nanoleaf-kde-sync/config.toml"
            config.parent.mkdir(parents=True)
            original = (
                "schema_version=2\nstart_on_launch=false\ndevice_zone_count=0\nunknown='keep'\n"
            )
            config.write_text(original)
            prefix = home / "native prefix with spaces"
            run(python, "-c", DRIVER, archive, prefix)
            installed = prefix / "bin/nanoleaf-native"
            first = installed.resolve()
            assert run(alias, "--version") == "nanoleaf-native " + release["version"]
            with tarfile.open(archive, "r:gz") as packaged:
                for name in ("nanoleaf-native", "nanoleaf-native-capture"):
                    assert (
                        first.with_name(name).read_bytes()
                        == packaged.extractfile("native/bin/" + name).read()
                    )
            run(alias, "--uninstall-native", prefix)
            assert not installed.exists() and first.is_file()
            if route == "venv":
                run(python, "-m", "pip", "uninstall", "-y", "nanoleaf-kde-sync")
            else:
                run(shutil.which("pipx") or "pipx", "uninstall", "nanoleaf-kde-sync")
            assert not alias.exists() and config.read_text() == original and first.is_file()
    result = {
        "version": release["version"],
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "pinned_archive_sha256": release["archive_sha256"],
        "pure_python_installer_only": True,
        "venv_install_native_pair_custom_prefix_and_uninstall": True,
        "pipx_install_native_pair_custom_prefix_and_uninstall": pipx,
        "configuration_preserved": True,
        "retained_native_versions": True,
        "download_transport": "exact local tested archive; no live network download",
        "desktop_cache": "stub" if stub_cache else "system kbuildsycoca6",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stub-desktop-cache", action="store_true")
    parser.add_argument("--pipx", action="store_true")
    args = parser.parse_args()
    verify(args.wheel, args.archive, args.output, args.stub_desktop_cache, args.pipx)


if __name__ == "__main__":
    main()
