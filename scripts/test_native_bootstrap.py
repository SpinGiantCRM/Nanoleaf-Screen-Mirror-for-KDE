"""Offline installer tests: explicit downloads, digest pins and hostile archives."""

import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BOOTSTRAP = Path(__file__).resolve().parent.parent / "packaging/pypi/bootstrap.py"
SPEC = importlib.util.spec_from_file_location("native_bootstrap_under_test", BOOTSTRAP)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.files = {name: name.encode() for name in bootstrap.FILES}
        self.files["SHA256SUMS"] = "".join(
            f"{hashlib.sha256(value).hexdigest()}  {name}\n" for name, value in self.files.items()
        ).encode()
        self.archive = self.root / "native.tar.gz"
        self.archive.write_bytes(self.archive_bytes())
        self.release = {"version": "2.0.0", "archive_sha256": self.digest()}
        self.addCleanup(patch.stopall)
        patch.dict(
            os.environ, {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state")}
        ).start()

    def archive_bytes(self, extras=(), omitted=()):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as packaged:
            for name, data in self.files.items():
                if name in omitted:
                    continue
                entry = tarfile.TarInfo("native/" + name)
                entry.size = len(data)
                packaged.addfile(entry, io.BytesIO(data))
            for entry in extras:
                packaged.addfile(entry, io.BytesIO(b"x" * entry.size))
        return output.getvalue()

    def digest(self):
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def fake_download(self, url, destination, _limit):
        self.assertTrue(
            url.startswith(
                "https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/"
                "releases/download/native-v2.0.0/native.tar.gz"
            )
        )
        data = (
            f"{self.digest()}  native.tar.gz\n".encode()
            if url.endswith(".sha256")
            else self.archive.read_bytes()
        )
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def test_exact_bundle_extracts_with_executable_permissions(self):
        bundle = bootstrap.unpack(self.archive, self.root / "unpacked")
        for name, value in self.files.items():
            self.assertEqual((bundle / name).read_bytes(), value)
        self.assertEqual((bundle / "bin/nanoleaf-native").stat().st_mode & 0o777, 0o755)

    def test_hostile_paths_links_duplicates_and_unexpected_directories_fail(self):
        for name, kind in (
            ("../escape", tarfile.REGTYPE),
            ("/escape", tarfile.REGTYPE),
            ("native/../escape", tarfile.REGTYPE),
            ("native/extra", tarfile.REGTYPE),
            ("native/LICENSE", tarfile.REGTYPE),
            ("native/link", tarfile.SYMTYPE),
            ("native/link", tarfile.LNKTYPE),
            ("native/extra", tarfile.DIRTYPE),
        ):
            with self.subTest(name=name, kind=kind):
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.linkname = "/outside"
                self.archive.write_bytes(self.archive_bytes([entry]))
                with (
                    tempfile.TemporaryDirectory(dir=self.root) as directory,
                    self.assertRaises(ValueError),
                ):
                    bootstrap.unpack(self.archive, Path(directory))
        self.assertFalse((self.root / "escape").exists())

    def test_incomplete_archive_and_changed_internal_manifest_fail(self):
        self.archive.write_bytes(self.archive_bytes(omitted=["LICENSE"]))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            bootstrap.unpack(self.archive, self.root / "incomplete")
        self.files["LICENSE"] = b"changed"
        self.archive.write_bytes(self.archive_bytes())
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            bootstrap.unpack(self.archive, self.root / "changed")

    def test_explicit_install_verifies_then_runs_only_the_native_installer(self):
        prefix = self.root / "custom prefix"
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download", side_effect=self.fake_download),
            patch.object(
                bootstrap.subprocess, "check_output", return_value="nanoleaf-native 2.0.0\n"
            ),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            bootstrap.install(self.release, str(prefix))
        command = run.call_args.args[0]
        self.assertTrue(command[0].endswith("/native/bin/nanoleaf-native"))
        self.assertEqual(command[1:], ["--install-native", str(prefix)])
        record = json.loads(bootstrap.installation_record().read_text())
        self.assertEqual(record["command"], str(prefix / "bin/nanoleaf-native"))
        self.assertEqual(bootstrap.installation_record().stat().st_mode & 0o777, 0o600)

    def test_bad_archive_digest_never_executes_a_binary(self):
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download", return_value="0" * 64),
            patch.object(bootstrap.subprocess, "check_output") as execute,
            self.assertRaisesRegex(ValueError, "pinned release digest"),
        ):
            bootstrap.install(self.release, None)
        execute.assert_not_called()

    def test_install_without_prefix_reuses_previous_custom_prefix_and_explicit_prefix_wins(self):
        first = self.root / "first custom prefix"
        second = self.root / "explicit replacement"
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download", side_effect=self.fake_download),
            patch.object(
                bootstrap.subprocess, "check_output", return_value="nanoleaf-native 2.0.0\n"
            ),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            bootstrap.install(self.release, str(first))
            bootstrap.install(self.release, None)
            self.assertEqual(run.call_args.args[0][1:], ["--install-native", str(first)])
            bootstrap.install(self.release, str(second))
            self.assertEqual(run.call_args.args[0][1:], ["--install-native", str(second)])
        record = json.loads(bootstrap.installation_record().read_text())
        self.assertEqual(record["command"], str(second / "bin/nanoleaf-native"))
        self.assertFalse((self.root / ".local/bin/nanoleaf-native").exists())

    def test_alias_rollback_and_uninstall_without_prefix_target_recorded_custom_install(self):
        installed = self.root / "bootstrap.py"
        installed.with_name("release.json").write_text(json.dumps(self.release))
        prefix = self.root / "custom prefix"
        executable = prefix / "bin/nanoleaf-native"
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture")
        record = bootstrap.installation_record()
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"command": str(executable)}))
        for command in ("--rollback-native", "--uninstall-native"):
            with (
                self.subTest(command=command),
                patch.object(bootstrap, "__file__", str(installed)),
                patch.object(bootstrap.sys, "argv", ["nanoleaf-kde-sync", command]),
                patch.object(
                    bootstrap.os, "execv", side_effect=RuntimeError("exec reached")
                ) as execute,
                self.assertRaisesRegex(RuntimeError, "exec reached"),
            ):
                bootstrap.main()
            execute.assert_called_once_with(
                str(executable), [str(executable), command, str(prefix)]
            )

    def test_corrupt_record_fails_before_network_and_explicit_install_repairs_it(self):
        record = bootstrap.installation_record()
        record.parent.mkdir(parents=True)
        record.write_text("invalid json")
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download") as download,
            self.assertRaisesRegex(ValueError, "installation record"),
        ):
            bootstrap.install(self.release, None)
        download.assert_not_called()
        prefix = self.root / "explicit repair"
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download", side_effect=self.fake_download),
            patch.object(
                bootstrap.subprocess, "check_output", return_value="nanoleaf-native 2.0.0\n"
            ),
            patch.object(bootstrap.subprocess, "run"),
        ):
            bootstrap.install(self.release, str(prefix))
        self.assertEqual(
            json.loads(record.read_text())["command"], str(prefix / "bin/nanoleaf-native")
        )

    def test_explicit_alias_prefix_wins_even_with_a_corrupt_record(self):
        installed = self.root / "bootstrap.py"
        installed.with_name("release.json").write_text(json.dumps(self.release))
        prefix = self.root / "explicit target"
        executable = prefix / "bin/nanoleaf-native"
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture")
        record = bootstrap.installation_record()
        record.parent.mkdir(parents=True)
        record.write_text("corrupt")
        with (
            patch.object(bootstrap, "__file__", str(installed)),
            patch.object(
                bootstrap.sys, "argv", ["nanoleaf-kde-sync", "--rollback-native", str(prefix)]
            ),
            patch.object(
                bootstrap.os, "execv", side_effect=RuntimeError("exec reached")
            ) as execute,
            self.assertRaisesRegex(RuntimeError, "exec reached"),
        ):
            bootstrap.main()
        execute.assert_called_once_with(
            str(executable), [str(executable), "--rollback-native", str(prefix)]
        )

    def test_missing_recorded_command_does_not_target_an_unrelated_default_install(self):
        installed = self.root / "bootstrap.py"
        installed.with_name("release.json").write_text(json.dumps(self.release))
        record = bootstrap.installation_record()
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"command": str(self.root / "missing/bin/nanoleaf-native")}))
        with (
            patch.object(bootstrap, "__file__", str(installed)),
            patch.object(bootstrap.sys, "argv", ["nanoleaf-kde-sync", "--uninstall-native"]),
            patch.object(
                bootstrap.shutil, "which", return_value="/unrelated/nanoleaf-native"
            ) as find,
            patch.object(bootstrap.os, "execv") as execute,
            self.assertRaises(SystemExit),
        ):
            bootstrap.main()
        find.assert_not_called()
        execute.assert_not_called()

    def test_malformed_and_symlinked_record_paths_are_refused_clearly(self):
        record = bootstrap.installation_record()
        record.parent.mkdir(parents=True)
        for value in (
            [],
            {},
            {"command": 12},
            {"command": "relative/bin/nanoleaf-native"},
            {"command": "/prefix/not-bin/nanoleaf-native"},
            {"command": "/prefix/bin/other"},
            {"command": "/prefix/../bin/nanoleaf-native"},
        ):
            record.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "explicit PREFIX"):
                bootstrap.remembered_command()
        record.unlink()
        record.symlink_to(self.root / "missing-record")
        with self.assertRaisesRegex(ValueError, "explicit PREFIX"):
            bootstrap.remembered_command()

    def test_unsupported_platform_and_invalid_pin_never_download(self):
        with (
            patch.object(bootstrap.sys, "platform", "darwin"),
            patch.object(bootstrap, "download") as download,
            self.assertRaisesRegex(ValueError, "Linux x86_64"),
        ):
            bootstrap.install(self.release, None)
        download.assert_not_called()
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.platform, "machine", return_value="x86_64"),
            patch.object(bootstrap, "download") as download,
            self.assertRaisesRegex(ValueError, "metadata"),
        ):
            bootstrap.install({"version": "../outside", "archive_sha256": "0" * 64}, None)
        download.assert_not_called()

    def test_http_and_non_https_redirects_are_refused(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            bootstrap.download("http://example.invalid/file", self.root / "file", 10)
        with self.assertRaisesRegex(ValueError, "non-HTTPS"):
            bootstrap.HTTPSRedirects().redirect_request(
                None, None, 302, "", {}, "http://example.invalid"
            )

    def test_help_version_and_missing_install_do_not_download(self):
        installed = self.root / "bootstrap.py"
        installed.with_name("release.json").write_text(json.dumps(self.release))
        with (
            patch.object(bootstrap, "__file__", str(installed)),
            patch.object(bootstrap, "download") as download,
            patch.object(bootstrap.shutil, "which", return_value=None),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            for args in ([], ["--help"], ["--version"]):
                with patch.object(bootstrap.sys, "argv", ["nanoleaf-kde-sync", *args]):
                    bootstrap.main()
            with (
                patch.object(bootstrap.sys, "argv", ["nanoleaf-kde-sync", "--doctor"]),
                self.assertRaises(SystemExit),
            ):
                bootstrap.main()
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
