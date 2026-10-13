"""Include published dependency licence declarations and available notices.

Build-time only. No network fetching and no Python dependency in the runtime.
Cargo metadata is filtered to the actual host; include both application and
capture graphs, including their build dependencies, conservatively.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    host = next(
        line.split(": ", 1)[1]
        for line in subprocess.check_output(["rustc", "+1.95.0", "-vV"], text=True).splitlines()
        if line.startswith("host: ")
    )
    packages = {}
    for manifest, features in [
        ("native/app/Cargo.toml", ["--features", "gui"]),
        ("native/stream-probe/Cargo.toml", []),
    ]:
        command = [
            "cargo",
            "+1.95.0",
            "metadata",
            "--locked",
            "--offline",
            "--format-version",
            "1",
            "--filter-platform",
            host,
            "--manifest-path",
            manifest,
            *features,
        ]
        data = json.loads(
            subprocess.check_output(command, text=True, cwd=Path(__file__).resolve().parents[1])
        )
        for package in data["packages"]:
            if package["source"] is not None:
                packages[package["id"]] = package
    chunks = [
        "Native Nanoleaf Screen Mirror: third-party declarations and available notices.\n\n"
        "This inventory includes conservative build dependencies. Declarations are from locked\n"
        "published Cargo manifests; available licence and notice files follow. Not every listed\n"
        "dependency is linked at runtime.\n"
    ]
    missing = []
    for package in sorted(packages.values(), key=lambda p: (p["name"], p["version"])):
        root = Path(package["manifest_path"]).parent
        files = set()
        if package.get("license_file"):
            candidate = root / package["license_file"]
            if candidate.is_file():
                files.add(candidate)
        for candidate in root.rglob("*"):
            name = candidate.name.lower()
            if any(
                term in name for term in ("license", "licence", "copying", "notice", "copyright")
            ) or ("fonts" in candidate.parts and candidate.suffix == ".txt"):
                if candidate.is_file():
                    files.add(candidate)
                elif candidate.is_dir():
                    files.update(p for p in candidate.rglob("*") if p.is_file())
        chunks.append(
            f"\n{'=' * 72}\n{package['name']} {package['version']}\n"
            f"Declared licence: {package.get('license') or 'See supplied licence file'}\n"
            f"Authors: {', '.join(package.get('authors', []))}\n"
            f"Repository: {package.get('repository') or 'Not declared'}\n"
        )
        if not files:
            missing.append(f"{package['name']} {package['version']}: {package.get('license')}")
            chunks.append("Published licence declaration; no separate notice file in this crate.\n")
        for file in sorted(files):
            label = (
                file.name if not file.is_relative_to(root) else file.relative_to(root).as_posix()
            )
            chunks.append(f"\n--- {label} ---\n{file.read_text(errors='replace')}\n")
    args.output.write_text("".join(chunks))
    print(
        json.dumps(dict(packages=len(packages), declarations_without_separate_root_notice=missing))
    )


if __name__ == "__main__":
    main()
