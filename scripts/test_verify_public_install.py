"""Public-channel checks must reject inconsistent or executable wheel contents."""

import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from verify_public_install import isolated_environment, validate_channels, validate_wheel


class PublicInstallTests(unittest.TestCase):
    def test_parent_pip_placement_settings_cannot_escape_disposable_home(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "PIP_TARGET": "/outside/site-packages",
                    "PIP_PREFIX": "/outside/prefix",
                    "PIP_ROOT": "/outside/root",
                    "PIP_USER": "1",
                    "PIP_EXTRA_INDEX_URL": "https://unrelated.invalid/simple",
                },
            ),
        ):
            env = isolated_environment(Path(directory))
        self.assertEqual(
            {name: value for name, value in env.items() if name.startswith("PIP_")},
            {
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_INDEX_URL": "https://pypi.org/simple",
            },
        )

    def setUp(self):
        self.github = {
            "tag_name": "native-v2.0.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "native.tar.gz", "digest": "sha256:" + "a" * 64},
                {"name": "native.tar.gz.sha256"},
            ],
        }
        self.pypi = {
            "info": {"version": "2.0.0"},
            "urls": [
                {
                    "filename": "nanoleaf_kde_sync-2.0.0-py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                    "url": "https://files.pythonhosted.org/packages/test.whl",
                    "digests": {"sha256": "b" * 64},
                }
            ],
        }

    def test_matching_stable_channels_select_the_exact_pure_wheel(self):
        version, wheel, digest = validate_channels(self.github, self.pypi)
        self.assertEqual(version, "2.0.0")
        self.assertEqual(wheel["url"], "https://files.pythonhosted.org/packages/test.whl")
        self.assertEqual(digest, "a" * 64)

    def test_mismatched_or_unpublished_channels_fail_before_installation(self):
        for field, value in (("draft", True), ("prerelease", True), ("tag_name", "v1.9.3")):
            github = dict(self.github, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_channels(github, self.pypi)
        pypi = copy.deepcopy(self.pypi)
        pypi["info"]["version"] = "1.9.3"
        with self.assertRaises(ValueError):
            validate_channels(self.github, pypi)
        with self.assertRaises(ValueError):
            validate_channels(dict(self.github, assets=[]), self.pypi)

    def test_yanked_wrong_platform_and_untrusted_downloads_fail(self):
        for field, value in (
            ("yanked", True),
            ("filename", "nanoleaf_kde_sync-2.0.0-linux_x86_64.whl"),
            ("url", "http://files.pythonhosted.org/test.whl"),
            ("url", "https://unrelated.invalid/test.whl"),
            ("digests", {"sha256": "not-a-digest"}),
        ):
            pypi = copy.deepcopy(self.pypi)
            pypi["urls"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_channels(self.github, pypi)

    def wheel(self, version="2.0.0", digest="a" * 64, payload=b"print('installer')"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("nanoleaf_native_installer/bootstrap.py", payload)
            archive.writestr(
                "nanoleaf_native_installer/release.json",
                json.dumps({"version": version, "archive_sha256": digest}),
            )
        return output.getvalue()

    def test_embedded_release_must_match_github_and_contain_no_elf(self):
        validate_wheel(self.wheel(), "2.0.0", "a" * 64)
        for wheel in (
            self.wheel(version="1.9.3"),
            self.wheel(digest="c" * 64),
            self.wheel(payload=b"\x7fELFnative executable"),
        ):
            with self.subTest(wheel=wheel[:20]), self.assertRaises(ValueError):
                validate_wheel(wheel, "2.0.0", "a" * 64)


if __name__ == "__main__":
    unittest.main()
