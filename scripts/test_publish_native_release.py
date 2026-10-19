"""No-network release lifecycle regressions with a simulated GitHub CLI."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish_native_release import publish


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "native.tar.gz"
        self.archive.write_bytes(b"tested archive")
        self.checksum = Path(str(self.archive) + ".sha256")
        self.checksum.write_text(
            f"{hashlib.sha256(self.archive.read_bytes()).hexdigest()}  native.tar.gz\n"
        )
        self.notes = self.root / "notes.md"
        self.notes.write_text("Release notes")
        self.draft = None
        self.remote = {}
        self.calls = []
        self.corrupt_download = False
        self.missing_download = False
        self.network_failure = False
        self.mock = patch("publish_native_release.gh", side_effect=self.gh).start()
        self.addCleanup(patch.stopall)

    def gh(self, repo, *args):
        self.assertEqual(repo, "example/project")
        self.calls.append(args[0])
        if args[0] == "view":
            if self.network_failure:
                return subprocess.CompletedProcess(args, 1, "", "network unavailable")
            if self.draft is None:
                return subprocess.CompletedProcess(args, 1, "", "release not found")
            return subprocess.CompletedProcess(args, 0, json.dumps({"isDraft": self.draft}), "")
        if args[0] == "create":
            self.assertIn("--draft", args)
            self.draft = True
        elif args[0] == "upload":
            self.assertTrue(self.draft)
            self.remote = {Path(name).name: Path(name).read_bytes() for name in args[2:4]}
        elif args[0] == "download":
            destination = Path(args[args.index("--dir") + 1])
            for name, value in self.remote.items():
                if self.missing_download and name.endswith(".sha256"):
                    continue
                if self.corrupt_download and name.endswith(".tar.gz"):
                    value += b"corrupt"
                (destination / name).write_bytes(value)
        elif args[0] == "edit":
            self.assertIn("--draft=false", args)
            self.draft = False
        return subprocess.CompletedProcess(args, 0, "", "")

    def publish(self, tag="native-v2.0.0"):
        publish("example/project", tag, self.archive, self.notes, "2.0.0")

    def test_new_release_is_published_only_after_upload_and_download_verification(self):
        self.publish()
        self.assertEqual(self.calls, ["view", "create", "upload", "download", "edit"])

    def test_existing_draft_resumes_upload_and_verification(self):
        self.draft = True
        self.publish()
        self.assertEqual(self.calls, ["view", "upload", "download", "edit"])

    def test_identical_published_release_is_an_immutable_no_op(self):
        self.draft = False
        self.remote = {path.name: path.read_bytes() for path in (self.archive, self.checksum)}
        self.publish()
        self.assertEqual(self.calls, ["view", "download"])

    def test_corrupt_draft_upload_is_never_published(self):
        self.corrupt_download = True
        with self.assertRaisesRegex(ValueError, "archive differs"):
            self.publish()
        self.assertTrue(self.draft)
        self.assertNotIn("edit", self.calls)

    def test_missing_draft_asset_is_never_published(self):
        self.missing_download = True
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.assertTrue(self.draft)
        self.assertNotIn("edit", self.calls)

    def test_differing_published_assets_are_never_replaced(self):
        self.draft = False
        self.remote = {self.archive.name: b"different", self.checksum.name: b"different"}
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            self.publish()
        self.assertEqual(self.calls, ["view", "download"])

    def test_missing_published_assets_are_never_replaced(self):
        self.draft = False
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.assertEqual(self.calls, ["view", "download"])

    def test_tag_mismatch_and_local_corruption_never_contact_github(self):
        with self.assertRaisesRegex(ValueError, "tag/version mismatch"):
            self.publish("native-v1.0.0")
        self.archive.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "archive checksum mismatch"):
            self.publish()
        self.assertEqual(self.calls, [])

    def test_network_failure_is_not_treated_as_a_missing_release(self):
        self.network_failure = True
        with self.assertRaisesRegex(RuntimeError, "network unavailable"):
            self.publish()
        self.assertEqual(self.calls, ["view"])


if __name__ == "__main__":
    unittest.main()
