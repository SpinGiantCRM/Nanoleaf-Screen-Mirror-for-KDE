"""Explicit, digest-pinned native installer; daily use replaces this process."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

FILES = {
    "bin/nanoleaf-native",
    "bin/nanoleaf-native-capture",
    "LICENSE",
    "README.md",
    "60-nanoleaf-kde-sync.rules",
    "THIRD_PARTY_NOTICES.txt",
}
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024


def installation_record() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return state / "nanoleaf-native-installer/installation.json"


def remembered_command() -> Path | None:
    record = installation_record()
    try:
        if record.is_symlink():
            raise ValueError("Symlinked installation record")
        saved = json.loads(record.read_text())
        command = saved.get("command") if isinstance(saved, dict) else None
        if not isinstance(command, str):
            raise ValueError("Missing native command")
        candidate = Path(command)
        if (
            not candidate.is_absolute()
            or candidate.name != "nanoleaf-native"
            or candidate.parent.name != "bin"
            or ".." in candidate.parts
        ):
            raise ValueError("Invalid native command path")
        # Keep the managed symlink path, including when temporarily missing.
        # Resolving it would mistake the immutable version for the install prefix.
        return candidate
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise ValueError(
            "Invalid native installation record; "
            "use --install-native with an explicit PREFIX to repair it."
        ) from error


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("Native download refused a non-HTTPS redirect")
        return super().redirect_request(request, response, code, message, headers, url)


def download(url: str, destination: Path, limit: int) -> str:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Native downloads require HTTPS")
    opener = urllib.request.build_opener(HTTPSRedirects())
    digest = hashlib.sha256()
    size = 0
    with opener.open(url, timeout=30) as response, destination.open("xb") as output:
        while block := response.read(65536):
            size += len(block)
            if size > limit:
                raise ValueError("Native download exceeds its size limit")
            digest.update(block)
            output.write(block)
    return digest.hexdigest()


def unpack(archive: Path, destination: Path) -> Path:
    """Extract only known regular bundle files into a private directory."""
    seen = set()
    total = 0
    bundle = destination / "native"
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if member.isdir() and member.name in {"native", "native/bin"}:
                continue
            name = member.name.removeprefix("native/")
            if member.name != "native/" + name or name not in FILES | {"SHA256SUMS"}:
                raise ValueError("Unexpected native archive path")
            if not member.isfile() or name in seen:
                raise ValueError("Native archive contains a link or duplicate file")
            total += member.size
            if member.size < 0 or total > MAX_UNPACKED:
                raise ValueError("Native archive exceeds its unpacked size limit")
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, path.open("xb") as output:
                shutil.copyfileobj(incoming, output, length=65536)
            path.chmod(0o755 if name.startswith("bin/") else 0o644)
            seen.add(name)
    if seen != FILES | {"SHA256SUMS"}:
        raise ValueError("Native archive is incomplete")
    verified = set()
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name not in FILES or name in verified:
            raise ValueError("Unexpected or duplicate native manifest entry")
        if hashlib.sha256((bundle / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Native bundle checksum mismatch")
        verified.add(name)
    if verified != FILES:
        raise ValueError("Native bundle manifest is incomplete")
    return bundle


def install(release: dict, prefix: str | None) -> None:
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("The native application requires Linux x86_64 and KDE Plasma 6 Wayland")
    version = release["version"]
    expected = release["archive_sha256"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid pinned native release metadata")
    if prefix is None:
        previous = remembered_command()
        if previous is not None:
            prefix = str(previous.parent.parent)
    url = (
        "https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/"
        f"releases/download/native-v{version}/native.tar.gz"
    )
    with tempfile.TemporaryDirectory(prefix="nanoleaf-native-install-") as directory:
        root = Path(directory)
        archive = root / "native.tar.gz"
        checksum = root / "native.tar.gz.sha256"
        if download(url, archive, MAX_ARCHIVE) != expected:
            raise ValueError("Downloaded archive differs from the pinned release digest")
        download(url + ".sha256", checksum, 512)
        if checksum.read_text() != f"{expected}  native.tar.gz\n":
            raise ValueError("Published checksum differs from the pinned release digest")
        bundle = unpack(archive, root)
        executable = str(bundle / "bin/nanoleaf-native")
        actual = subprocess.check_output([executable, "--version"], text=True, timeout=10).strip()
        if actual != "nanoleaf-native " + version:
            raise ValueError("Downloaded application version differs from the pinned release")
        command = [executable, "--install-native"]
        if prefix is not None:
            command.append(prefix)
        subprocess.run(command, check=True)
        target = (Path(prefix) if prefix is not None else Path.home() / ".local").resolve()
        record = installation_record()
        record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile("w", dir=record.parent, delete=False) as saved:
            json.dump({"command": str(target / "bin/nanoleaf-native")}, saved)
            temporary = Path(saved.name)
        try:
            temporary.replace(record)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    release = json.loads(Path(__file__).with_name("release.json").read_text())
    args = sys.argv[1:]
    if args[:1] == ["--install-native"]:
        if len(args) > 2:
            raise SystemExit("Use nanoleaf-kde-sync --install-native [PREFIX]")
        try:
            install(release, args[1] if len(args) == 2 else None)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise SystemExit(f"Native installation failed: {error}") from error
        return
    control = args[:1] in (["--rollback-native"], ["--uninstall-native"])
    explicit = control and len(args) > 1
    try:
        previous = None if explicit else remembered_command()
    except ValueError as error:
        raise SystemExit(str(error)) from error
    native = (
        Path(args[1]).resolve() / "bin/nanoleaf-native"
        if explicit
        else previous or Path.home() / ".local/bin/nanoleaf-native"
    )
    executable = str(native) if native.is_file() else None
    if executable is None and previous is None:
        executable = shutil.which("nanoleaf-native")
    if executable:
        if control and len(args) == 1 and previous is not None:
            args.append(str(previous.parent.parent))
        os.execv(executable, [executable, *args])
    if args == ["--version"]:
        print("nanoleaf-kde-sync native installer " + release["version"])
    elif not args or args in (["--help"], ["-h"]):
        print(
            "Nanoleaf native installer " + release["version"] + "\n"
            "Install the Linux x86_64 app explicitly:\n"
            "  nanoleaf-kde-sync --install-native [PREFIX]\n"
            "This downloads the pinned GitHub native release and verifies its SHA256.\n"
            "Then open Nanoleaf Screen Mirror from KDE's launcher.\n"
            "Later commands pass directly to the installed native app."
        )
    else:
        raise SystemExit(
            "Install first with nanoleaf-kde-sync --install-native; no download started."
        )


if __name__ == "__main__":
    main()
