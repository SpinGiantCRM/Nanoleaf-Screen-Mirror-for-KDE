"""Build a pure Python installer wheel pinned to the tested native archive digest."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import stat
import tomllib
import zipfile
from pathlib import Path

PACKAGE = "nanoleaf_native_installer"


def build(archive: Path, output: Path, manifest: Path, readme: Path, bootstrap: Path) -> Path:
    version = tomllib.loads(manifest.read_text())["package"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Native wheel requires a stable semantic version")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive.name != "native.tar.gz":
        raise ValueError("Expected the canonical native release archive")
    if Path(str(archive) + ".sha256").read_text() != f"{digest}  native.tar.gz\n":
        raise ValueError("Tested archive checksum mismatch")
    info = f"nanoleaf_kde_sync-{version}.dist-info"
    repo = "https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE"
    metadata = (
        "Metadata-Version: 2.4\nName: nanoleaf-kde-sync\n"
        f"Version: {version}\nSummary: Digest-pinned installer for the native Nanoleaf KDE app\n"
        "Requires-Python: >=3.11\nAuthor: SpinGiantCRM\n"
        "License-Expression: LicenseRef-Nanoleaf-Source-Available-Non-Commercial\n"
        "License-File: LICENSE\nClassifier: Operating System :: POSIX :: Linux\n"
        "Classifier: Programming Language :: Python :: 3\n"
        f"Project-URL: Homepage, {repo}\nProject-URL: Repository, {repo}\n"
        f"Project-URL: Issues, {repo}/issues\n"
        f"Project-URL: Documentation, {repo}/blob/native-v{version}/docs/NATIVE_INSTALL.md\n"
        "Description-Content-Type: text/markdown\n\n" + readme.read_text()
    )
    files = {
        f"{PACKAGE}/__init__.py": b"",
        f"{PACKAGE}/bootstrap.py": bootstrap.read_bytes(),
        f"{PACKAGE}/release.json": (
            json.dumps({"version": version, "archive_sha256": digest}, sort_keys=True) + "\n"
        ).encode(),
        f"{info}/METADATA": metadata.encode(),
        f"{info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: nanoleaf-native-installer-wheel\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        f"{info}/entry_points.txt": (
            f"[console_scripts]\nnanoleaf-kde-sync = {PACKAGE}.bootstrap:main\n".encode()
        ),
        f"{info}/licenses/LICENSE": (
            Path(__file__).resolve().parent.parent / "LICENSE"
        ).read_bytes(),
    }
    record = io.StringIO(newline="")
    rows = csv.writer(record, lineterminator="\n")
    for name, data in files.items():
        hashed = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.writerow([name, "sha256=" + hashed, len(data)])
    rows.writerow([f"{info}/RECORD", "", ""])
    files[f"{info}/RECORD"] = record.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    wheel = output / f"nanoleaf_kde_sync-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as packaged:
        for name, data in files.items():
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            packaged.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return wheel


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=root / "native/app/Cargo.toml")
    parser.add_argument("--readme", type=Path, default=root / "packaging/pypi/README.md")
    args = parser.parse_args()
    print(
        build(
            args.archive,
            args.output,
            args.manifest,
            args.readme,
            root / "packaging/pypi/bootstrap.py",
        )
    )


if __name__ == "__main__":
    main()
