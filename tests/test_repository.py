from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class RepositoryTests(unittest.TestCase):
    def final_operation_error(self, result: subprocess.CompletedProcess[str]) -> dict[str, str]:
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr.splitlines()[-1])
        self.assertEqual(set(payload), {"code", "message"})
        self.assertTrue(payload["code"])
        self.assertTrue(payload["message"])
        return payload

    def run_posix_beeldengeluid_list(
        self,
        playlist_url: str,
        list_page: str,
        media_list_contract: bool = False,
        episode_page: str | None = None,
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
            default_episode_page = (
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
                r'\"broadcasters\":[{\"name\":\"Current TV\"}],\"url\":\"fixture\"</script>'
            )
            (fixtures / "episode.html").write_text(
                episode_page if episode_page is not None else default_episode_page,
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
    */aflevering/102) exit 22 ;;
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

    def test_beeldengeluid_has_minimal_runtime_configuration(self) -> None:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid"
        manifest = tomllib.loads(
            (addon_root / "addon.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [setting["key"] for setting in manifest["settings"]],
            ["MEDIA_STORAGE_PATH", "CURL_BIN"],
        )
        self.assertEqual(
            manifest["media_list_storage"],
            {
                "path_setting": "MEDIA_STORAGE_PATH",
                "default_subdirectory": "beeldengeluid_media",
                "source_name": "beeldengeluid",
            },
        )
        self.assertFalse(
            {"python", "python3"} & set(manifest["permissions"]["external_commands"])
        )
        for relative_path in [
            "addon.sh",
            "addon.bat",
            "libexec/beeldengeluid.sh",
            "libexec/beeldengeluid.bat",
        ]:
            contents = (addon_root / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("ERSATZRS_ADDON_SETTING_ACTION_ID", contents)
            self.assertNotIn("BEELDENGELUID_ACTION_ID", contents)

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
    def test_posix_operations_emit_structured_final_stderr_lines(self) -> None:
        for addon_id, extra in [
            ("org.ersatzrs.addon.beeldengeluid", {"ERSATZRS_ADDON_SETTING_CURL_BIN": "/bin/true"}),
            ("org.ersatzrs.addon.yt-dlp", {"ERSATZRS_ADDON_SETTING_YT_DLP_BIN": "/bin/true"}),
        ]:
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / addon_id / "addon.sh"), "list"],
                check=False,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "FFMPEG_BIN": "/bin/true", **extra},
            )
            self.assertEqual(self.final_operation_error(result)["code"], "missing-setting")

        with tempfile.TemporaryDirectory() as temporary:
            fake = pathlib.Path(temporary) / "yt-dlp"
            fake.write_text("#!/bin/sh\necho provider prose >&2\nexit 23\n", encoding="utf-8")
            fake.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "list"],
                check=False,
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin",
                    "FFMPEG_BIN": "/bin/true",
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "ERSATZRS_MEDIA_LIST_URL": "https://video.example/playlist",
                },
            )
        self.assertEqual(self.final_operation_error(result)["code"], "provider-unreachable")

    def test_windows_entrypoints_declare_structured_operation_codes(self) -> None:
        for addon_id in [
            "org.ersatzrs.addon.beeldengeluid",
            "org.ersatzrs.addon.yt-dlp",
        ]:
            source = (ROOT / "addons" / addon_id / "addon.bat").read_text(encoding="utf-8")
            for code in ["missing-setting", "provider-unreachable", "operation-failed"]:
                self.assertIn(code, source)

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_names_a_shared_list_after_the_list_itself(self) -> None:
        shared_page = (
            r'<script>\"title\":\"Teleac \u0026 Friends\",\"description\":\"Gedeelde lijst\",'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/first/aflevering/101\",\"isPlayable\":true</script>'
        )
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd",
            shared_page,
            media_list_contract=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["record_type"], "list")
        self.assertEqual(rows[0]["name"], "Teleac & Friends")
        self.assertEqual(
            rows[0]["provider_id"], "lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd"
        )

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
        self.assertEqual([row["id"] for row in rows], ["101", "102", "103"])
        self.assertEqual(rows[0]["plot"], "Fixture plot")
        self.assertEqual(rows[0]["duration_seconds"], 120)
        self.assertEqual(rows[0]["genres"], ["Education"])
        self.assertEqual(rows[0]["tags"], ["Drawing"])
        self.assertEqual(rows[0]["collection"], "Fixture Collection")
        self.assertEqual(rows[0]["people"], [{"name": "Presenter One", "role": "presenter"}])
        self.assertEqual(rows[0]["producers"], ["Fixture Producer"])
        self.assertEqual(rows[0]["original_broadcasters"], ["Original TV"])
        self.assertEqual(rows[0]["broadcasters"], ["Current TV"])
        self.assertEqual(rows[0]["availability"], "available")
        self.assertEqual(rows[0]["content_kind"], "television_episode")
        self.assertEqual(rows[0]["provider_id"], "episode:101")
        self.assertEqual(rows[0]["guids"], ["beeldengeluid://101"])
        self.assertEqual(rows[1]["title"], "missing")
        self.assertEqual(rows[1]["availability"], "unavailable")
        self.assertEqual(rows[1]["availability_reason"], "not_playable")
        self.assertEqual(rows[1]["content_kind"], "auto")
        self.assertEqual(
            result.stderr,
            "beeldengeluid.sh: retained 1 unavailable Schatkamer shared-list item(s)\n",
        )

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_classifies_provider_metadata(self) -> None:
        cases = [
            ("Education", "television_episode"),
            ("Music concert", "music_video"),
            ("Speelfilm", "movie"),
            ("Reclame", "other_video"),
        ]
        for genre, expected in cases:
            with self.subTest(genre=genre):
                episode_page = (
                    '<h1>Fixture Series</h1><h3>Fixture Episode</h3>'
                    '<script>\\"description\\":\\"Fixture plot\\",\\"disclaimer\\":null,'
                    f'\\"genres\\":[\\"{genre}\\"],'
                    r'\"subjects\":[],\"collection\":null,\"url\":\"fixture\"</script>'
                )
                result = self.run_posix_beeldengeluid_list(
                    "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
                    "",
                    episode_page=episode_page,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertTrue(rows)
                self.assertTrue(all(row["content_kind"] == expected for row in rows))

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_rejects_unavailable_and_invalid_shared_lists(self) -> None:
        private = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd",
            "<html>Sign in required</html>",
        )
        self.assertNotEqual(private.returncode, 0)
        self.assertIn("unavailable or private", private.stderr)
        self.assertEqual(self.final_operation_error(private)["code"], "provider-unreachable")

        invalid = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/not-a-uuid",
            "",
        )
        self.assertEqual(invalid.returncode, 64)
        self.assertIn("must be a UUID", invalid.stderr)
        self.assertEqual(self.final_operation_error(invalid)["code"], "provider-unreachable")

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
        self.assertEqual(rows[0]["name"], "Beeld & Geluid Schatkamer")
        self.assertEqual([row["provider_id"] for row in rows[1:]], ["episode:201", "episode:203"])
        self.assertEqual([row["rank"] for row in rows[1:]], [0, 1])
        self.assertEqual([row["year"] for row in rows[1:]], [1993, 1993])
        self.assertTrue(all(row["kind"] == "remote_stream" for row in rows[1:]))
        self.assertTrue(all(row["source_url"].startswith("https://") for row in rows[1:]))

    def test_yt_dlp_declares_file_backed_list_storage(self) -> None:
        manifest = tomllib.loads(
            (
                ROOT
                / "addons"
                / "org.ersatzrs.addon.yt-dlp"
                / "addon.toml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertTrue(
            {
                "media-list.list.v1",
                "media-list.list.v2",
                "remote-stream.list.v1",
                "remote-stream.list.v2",
                "remote-stream.play.v1",
            }
            <= {item["id"] for item in manifest["capabilities"]}
        )
        self.assertEqual(
            manifest["media_list_storage"],
            {
                "path_setting": "MEDIA_STORAGE_PATH",
                "default_subdirectory": "yt-dlp_media",
                "source_name": "yt-dlp",
            },
        )

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_yt_dlp_projects_playlist_as_remote_stream_records(self) -> None:
        addon = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"
        with tempfile.TemporaryDirectory() as temporary:
            fake = pathlib.Path(temporary) / "yt-dlp"
            arguments = pathlib.Path(temporary) / "arguments.txt"
            fake.write_text(
                """#!/bin/sh
printf '%s\n' "$@" > "$FAKE_ARGUMENTS"
printf '%s\n' '{"record_type":"item","provider_id":"video-1","rank":1,"display_title":"Fixture","title":"Fixture","kind":"remote_stream","guids":[],"source_url":"https://video.example/watch?v=1"}'
""",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(addon), "list"],
                check=False,
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin",
                    "FFMPEG_BIN": "/bin/true",
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "ERSATZRS_MEDIA_LIST_URL": "https://video.example/playlist?id=fixture",
                    "FAKE_ARGUMENTS": str(arguments),
                },
            )
            yt_dlp_arguments = arguments.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["record_type"], "list")
        self.assertEqual(rows[1]["kind"], "remote_stream")
        self.assertEqual(rows[1]["source_url"], "https://video.example/watch?v=1")

        source = addon.read_text(encoding="utf-8")
        windows_source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.yt-dlp"
            / "libexec"
            / "youtube-list.ps1"
        ).read_text(encoding="utf-8")
        for token in ["other_video", "music_video", "movie", "television_episode", "auto"]:
            self.assertIn(token, source)
            self.assertIn(token, windows_source)
        for keyword in ["reclame", "muziek", "speelfilm"]:
            self.assertIn(keyword, source)
            self.assertIn(keyword, windows_source)
        self.assertIn("webpage_url,original_url,url", source)
        self.assertIn("--output-na-placeholder null", source)
        self.assertIn("AvailabilityReason", windows_source)
        self.assertEqual(
            windows_source.count("Where-Object { $null -ne $_ }"),
            2,
        )
        self.assertIn("genres = $genres", windows_source)
        self.assertIn("tags = $tags", windows_source)
        self.assertIn("%(ersatzrs_availability)j", yt_dlp_arguments)
        self.assertNotIn("%(availability)j", yt_dlp_arguments)

    def test_yt_dlp_normalizes_provider_availability_on_both_platforms(self) -> None:
        source = (
            ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"
        ).read_text(encoding="utf-8")
        windows_source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.yt-dlp"
            / "libexec"
            / "youtube-list.ps1"
        ).read_text(encoding="utf-8")
        fixtures = [
            ("public", "available"),
            ("unlisted", "available"),
            ("private", "unavailable"),
            ("premium_only", "unavailable"),
            ("subscriber_only", "unavailable"),
            ("needs_auth", "unavailable"),
            (None, "unknown"),
            ("future_provider_value", "unknown"),
        ]

        for provider_token, canonical_token in fixtures:
            with self.subTest(provider_token=provider_token):
                if provider_token not in (None, "future_provider_value"):
                    self.assertIn(provider_token, source)
                    self.assertIn(provider_token, windows_source)
                self.assertIn(canonical_token, source)
                self.assertIn(f"return '{canonical_token}'", windows_source)

        self.assertIn("%(availability|unknown)s", source)
        self.assertIn("^(?!(available|unavailable|unknown)$).*$", source)
        self.assertIn("return 'unknown'", windows_source)
        self.assertIn('\"availability\":%(ersatzrs_availability)j', source)
        self.assertNotIn('\"availability\":%(availability)j', source)
        self.assertIn('ersatzrs_unavailable&\"not_playable\"|null', source)
        self.assertIn("AvailabilityReason", windows_source)

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
        self.assertIn("$sharedListName", source)
        self.assertIn("name = $listName", source)
        self.assertIn("isPlayable", source)
        self.assertIn("$seen.Add($path)", source)
        self.assertIn("retained {0} unavailable Schatkamer shared-list item(s)", source)
        self.assertIn("availability_reason = 'not_playable'", source)
        self.assertIn("content_kind = 'auto'", source)
        self.assertIn("$slug", source)


if __name__ == "__main__":
    unittest.main()
