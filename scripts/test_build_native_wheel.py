"""Pure installer wheel metadata and digest pin integrity regressions."""

import base64
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_native_wheel import build


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "native.tar.gz"
        self.archive.write_bytes(b"tested native archive")
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        Path(str(self.archive) + ".sha256").write_text(f"{self.digest}  native.tar.gz\n")
        self.manifest = self.root / "Cargo.toml"
        self.manifest.write_text('[package]\nversion="2.0.0"\n')
        self.readme = self.root / "README.md"
        self.readme.write_text("Native installer only. Explicit download required.")
        self.bootstrap = Path(__file__).resolve().parent.parent / "packaging/pypi/bootstrap.py"

    def build(self):
        return build(self.archive, self.root / "wheels", self.manifest, self.readme, self.bootstrap)

    def test_pure_wheel_contains_only_installer_metadata_and_exact_digest(self):
        wheel = self.build()
        self.assertEqual(wheel.name, "nanoleaf_kde_sync-2.0.0-py3-none-any.whl")
        with zipfile.ZipFile(wheel) as packaged:
            info = "nanoleaf_kde_sync-2.0.0.dist-info/"
            self.assertIn(b"Root-Is-Purelib: true", packaged.read(info + "WHEEL"))
            self.assertIn(b"Tag: py3-none-any", packaged.read(info + "WHEEL"))
            self.assertNotIn(b"Requires-Dist:", packaged.read(info + "METADATA"))
            entries = packaged.read(info + "entry_points.txt")
            self.assertIn(b"nanoleaf-kde-sync =", entries)
            self.assertNotIn(b"nanoleaf-native =", entries)
            pinned = json.loads(packaged.read("nanoleaf_native_installer/release.json"))
            self.assertEqual(pinned, {"version": "2.0.0", "archive_sha256": self.digest})
            for name, digest, size in csv.reader(
                io.StringIO(packaged.read(info + "RECORD").decode())
            ):
                data = packaged.read(name)
                self.assertFalse(data.startswith(b"\x7fELF"))
                if name.endswith("/RECORD"):
                    self.assertEqual((digest, size), ("", ""))
                    continue
                calculated = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
                self.assertEqual(digest, "sha256=" + calculated.decode())
                self.assertEqual(int(size), len(data))

    def test_changed_archive_or_path_injected_version_is_rejected(self):
        self.archive.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.build()
        self.manifest.write_text('[package]\nversion="../../outside"\n')
        with self.assertRaisesRegex(ValueError, "semantic version"):
            self.build()


if __name__ == "__main__":
    unittest.main()
