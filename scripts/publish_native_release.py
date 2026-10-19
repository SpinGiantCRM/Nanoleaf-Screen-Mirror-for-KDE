"""Publish a tested native archive only after uploaded draft assets are verified."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path


def gh(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", "release", *args, "--repo", repo], capture_output=True, text=True, check=False
    )


def checked(repo: str, *args: str) -> str:
    result = gh(repo, *args)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GitHub release operation failed")
    return result.stdout


def publish(repo: str, tag: str, archive: Path, notes: Path, version: str) -> None:
    if tag != "native-v" + version:
        raise ValueError("Native release tag/version mismatch")
    archive = archive.resolve()
    checksum = Path(str(archive) + ".sha256")
    expected = f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    if checksum.read_text() != expected:
        raise ValueError("Tested archive checksum mismatch")
    state = gh(repo, "view", tag, "--json", "isDraft")
    if state.returncode:
        if "release not found" not in state.stderr.lower():
            raise RuntimeError(state.stderr.strip() or "Cannot inspect native release")
        checked(
            repo,
            "create",
            tag,
            "--draft",
            "--verify-tag",
            "--title",
            f"Nanoleaf Screen Mirror {version}",
            "--notes-file",
            str(notes),
        )
        draft = True
    else:
        draft = json.loads(state.stdout)["isDraft"]
    if draft:
        checked(repo, "upload", tag, str(archive), str(checksum), "--clobber")
    # A published release is immutable here. Reruns only accept the same tested
    # bytes; incomplete or differing published assets require operator attention.
    with tempfile.TemporaryDirectory(prefix="nanoleaf-release-verify-") as directory:
        checked(
            repo,
            "download",
            tag,
            "--pattern",
            archive.name,
            "--pattern",
            checksum.name,
            "--dir",
            directory,
        )
        downloaded = Path(directory)
        if (downloaded / checksum.name).read_text() != expected:
            raise ValueError("Uploaded release checksum differs from the tested archive")
        if hashlib.sha256((downloaded / archive.name).read_bytes()).hexdigest() != expected[:64]:
            raise ValueError("Uploaded release archive differs from the tested archive")
    if draft:
        checked(repo, "edit", tag, "--draft=false", "--latest")
    print(f"Verified native release: {tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("native/app/Cargo.toml"))
    args = parser.parse_args()
    version = tomllib.loads(args.manifest.read_text())["package"]["version"]
    publish(args.repo, args.tag, args.archive, args.notes, version)


if __name__ == "__main__":
    main()
