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
import tarfile
import tempfile
import time
from pathlib import Path


def verify_manifest(bundle: Path) -> dict[str, str]:
    """Check all distributed files before any executable is started."""
    names = {
        "bin/nanoleaf-native",
        "bin/nanoleaf-native-capture",
        "LICENSE",
        "README.md",
        "60-nanoleaf-kde-sync.rules",
        "THIRD_PARTY_NOTICES.txt",
    }
    entries = {}
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name not in names or name in entries:
            raise ValueError("Unexpected or duplicate bundle manifest entry")
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular bundle file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Bundle checksum mismatch: {name}")
        entries[name] = digest
    if set(entries) != names:
        raise ValueError("Incomplete bundle manifest")
    return entries


def verify_archive(bundle: Path, archive: Path) -> None:
    """Match the release archive and its detached checksum to the staged bundle."""
    expected = f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    if Path(str(archive) + ".sha256").read_text() != expected:
        raise ValueError("Archive checksum mismatch")
    expected_files = {
        str(path.relative_to(bundle)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*")
        if path.is_file()
    }
    found = {}
    with tarfile.open(archive, "r:gz") as packaged:
        for member in packaged:
            parts = Path(member.name).parts
            if not parts or parts[0] != bundle.name or ".." in parts:
                raise ValueError("Unexpected archive path")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Expected a regular archive file")
            name = str(Path(*parts[1:]))
            if name in found:
                raise ValueError("Duplicate archive file")
            with packaged.extractfile(member) as stream:
                found[name] = hashlib.sha256(stream.read()).hexdigest()
    if found != expected_files:
        raise ValueError("Archive contents differ from the staged bundle")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--stub-desktop-cache",
        action="store_true",
        help="Stub only kbuildsycoca6 for CI hosts without KDE; recorded in the result",
    )
    args = parser.parse_args()
    entries = verify_manifest(args.bundle)
    if args.archive:
        verify_archive(args.bundle, args.archive)
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
        if args.stub_desktop_cache:
            tools = root / "tools"
            tools.mkdir()
            cache = tools / "kbuildsycoca6"
            cache.write_text("#!/bin/sh\nexit 0\n")
            cache.chmod(0o755)
            env["PATH"] = str(tools) + os.pathsep + env["PATH"]
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

        def verify_pair(binary):
            assert binary.parent.name == "bin"
            assert binary.parent.parent.parent == prefix / "lib/nanoleaf-native"
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == entries["bin/nanoleaf-native"]
            helper = binary.with_name("nanoleaf-native-capture")
            assert (
                hashlib.sha256(helper.read_bytes()).hexdigest()
                == entries["bin/nanoleaf-native-capture"]
            )
            launcher = (
                root / "data/applications/org.spingiantcrm.NanoleafNative.desktop"
            ).read_text()
            assert f'Exec="{binary}" --daemon\n' in launcher
            icon = Path(
                next(line[5:] for line in launcher.splitlines() if line.startswith("Icon="))
            )
            assert icon.parent == binary.parent.parent
            assert (
                icon.name
                == f"nanoleaf-kde-sync-{hashlib.sha256(icon.read_bytes()).hexdigest()}.svg"
            )

        verify_pair(first)
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
        verify_pair(second)
        # Reject a changed helper before switching either executable on rollback.
        previous_helper = first.with_name("nanoleaf-native-capture")
        original_helper = previous_helper.read_bytes()
        try:
            previous_helper.write_bytes(original_helper + b"corruption")
            rejected = subprocess.run(
                [str(installed), "--rollback-native", str(prefix)],
                env=env,
                capture_output=True,
                timeout=5,
            )
            assert rejected.returncode != 0 and b"checksum" in rejected.stderr.lower()
            assert installed.resolve() == second
        finally:
            previous_helper.write_bytes(original_helper)
        run(installed, "--rollback-native", prefix)
        assert installed.resolve() == first
        verify_pair(installed.resolve())
        run(installed, "--rollback-native", prefix)
        assert installed.resolve() == second
        verify_pair(installed.resolve())
        # The stopped tray owns its instance lease. An upgrade cannot race it.
        child = subprocess.Popen(
            [str(installed), "--headless", str(config)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
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
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
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
            bundle_checksums=True,
            archive_checksums_and_contents=True if args.archive else None,
            desktop_cache="stub" if args.stub_desktop_cache else "system kbuildsycoca6",
            helper_discovery=True,
            install_upgrade_rollback=True,
            paired_app_and_helper_rollback=True,
            branded_launcher_immutable_icon=True,
            corrupt_previous_helper_blocks_rollback=True,
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
