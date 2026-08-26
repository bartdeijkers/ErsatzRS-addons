from __future__ import annotations

import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 in the pinned Linux validation image.
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]

YT_DLP_LIVE_URL = "https://www.youtube.com/watch?v=mhJRzQsLZGg"
YT_DLP_FINITE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT_DLP_PLAYLIST_URL = (
    "https://www.youtube.com/playlist?list=PLJ_TJFLc25JRdChhr9sp00ajl7FAeKDx-"
)
BEELDENGELUID_LIST_URL = (
    "https://schatkamer.beeldengeluid.nl/lijst/"
    "14df8d33-ce8a-4680-a83b-0cc2a9c58bcd"
)
BEELDENGELUID_SEARCH_URL = (
    "https://schatkamer.beeldengeluid.nl/zoeken?q=reclame&startdatum=01-01-1995"
    "&einddatum=01-03-1995"
)
BEELDENGELUID_SERIES_URL = (
    "https://schatkamer.beeldengeluid.nl/serie/2101608030022669331/"
    "de-fascinaties-van-boudewijn-buch"
)
BEELDENGELUID_EPISODE_URL = (
    "https://schatkamer.beeldengeluid.nl/serie/2101608030021828731/"
    "ster-reclame/aflevering/2101608040033953431"
)

class RepositoryTests(unittest.TestCase):
    def final_operation_error(self, result: subprocess.CompletedProcess[str]) -> dict[str, str]:
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr.splitlines()[-1])
        self.assertEqual(set(payload), {"code", "message"})
        self.assertTrue(payload["code"])
        self.assertTrue(payload["message"])
        return payload

    def beeldengeluid_strip_overview(self) -> tuple[str, list[str]]:
        episode_ids = [
            "2101608050040897825",
            "2101608050040897826",
            "2101608050040897827",
            "2101608050040897828",
            "2101608050040897829",
            "2101608050040897830",
            "2101608050040897831",
            "2101608050040897832",
        ]
        cards = []
        embedded = []
        for rank, episode_id in enumerate(episode_ids):
            path = (
                "/serie/2101608030022428031/strip-en-cartoontekenen/aflevering/"
                + episode_id
            )
            cards.append(
                f'<li><a data-gtm-interaction-text="Les {rank + 1}" href="{path}">'
                f'<img src="https://schatkamer.beeldengeluid.nl/assets/card-{rank + 1}.jpg">'
                f'<h3>Les {rank + 1}</h3></a><p>Korte beschrijving {rank + 1}</p></li>'
            )
            release_date = "1993-03-07" if rank == 6 else f"1993-02-{rank + 1:02d}"
            provider_title = (
                "Les 7: Cartoon, strook en paginaverhaal"
                if rank == 6
                else f"Strip- en cartoontekenen - Aflevering {rank + 1}"
            )
            embedded.append(
                {
                    "url": "https://schatkamer.beeldengeluid.nl" + path,
                    "isPlayable": rank != 6,
                    "title": provider_title,
                    "description": f"Uitgebreide providerbeschrijving voor les {rank + 1}.",
                    "publishedAtISO": release_date + "T12:00:00Z",
                    "image": (
                        "https://schatkamer.beeldengeluid.nl/assets/"
                        f"provider-{rank + 1}.jpg"
                    ),
                }
            )
        return "".join(cards) + f"<script>{json.dumps(embedded)}</script>", episode_ids

    def run_resumable_beeldengeluid_discover(
        self, source_url: str, overview: str
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            fixture = fixtures / "overview.html"
            fixture.write_text(overview, encoding="utf-8")
            calls = fixtures / "calls.txt"
            if os.name == "nt":
                project = fixtures / "FakeCurl.csproj"
                project.write_text(
                    '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
                    '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
                    '</PropertyGroup></Project>',
                    encoding="utf-8",
                )
                (fixtures / "Program.cs").write_text(
                    'var calls = Environment.GetEnvironmentVariable("FAKE_CALLS")!;\n'
                    'var fixture = Environment.GetEnvironmentVariable("FAKE_FIXTURE")!;\n'
                    'File.AppendAllText(calls, string.Join(" ", args) + Environment.NewLine);\n'
                    'Console.WriteLine(File.ReadAllText(fixture));\n'
                    'Console.WriteLine("__ERSATZRS_HTTP_STATUS__:200");\n',
                    encoding="utf-8",
                )
                output = fixtures / "fake-curl-bin"
                compiled = subprocess.run(
                    [
                        shutil.which("dotnet") or "dotnet",
                        "build",
                        str(project),
                        "--nologo",
                        "--configuration",
                        "Release",
                        "--output",
                        str(output),
                        "-p:RestoreIgnoreFailedSources=true",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "DOTNET_CLI_HOME": str(fixtures),
                        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                    },
                )
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                fake = output / "FakeCurl.exe"
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    str(addon_root / "addon.bat"),
                ]
            else:
                fake = fixtures / "fake-curl"
                fake.write_text(
                    '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CALLS"\n'
                    'cat "$FAKE_FIXTURE"\nprintf \'\\n__ERSATZRS_HTTP_STATUS__:200\'\n',
                    encoding="utf-8",
                )
                fake.chmod(0o755)
                command = ["/bin/sh", str(addon_root / "addon.sh")]
            environment = os.environ.copy()
            environment.update(
                {
                    "CURL_BIN": str(fake),
                    "ERSATZRS_ADDON_SETTING_CURL_BIN": str(fake),
                    "FAKE_CALLS": str(calls),
                    "FAKE_FIXTURE": str(fixture),
                }
            )
            request = {
                "source_url": source_url,
                "record_capability": "media-list.list.v5",
                "limits": {"max_items": 250, "max_output_bytes": 4_194_304},
            }
            result = subprocess.run(
                [*command, "discover"],
                input=json.dumps(request),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            return result, calls.read_text(encoding="utf-8").splitlines()

    def run_posix_beeldengeluid_list(
        self,
        playlist_url: str,
        list_page: str,
        media_list_contract: bool = False,
        episode_page: str | None = None,
        list_page_2: str = "<html></html>",
        series_page: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        addon = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid" / "addon.sh"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            (fixtures / "list.html").write_text(list_page, encoding="utf-8")
            (fixtures / "list-2.html").write_text(list_page_2, encoding="utf-8")
            (fixtures / "series.html").write_text(
                series_page
                if series_page is not None
                else (
                    '<a href="/serie/20/fixture/aflevering/201"></a>'
                    '<a href="/serie/20/fixture/aflevering/203"></a>'
                ),
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
    */lijst/*'pagina=1'*) source_file=$FAKE_FIXTURES/list.html ;;
    */lijst/*'pagina=2'*) source_file=$FAKE_FIXTURES/list-2.html ;;
    */lijst/*'pagina='*) source_file=$FAKE_FIXTURES/empty.html ;;
    *'pagina=1'*) source_file=$FAKE_FIXTURES/series.html ;;
    *'pagina='*) source_file=$FAKE_FIXTURES/empty.html ;;
    */aflevering/102) exit 22 ;;
    */aflevering/2101608050040897831)
        printf 'unexpected-detail-request: %s\n' "$url" >&2
        exit 22
        ;;
    */aflevering/*) source_file=$FAKE_FIXTURES/episode.html ;;
    *) exit 22 ;;
esac
printf 'fake-curl-url: %s\n' "$url" >&2
cp "$source_file" "$output"
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            deno = shutil.which("deno") or shutil.which("deno.exe")
            runtime = fixtures / "deno"
            runtime.write_text(
                "#!/bin/sh\nexec " + shlex.quote(deno or "deno") + ' "$@"\n',
                encoding="utf-8",
            )
            runtime.chmod(0o755)
            environment = {
                "PATH": f"{fixtures}:/usr/bin:/bin",
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

    def run_windows_beeldengeluid_media_list(
        self,
        playlist_url: str = "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
        series_page: str | None = None,
        list_page: str = "<html></html>",
        episode_page: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        addon = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid" / "addon.bat"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            default_series_page = (
                '<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"CreativeWorkSeries",'
                '"name":"Fixture Programme","description":"Fixture introduction",'
                '"image":"https://schatkamer.beeldengeluid.nl/assets/programme.jpg"}'
                '</script><a href="/serie/20/fixture/aflevering/201">'
                '<img src="https://schatkamer.beeldengeluid.nl/image-optimizer?'
                'url=aHR0cHM6Ly9zay12aWRlby5jZG4uYmVlbGRlbmdlbHVpZC5ubC9maXh0dXJlL3N0aWxsLmpwZw'
                '&amp;width=640&amp;quality=80&amp;format=webp"></a>'
            )
            (fixtures / "series.html").write_text(
                series_page if series_page is not None else default_series_page,
                encoding="utf-8",
            )
            (fixtures / "list.html").write_text(list_page, encoding="utf-8")
            (fixtures / "empty.html").write_text("<html></html>", encoding="utf-8")
            default_episode_page = (
                '<h1>Fixture Programme</h1><h3>First Episode</h3>'
                '<script>{"image":"https://schatkamer.beeldengeluid.nl/assets/episode.jpg"};'
                r'\"program\":{\"id\":\"__EPISODE_ID__\",'
                r'\"description\":\"Fixture plot\",\"disclaimer\":null,'
                r'\"durationNumber\":120,\"publishedAtISO\":\"1993-01-24T12:30:00Z\",'
                r'\"ageRating\":\"Alle leeftijden\",\"genres\":[\"Education\"],'
                r'\"subjects\":[\"Drawing\"],\"collection\":\"Fixture Collection\",'
                r'\"presenters\":[{\"name\":\"Presenter One\"}],\"actors\":[],'
                r'\"guests\":[],\"directors\":[],\"performers\":[],\"others\":[],'
                r'\"productionCompanies\":[\"Fixture Producer\"],'
                r'\"genres\":[\"Education\"],'
                r'\"originalBroadcasters\":[{\"name\":\"Original TV\"}],'
                r'\"broadcaster\":null,\"broadcasters\":[{\"name\":\"Current TV\"}],'
                r'\"url\":\"fixture\"</script>'
            )
            (fixtures / "episode.html").write_text(
                episode_page if episode_page is not None else default_episode_page,
                encoding="utf-8",
            )
            fake_curl = fixtures / "fake-curl.ps1"
            fake_curl.write_text(
                r"""$ErrorActionPreference = 'Stop'
$output = $null
$url = $null
for ($index = 0; $index -lt $args.Count; $index++) {
    $argument = [string]$args[$index]
    if ($argument -eq '--output') {
        $index++
        $output = [string]$args[$index]
    } elseif ($argument -match '^https?://') {
        $url = $argument
    }
}
if (-not $output -or -not $url) { exit 22 }
if ($url -match '/aflevering/(\d+)$') {
    if ($Matches[1] -eq '2101608050040897831') {
        [Console]::Error.WriteLine("unexpected-detail-request: $url")
        exit 22
    }
    $content = [IO.File]::ReadAllText((Join-Path $env:FAKE_FIXTURES 'episode.html'))
    [IO.File]::WriteAllText($output, $content.Replace('__EPISODE_ID__', $Matches[1]))
    [Console]::Error.WriteLine("fake-curl-url: $url")
    exit 0
} elseif ($url -like '*pagina=1*') {
    $source = if ($url -like '*/lijst/*') { 'list.html' } else { 'series.html' }
} elseif ($url -like '*pagina=*') {
    $source = 'empty.html'
} else {
    Write-Error "Unexpected fixture URL: $url"
    exit 22
}
[Console]::Error.WriteLine("fake-curl-url: $url")
Copy-Item -LiteralPath (Join-Path $env:FAKE_FIXTURES $source) -Destination $output
exit 0
""",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "ERSATZRS_ADDON_SETTING_CURL_BIN": str(fake_curl),
                    "ERSATZRS_MEDIA_LIST_URL": playlist_url,
                    "FAKE_FIXTURES": str(fixtures),
                    "TEMP": str(fixtures),
                    "TMP": str(fixtures),
                }
            )
            return subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(addon), "list"],
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
        self.assertIn("deno", manifest["permissions"]["external_commands"])
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
        with tempfile.TemporaryDirectory() as temporary:
            # yt-dlp resolves its JavaScript runtime from PATH, so a ready
            # result depends on one being discoverable.
            runtime = pathlib.Path(temporary) / "deno"
            runtime.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runtime.chmod(0o755)
            for addon_id, extra in [
                (
                    "org.ersatzrs.addon.beeldengeluid",
                    {"ERSATZRS_ADDON_SETTING_CURL_BIN": "/bin/true"},
                ),
                ("org.ersatzrs.addon.yt-dlp", {"ERSATZRS_ADDON_SETTING_YT_DLP_BIN": "/bin/true"}),
            ]:
                environment = {
                    "PATH": f"{temporary}:/usr/bin:/bin",
                    "FFMPEG_BIN": "/bin/true",
                    **extra,
                }
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
    def test_posix_yt_dlp_readiness_requires_a_javascript_runtime(self) -> None:
        # An empty PATH guarantees the runtime is absent regardless of what the
        # host machine happens to have installed.
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "check"],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": temporary,
                    "FFMPEG_BIN": "/bin/true",
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": "/bin/true",
                },
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["code"], "missing-js-runtime")
        self.assertEqual(result.stderr, "")

    @unittest.skipUnless(
        pathlib.Path("/bin/sh").exists() and shutil.which("deno"),
        "POSIX shell and deno required",
    )
    def test_posix_yt_dlp_media_list_mode_emits_only_media_list_records(self) -> None:
        # Regression: the media-list branch used to fall through into the
        # Remote Stream branch, so one invocation emitted two incompatible
        # record shapes and enumerated the provider twice.
        with tempfile.TemporaryDirectory() as temporary:
            calls = pathlib.Path(temporary) / "calls"
            playlist = (
                '{"title":"Fixture playlist","entries":[{'
                '"id":"video-1","title":"One",'
                '"webpage_url":"https://video.example/watch?v=1",'
                '"availability":"public"}]}'
            )
            definition = (
                '{"id":"video-1","provider_id":"video-1",'
                '"url":"https://video.example/watch?v=1","title":"One","is_live":false}'
            )
            # Stand in for full yt-dlp JSON on the first invocation and the
            # Remote Stream shape on any accidental second invocation.
            fake = pathlib.Path(temporary) / "yt-dlp"
            fake.write_text(
                "#!/bin/sh\n"
                f"echo x >> {calls}\n"
                f'if [ "$(wc -l < {calls})" = "1" ]; then\n'
                f"    printf '%s\\n' '{playlist}'\n"
                "else\n"
                f"    printf '%s\\n' '{definition}'\n"
                "fi\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "list"],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": f"{pathlib.Path(shutil.which('deno') or '/usr/bin').parent}:/usr/bin:/bin",
                    "FFMPEG_BIN": "/bin/true",
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "ERSATZRS_MEDIA_LIST_URL": "https://video.example/playlist",
                },
            )
            invocations = calls.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all("record_type" in row for row in rows))
        self.assertEqual(rows[0]["record_type"], "list")
        self.assertEqual(len(invocations), 1)

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_yt_dlp_remote_stream_mode_emits_no_media_list_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            definition = (
                '{"id":"video-1","provider_id":"video-1",'
                '"url":"https://video.example/watch?v=1","title":"One","is_live":false}'
            )
            fake = pathlib.Path(temporary) / "yt-dlp"
            fake.write_text(
                f"#!/bin/sh\nprintf '%s\\n' '{definition}'\n", encoding="utf-8"
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "list"],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": f"{pathlib.Path(shutil.which('deno') or '/usr/bin').parent}:/usr/bin:/bin",
                    "FFMPEG_BIN": "/bin/true",
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "ERSATZRS_REMOTE_STREAM_PLAYLIST_URL": "https://video.example/playlist",
                },
            )
        self.assertNotIn("record_type", result.stdout)
        self.assertTrue(result.stdout.strip())

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
                    "PATH": f"{pathlib.Path(shutil.which('deno') or '/usr/bin').parent}:/usr/bin:/bin",
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
    def test_posix_yt_dlp_item_requires_at_least_one_identity(self) -> None:
        result = subprocess.run(
            ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "item"],
            check=False,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "FFMPEG_BIN": "/bin/true",
                "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": "/bin/true",
            },
        )
        self.assertEqual(self.final_operation_error(result)["code"], "missing-setting")

    def test_yt_dlp_declares_the_item_metadata_capability(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.toml").read_text(
                encoding="utf-8"
            )
        )
        capabilities = [entry["id"] for entry in manifest["capabilities"]]
        self.assertIn("remote-stream.item.v2", capabilities)
        source = (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("ERSATZRS_REMOTE_STREAM_ITEM_IDS", source)
        # Enrichment must be a full extraction; a flat listing is what omits
        # the descriptive fields in the first place.
        item_branch = source.split("    item)", 1)[1].split("    play)", 1)[0]
        self.assertNotIn("--flat-playlist", item_branch)
        self.assertIn("--skip-download", item_branch)
        self.assertIn("--dump-json", item_branch)

    @unittest.skipUnless(shutil.which("deno"), "deno required")
    def test_yt_dlp_item_metadata_formats_sparse_fractional_chapters(self) -> None:
        source = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "libexec" / "item-metadata.ts"
        result = subprocess.run(
            ["deno", "run", "--quiet", str(source)],
            input=json.dumps({
                "id": "video-1",
                "availability": "public",
                "chapters": [
                    {"start_time": 0.2, "title": " Intro "},
                    {"start_time": 19.6, "title": "Sculpt Mode"},
                ],
            }) + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
        row = json.loads(result.stdout)
        self.assertEqual(row["chapter_input"], "0:00 Intro\n0:20 Sculpt Mode")

        no_chapters = subprocess.run(
            ["deno", "run", "--quiet", str(source)],
            input=json.dumps({"id": "video-2", "chapters": None}) + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertNotIn("chapter_input", json.loads(no_chapters.stdout))

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists() and shutil.which("deno"), "POSIX shell and deno required")
    def test_posix_yt_dlp_chapter_enrichment_uses_one_full_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            calls = root / "calls"
            fake = root / "yt-dlp"
            fake.write_text(
                "#!/bin/sh\nprintf x >> \"$CALLS\"\nprintf '%s\\n' '{\"id\":\"video-1\",\"availability\":\"public\",\"chapters\":[{\"start_time\":0,\"title\":\"Intro\"}]}'\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"), "item"],
                check=True,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "CALLS": str(calls),
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "ERSATZRS_REMOTE_STREAM_ITEM_IDS": "video-1",
                },
            )
            self.assertEqual(calls.read_text(encoding="utf-8"), "x")
            self.assertEqual(json.loads(result.stdout)["chapter_input"], "0:00 Intro")

    def test_yt_dlp_chapter_rounding_is_owned_by_both_package_entrypoints(self) -> None:
        posix = (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "libexec" / "item-metadata.ts").read_text(encoding="utf-8")
        windows = (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "libexec" / "item-metadata.ps1").read_text(encoding="utf-8")
        self.assertIn("Math.round", posix)
        self.assertIn("[Math]::Round", windows)
        self.assertIn("chapter_input", posix)
        self.assertIn("chapter_input", windows)

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists() and shutil.which("deno"), "POSIX shell and deno required")
    def test_fragment_playback_strips_bounds_and_applies_seek_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            arguments = root / "arguments"
            fake = root / "yt-dlp"
            fake.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$ARGUMENTS\"\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            script = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "libexec" / "fragment-playback.ts"
            subprocess.run(
                ["deno", "run", "--quiet", "--allow-env", "--allow-run", str(script)],
                check=True,
                env={
                    **os.environ,
                    "ARGUMENTS": str(arguments),
                    "YT_DLP_BIN": str(fake),
                    "FFMPEG_BIN": "/managed/ffmpeg",
                    "ERSATZRS_REMOTE_STREAM_URL": "https://video.example/watch?v=1&start=20&end=65",
                    "ERSATZRS_REMOTE_STREAM_SEEK": "00:00:05",
                },
            )
            values = arguments.read_text(encoding="utf-8").splitlines()
            self.assertIn("ffmpeg_i:-ss 25 -t 40", values)
            self.assertIn("https://video.example/watch?v=1", values)
            self.assertFalse(any("start=" in value or "end=" in value for value in values))
            # A progressive rendition is served from a client-bound media URL
            # that the managed FFmpeg downloader is refused when it fetches the
            # URL itself, so an adaptive manifest has to be preferred.
            selector = next(value for value in values if value.startswith("best["))
            self.assertTrue(
                selector.startswith("best[protocol^=m3u8]"),
                f"manifest formats must be preferred, got {selector}",
            )

    def test_yt_dlp_declares_its_javascript_runtime_on_both_platforms(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.toml").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("deno", manifest["permissions"]["external_commands"])
        windows = (ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("missing-js-runtime", windows)
        self.assertIn("deno.exe", windows)

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
        self.assertEqual(rows[0]["release_date"], "1993-01-24")
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
        self.assertIn(
            "beeldengeluid.sh: retained 1 unavailable Schatkamer shared-list item(s)\n",
            result.stderr,
        )

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_paginates_and_deduplicates_shared_lists(self) -> None:
        first_page = (
            r'<script>\"description\":\"Gedeelde lijst\",'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/first/aflevering/101\",\"isPlayable\":true,'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/second/aflevering/103\",\"isPlayable\":true</script>'
        )
        second_page = (
            r'<script>\"description\":\"Gedeelde lijst\",'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/second/aflevering/103\",\"isPlayable\":true,'
            r'\"url\":\"https://schatkamer.beeldengeluid.nl/serie/10/third/aflevering/104\",\"isPlayable\":true</script>'
        )
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/lijst/14df8d33-ce8a-4680-a83b-0cc2a9c58bcd",
            first_page,
            list_page_2=second_page,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row["id"] for row in rows], ["101", "103", "104"])

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_imports_series_introduction_and_images(self) -> None:
        series_page = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"CreativeWorkSeries",'
            '"name":"Fixture Programme","description":"Full editorial introduction",'
            '"image":"https://schatkamer.beeldengeluid.nl/assets/programme.jpg"}'
            '</script><a href="/serie/20/fixture/aflevering/201">'
            '<img src="https://schatkamer.beeldengeluid.nl/image-optimizer?'
            'url=aHR0cHM6Ly9zay12aWRlby5jZG4uYmVlbGRlbmdlbHVpZC5ubC9maXh0dXJlL3N0aWxsLmpwZw'
            '&amp;width=640&amp;quality=80&amp;format=webp"></a>'
        )
        episode_page = (
            '<h1>Fixture Programme</h1><h3>First Episode</h3>'
            '<script>{"image":"https://schatkamer.beeldengeluid.nl/assets/episode.jpg"};'
            r'\"description\":\"Fixture plot\",\"disclaimer\":null,'
            r'\"durationNumber\":120,\"publishedAtISO\":\"1993-01-24T12:30:00Z\"</script>'
        )
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
            "",
            media_list_contract=True,
            episode_page=episode_page,
            series_page=series_page,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["name"], "Fixture Programme")
        self.assertEqual(rows[0]["description"], "Full editorial introduction")
        self.assertNotIn("duration_seconds", rows[1])
        self.assertNotIn("release_date", rows[1]["metadata"])
        self.assertEqual(
            rows[1]["additional_image_urls"],
            ["https://sk-video.cdn.beeldengeluid.nl/fixture/still.jpg"],
        )
        self.assertNotIn("/aflevering/201", result.stderr)

    @unittest.skipUnless(
        (shutil.which("deno") or shutil.which("deno.exe"))
        and (os.name != "nt" or shutil.which("dotnet")),
        "deno and a native fake-curl build tool required",
    )
    def test_beeldengeluid_adapter_normalizes_the_v4_contract_boundary(self) -> None:
        adapter = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "libexec"
            / "media-list-adapter.ts"
        )
        source = ROOT / "tests" / "fixtures" / "beeldengeluid-media-list-raw.ndjson"
        result = subprocess.run(
            [
                shutil.which("deno") or shutil.which("deno.exe") or "deno",
                "run",
                "--quiet",
                f"--allow-read={source}",
                str(adapter),
                "--normalize",
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertIsInstance(rows[0]["metadata"]["artwork"], list)
        metadata = rows[1]["metadata"]
        self.assertEqual(metadata["release_date"], "1993-01-24")
        self.assertEqual(metadata["content_ratings"], ["nl:AL"])
        self.assertEqual(metadata["tags"], ["drawing"])
        self.assertEqual(
            metadata["people"], [{"name": "Presenter One", "role": "presenter"}]
        )
        self.assertIsInstance(metadata["artwork"], list)
        self.assertEqual(
            rows[1]["additional_image_urls"],
            ["https://images.example.test/still.jpg"],
        )
        self.assertNotIn("provider_private_field", metadata)

    @unittest.skipUnless(pathlib.Path("/bin/sh").exists(), "POSIX shell required")
    def test_posix_beeldengeluid_accepts_one_episode_as_a_list(self) -> None:
        result = self.run_posix_beeldengeluid_list(
            "https://schatkamer.beeldengeluid.nl/serie/20/fixture/aflevering/201",
            "",
            media_list_contract=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["provider_id"], "episode:201")
        self.assertNotIn("start=", rows[1]["source_url"])

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
        self.assertTrue(all("year" not in row for row in rows[1:]))
        self.assertTrue(all(row["kind"] == "remote_stream" for row in rows[1:]))
        self.assertTrue(all(row["liveness"] == "finite" for row in rows[1:]))
        self.assertTrue(all(row["source_url"].startswith("https://") for row in rows[1:]))
        self.assertNotIn("/aflevering/", result.stderr)

    def test_yt_dlp_declares_file_backed_list_storage(self) -> None:
        manifest = tomllib.loads(
            (
                ROOT
                / "addons"
                / "org.ersatzrs.addon.yt-dlp"
                / "addon.toml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["manifest_version"], 4)
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

    @unittest.skipUnless(
        pathlib.Path("/bin/sh").exists() and shutil.which("deno"),
        "POSIX shell and deno required",
    )
    def test_posix_yt_dlp_projects_playlist_as_remote_stream_records(self) -> None:
        addon = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"
        with tempfile.TemporaryDirectory() as temporary:
            fake = pathlib.Path(temporary) / "yt-dlp"
            arguments = pathlib.Path(temporary) / "arguments.txt"
            fake.write_text(
                """#!/bin/sh
printf '%s\n' "$@" > "$FAKE_ARGUMENTS"
printf '%s\n' '{"title":"Fixture playlist","description":"Fixture list description","channel":"Fixture Channel","entries":[{"id":"video-1","title":"Fixture","description":"Fixture description","webpage_url":"https://video.example/watch?v=1","availability":"public","duration":42,"upload_date":"20240821","categories":["Documentary"],"tags":["archive"],"channel":"Fixture Channel","thumbnail":"https://images.example.test/thumb.jpg"}]}'
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
                    "PATH": f"{pathlib.Path(shutil.which('deno') or '/usr/bin').parent}:/usr/bin:/bin",
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
        self.assertEqual(rows[1]["metadata"]["release_date"], "2024-08-21")
        self.assertEqual(rows[1]["metadata"]["people"][0]["name"], "Fixture Channel")
        self.assertEqual(rows[1]["metadata"]["artwork"][0]["role"], "thumb")

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
        self.assertIn("--dump-single-json", yt_dlp_arguments)
        self.assertIn("--skip-download", yt_dlp_arguments)
        self.assertNotIn("--flat-playlist", yt_dlp_arguments)

    @unittest.skipUnless(shutil.which("deno"), "deno required")
    def test_yt_dlp_v4_transformer_maps_complete_shared_metadata(self) -> None:
        transformer = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.yt-dlp"
            / "libexec"
            / "media-list.ts"
        )
        fixture = {
            "title": "RLM - Highlights",
            "description": "Playlist description",
            "channel": "RedLetterMedia",
            "thumbnail": "https://images.example.test/list.webp",
            "entries": [
                {
                    "id": "video-1",
                    "title": "Highlight",
                    "description": "Item description",
                    "webpage_url": "https://www.youtube.com/watch?v=video-1",
                    "availability": "public",
                    "duration": 342.4,
                    "upload_date": "20240718",
                    "categories": ["Entertainment"],
                    "tags": ["redlettermedia", "highlight"],
                    "channel": "RedLetterMedia",
                    "uploader": "RLM",
                    "thumbnail": "https://images.example.test/item.webp",
                    "thumbnail_width": 1280,
                    "thumbnail_height": 720,
                }
            ],
        }
        environment = os.environ.copy()
        environment["ERSATZRS_MEDIA_LIST_URL"] = (
            "https://www.youtube.com/playlist?list=fixture"
        )
        result = subprocess.run(
            [
                "deno",
                "run",
                "--quiet",
                "--allow-env=ERSATZRS_MEDIA_LIST_URL,PLAYLIST_URL",
                str(transformer),
            ],
            input=json.dumps(fixture),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["metadata"]["title"], "RLM - Highlights")
        self.assertEqual(rows[0]["metadata"]["people"][0]["role"], "Channel")
        metadata = rows[1]["metadata"]
        self.assertEqual(metadata["release_date"], "2024-07-18")
        self.assertEqual(metadata["year"], 2024)
        self.assertEqual(metadata["genres"], ["Entertainment"])
        self.assertEqual(metadata["tags"], ["redlettermedia", "highlight"])
        self.assertEqual(metadata["broadcasters"], ["RedLetterMedia"])
        self.assertEqual(
            metadata["people"],
            [
                {"name": "RedLetterMedia", "role": "Channel", "order": 0},
                {"name": "RLM", "role": "Uploader", "order": 1},
            ],
        )
        self.assertEqual(metadata["artwork"][0]["role"], "thumb")
        self.assertEqual(metadata["artwork"][0]["width"], 1280)
        self.assertEqual(rows[1]["duration_seconds"], 342)

        posix_source = (
            ROOT / "addons" / "org.ersatzrs.addon.yt-dlp" / "addon.sh"
        ).read_text(encoding="utf-8")
        windows_source = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.yt-dlp"
            / "libexec"
            / "youtube-list.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("media-list.ts", posix_source)
        self.assertIn("media-list.ts", windows_source)

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
        self.assertIn(r"([^\\\x22]*)\\\x22,\\\x22description", source)
        self.assertIn("$sharedListName", source)
        self.assertIn("name = $listName", source)
        importer = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "libexec"
            / "media-list-import.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("isPlayable", importer)
        self.assertIn("--extract-overview", source)
        self.assertIn("$seen.Add($path)", source)
        self.assertIn(
            "('beeldengeluid.bat: result page {0} yielded {1} new episode(s)' -f $page, $added)",
            source,
        )
        self.assertIn(
            "('beeldengeluid.bat: shared-list page {0} yielded {1} new item(s)' -f $page, $added)",
            source,
        )
        self.assertIn("retained {0} unavailable Schatkamer shared-list item(s)", source)
        self.assertIn("availability_reason = 'not_playable'", source)
        self.assertIn("content_kind = 'auto'", source)
        self.assertIn("$slug", source)

    @unittest.skipUnless(
        os.name == "nt" and (shutil.which("powershell.exe") or shutil.which("pwsh")),
        "native Windows PowerShell required",
    )
    def test_windows_beeldengeluid_decodes_quoted_programme_descriptions(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        helper = (
            ROOT
            / "addons"
            / "org.ersatzrs.addon.beeldengeluid"
            / "libexec"
            / "beeldengeluid-json.ps1"
        )
        environment = os.environ.copy()
        environment["ERSATZRS_TEST_HELPER"] = str(helper)
        environment["ERSATZRS_TEST_ESCAPED_JSON"] = (
            r'\"What does a \\\"portrait\\\" cost?\\nNext\"'
        )
        result = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ". $env:ERSATZRS_TEST_HELPER; "
                "ConvertFrom-EscapedJsonValue $env:ERSATZRS_TEST_ESCAPED_JSON",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'What does a "portrait" cost?\nNext')

    @unittest.skipUnless(
        os.name == "nt" and (shutil.which("powershell.exe") or shutil.which("pwsh")),
        "native Windows PowerShell required",
    )
    def test_windows_beeldengeluid_keeps_aggregate_metadata_arrays_without_details(
        self,
    ) -> None:
        result = self.run_windows_beeldengeluid_media_list()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0]["metadata"]["artwork"],
            [
                {
                    "role": "poster",
                    "url": "https://schatkamer.beeldengeluid.nl/assets/programme.jpg",
                }
            ],
        )
        self.assertEqual(rows[1]["metadata"]["content_ratings"], [])
        self.assertNotIn("release_date", rows[1]["metadata"])
        self.assertEqual(
            rows[1]["metadata"]["artwork"],
            [
                {
                    "role": "thumb",
                    "url": "https://sk-video.cdn.beeldengeluid.nl/fixture/still.jpg",
                }
            ],
        )
        self.assertEqual(rows[1]["metadata"]["people"], [])
        self.assertNotIn("/aflevering/201", result.stderr)

    @unittest.skipUnless(
        shutil.which("deno") or shutil.which("deno.exe"), "deno required"
    )
    def test_resumable_beeldengeluid_merges_eight_provider_ordered_items(self) -> None:
        overview, episode_ids = self.beeldengeluid_strip_overview()
        source_url = (
            "https://schatkamer.beeldengeluid.nl/serie/2101608030022428031/"
            "strip-en-cartoontekenen"
            "?alleenafspeelbaar=nee&operator=strip&pagina=99&operator=tekenen"
        )
        result, calls = self.run_resumable_beeldengeluid_discover(source_url, overview)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        items = [row for row in rows if row.get("record_type") == "item"]
        self.assertEqual(
            [row["provider_id"] for row in items],
            [f"episode:{episode_id}" for episode_id in episode_ids],
        )
        self.assertEqual([row["rank"] for row in items], list(range(8)))
        unavailable = items[6]
        self.assertEqual(unavailable["provider_id"], "episode:2101608050040897831")
        self.assertEqual(unavailable["rank"], 6)
        self.assertEqual(
            unavailable["title"], "Les 7: Cartoon, strook en paginaverhaal"
        )
        self.assertEqual(unavailable["metadata"]["plot"], "Uitgebreide providerbeschrijving voor les 7.")
        self.assertEqual(unavailable["metadata"]["release_date"], "1993-03-07")
        self.assertEqual(unavailable["availability"], "unavailable")
        self.assertEqual(unavailable["availability_reason"], "not_playable")
        self.assertEqual(len(calls), 1)
        self.assertIn(
            "https://schatkamer.beeldengeluid.nl/serie/2101608030022428031/"
            "strip-en-cartoontekenen"
            "?alleenafspeelbaar=nee&operator=strip&pagina=1&operator=tekenen",
            calls[0],
        )

    @unittest.skipUnless(
        pathlib.Path("/bin/sh").exists()
        and (shutil.which("deno") or shutil.which("deno.exe")),
        "POSIX shell and deno required",
    )
    def test_posix_legacy_beeldengeluid_merges_eight_provider_ordered_items(self) -> None:
        overview, episode_ids = self.beeldengeluid_strip_overview()
        source_url = (
            "https://schatkamer.beeldengeluid.nl/serie/2101608030022428031/"
            "strip-en-cartoontekenen"
            "?alleenafspeelbaar=nee&operator=strip&pagina=99&operator=tekenen"
        )
        result = self.run_posix_beeldengeluid_list(
            source_url,
            "",
            media_list_contract=True,
            series_page=overview,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        items = rows[1:]
        self.assertEqual(
            [row["provider_id"] for row in items],
            [f"episode:{episode_id}" for episode_id in episode_ids],
        )
        unavailable = items[6]
        self.assertEqual(unavailable["rank"], 6)
        self.assertEqual(unavailable["metadata"]["release_date"], "1993-03-07")
        self.assertEqual(unavailable["availability"], "unavailable")
        self.assertEqual(unavailable["availability_reason"], "not_playable")
        self.assertNotIn("unexpected-detail-request", result.stderr)
        self.assertIn(
            "fake-curl-url: https://schatkamer.beeldengeluid.nl/serie/"
            "2101608030022428031/strip-en-cartoontekenen?alleenafspeelbaar=nee&"
            "operator=strip&pagina=1&operator=tekenen",
            result.stderr,
        )

    @unittest.skipUnless(
        os.name == "nt" and (shutil.which("powershell.exe") or shutil.which("pwsh")),
        "native Windows PowerShell required",
    )
    def test_windows_legacy_beeldengeluid_merges_eight_provider_ordered_items(self) -> None:
        overview, episode_ids = self.beeldengeluid_strip_overview()
        source_url = (
            "https://schatkamer.beeldengeluid.nl/serie/2101608030022428031/"
            "strip-en-cartoontekenen"
            "?alleenafspeelbaar=nee&operator=strip&pagina=99&operator=tekenen"
        )
        result = self.run_windows_beeldengeluid_media_list(
            playlist_url=source_url,
            series_page=overview,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        items = rows[1:]
        self.assertEqual(
            [row["provider_id"] for row in items],
            [f"episode:{episode_id}" for episode_id in episode_ids],
        )
        unavailable = items[6]
        self.assertEqual(unavailable["rank"], 6)
        self.assertEqual(unavailable["metadata"]["release_date"], "1993-03-07")
        self.assertEqual(unavailable["availability"], "unavailable")
        self.assertEqual(unavailable["availability_reason"], "not_playable")
        self.assertNotIn("unexpected-detail-request", result.stderr)
        self.assertIn(
            "fake-curl-url: https://schatkamer.beeldengeluid.nl/serie/"
            "2101608030022428031/strip-en-cartoontekenen?alleenafspeelbaar=nee&"
            "operator=strip&pagina=1&operator=tekenen",
            result.stderr,
        )

    def beeldengeluid_unavailable_overview(self, shared: bool = False) -> str:
        prefix = (
            r'<script>\"title\":\"Fixture\",\"description\":\"Gedeelde lijst\",'
            if shared
            else "<script>"
        )
        return (
            prefix
            + '{"url":"https://schatkamer.beeldengeluid.nl/serie/20/'
            'strip-en-cartoontekenen/aflevering/2101608050040897831",'
            '"isPlayable":false,"title":"Niet afspeelbaar",'
            '"publishedAtISO":"1993-03-07T12:00:00Z"}</script>'
        )

    @unittest.skipUnless(
        pathlib.Path("/bin/sh").exists()
        and (shutil.which("deno") or shutil.which("deno.exe")),
        "POSIX shell and deno required",
    )
    def test_posix_legacy_beeldengeluid_pagination_preserves_operator_queries(self) -> None:
        shared_id = "14df8d33-ce8a-4680-a83b-0cc2a9c58bcd"
        cases = [
            (
                "https://schatkamer.beeldengeluid.nl/serie/20/fixture"
                "?operator=een&pagina=99&operator=twee",
                "https://schatkamer.beeldengeluid.nl/serie/20/fixture"
                "?operator=een&pagina=1&operator=twee",
                False,
            ),
            (
                f"https://schatkamer.beeldengeluid.nl/lijst/{shared_id}"
                "?eigenaar=operator&pagina=99&sortering=oudste",
                f"https://schatkamer.beeldengeluid.nl/lijst/{shared_id}"
                "?eigenaar=operator&pagina=1&sortering=oudste",
                True,
            ),
            (
                "https://schatkamer.beeldengeluid.nl/zoeken"
                "?term=strip%20cartoon&type=video&pagina=99",
                "https://schatkamer.beeldengeluid.nl/zoeken"
                "?term=strip%20cartoon&type=video&pagina=1",
                False,
            ),
        ]
        for source_url, expected_page, shared in cases:
            with self.subTest(source_url=source_url):
                overview = self.beeldengeluid_unavailable_overview(shared)
                result = self.run_posix_beeldengeluid_list(
                    source_url,
                    overview if shared else "",
                    media_list_contract=True,
                    series_page=overview,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("fake-curl-url: " + expected_page, result.stderr)
                self.assertNotIn("pagina=99", result.stderr)
                self.assertNotIn("unexpected-detail-request", result.stderr)

    @unittest.skipUnless(
        os.name == "nt" and (shutil.which("powershell.exe") or shutil.which("pwsh")),
        "native Windows PowerShell required",
    )
    def test_windows_legacy_beeldengeluid_pagination_preserves_operator_queries(self) -> None:
        shared_id = "14df8d33-ce8a-4680-a83b-0cc2a9c58bcd"
        cases = [
            (
                "https://schatkamer.beeldengeluid.nl/serie/20/fixture"
                "?operator=een&pagina=99&operator=twee",
                "https://schatkamer.beeldengeluid.nl/serie/20/fixture"
                "?operator=een&pagina=1&operator=twee",
                False,
            ),
            (
                f"https://schatkamer.beeldengeluid.nl/lijst/{shared_id}"
                "?eigenaar=operator&pagina=99&sortering=oudste",
                f"https://schatkamer.beeldengeluid.nl/lijst/{shared_id}"
                "?eigenaar=operator&pagina=1&sortering=oudste",
                True,
            ),
            (
                "https://schatkamer.beeldengeluid.nl/zoeken"
                "?term=strip%20cartoon&type=video&pagina=99",
                "https://schatkamer.beeldengeluid.nl/zoeken"
                "?term=strip%20cartoon&type=video&pagina=1",
                False,
            ),
        ]
        for source_url, expected_page, shared in cases:
            with self.subTest(source_url=source_url):
                overview = self.beeldengeluid_unavailable_overview(shared)
                result = self.run_windows_beeldengeluid_media_list(
                    playlist_url=source_url,
                    series_page=overview,
                    list_page=overview,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("fake-curl-url: " + expected_page, result.stderr)
                self.assertNotIn("pagina=99", result.stderr)
                self.assertNotIn("unexpected-detail-request", result.stderr)

    @unittest.skipUnless(
        shutil.which("deno") or shutil.which("deno.exe"), "deno required"
    )
    def test_resumable_beeldengeluid_import_separates_overview_and_detail_requests(self) -> None:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            overview = fixtures / "overview.html"
            overview.write_text(
                '<script type="application/ld+json">'
                '{"@type":"CreativeWorkSeries","name":"Fixture Programme",'
                '"description":"Programme description",'
                '"image":"https://schatkamer.beeldengeluid.nl/assets/programme.jpg"}'
                '</script><li><a data-gtm-interaction-text="Home" href="/">Home</a></li>'
                '<li><a data-gtm-interaction-text="First episode" '
                'href="/serie/20/fixture/aflevering/201">'
                '<img src="https://schatkamer.beeldengeluid.nl/assets/episode.jpg">'
                '<div role="img" aria-label="Video"></div>'
                '<span class="highlight-title">First episode</span>'
                '<span>24 januari 1993</span></a>'
                '<p>Overview plot</p></li>\n',
                encoding="utf-8",
            )
            detail = fixtures / "detail.html"
            detail.write_text(
                '<h1>Fixture Programme</h1><h3>First episode</h3>'
                '<script>{"image":"https://schatkamer.beeldengeluid.nl/assets/episode.jpg",'
                '"description":"Detailed plot","durationNumber":120,'
                '"publishedAtISO":"1993-01-24T12:30:00Z",'
                '"genres":["Education"],"subjects":["Drawing"]}</script>\n',
                encoding="utf-8",
            )
            calls = fixtures / "calls.txt"
            if os.name == "nt":
                fake = fixtures / "fake-curl.cmd"
                fake.write_text(
                    '@echo off\n>>"%FAKE_CALLS%" echo %*\ntype "%FAKE_FIXTURE%"\n'
                    'echo __ERSATZRS_HTTP_STATUS__:200\n',
                    encoding="utf-8",
                )
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    str(addon_root / "addon.bat"),
                ]
            else:
                fake = fixtures / "fake-curl"
                fake.write_text(
                    '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CALLS"\n'
                    'cat "$FAKE_FIXTURE"\nprintf \'\\n__ERSATZRS_HTTP_STATUS__:200\'\n',
                    encoding="utf-8",
                )
                fake.chmod(0o755)
                command = ["/bin/sh", str(addon_root / "addon.sh")]
            environment = os.environ.copy()
            environment.update(
                {
                    "CURL_BIN": str(fake),
                    "ERSATZRS_ADDON_SETTING_CURL_BIN": str(fake),
                    "FAKE_CALLS": str(calls),
                    "FAKE_FIXTURE": str(overview),
                }
            )
            discover_request = {
                "source_url": "https://schatkamer.beeldengeluid.nl/serie/20/fixture",
                "record_capability": "media-list.list.v5",
                "limits": {"max_items": 250, "max_output_bytes": 4_194_304},
            }
            discovered = subprocess.run(
                [*command, "discover"],
                input=json.dumps(discover_request),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(discovered.returncode, 0, discovered.stderr)
            rows = [json.loads(line) for line in discovered.stdout.splitlines()]
            self.assertEqual(rows[0]["record_type"], "page")
            self.assertEqual(rows[1]["name"], "Fixture Programme")
            self.assertEqual(rows[2]["title"], "First episode")
            self.assertEqual(rows[2]["metadata"]["plot"], "Overview plot")
            self.assertEqual(rows[2]["metadata"]["release_date"], "1993-01-24")
            self.assertNotIn("thumbnail_url", rows[2])
            self.assertEqual(
                rows[2]["additional_image_urls"],
                ["https://schatkamer.beeldengeluid.nl/assets/episode.jpg"],
            )
            self.assertEqual(rows[2]["liveness"], "finite")
            overview_calls = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(overview_calls), 1)
            self.assertIn("pagina=1", overview_calls[0])
            self.assertNotIn("aflevering/201", overview_calls[0])

            environment["FAKE_FIXTURE"] = str(detail)
            enrich_request = {
                "source_url": discover_request["source_url"],
                "record_capability": "media-list.list.v5",
                "provider_id": "episode:201",
                "overview_fingerprint": "fixture-fingerprint",
                "item": rows[2],
            }
            enriched = subprocess.run(
                [*command, "enrich"],
                input=json.dumps(enrich_request),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(enriched.returncode, 0, enriched.stderr)
            detail_rows = [json.loads(line) for line in enriched.stdout.splitlines()]
            self.assertEqual(detail_rows[0]["outcome"], "complete")
            self.assertEqual(detail_rows[1]["metadata"]["plot"], "Detailed plot")
            self.assertEqual(detail_rows[1]["duration_seconds"], 120)
            all_calls = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(all_calls), 2)
            self.assertIn("aflevering/201", all_calls[1])

        manifest = tomllib.loads((addon_root / "addon.toml").read_text(encoding="utf-8"))
        capabilities = {item["id"] for item in manifest["capabilities"]}
        self.assertIn("media-list.import.v1", capabilities)
        self.assertIn("media-list.list.v5", capabilities)
        for entrypoint in ["addon.sh", "addon.bat"]:
            source = (addon_root / entrypoint).read_text(encoding="utf-8")
            self.assertIn("media-list-import.ts", source)
            self.assertIn("discover", source)
            self.assertIn("enrich", source)

    @unittest.skipUnless(
        shutil.which("deno") or shutil.which("deno.exe"), "deno required"
    )
    def test_resumable_yt_dlp_import_uses_flat_discovery_and_one_full_item(self) -> None:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp"
        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            playlist = fixtures / "playlist.json"
            playlist.write_text(
                '{"id":"playlist-1","title":"Fixture playlist",'
                '"description":"Overview description","playlist_count":4,"entries":[{'
                '"id":"video-1","title":"Overview title","description":"Overview plot",'
                '"webpage_url":"https://www.youtube.com/watch?v=video-1",'
                '"availability":"public","duration":42,"upload_date":"20240821",'
                '"thumbnail":"https://images.example.test/thumb.jpg",'
                '"live_status":"not_live"},{'
                '"id":"live-1","title":"Live now",'
                '"webpage_url":"https://www.youtube.com/watch?v=live-1",'
                '"availability":"public","live_status":"is_live","is_live":true},{'
                '"id":"upcoming-1","title":"Upcoming",'
                '"webpage_url":"https://www.youtube.com/watch?v=upcoming-1",'
                '"availability":"public","live_status":"is_upcoming","is_live":false},{'
                '"id":"post-live-1","title":"Ended broadcast",'
                '"webpage_url":"https://www.youtube.com/watch?v=post-live-1",'
                '"availability":"public","live_status":"post_live","is_live":false}]}\n',
                encoding="utf-8",
            )
            detail = fixtures / "detail.json"
            detail.write_text(
                '{"id":"video-1","title":"Detailed title",'
                '"description":"Detailed plot",'
                '"webpage_url":"https://www.youtube.com/watch?v=video-1",'
                '"availability":"public","duration":43,"upload_date":"20240822",'
                '"thumbnail":"https://images.example.test/detail.jpg",'
                '"live_status":"not_live","categories":["Documentary"]}\n',
                encoding="utf-8",
            )
            calls = fixtures / "calls.txt"
            if os.name == "nt":
                fake = fixtures / "fake-yt-dlp.cmd"
                fake.write_text(
                    '@echo off\n>>"%FAKE_CALLS%" echo %*\ntype "%FAKE_FIXTURE%"\n',
                    encoding="utf-8",
                )
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    str(addon_root / "addon.bat"),
                ]
            else:
                fake = fixtures / "fake-yt-dlp"
                fake.write_text(
                    '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CALLS"\n'
                    'cat "$FAKE_FIXTURE"\n',
                    encoding="utf-8",
                )
                fake.chmod(0o755)
                command = ["/bin/sh", str(addon_root / "addon.sh")]
            environment = os.environ.copy()
            environment.update(
                {
                    "YT_DLP_BIN": str(fake),
                    "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                    "FAKE_CALLS": str(calls),
                    "FAKE_FIXTURE": str(playlist),
                }
            )
            discover_request = {
                "source_url": "https://www.youtube.com/playlist?list=fixture",
                "record_capability": "media-list.list.v5",
                "limits": {"max_items": 250, "max_output_bytes": 4_194_304},
            }
            discovered = subprocess.run(
                [*command, "discover"],
                input=json.dumps(discover_request),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(discovered.returncode, 0, discovered.stderr)
            rows = [json.loads(line) for line in discovered.stdout.splitlines()]
            self.assertTrue(rows[0]["complete"])
            self.assertEqual(rows[2]["metadata"]["plot"], "Overview plot")
            self.assertEqual(rows[2]["metadata"]["release_date"], "2024-08-21")
            self.assertNotIn("thumbnail_url", rows[2])
            self.assertEqual(
                rows[2]["additional_image_urls"],
                ["https://images.example.test/thumb.jpg"],
            )
            self.assertEqual(
                [row["liveness"] for row in rows[2:]],
                ["finite", "live", "live", "finite"],
            )
            discovery_calls = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(discovery_calls), 1)
            self.assertIn("--flat-playlist", discovery_calls[0])

            environment["FAKE_FIXTURE"] = str(detail)
            enrich_request = {
                "source_url": discover_request["source_url"],
                "record_capability": "media-list.list.v5",
                "provider_id": "video-1",
                "overview_fingerprint": "fixture-fingerprint",
                "item": rows[2],
            }
            enriched = subprocess.run(
                [*command, "enrich"],
                input=json.dumps(enrich_request),
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(enriched.returncode, 0, enriched.stderr)
            detail_rows = [json.loads(line) for line in enriched.stdout.splitlines()]
            self.assertEqual(detail_rows[0]["outcome"], "complete")
            self.assertEqual(detail_rows[1]["title"], "Detailed title")
            self.assertEqual(detail_rows[1]["metadata"]["release_date"], "2024-08-22")
            all_calls = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(all_calls), 2)
            self.assertNotIn("--flat-playlist", all_calls[1])
            self.assertIn("--no-playlist", all_calls[1])
            self.assertIn("watch?v=video-1", all_calls[1])

        manifest = tomllib.loads((addon_root / "addon.toml").read_text(encoding="utf-8"))
        capabilities = {item["id"] for item in manifest["capabilities"]}
        self.assertIn("media-list.import.v1", capabilities)
        self.assertIn("media-list.list.v5", capabilities)
        for entrypoint in ["addon.sh", "addon.bat"]:
            source = (addon_root / entrypoint).read_text(encoding="utf-8")
            self.assertIn("media-list-import.ts", source)
            self.assertIn("discover", source)
            self.assertIn("enrich", source)

        posix_source = (addon_root / "addon.sh").read_text(encoding="utf-8")
        powershell_source = (addon_root / "libexec" / "youtube-list.ps1").read_text(
            encoding="utf-8"
        )
        for provider_state in ["is_live", "is_upcoming", "post_live", "not_live"]:
            self.assertIn(provider_state, posix_source)
            self.assertIn(provider_state, powershell_source)
        self.assertIn('"liveness":%(ersatzrs_liveness)j', posix_source)
        self.assertIn('"is_live":%(ersatzrs_live_flag)s', posix_source)
        self.assertIn("liveness = $liveness", powershell_source)

    @unittest.skipUnless(
        shutil.which("deno") or shutil.which("deno.exe"), "deno required"
    )
    def test_amm_g07_yt_dlp_exact_urls_across_native_import_transports(self) -> None:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp"
        cases = [
            (
                YT_DLP_LIVE_URL,
                {
                    "id": "mhJRzQsLZGg",
                    "title": "AMM-G07 live video",
                    "webpage_url": YT_DLP_LIVE_URL,
                    "availability": "public",
                    "live_status": "is_live",
                    "is_live": True,
                },
                ["mhJRzQsLZGg"],
                ["live"],
            ),
            (
                YT_DLP_FINITE_URL,
                {
                    "id": "dQw4w9WgXcQ",
                    "title": "AMM-G07 finite video",
                    "webpage_url": YT_DLP_FINITE_URL,
                    "availability": "public",
                    "live_status": "not_live",
                    "is_live": False,
                    "duration": 213,
                },
                ["dQw4w9WgXcQ"],
                ["finite"],
            ),
            (
                YT_DLP_PLAYLIST_URL,
                {
                    "id": "PLJ_TJFLc25JRdChhr9sp00ajl7FAeKDx-",
                    "title": "AMM-G07 ordered playlist",
                    "entries": [
                        {
                            "id": "playlist-first",
                            "title": "First",
                            "webpage_url": "https://www.youtube.com/watch?v=playlist-first",
                            "availability": "public",
                            "live_status": "not_live",
                        },
                        {
                            "id": "playlist-second",
                            "title": "Second",
                            "webpage_url": "https://www.youtube.com/watch?v=playlist-second",
                            "availability": "public",
                            "live_status": "is_live",
                        },
                        {
                            "id": "playlist-third",
                            "title": "Third",
                            "webpage_url": "https://www.youtube.com/watch?v=playlist-third",
                            "availability": "public",
                            "live_status": "post_live",
                        },
                    ],
                },
                ["playlist-first", "playlist-second", "playlist-third"],
                ["finite", "live", "finite"],
            ),
            (
                "https://www.youtube.com/watch?v=invalid-output",
                {"title": "Invalid provider root"},
                [],
                [],
            ),
        ]
        for source_url, payload, expected_ids, expected_liveness in cases:
            for resumable in [True, False]:
                with self.subTest(source_url=source_url, resumable=resumable):
                    with tempfile.TemporaryDirectory() as temporary:
                        fixtures = pathlib.Path(temporary)
                        fixture = fixtures / "provider.json"
                        fixture.write_text(json.dumps(payload), encoding="utf-8")
                        calls = fixtures / "calls.txt"
                        if os.name == "nt":
                            fake = fixtures / "fake-yt-dlp.cmd"
                            fake.write_text(
                                '@echo off\n>>"%FAKE_CALLS%" echo %*\n'
                                'type "%FAKE_FIXTURE%"\n',
                                encoding="utf-8",
                            )
                            command = [
                                os.environ.get("COMSPEC", "cmd.exe"),
                                "/d",
                                "/c",
                                str(addon_root / "addon.bat"),
                            ]
                        else:
                            fake = fixtures / "fake-yt-dlp"
                            fake.write_text(
                                '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CALLS"\n'
                                'cat "$FAKE_FIXTURE"\n',
                                encoding="utf-8",
                            )
                            fake.chmod(0o755)
                            command = ["/bin/sh", str(addon_root / "addon.sh")]
                        environment = os.environ.copy()
                        environment.update(
                            {
                                "YT_DLP_BIN": str(fake),
                                "ERSATZRS_ADDON_SETTING_YT_DLP_BIN": str(fake),
                                "FAKE_CALLS": str(calls),
                                "FAKE_FIXTURE": str(fixture),
                            }
                        )
                        if resumable:
                            request = {
                                "source_url": source_url,
                                "record_capability": "media-list.list.v5",
                                "limits": {
                                    "max_items": 250,
                                    "max_output_bytes": 4_194_304,
                                },
                            }
                            result = subprocess.run(
                                [*command, "discover"],
                                input=json.dumps(request),
                                check=False,
                                capture_output=True,
                                text=True,
                                env=environment,
                            )
                        else:
                            environment["ERSATZRS_MEDIA_LIST_URL"] = source_url
                            result = subprocess.run(
                                [*command, "list"],
                                check=False,
                                capture_output=True,
                                text=True,
                                env=environment,
                            )
                        if not expected_ids:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("no valid media items", result.stderr)
                            continue
                        self.assertEqual(result.returncode, 0, result.stderr)
                        rows = [json.loads(line) for line in result.stdout.splitlines()]
                        items = [
                            row for row in rows if row.get("record_type") == "item"
                        ]
                        self.assertEqual(
                            [row["provider_id"] for row in items], expected_ids
                        )
                        self.assertEqual(
                            [row["liveness"] for row in items], expected_liveness
                        )
                        self.assertEqual(
                            [row["rank"] for row in items], list(range(len(items)))
                        )
                        call_log = calls.read_text(encoding="utf-8").splitlines()
                        self.assertEqual(len(call_log), 1)
                        self.assertIn(source_url, call_log[0])
                        if resumable:
                            self.assertIn("--flat-playlist", call_log[0])

    @unittest.skipUnless(
        shutil.which("deno") or shutil.which("deno.exe"), "deno required"
    )
    def test_amm_g07_beeldengeluid_exact_urls_across_native_import_transports(
        self,
    ) -> None:
        addon_root = ROOT / "addons" / "org.ersatzrs.addon.beeldengeluid"
        episode_ids = [
            "2101608040033953431",
            "2101608040033953432",
            "2101608040033953433",
        ]

        def overview(ids: list[str], shared: bool = False) -> str:
            header = (
                r'<script>\"title\":\"AMM-G07 frozen list\",'
                r'\"description\":\"Gedeelde lijst\"</script>'
                if shared
                else '<script type="application/ld+json">'
                '{"@type":"CreativeWorkSeries","name":"AMM-G07 frozen series",'
                '"description":"Frozen aggregate overview"}</script>'
            )
            cards = []
            for index, episode_id in enumerate(ids):
                path = (
                    "/serie/2101608030021828731/ster-reclame/aflevering/"
                    + episode_id
                )
                cards.append(
                    f'<li><a data-title="Frozen item {episode_id}" href="{path}">'
                    f'<h3>Frozen item {episode_id}</h3></a>'
                    f'<p>Overview plot {episode_id}</p></li>'
                    '<script>{"url":"https://schatkamer.beeldengeluid.nl'
                    f'{path}","isPlayable":true,"title":"Provider title {episode_id}",'
                    f'"publishedAtISO":"1995-02-{index + 1:02d}T12:00:00Z"}}</script>'
                )
            return header + "".join(cards)

        detail = (
            '<h1>STER reclame</h1><h3>AMM-G07 direct episode</h3>'
            r'<script>\"program\":{\"id\":\"2101608040033953431\",'
            r'\"isPlayable\":false,\"description\":\"Frozen direct plot\",'
            r'\"disclaimer\":null,\"durationNumber\":87,'
            r'\"publishedAtISO\":\"1995-02-14T12:00:00Z\",'
            r'\"ageRating\":\"Alle leeftijden\",\"genres\":[\"Reclame\"],'
            r'\"subjects\":[\"Commercial\"],\"collection\":null,'
            r'\"presenters\":[],\"actors\":[],\"guests\":[],'
            r'\"directors\":[],\"performers\":[],\"others\":[],'
            r'\"productionCompanies\":[],\"originalBroadcasters\":[],'
            r'\"broadcaster\":null,\"broadcasters\":[],\"url\":\"fixture\"}'
            '</script>'
        )

        with tempfile.TemporaryDirectory() as temporary:
            fixtures = pathlib.Path(temporary)
            (fixtures / "page-1.html").write_text(
                overview(episode_ids[:2], shared=True), encoding="utf-8"
            )
            (fixtures / "page-2.html").write_text(
                overview(episode_ids[1:]), encoding="utf-8"
            )
            (fixtures / "empty.html").write_text("<html></html>", encoding="utf-8")
            (fixtures / "detail.html").write_text(detail, encoding="utf-8")
            calls = fixtures / "calls.txt"

            if os.name == "nt":
                project = fixtures / "FrozenCurl.csproj"
                project.write_text(
                    '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
                    '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
                    '</PropertyGroup></Project>',
                    encoding="utf-8",
                )
                (fixtures / "Program.cs").write_text(
                    'var root = Environment.GetEnvironmentVariable("FAKE_FIXTURES")!;\n'
                    'var calls = Environment.GetEnvironmentVariable("FAKE_CALLS")!;\n'
                    'var url = args.Last(value => value.StartsWith("http", '
                    'StringComparison.OrdinalIgnoreCase));\n'
                    'File.AppendAllText(calls, url + Environment.NewLine);\n'
                    'var name = url.Contains("/aflevering/") ? "detail.html" : '
                    'url.Contains("pagina=1") ? "page-1.html" : '
                    'url.Contains("pagina=2") ? "page-2.html" : "empty.html";\n'
                    'var content = File.ReadAllText(Path.Combine(root, name));\n'
                    'var outputAt = Array.IndexOf(args, "--output");\n'
                    'if (outputAt >= 0) File.WriteAllText(args[outputAt + 1], content);\n'
                    'else { Console.Write(content); '
                    'Console.Write("\\n__ERSATZRS_HTTP_STATUS__:200"); }\n',
                    encoding="utf-8",
                )
                output = fixtures / "frozen-curl-bin"
                compiled = subprocess.run(
                    [
                        shutil.which("dotnet") or "dotnet",
                        "build",
                        str(project),
                        "--nologo",
                        "--configuration",
                        "Release",
                        "--output",
                        str(output),
                        "-p:RestoreIgnoreFailedSources=true",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "DOTNET_CLI_HOME": str(fixtures),
                        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                    },
                )
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                fake = output / "FrozenCurl.exe"
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    str(addon_root / "addon.bat"),
                ]
            else:
                fake = fixtures / "frozen-curl"
                fake.write_text(
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
printf '%s\n' "$url" >> "$FAKE_CALLS"
case "$url" in
    */aflevering/*) source_file=$FAKE_FIXTURES/detail.html ;;
    *pagina=1*) source_file=$FAKE_FIXTURES/page-1.html ;;
    *pagina=2*) source_file=$FAKE_FIXTURES/page-2.html ;;
    *) source_file=$FAKE_FIXTURES/empty.html ;;
esac
if [ -n "$output" ]; then
    cp "$source_file" "$output"
else
    cat "$source_file"
    printf '\n__ERSATZRS_HTTP_STATUS__:200'
fi
""",
                    encoding="utf-8",
                )
                fake.chmod(0o755)
                command = ["/bin/sh", str(addon_root / "addon.sh")]

            environment = os.environ.copy()
            environment.update(
                {
                    "CURL_BIN": str(fake),
                    "ERSATZRS_ADDON_SETTING_CURL_BIN": str(fake),
                    "FAKE_CALLS": str(calls),
                    "FAKE_FIXTURES": str(fixtures),
                    "TEMP": str(fixtures),
                    "TMP": str(fixtures),
                }
            )
            aggregate_urls = [
                BEELDENGELUID_LIST_URL,
                BEELDENGELUID_SEARCH_URL,
                BEELDENGELUID_SERIES_URL,
            ]
            for source_url in [*aggregate_urls, BEELDENGELUID_EPISODE_URL]:
                for resumable in [True, False]:
                    with self.subTest(source_url=source_url, resumable=resumable):
                        calls.write_text("", encoding="utf-8")
                        items: list[dict[str, object]] = []
                        if resumable:
                            cursor = None
                            for _ in range(4):
                                request = {
                                    "source_url": source_url,
                                    "record_capability": "media-list.list.v5",
                                    "limits": {
                                        "max_items": 250,
                                        "max_output_bytes": 4_194_304,
                                    },
                                }
                                if cursor is not None:
                                    request["cursor"] = cursor
                                result = subprocess.run(
                                    [*command, "discover"],
                                    input=json.dumps(request),
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                    env=environment,
                                )
                                self.assertEqual(result.returncode, 0, result.stderr)
                                rows = [
                                    json.loads(line)
                                    for line in result.stdout.splitlines()
                                ]
                                page = rows[0]
                                items.extend(
                                    row
                                    for row in rows
                                    if row.get("record_type") == "item"
                                )
                                if page["complete"]:
                                    break
                                cursor = page["next_cursor"]
                                self.assertLessEqual(len(cursor.encode("utf-8")), 4_096)
                            else:
                                self.fail("resumable discovery did not complete")
                        else:
                            environment["ERSATZRS_MEDIA_LIST_URL"] = source_url
                            result = subprocess.run(
                                [*command, "list"],
                                check=False,
                                capture_output=True,
                                text=True,
                                env=environment,
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            rows = [
                                json.loads(line) for line in result.stdout.splitlines()
                            ]
                            items = [
                                row for row in rows if row.get("record_type") == "item"
                            ]

                        call_log = calls.read_text(encoding="utf-8").splitlines()
                        if source_url == BEELDENGELUID_EPISODE_URL:
                            self.assertEqual(call_log, [BEELDENGELUID_EPISODE_URL])
                            self.assertEqual(len(items), 1)
                            self.assertIn("AMM-G07 direct episode", items[0]["title"])
                            if resumable:
                                self.assertEqual(items[0]["availability"], "unavailable")
                                self.assertEqual(
                                    items[0]["availability_reason"], "not_playable"
                                )
                                self.assertEqual(items[0]["duration_seconds"], 87)
                                self.assertEqual(
                                    items[0]["metadata"]["plot"], "Frozen direct plot"
                                )
                            continue

                        self.assertEqual(
                            [row["provider_id"] for row in items],
                            [f"episode:{episode_id}" for episode_id in episode_ids],
                        )
                        self.assertEqual([row["rank"] for row in items], [0, 1, 2])
                        self.assertEqual(len(call_log), 3)
                        self.assertTrue(all("/aflevering/" not in url for url in call_log))
                        self.assertEqual(sum("pagina=1" in url for url in call_log), 1)
                        self.assertEqual(sum("pagina=2" in url for url in call_log), 1)
                        self.assertTrue(any("pagina=3" in url for url in call_log))
                        if source_url == BEELDENGELUID_SEARCH_URL:
                            self.assertTrue(
                                all("q=reclame" in url for url in call_log)
                            )
                            self.assertTrue(
                                all("startdatum=01-01-1995" in url for url in call_log)
                            )
                            self.assertTrue(
                                all("einddatum=01-03-1995" in url for url in call_log)
                            )


if __name__ == "__main__":
    unittest.main()
