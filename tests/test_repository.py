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
    def write_native_artifacts(self, root: pathlib.Path) -> None:
        manifest = BUILD_REPOSITORY.tomllib.loads(
            (ROOT / "addons" / "org.ersatzrs.addon.trakt" / "addon.toml").read_text(
                encoding="utf-8"
            )
        )
        for entrypoint in manifest["entrypoints"].values():
            destination = root / manifest["id"] / entrypoint["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"fixture native executable")

    def run_posix_beeldengeluid_list(
        self,
        playlist_url: str,
        list_page: str,
        media_list_contract: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        addon = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid" / "addon.sh"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            (fixtures / "list.html").write_text(list_page, encoding="utf-8")
            (fixtures / "series.html").write_text(
                '<a href="/serie/20/fixture/aflevering/201"></a>'
                '<a href="/serie/20/fixture/aflevering/203"></a>',
                encoding="utf-8",
            )
            (fixtures / "empty.html").write_text("<html></html>", encoding="utf-8")
            (fixtures / "episode.html").write_text(
                '<h1>Fixture Series</h1><h3>Fixture Episode</h3>'
                '<a href="/zoeken?collectie=fixture">Fixture Collection</a>'
                r'<script>\"description\":\"Fixture plot\",\"disclaimer\":null,'
                r'\"durationNumber\":120,\"publishedAtISO\":\"1993-01-24T12:30:00Z\",'
                r'\"ageRating\":\"Alle leeftijden\",\"genres\":[\"Education\"],'
                r'\"subjects\":[\"Drawing\"],\"collection\":\"Fixture Collection\",'
                r'\"presenters\":[{\"name\":\"Presenter One\"}],\"actors\":[],'
                r'\"guests\":[],\"directors\":[],\"performers\":[],\"others\":[],'
                r'\"productionCompanies\":[\"Fixture Producer\"],\"genres\":[\"Education\"],'
                r'\"originalBroadcasters\":[{\"name\":\"Original TV\"}],\"broadcaster\":null,'
                r'\"broadcasters\":[{\"name\":\"Current TV\"}],\"url\":\"fixture\"</script>',
                encoding="utf-8",
            )
            fake_curl = fixtures / "curl"
            fake_curl.write_text(
                """#!/bin/sh
set -eu
output=
url=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) shift; output=$1 ;;
        http://*|https://*) url=$1 ;;
    esac
    shift
done
case "$url" in
    */lijst/*) source_file=$FAKE_FIXTURES/list.html ;;
    *'pagina=1') source_file=$FAKE_FIXTURES/series.html ;;
    *'pagina='*) source_file=$FAKE_FIXTURES/empty.html ;;
    */aflevering/*) source_file=$FAKE_FIXTURES/episode.html ;;
    *) exit 22 ;;
esac
cp "$source_file" "$output"
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            environment = {
                "PATH": "/usr/bin:/bin",
                "FFMPEG_BIN": "/bin/true",
                "ERSATZRS_ADDON_SETTING_CURL_BIN": str(fake_curl),
                "FAKE_FIXTURES": str(fixtures),
            }
            environment[
                "ERSATZRS_MEDIA_LIST_URL"
                if media_list_contract
                else "ERSATZRS_REMOTE_STREAM_PLAYLIST_URL"
            ] = playlist_url
            return subprocess.run(
                ["/bin/sh", str(addon), "list"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

    def test_build_is_reproducible_and_catalog_hashes_match(self) -> None:
        generated = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
            tempfile.TemporaryDirectory() as artifacts,
        ):
            artifact_root = pathlib.Path(artifacts)
            self.write_native_artifacts(artifact_root)
            BUILD_REPOSITORY.build(
                ROOT, pathlib.Path(first), 7, "https://example.test/addons", generated, artifact_root
            )
            BUILD_REPOSITORY.build(
                ROOT, pathlib.Path(second), 7, "https://example.test/addons", generated, artifact_root
            )
            first_index = pathlib.Path(first, "index-v1.json").read_bytes()
            self.assertEqual(first_index, pathlib.Path(second, "index-v1.json").read_bytes())
            index = json.loads(first_index)
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(index["repository_id"], "org.ersatzrs.addons.official")
            self.assertEqual(len(index["addons"]), 3)
            for addon in index["addons"]:
                self.assertEqual(addon["license"], "Zlib")
                if addon["id"] != "org.ersatzrs.addon.trakt":
                    self.assertIn("stream", addon["summary"]["en-US"].lower())
                self.assertEqual(addon["dependencies"], [])
                if "icon" in addon:
                    icon = addon["icon"]
                    icon_filename = icon["url"].rsplit("/", 1)[1]
                    icon_contents = pathlib.Path(first, "icons", icon_filename).read_bytes()
                    self.assertEqual(hashlib.sha256(icon_contents).hexdigest(), icon["sha256"])
                    self.assertEqual(len(icon_contents), icon["size"])
                    self.assertEqual(icon["media_type"], "png")
                for rid, package in addon["packages"].items():
                    filename = package["url"].rsplit("/", 1)[1]
                    contents = pathlib.Path(first, "packages", filename).read_bytes()
                    self.assertEqual(hashlib.sha256(contents).hexdigest(), package["sha256"])
                    self.assertEqual(len(contents), package["size"])
                    with zipfile.ZipFile(pathlib.Path(first, "packages", filename)) as archive:
                        self.assertIn("addon.toml", archive.namelist())
                        if "icon" in addon:
                            self.assertIn("icon.png", archive.namelist())
                        self.assertEqual(archive.read("LICENSE"), (ROOT / "LICENSE").read_bytes())
                        batch_files = [name for name in archive.namelist() if name.endswith(".bat")]
                        for batch_file in batch_files:
                            batch_contents = archive.read(batch_file)
                            self.assertNotIn(b"\n", batch_contents.replace(b"\r\n", b""))
                        if addon["id"] == "org.ersatzrs.addon.trakt":
                            executable = "ersatzrs-trakt-addon.exe" if rid == "win-x64" else "ersatzrs-trakt-addon"
                            self.assertIn(f"bin/{rid}/{executable}", archive.namelist())
                            self.assertNotIn("trakt.py", archive.namelist())

            trakt = next(
                addon for addon in index["addons"] if addon["id"] == "org.ersatzrs.addon.trakt"
            )
            self.assertIn("media-list.list.v1", trakt["capabilities"])
            self.assertEqual(set(trakt["packages"]), BUILD_REPOSITORY.SUPPORTED_RIDS - {"any"})
            self.assertEqual(trakt["permissions"]["external_commands"], [])

            beeldengeluid = next(
                addon
                for addon in index["addons"]
                if addon["id"] == "org.ersatzrs.addon.beeldengeluid"
            )
            self.assertNotIn("python", beeldengeluid["permissions"]["external_commands"])
            self.assertNotIn("python3", beeldengeluid["permissions"]["external_commands"])
            for package in beeldengeluid["packages"].values():
                filename = package["url"].rsplit("/", 1)[1]
                with zipfile.ZipFile(pathlib.Path(first, "packages", filename)) as archive:
                    self.assertNotIn("libexec/beeldengeluid-media-list.py", archive.namelist())

    def test_beeldengeluid_manifest_has_no_python_runtime(self) -> None:
        manifest = BUILD_REPOSITORY.tomllib.loads(
            (
                ROOT
                / "addons"
                / "org.ersatzrs.addon.beeldengeluid"
                / "addon.toml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [setting["key"] for setting in manifest["settings"]],
            ["CURL_BIN", "ACTION_ID"],
        )
        self.assertFalse(
            {"python", "python3"} & set(manifest["permissions"]["external_commands"])
        )

    def test_trakt_manifest_suggests_only_a_secret_reference_name(self) -> None:
        manifest = BUILD_REPOSITORY.tomllib.loads(
            (ROOT / "addons" / "org.ersatzrs.addon.trakt" / "addon.toml").read_text(
                encoding="utf-8"
            )
        )
        client_id = next(setting for setting in manifest["settings"] if setting["key"] == "CLIENT_ID")
        self.assertEqual([setting["key"] for setting in manifest["settings"]], ["CLIENT_ID"])
        self.assertTrue(
            all(entrypoint["kind"] == "native" for entrypoint in manifest["entrypoints"].values())
        )
        self.assertEqual(client_id["kind"], "secret_reference")
        self.assertNotIn("default", client_id)
        self.assertEqual(
            client_id["suggested_reference"],
            {"kind": "environment", "reference": "TRAKT__CLIENTID"},
        )

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_readiness_contracts_emit_one_json_object(self) -> None:
        for addon_id, extra in [
            (
                "org.ersatzrs.addon.beeldengeluid",
                {"ERSATZRS_ADDON_SETTING_CURL_BIN": "/bin/true"},
            ),
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

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_enumerates_public_shared_list_in_order(self) -> None:
        shared_page = (
            r'<script>\"description\":\"Gedeelde lijst\",'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/first/aflevering/101\",\"isPlayable\":true,'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/missing/aflevering/102\",\"isPlayable\":false,'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/first/aflevering/101\",\"isPlayable\":true,'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/11/last/aflevering/103\",\"isPlayable\":true</script>'
        )
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd",
            shared_page,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["id"] for row in rows], ["101", "103"])
        self.assertEqual(rows[0]["plot"], "Fixture plot")
        self.assertEqual(rows[0]["duration_seconds"], 120)
        self.assertEqual(rows[0]["genres"], ["Education"])
        self.assertEqual(rows[0]["tags"], ["Drawing"])
        self.assertEqual(rows[0]["collection"], "Fixture Collection")
        self.assertEqual(rows[0]["people"], [{"name": "Presenter One", "role": "presenter"}])
        self.assertEqual(rows[0]["producers"], ["Fixture Producer"])
        self.assertEqual(rows[0]["original_broadcasters"], ["Original TV"])
        self.assertEqual(rows[0]["broadcasters"], ["Current TV"])
        self.assertEqual(
            result.stderr,
            "beeldengeluid.sh: skipped 1 unavailable Schatkamer shared-list item(s)\n",
        )

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_rejects_unavailable_and_invalid_shared_lists(self) -> None:
        private = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd",
            "<html>Sign in required</html>",
        )
        self.assertNotEqual(private.returncode, 0)
        self.assertIn("unavailable or private", private.stderr)

        invalid = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/not-a-uuid",
            "",
        )
        self.assertEqual(invalid.returncode, 64)
        self.assertIn("must be a UUID", invalid.stderr)

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_retains_series_enumeration(self) -> None:
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
            "",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["id"] for row in rows], ["201", "203"])

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_accepts_saved_search_links(self) -> None:
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/zoeken?collectie=fixture",
            "",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["id"] for row in rows], ["201", "203"])

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_projects_links_as_media_list_records(self) -> None:
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
            "",
            media_list_contract=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["record_type"], "list")
        self.assertEqual(rows[0]["provider_id"], "serie/20/fixture")
        self.assertEqual([row["provider_id"] for row in rows[1:]], ["episode:201", "episode:203"])
        self.assertEqual([row["rank"] for row in rows[1:]], [0, 1])
        self.assertEqual([row["year"] for row in rows[1:]], [1993, 1993])
        self.assertTrue(all(row["kind"] == "episode" for row in rows[1:]))

    def test_windows_beeldengeluid_declares_shared_list_contract(self) -> None:
        entrypoint_batch_source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "addon.bat"
        ).read_text(encoding="utf-8")
        batch_source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "libexec"
            / "beeldengeluid.bat"
        ).read_text(encoding="utf-8")
        source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "libexec"
            / "beeldengeluid-list.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('set "BEELDENGELUID_OUTPUT=media-list"', entrypoint_batch_source)
        self.assertIn('beeldengeluid-list.ps1"', batch_source)
        self.assertIn("$isSharedList", source)
        self.assertIn("$mediaListMode", source)
        self.assertIn("record_type = 'list'", source)
        self.assertIn("record_type = 'item'", source)
        self.assertIn("Gedeelde lijst", source)
        self.assertIn("isPlayable", source)
        self.assertIn("$seen.Add($path)", source)
        self.assertIn("skipped {0} unavailable Schatkamer shared-list item(s)", source)


if __name__ == "__main__":
    unittest.main()
