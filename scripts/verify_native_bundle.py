"""Relocation/install/upgrade/rollback smoke tests with isolated user directories.

Uses only read-only diagnostics and a stopped service. Never requests capture,
opens strip output, or edits real user configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nanoleaf-package-smoke-") as directory:
        root = Path(directory)
        relocated = root / "relocated bundle"
        shutil.copytree(args.bundle, relocated)
        env = dict(
            os.environ,
            HOME=str(root),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_CACHE_HOME=str(root / "cache"),
            XDG_RUNTIME_DIR=str(root / "runtime"),
        )
        (root / "runtime").mkdir(mode=0o700)
        prefix = root / "prefix with spaces"
        exe = relocated / "bin/nanoleaf-native"

        def run(binary, *commands):
            return subprocess.check_output(
                [str(binary), *map(str, commands)],
                env=env,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )

        version = run(exe, "--version").strip()
        run(exe, "--install-native", prefix)
        installed = prefix / "bin/nanoleaf-native"
        first = installed.resolve()
        assert run(installed, "--version").strip() == version
        assert (
            installed.with_name("nanoleaf-native-capture").exists() is False
        )  # helper belongs to immutable version
        assert first.with_name("nanoleaf-native-capture").is_file()
        config = root / "config/nanoleaf-kde-sync/config.toml"
        config.parent.mkdir(parents=True)
        original = (
            "schema_version=2\nstart_on_launch=false\ndevice_zone_count=0\n"
            "unknown_setting='preserve'\n[led_calibration_profile_sdr]\n"
            "red_gain=0.873123456789\n"
        )
        config.write_text(original)
        unrelated = root / "data/applications/example-unrelated.desktop"
        unrelated.write_text("original unrelated launcher")
        unrelated_autostart = root / "config/autostart/example-unrelated.desktop"
        unrelated_autostart.parent.mkdir(parents=True)
        unrelated_autostart.write_text("original unrelated autostart")
        doctor = json.loads(run(installed, "--doctor"))
        assert (
            doctor["configuration_read_only"]
            and doctor["stream_helper_present"]
            and not doctor["usb_output_tested"]
        )
        run(installed, "--autostart", "on")
        native_autostart = unrelated_autostart.with_name("org.spingiantcrm.NanoleafNative.desktop")
        assert str(installed) in native_autostart.read_text()
        # Version identity covers all bundle files. A changed readme is enough
        # to exercise a distinct installation without fabricating a new binary.
        upgraded = root / "upgrade bundle"
        shutil.copytree(relocated, upgraded)
        (upgraded / "README.md").write_text(
            (upgraded / "README.md").read_text() + "\nSmoke test version.\n"
        )
        names = [
            line.split("  ", 1)[1] for line in (upgraded / "SHA256SUMS").read_text().splitlines()
        ]
        (upgraded / "SHA256SUMS").write_text(
            "".join(
                f"{hashlib.sha256((upgraded / name).read_bytes()).hexdigest()}  {name}\n"
                for name in names
            )
        )
        run(upgraded / "bin/nanoleaf-native", "--install-native", prefix)
        second = installed.resolve()
        assert second != first
        run(installed, "--rollback-native", prefix)
        assert installed.resolve() == first
        run(installed, "--rollback-native", prefix)
        assert installed.resolve() == second
        # The stopped tray owns its instance lease. An upgrade cannot race it.
        child = subprocess.Popen(
            [str(installed), "--headless", str(config)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        endpoint = root / "runtime/nanoleaf-native/control.sock"
        end = time.monotonic() + 5
        while not endpoint.exists() and time.monotonic() < end:
            time.sleep(0.01)
        rejected = subprocess.run(
            [str(exe), "--install-native", str(prefix)], env=env, capture_output=True, timeout=5
        )
        assert rejected.returncode != 0 and b"Quit the native tray" in rejected.stderr
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(str(endpoint))
            client.sendall(b'{"action":"quit"}\n')
            client.shutdown(socket.SHUT_WR)
            while client.recv(16384):
                pass
        child.wait(timeout=5)
        assert child.returncode == 0
        run(installed, "--autostart", "off")
        assert not native_autostart.exists()
        run(installed, "--uninstall-native", prefix)
        assert not installed.exists() and first.is_file() and second.is_file()
        # Cleanup stays usable after the installer's launcher has been removed.
        run(exe, "--autostart", "off")
        assert config.read_text() == original
        assert unrelated.read_text() == "original unrelated launcher"
        assert unrelated_autostart.read_text() == "original unrelated autostart"
        result = dict(
            scope="Relocated real binaries; isolated HOME/XDG; no capture or USB output",
            version=version,
            relocation=True,
            helper_discovery=True,
            install_upgrade_rollback=True,
            autostart_tracks_managed_command=True,
            live_service_blocks_upgrade=True,
            uninstall_retains_versions=True,
            configuration_and_unrelated_files_unchanged=True,
            binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
