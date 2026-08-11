from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_repository", ROOT / "tools" / "build_repository.py")
BUILD_REPOSITORY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BUILD_REPOSITORY)


class RepositoryTests(unittest.TestCase):
    def test_build_is_reproducible_and_catalog_hashes_match(self) -> None:
        generated = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            BUILD_REPOSITORY.build(ROOT, pathlib.Path(first), 7, "https://example.test/addons", generated)
            BUILD_REPOSITORY.build(ROOT, pathlib.Path(second), 7, "https://example.test/addons", generated)
            first_index = pathlib.Path(first, "index-v1.json").read_bytes()
            self.assertEqual(first_index, pathlib.Path(second, "index-v1.json").read_bytes())
            index = json.loads(first_index)
            self.assertEqual(index["repository_id"], "org.ersatzrs.addons.official")
            self.assertEqual(len(index["addons"]), 2)
            for addon in index["addons"]:
                self.assertEqual(addon["dependencies"], [])
                package = addon["packages"]["any"]
                filename = package["url"].rsplit("/", 1)[1]
                contents = pathlib.Path(first, "packages", filename).read_bytes()
                self.assertEqual(hashlib.sha256(contents).hexdigest(), package["sha256"])
                self.assertEqual(len(contents), package["size"])
                with zipfile.ZipFile(pathlib.Path(first, "packages", filename)) as archive:
                    self.assertIn("addon.toml", archive.namelist())

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_readiness_contracts_emit_one_json_object(self) -> None:
        for addon_id, extra in [
            ("org.ersatzrs.addon.beeldengeluid", {"ERSATZRS_ADDON_SETTING_CURL_BIN": "/bin/true"}),
            ("org.ersatzrs.addon.yt-dlp", {"ERSATZRS_ADDON_SETTING_YT_DLP_BIN": "/bin/true"}),
        ]:
            environment = {"PATH": "/usr/bin:/bin", "FFMPEG_BIN": "/bin/true", **extra}
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / addon_id / "addon.sh"), "check"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
