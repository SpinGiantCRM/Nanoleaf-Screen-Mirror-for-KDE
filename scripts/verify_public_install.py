"""Install the latest public PyPI/GitHub native release in disposable directories.

Uses real HTTPS downloads, a hash-pinned pip install and the published installer.
Only version/help, installation, read-only doctor and uninstall commands run.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = "SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE"


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("Refusing a non-HTTPS download redirect")
        return super().redirect_request(request, response, code, message, headers, url)


def fetch(url: str, limit: int = 4 * 1024 * 1024) -> bytes:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Public downloads require HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "nanoleaf-maintenance"})
    opener = urllib.request.build_opener(HTTPSRedirects())
    with opener.open(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Public metadata or wheel exceeds its download limit")
    return data


def validate_channels(github: dict, pypi: dict) -> tuple[str, dict, str]:
    tag = github["tag_name"]
    if github["draft"] or github["prerelease"] or not re.fullmatch(r"native-v\d+\.\d+\.\d+", tag):
        raise ValueError("Latest GitHub release is not a published stable native release")
    version = tag.removeprefix("native-v")
    if pypi["info"]["version"] != version:
        raise ValueError("Latest GitHub and PyPI versions differ")
    assets = {asset["name"]: asset for asset in github["assets"]}
    if not {"native.tar.gz", "native.tar.gz.sha256"} <= assets.keys():
        raise ValueError("Published native archive or checksum is missing")
    digest = assets["native.tar.gz"].get("digest", "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("GitHub archive has no valid SHA-256 digest")
    wheels = [
        entry
        for entry in pypi["urls"]
        if entry["filename"] == f"nanoleaf_kde_sync-{version}-py3-none-any.whl"
        and entry["packagetype"] == "bdist_wheel"
        and not entry["yanked"]
    ]
    if len(wheels) != 1:
        raise ValueError("Expected one unyanked pure installer wheel on PyPI")
    wheel = wheels[0]
    url = urllib.parse.urlsplit(wheel["url"])
    if url.scheme != "https" or url.netloc != "files.pythonhosted.org":
        raise ValueError("Wheel download is outside public PyPI HTTPS storage")
    if not re.fullmatch(r"[0-9a-f]{64}", wheel["digests"]["sha256"]):
        raise ValueError("PyPI wheel has no valid SHA-256 digest")
    return version, wheel, digest


def validate_wheel(data: bytes, version: str, archive_digest: str) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        if any(wheel.read(name).startswith(b"\x7fELF") for name in wheel.namelist()):
            raise ValueError("The pure installer wheel contains an ELF binary")
        release = json.loads(wheel.read("nanoleaf_native_installer/release.json"))
    if release != {"version": version, "archive_sha256": archive_digest}:
        raise ValueError("Wheel native version/digest differs from the GitHub release")


def isolated_environment(home: Path) -> dict[str, str]:
    """Discard inherited pip destinations before constructing the private environment."""
    parent = {name: value for name, value in os.environ.items() if not name.startswith("PIP_")}
    env = dict(
        parent,
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
        XDG_STATE_HOME=str(home / "state"),
        XDG_RUNTIME_DIR=str(home / "runtime"),
        PIP_CONFIG_FILE=os.devnull,
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_INDEX_URL="https://pypi.org/simple",
        PATH=os.pathsep.join(
            [str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]
        ),
    )
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        env.pop(name, None)
    return env


def verify(output: Path, stub_cache: bool) -> None:
    github = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases/latest"))
    pypi = json.loads(fetch("https://pypi.org/pypi/nanoleaf-kde-sync/json"))
    version, wheel, archive_digest = validate_channels(github, pypi)
    data = fetch(wheel["url"])
    wheel_digest = hashlib.sha256(data).hexdigest()
    if wheel_digest != wheel["digests"]["sha256"]:
        raise ValueError("Public wheel checksum differs from PyPI metadata")
    validate_wheel(data, version, archive_digest)
    print(f"Verified public metadata for native {version}; installing from PyPI", flush=True)
    with tempfile.TemporaryDirectory(prefix="nanoleaf-public-install-") as directory:
        home = Path(directory)
        runtime = home / "runtime"
        runtime.mkdir(mode=0o700)
        env = isolated_environment(home)
        if stub_cache:
            tools = home / "tools"
            tools.mkdir()
            cache = tools / "kbuildsycoca6"
            cache.write_text("#!/bin/sh\nexit 0\n")
            cache.chmod(0o755)
            env["PATH"] = str(tools) + os.pathsep + env["PATH"]

        def run(*command):
            result = subprocess.run(
                [str(part) for part in command],
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr + result.stdout)
            return result.stdout.strip()

        venv = home / "venv"
        run(sys.executable, "-m", "venv", venv)
        requirements = home / "requirements.txt"
        requirements.write_text(f"nanoleaf-kde-sync=={version} --hash=sha256:{wheel_digest}\n")
        run(
            venv / "bin/python",
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-deps",
            "--only-binary=:all:",
            "--require-hashes",
            "--index-url",
            "https://pypi.org/simple",
            "-r",
            requirements,
        )
        alias = venv / "bin/nanoleaf-kde-sync"
        assert "native installer " + version in run(alias, "--version")
        assert "--install-native" in run(alias, "--help")
        config = home / "config/nanoleaf-kde-sync/config.toml"
        config.parent.mkdir(parents=True)
        original = (
            "schema_version=2\nstart_on_launch=false\ndevice_zone_count=0\nunknown='preserve'\n"
            "[led_calibration_profile_sdr]\nred_gain=0.873123456789\n"
        )
        config.write_text(original)
        prefix = home / "native prefix with spaces"
        run(alias, "--install-native", prefix)
        native = prefix / "bin/nanoleaf-native"
        installed = native.resolve()
        assert run(alias, "--version") == "nanoleaf-native " + version
        doctor = json.loads(run(native, "--doctor"))
        assert doctor["configuration_read_only"] and doctor["stream_helper_present"]
        assert not doctor["usb_output_tested"]
        # A subsequent upgrade must remember the custom prefix without extra arguments.
        run(alias, "--install-native")
        assert native.resolve() == installed
        assert not (home / ".local/bin/nanoleaf-native").exists()
        run(alias, "--uninstall-native")
        assert not native.exists() and installed.is_file()
        assert config.read_text() == original
        run(venv / "bin/python", "-m", "pip", "uninstall", "-y", "nanoleaf-kde-sync")
        assert not alias.exists()
    result = {
        "version": version,
        "release_tag": github["tag_name"],
        "transport": "actual public PyPI and HTTPS GitHub release downloads",
        "wheel_sha256": wheel_digest,
        "archive_sha256": archive_digest,
        "pure_installer_wheel": True,
        "native_install_and_upgrade": True,
        "remembered_custom_prefix_uninstall": True,
        "configuration_preserved": True,
        "retained_native_versions": True,
        "capture_or_output_started": False,
        "desktop_cache": "stub" if stub_cache else "system kbuildsycoca6",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stub-desktop-cache", action="store_true")
    args = parser.parse_args()
    verify(args.output, args.stub_desktop_cache)


if __name__ == "__main__":
    main()
