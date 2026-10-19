"""Exercise native Arch package staging without installing or opening hardware."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

RECIPE = Path(__file__).resolve().parents[1] / "packaging/arch/nanoleaf-kde-sync-bin"


class NativeArchPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="nanoleaf-arch-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.package = self.root / "package"
        self.source.mkdir()
        template = RECIPE / "PKGBUILD"
        if not template.exists():
            template = RECIPE / "PKGBUILD.in"
        self.recipe = self.root / "PKGBUILD"
        self.recipe.write_text(template.read_text().replace("@NATIVE_ARCHIVE_SHA256@", "0" * 64))
        for name in (
            "nanoleaf-native.desktop",
            "nanoleaf-kde-sync.svg",
            "60-nanoleaf-kde-sync.rules",
        ):
            shutil.copyfile(RECIPE / name, self.source / name)
        self.bundle = self.source / "native"
        (self.bundle / "bin").mkdir(parents=True)
        files = {
            "bin/nanoleaf-native": b"app fixture\n",
            "bin/nanoleaf-native-capture": b"matching capture fixture\n",
            "LICENSE": b"native non-commercial license fixture\n",
            "THIRD_PARTY_NOTICES.txt": b"dependency notices fixture\n",
            "README.md": b"native install documentation fixture\n",
        }
        manifest = []
        for name, data in files.items():
            (self.bundle / name).write_bytes(data)
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        (self.bundle / "SHA256SUMS").write_text("".join(manifest))

    def stage(self) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(srcdir=str(self.source), pkgdir=str(self.package))
        return subprocess.run(
            ["bash", "-ec", 'source "$1"; prepare; package', "arch-package", str(self.recipe)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_system_staging_keeps_native_pair_and_desktop_permission_together(self) -> None:
        result = self.stage()
        self.assertEqual(result.returncode, 0, result.stderr)
        base = self.package / "usr/lib/nanoleaf-native/bin"
        for name in ("nanoleaf-native", "nanoleaf-native-capture"):
            target = base / name
            self.assertEqual(target.read_bytes(), (self.bundle / "bin" / name).read_bytes())
            self.assertTrue(target.stat().st_mode & 0o111)
        command = self.package / "usr/bin/nanoleaf-native"
        self.assertEqual(os.readlink(command), "../lib/nanoleaf-native/bin/nanoleaf-native")
        self.assertEqual(command.resolve(), (base / "nanoleaf-native").resolve())
        desktop = self.package / "usr/share/applications/org.spingiantcrm.NanoleafNative.desktop"
        fields = dict(
            line.split("=", 1) for line in desktop.read_text().splitlines() if "=" in line
        )
        self.assertEqual(fields["Exec"], "/usr/lib/nanoleaf-native/bin/nanoleaf-native --daemon")
        self.assertEqual(fields["X-KDE-DBUS-Restricted-Interfaces"], "org.kde.KWin.ScreenShot2")
        icon = self.package / f"usr/share/icons/hicolor/scalable/apps/{fields['Icon']}.svg"
        self.assertTrue(icon.is_file())
        rule = (self.package / "usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules").read_text()
        self.assertEqual(rule.count('TAG+="uaccess"'), 2)
        self.assertNotIn('MODE="0666"', rule)
        self.assertNotIn("GROUP=", rule)
        self.assertEqual({entry.name for entry in self.package.iterdir()}, {"usr"})
        self.assertTrue(
            (self.package / "usr/share/licenses/nanoleaf-kde-sync-bin/LICENSE").is_file()
        )
        self.assertFalse((self.package / "etc").exists())
        self.assertFalse((self.package / "home").exists())

    def test_tampered_capture_helper_prevents_any_package_staging(self) -> None:
        (self.bundle / "bin/nanoleaf-native-capture").write_bytes(b"wrong helper")
        result = self.stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.package.exists())

    @unittest.skipUnless(shutil.which("makepkg"), "Arch makepkg is unavailable")
    def test_makepkg_metadata_has_native_dependencies_and_no_install_script(self) -> None:
        result = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        fields: dict[str, list[str]] = {}
        for line in result.stdout.splitlines():
            if " = " in line:
                key, value = line.strip().split(" = ", 1)
                fields.setdefault(key, []).append(value)
        self.assertEqual(fields["pkgname"], ["nanoleaf-kde-sync-bin"])
        self.assertEqual(fields["arch"], ["x86_64"])
        self.assertIn("libpipewire", fields["depends"])
        self.assertIn("kwin>=6", fields["depends"])
        self.assertFalse(any("python" in value.lower() for value in fields["depends"]))
        self.assertNotIn("install", fields)
        manifest = RECIPE.parents[2] / "native/app/Cargo.toml"
        version = tomllib.loads(manifest.read_text())["package"]["version"]
        self.assertEqual(fields["pkgver"], [version])
        self.assertEqual(fields["provides"], [f"nanoleaf-kde-sync={version}"])
        self.assertIn(f"native-v{version}/native.tar.gz", fields["source"][0])
        self.assertTrue(all(len(value) == 64 for value in fields["sha256sums"]))
        for name, checksum in zip(fields["source"][1:], fields["sha256sums"][1:], strict=True):
            self.assertEqual(checksum, hashlib.sha256((RECIPE / name).read_bytes()).hexdigest())

    @unittest.skipUnless(shutil.which("makepkg"), "Arch makepkg is unavailable")
    def test_pinned_srcinfo_matches_makepkg_output(self) -> None:
        if not (RECIPE / "PKGBUILD").exists():
            self.skipTest("Release archive checksum has not been pinned yet")
        self.assertTrue((RECIPE / ".SRCINFO").is_file())
        result = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=RECIPE,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (RECIPE / ".SRCINFO").read_text())


if __name__ == "__main__":
    unittest.main()
