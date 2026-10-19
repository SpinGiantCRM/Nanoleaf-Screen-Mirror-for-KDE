"""Offline release archive integrity and staging regression checks."""

import hashlib
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from verify_native_bundle import verify_archive, verify_manifest


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bundle = self.root / "native"
        for name in (
            "bin/nanoleaf-native",
            "bin/nanoleaf-native-capture",
            "LICENSE",
            "README.md",
            "60-nanoleaf-kde-sync.rules",
            "THIRD_PARTY_NOTICES.txt",
        ):
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.manifest = self.bundle / "SHA256SUMS"
        self.manifest.write_text(
            "".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
                f"{path.relative_to(self.bundle)}\n"
                for path in sorted(self.bundle.rglob("*"))
                if path.is_file()
            )
        )
        self.archive = self.root / "native.tar.gz"
        with tarfile.open(self.archive, "w:gz") as output:
            output.add(self.bundle, arcname="native")
        self.checksum = Path(str(self.archive) + ".sha256")
        self.refresh_checksum()

    def refresh_checksum(self):
        self.checksum.write_text(
            f"{hashlib.sha256(self.archive.read_bytes()).hexdigest()}  {self.archive.name}\n"
        )

    def test_complete_staging_and_archive_match(self):
        self.assertEqual(len(verify_manifest(self.bundle)), 6)
        verify_archive(self.bundle, self.archive)

    def test_changed_capture_helper_is_rejected(self):
        (self.bundle / "bin/nanoleaf-native-capture").write_text("modified")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_manifest(self.bundle)

    def test_missing_duplicate_and_unexpected_manifest_entries_are_rejected(self):
        original = self.manifest.read_text()
        for invalid in (
            original.split("\n", 1)[1],
            original + original.splitlines()[0] + "\n",
            original + "0" * 64 + "  ../unexpected\n",
        ):
            with self.subTest(manifest=invalid), self.assertRaises(ValueError):
                self.manifest.write_text(invalid)
                verify_manifest(self.bundle)

    def test_symlinked_bundle_file_is_rejected(self):
        path = self.bundle / "LICENSE"
        path.unlink()
        path.symlink_to(self.bundle / "README.md")
        with self.assertRaisesRegex(ValueError, "regular bundle file"):
            verify_manifest(self.bundle)

    def test_changed_archive_checksum_is_rejected(self):
        self.checksum.write_text("0" * 64 + "  native.tar.gz\n")
        with self.assertRaisesRegex(ValueError, "Archive checksum mismatch"):
            verify_archive(self.bundle, self.archive)

    def test_stale_archive_cannot_match_new_staging(self):
        (self.bundle / "README.md").write_text("updated")
        with self.assertRaisesRegex(ValueError, "contents differ"):
            verify_archive(self.bundle, self.archive)

    def test_unsafe_and_duplicate_archive_members_are_rejected(self):
        for name, symlink in (
            ("../escape", False),
            ("native/link", True),
            ("native/duplicate", False),
        ):
            with self.subTest(name=name):
                with tarfile.open(self.archive, "w:gz") as output:
                    info = tarfile.TarInfo(name)
                    if symlink:
                        info.type = tarfile.SYMTYPE
                        info.linkname = "/outside"
                        output.addfile(info)
                    else:
                        info.size = 1
                        output.addfile(info, io.BytesIO(b"x"))
                        output.addfile(info, io.BytesIO(b"x"))
                self.refresh_checksum()
                with self.assertRaises(ValueError):
                    verify_archive(self.bundle, self.archive)

    def test_build_refuses_existing_archive_before_running_cargo(self):
        script = Path(__file__).resolve().with_name("build_native_bundle.sh")
        destination = self.root / "new bundle"
        for suffix in ("", ".tar.gz", ".tar.gz.sha256"):
            collision = Path(str(destination) + suffix)
            collision.write_text("preserve")
            result = subprocess.run(
                ["bash", str(script), str(destination)], capture_output=True, text=True, timeout=5
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(collision.read_text(), "preserve")
            collision.unlink()


if __name__ == "__main__":
    unittest.main()
