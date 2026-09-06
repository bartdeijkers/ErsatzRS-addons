"""Synthetic adapters only: no provider network, cookies, or browser profiles."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp"


@unittest.skipUnless(os.name == "posix" and shutil.which("deno"), "POSIX and Deno required")
class ItemOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "staging"
        self.stage.mkdir()
        self.log = self.root / "arguments.jsonl"
        program = self.root / "fixture.py"
        program.write_text(
            '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["FIXTURE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
mode = os.environ.get("FIXTURE_MODE", "success")
if "--version" in args:
    print("2026.08.19")
elif "-show_entries" in args:
    print(json.dumps({"format": {"duration": "12.5"}, "streams": [{"codec_type": "video"}]}))
elif "--sponsorblock-remove" in args:
    path = pathlib.Path(args[args.index("--output") + 1].replace("%(ext)s", "mkv"))
    path.write_bytes(b"synthetic processed media")
    if mode == "processing-failure":
        sys.stderr.write("SponsorBlock API exhausted retries SYNTHETIC_PRIVATE_DIAGNOSTIC")
        sys.exit(1)
    if mode == "no-segments":
        sys.stderr.write("SponsorBlock: no matching segments")
    if mode == "entire-video":
        sys.stderr.write("WARNING: You have requested to remove the entire video, which is not possible")
    print(json.dumps({"path": str(path), "format": "137+140"}))
elif "--sponsorblock-mark" in args:
    if mode == "metadata-invalid-json":
        print("SYNTHETIC_PRIVATE_DIAGNOSTIC")
    else:
        print(os.environ.get("FIXTURE_METADATA", json.dumps({
            "duration": 100.125, "live_status": "not_live", "is_live": False,
            "sponsorblock_chapters": [
                {"start_time": 10.0004, "end_time": 20.1256, "category": "sponsor"},
                {"start_time": 70, "end_time": 80, "category": "outro"},
            ],
        })))
    if mode == "metadata-failure":
        sys.stderr.write("HTTP Error 429 retry-after: 99999 SYNTHETIC_PRIVATE_DIAGNOSTIC")
        sys.exit(1)
elif "--dump-single-json" in args:
    print(os.environ.get("FIXTURE_RESOLVE", json.dumps({"id": "fixture", "title": "Fixture", "webpage_url": "https://www.youtube.com/watch?v=fixture", "availability": "public", "duration": 100, "live_status": "is_live" if mode == "live" else "not_live"})))
    if mode == "resolve-failure":
        sys.stderr.write("SYNTHETIC_PRIVATE_DIAGNOSTIC")
        sys.exit(1)
elif "--output" in args:
    sys.stdout.buffer.write(b"synthetic media stream")
elif mode == "success":
    print("fixture")
else:
    messages = {"profile": "could not find cookies database", "locked": "database is locked", "decrypt": "failed to decrypt DPAPI", "restricted": "Sign in to confirm your age", "retry": "HTTP Error 429 retry-after: 99999", "failure": "unclassified failure"}
    sys.stderr.write(messages[mode] + " SYNTHETIC_PRIVATE_DIAGNOSTIC")
    sys.exit(1)
''',
            encoding="utf-8",
        )
        executable = self.root / "fake-yt-dlp"
        executable.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(program))} \"$@\"\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        self.environment = dict(
            os.environ,
            ERSATZRS_ADDON_SETTING_YT_DLP_BIN=str(executable),
            ERSATZRS_ADDON_CACHE_DIR=str(self.root / "cache"),
            FFMPEG_BIN=str(executable),
            FFPROBE_BIN=str(executable),
            FIXTURE_LOG=str(self.log),
            FIXTURE_MODE="success",
        )

    def options(self, browser: str = "none", remove: bool | None = None) -> dict:
        values = {"cookies_from_browser": browser}
        if remove is not None:
            values["sponsorblock_remove"] = remove
        return {"schema": "media-list.options.v1", "values": values}

    def request(self, browser: str = "none") -> dict:
        return {
            "source_url": "https://www.youtube.com/watch?v=fixture",
            "provider_id": "fixture",
            "context_fingerprint": "a" * 64,
            "tool_version": "2026.08.19",
            "options": self.options(browser),
        }

    def invoke(self, operation: str, request: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sh", str(ADDON / "addon.sh"), operation],
            input=json.dumps(request), text=True, capture_output=True,
            env=self.environment, timeout=20,
        )

    def arguments(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def preparation(self) -> dict:
        return dict(
            self.request("firefox"), options=self.options("firefox", True),
            staging_directory=str(self.stage), maximum_file_bytes=1024,
            maximum_staging_bytes=4096, timeout_seconds=10, max_video_height=720,
        )

    def interval_request(self) -> dict:
        return dict(self.request("firefox"), options=self.options("firefox", True))

    def test_interval_metadata_is_artifact_free_and_matches_removal_categories(self) -> None:
        request = self.interval_request()
        request["source_url"] += "&start=00:00:10.5&end=90"
        result = self.invoke("interval-metadata", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output, {
            "provider_id": "fixture", "context_fingerprint": "a" * 64,
            "tool_version": "2026.08.19", "outcome": {
                "kind": "ready", "source_duration_milliseconds": 100125,
                "excluded_intervals_milliseconds": [
                    {"start": 10000, "end": 20126}, {"start": 70000, "end": 80000},
                ],
            },
        })
        commands = self.arguments()
        self.assertEqual(len(commands), 2)  # Local version + one metadata lookup.
        args = commands[-1]
        self.assertEqual(args[args.index("--sponsorblock-mark") + 1], "all,-filler,-poi_highlight,-chapter")
        self.assertEqual(args[args.index("--format") + 1], "bestvideo*+bestaudio/best")
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "firefox")
        self.assertEqual(args[-1], "https://www.youtube.com/watch?v=fixture")
        for required_arg in ("--simulate", "--skip-download", "--dump-single-json", "--no-config", "--no-update"):
            self.assertIn(required_arg, args)
        for forbidden in ("--sponsorblock-remove", "--remove-chapters", "--download-sections", "--print",
                          "--output", "--ffmpeg-location", "-show_entries", "--no-simulate"):
            self.assertFalse(any(forbidden in command for command in commands))
        self.assertEqual(list(self.stage.iterdir()), [])
        self.assertNotIn("https://", result.stdout)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)

    def test_explicit_empty_intervals_are_distinct_from_unsupported_metadata(self) -> None:
        finite = {"duration": 20, "live_status": "not_live"}
        for metadata, expected in (
            (dict(finite, sponsorblock_chapters=[]), "ready"),
            (finite, "unsupported"),  # Unsupported extractor or too-early print output.
            (dict(finite, sponsorblock_chapters=[], live_status="is_live"), "unsupported"),
            (dict(finite, sponsorblock_chapters=[], live_status=None), "unsupported"),
            (dict(finite, sponsorblock_chapters=[], is_live=True), "unsupported"),
        ):
            with self.subTest(metadata=metadata):
                self.environment["FIXTURE_METADATA"] = json.dumps(metadata)
                result = self.invoke("interval-metadata", self.interval_request())
                self.assertEqual(result.returncode, 0, result.stderr)
                outcome = json.loads(result.stdout)["outcome"]
                self.assertEqual(outcome["kind"], expected)
                if expected == "ready":
                    self.assertEqual(outcome["excluded_intervals_milliseconds"], [])
                else:
                    self.assertNotIn("excluded_intervals_milliseconds", outcome)

    def test_invalid_interval_metadata_never_becomes_empty_success(self) -> None:
        finite = {"duration": 20, "live_status": "not_live", "sponsorblock_chapters": []}
        cases = [[], None, dict(finite, duration=0), dict(finite, duration=-1),
                 dict(finite, duration="20"), dict(finite, duration=10**16),
                 dict(finite, sponsorblock_chapters=None),
                 dict(finite, sponsorblock_chapters=[{"start_time": 1, "end_time": 2}] * 1025)]
        for chapter in (None, [], {}, {"start_time": -1, "end_time": 2},
                        {"start_time": 2, "end_time": 2}, {"start_time": 3, "end_time": 2},
                        {"start_time": 2, "end_time": 21}, {"start_time": "1", "end_time": 2},
                        {"start_time": 1, "end_time": 1.0001}):
            cases.append(dict(finite, sponsorblock_chapters=[chapter]))
        for metadata in cases:
            with self.subTest(metadata=repr(metadata)[:100]):
                self.environment["FIXTURE_METADATA"] = json.dumps(metadata)
                result = self.invoke("interval-metadata", self.interval_request())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["outcome"], {"kind": "failed"})
                self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stdout + result.stderr)

    def test_interval_process_failure_discards_usable_stdout_and_redacts_diagnostics(self) -> None:
        for mode in ("metadata-failure", "metadata-invalid-json"):
            with self.subTest(mode=mode):
                self.environment["FIXTURE_MODE"] = mode
                result = self.invoke("interval-metadata", self.interval_request())
                self.assertEqual(result.returncode, 0, result.stderr)
                outcome = json.loads(result.stdout)["outcome"]
                self.assertEqual(outcome["kind"], "failed")
                self.assertNotIn("excluded_intervals_milliseconds", outcome)
                self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stdout + result.stderr)
                if mode == "metadata-failure":
                    self.assertEqual(outcome["retry_after_seconds"], 3600)

    def test_interval_context_rejects_disabled_removal_and_changed_identity_before_lookup(self) -> None:
        for request in (dict(self.interval_request(), options=self.options("firefox", False)),
                        dict(self.interval_request(), tool_version="changed"),
                        dict(self.interval_request(), context_fingerprint="invalid")):
            self.log.unlink(missing_ok=True)
            result = self.invoke("interval-metadata", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(self.arguments(), [["--no-config", "--no-update", "--version"]])

    def test_runtime_version_is_local_and_bounded(self) -> None:
        result = self.invoke("runtime-info", {})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"tool_version": "2026.08.19"})
        self.assertEqual(self.arguments(), [["--no-config", "--no-update", "--version"]])

    def test_access_uses_exact_browser_enum_and_redacted_outcomes(self) -> None:
        for browser in ("none", "firefox", "chrome", "chromium"):
            with self.subTest(browser=browser):
                result = self.invoke("test-access", self.request(browser))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["outcome"], "accessible")
                args = self.arguments()[-1]
                if browser == "none":
                    self.assertNotIn("--cookies-from-browser", args)
                else:
                    self.assertEqual(args[args.index("--cookies-from-browser") + 1], browser)
        for mode, expected in (("profile", "profile_unavailable"), ("locked", "profile_locked"),
                               ("decrypt", "decryption_failed"), ("restricted", "provider_restricted"),
                               ("failure", "failed"), ("retry", "failed")):
            with self.subTest(mode=mode):
                self.environment["FIXTURE_MODE"] = mode
                result = self.invoke("test-access", self.request("firefox"))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["outcome"], expected)
                self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stdout + result.stderr)
                if mode == "retry":
                    self.assertEqual(output["retry_after_seconds"], 3600)

    def test_invalid_browser_and_changed_tool_never_contact_source(self) -> None:
        for request in (self.request("Firefox"), self.request("firefox:synthetic-profile"),
                        dict(self.request(), tool_version="different")):
            self.log.unlink(missing_ok=True)
            result = self.invoke("test-access", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(self.arguments()), 1)
            self.assertIn("--version", self.arguments()[0])
            self.assertNotIn("synthetic-profile", result.stderr)

    def test_preparation_uses_final_file_duration_digest_and_selected_format(self) -> None:
        for mode in ("success", "no-segments"):
            with self.subTest(mode=mode):
                (self.stage / "prepared.mkv").unlink(missing_ok=True)
                self.environment["FIXTURE_MODE"] = mode
                result = self.invoke("prepare", self.preparation())
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["duration_milliseconds"], 12500)
                self.assertEqual(output["selected_format"], "137+140")
                self.assertEqual(output["relative_path"], "prepared.mkv")
                self.assertEqual(output["sha256"], hashlib.sha256(b"synthetic processed media").hexdigest())
                self.assertEqual(output["byte_length"], len(b"synthetic processed media"))
                args = next(args for args in reversed(self.arguments()) if "--sponsorblock-remove" in args)
                self.assertEqual(args[args.index("--sponsorblock-remove") + 1], "default")
                self.assertIn("--no-simulate", args)
                self.assertNotIn("--ignore-errors", args)
                self.assertNotEqual(args[args.index("--output") + 1], "-")
                self.assertIn("[height<=720]", args[args.index("--format") + 1])
                self.assertNotIn(str(self.stage), result.stdout)

    def test_failed_processing_and_live_sources_cannot_return_artifacts(self) -> None:
        for mode in ("live", "processing-failure"):
            with self.subTest(mode=mode):
                (self.stage / "prepared.mkv").unlink(missing_ok=True)
                self.log.unlink(missing_ok=True)
                self.environment["FIXTURE_MODE"] = mode
                result = self.invoke("prepare", self.preparation())
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stderr)
                if mode == "live":
                    self.assertFalse(any("--sponsorblock-remove" in args for args in self.arguments()))

    def test_prepared_file_budget_is_enforced(self) -> None:
        request = dict(self.preparation(), maximum_file_bytes=1)
        result = self.invoke("prepare", request)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_fragment_bounds_use_original_coordinate_removal_ranges(self) -> None:
        for query, expected in (
            ("&start=10&end=60", ["*0-10", "*60-inf"]),
            ("&start=00:00:10.5", ["*0-10.5"]),
            ("&end=60", ["*60-inf"]),
            ("&start=0&end=60", ["*60-inf"]),
        ):
            with self.subTest(query=query):
                (self.stage / "prepared.mkv").unlink(missing_ok=True)
                request = self.preparation()
                request["source_url"] += query
                result = self.invoke("prepare", request)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = next(args for args in reversed(self.arguments()) if "--sponsorblock-remove" in args)
                actual = [args[index + 1] for index, arg in enumerate(args) if arg == "--remove-chapters"]
                self.assertEqual(actual, expected)
                self.assertNotIn("--download-sections", args)
                self.assertEqual(args[-1], "https://www.youtube.com/watch?v=fixture")
                self.assertEqual(json.loads(result.stdout)["duration_milliseconds"], 12500)

    def test_empty_invalid_and_out_of_source_fragment_bounds_fail(self) -> None:
        for query in ("&start=", "&end=", "&start=-1", "&start=60&end=10",
                      "&start=10&end=10", "&end=0", "&start=100"):
            with self.subTest(query=query):
                self.log.unlink(missing_ok=True)
                request = self.preparation()
                request["source_url"] += query
                result = self.invoke("prepare", request)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertFalse(any("--sponsorblock-remove" in args for args in self.arguments()))

    def test_entire_fragment_removed_warning_cannot_admit_uncut_original(self) -> None:
        self.environment["FIXTURE_MODE"] = "entire-video"
        request = self.preparation()
        request["source_url"] += "&start=10&end=60"
        result = self.invoke("prepare", request)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(any("-show_entries" in args for args in self.arguments()))

    def test_v3_direct_playback_accepts_options_but_refuses_missing_preparation(self) -> None:
        self.environment.update(
            ERSATZRS_ADDON_CAPABILITY="remote-stream.play.v3",
            ERSATZRS_REMOTE_STREAM_URL="https://www.youtube.com/watch?v=fixture",
            ERSATZRS_MEDIA_LIST_OPTIONS=json.dumps(self.options("chromium", False)),
        )
        result = self.invoke("play", {})
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.arguments()[-1]
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "chromium")
        self.log.unlink()
        self.environment["ERSATZRS_MEDIA_LIST_OPTIONS"] = json.dumps(self.options("chromium", True))
        result = self.invoke("play", {})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.arguments(), [])

    def test_options_aware_enrichment_reuses_metadata_mapper(self) -> None:
        request = self.request("chrome")
        envelope = {"options": request["options"], "request": {
            "source_url": request["source_url"], "provider_id": "fixture",
            "record_capability": "media-list.list.v6", "overview_fingerprint": "a" * 64,
            "item": {"source_url": request["source_url"], "rank": 4},
        }}
        result = self.invoke("enrich-options", envelope)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["outcome"], "complete")
        self.assertEqual(rows[1]["provider_id"], "fixture")
        self.assertEqual(rows[1]["rank"], 4)
        args = self.arguments()[-1]
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "chrome")


class ItemTransportTests(unittest.TestCase):
    def test_interval_capability_preserves_file_mode_and_localized_removal_option(self) -> None:
        manifest = tomllib.loads((ADDON / "addon.toml").read_text())
        capabilities = {entry["id"]: entry for entry in manifest["capabilities"]}
        self.assertIn("media-list.interval-metadata.v1", capabilities)
        self.assertIn("remote-stream.play.v4", capabilities)
        self.assertNotIn("remote-stream.resolve.v1", capabilities)
        self.assertIn("media-list.prepare.v1", capabilities)
        options = capabilities["media-list.options.v1"]["options"]
        removal = next(option for option in options if option["key"] == "sponsorblock_remove")
        self.assertEqual(removal["operation_targets"], ["preparation", "playback"])
        self.assertTrue(removal["default"])
        self.assertEqual(set(removal["description"]),
                         {"en-US", "nl", "de-DE", "fr-FR", "it-IT", "pl", "pt-BR", "es-419", "es-ES"})

    def test_both_entrypoints_dispatch_shared_adapter(self) -> None:
        for filename in ("addon.sh", "addon.bat"):
            source = (ADDON / filename).read_text()
            for operation in ("runtime-info", "test-access", "interval-metadata", "resolve", "prepare", "enrich-options"):
                self.assertIn(operation, source)
            self.assertIn("item-operations.ts", source)


class InstalledYtDlpMetadataTests(unittest.TestCase):
    def test_real_preprocessing_is_metadata_only_and_uses_removal_categories(self) -> None:
        installed = shutil.which("yt-dlp")
        if not installed or not zipfile.is_zipfile(installed):
            self.skipTest("An installed Python-zip yt-dlp executable is required")
        # Exercise installed CLI option parsing and preprocessing offline. Network
        # and subprocess calls fail the test; only the SponsorBlock API is stubbed.
        program = r'''
import contextlib, io, json, pathlib, sys, tempfile
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import yt_dlp
from yt_dlp.postprocessor.sponsorblock import SponsorBlockPP
from yt_dlp.utils import DownloadError, PostProcessingError

arguments = ["--no-config", "--no-update", "--no-cache-dir", "--quiet", "--no-progress",
             "--no-playlist", "--abort-on-error", "--simulate", "--skip-download",
             "--dump-single-json", "--format", "bestvideo*+bestaudio/best",
             "--sponsorblock-mark", "all,-filler,-poi_highlight,-chapter"]
parsed = yt_dlp.parse_options(arguments)
removal = yt_dlp.parse_options(["--no-config", "--sponsorblock-remove", "default"])
assert parsed.options.sponsorblock_mark == removal.options.sponsorblock_remove
info = {"id": "fixture", "title": "Fixture", "extractor": "youtube", "extractor_key": "Youtube",
        "duration": 20, "live_status": "not_live", "is_live": False,
        "formats": [{"format_id": "fixture", "url": "https://example.invalid/fixture.mp4",
                     "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "protocol": "https"}]}
segments = [{"segment": [5, 7.125], "category": "sponsor", "actionType": "skip", "videoDuration": 20}]
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / "info.json"
    path.write_text(json.dumps(info), encoding="utf-8")
    for response in (segments, [], PostProcessingError("synthetic unavailable")):
        output = io.StringIO()
        error = io.StringIO()
        patch_options = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
        with patch.object(yt_dlp.YoutubeDL, "urlopen", side_effect=AssertionError("unexpected network")), \
             patch("subprocess.Popen", side_effect=AssertionError("unexpected external process")), \
             patch.object(SponsorBlockPP, "_get_sponsor_segments", **patch_options), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                with yt_dlp.YoutubeDL(parsed.ydl_opts) as downloader:
                    code = downloader.download_with_info_file(str(path))
            except DownloadError:
                code = 1
        if isinstance(response, Exception):
            assert code != 0, (code, output.getvalue())
        else:
            assert code == 0, error.getvalue()
            result = json.loads(output.getvalue())
            assert result["duration"] == 20
            chapters = result["sponsorblock_chapters"]
            assert len(chapters) == len(response)
            if chapters:
                assert chapters[0]["start_time"] == 5 and chapters[0]["end_time"] == 7.125
        assert list(pathlib.Path(directory).iterdir()) == [path], "no media or sidecar output"
print("installed yt-dlp offline interval preprocessing passed")
'''
        result = subprocess.run([sys.executable, "-I", "-c", program, installed],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("offline interval preprocessing passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
