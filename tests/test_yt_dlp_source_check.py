"""Bounded source checks using synthetic normalized extractor output only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp"


@unittest.skipUnless(shutil.which("deno"), "Deno required")
class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="source check ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data.json"
        self.calls = self.root / "calls.jsonl"
        provider = self.root / "provider.py"
        provider.write_text('''import json, os, pathlib, sys, time
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "success")
if mode == "sleep":
    time.sleep(60)
if mode == "stdout-limit":
    sys.stdout.write("x" * (1024 * 1024 + 1))
elif mode == "stderr-limit":
    sys.stderr.write("x" * (1024 * 1024 + 1))
elif mode == "malformed":
    print("SYNTHETIC_PRIVATE_DIAGNOSTIC")
else:
    sys.stdout.write(pathlib.Path(os.environ["FAKE_DATA"]).read_text())
if mode == "failure":
    sys.stderr.write("SYNTHETIC_PRIVATE_DIAGNOSTIC https://example.test/private")
    sys.exit(1)
''', encoding="utf-8")
        if os.name == "nt":
            fake = self.root / "fake yt-dlp.cmd"
            fake.write_text('@echo off\n"%PYTHON%" "%FAKE_PROVIDER%" %*\n')
            self.command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ADDON / "addon.bat"), "check"]
        else:
            fake = self.root / "fake yt-dlp"
            fake.write_text('#!/bin/sh\nexec "$PYTHON" "$FAKE_PROVIDER" "$@"\n')
            fake.chmod(0o755)
            self.command = ["/bin/sh", str(ADDON / "addon.sh"), "check"]
        self.env = dict(os.environ, PYTHON=sys.executable, FAKE_PROVIDER=str(provider),
                        FAKE_DATA=str(self.data), FAKE_CALLS=str(self.calls), FAKE_MODE="success",
                        ERSATZRS_ADDON_SETTING_YT_DLP_BIN=str(fake), FFMPEG_BIN=str(fake),
                        ERSATZRS_ADDON_CACHE_DIR=str(self.root / "cache"),
                        ERSATZRS_ADDON_CAPABILITY="media-list.source-check.v1")
        self.payload = {"_type": "playlist", "id": "list", "extractor_key": "VimeoAlbum",
                        "title": "Fixture", "entries": [{"id": "1", "ie_key": "Vimeo", "title": "One"}]}
        self.source = "https://media.example.test/list"

    def invoke(self, validator=None, payload=None, source=None, mode="success"):
        self.data.write_text(json.dumps(self.payload if payload is None else payload))
        request = {"source_url": source or self.source}
        if validator is not None:
            request["validator"] = validator
        result = subprocess.run(self.command, input=json.dumps(request), text=True,
                                capture_output=True, env=dict(self.env, FAKE_MODE=mode), timeout=16)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("SYNTHETIC_PRIVATE", result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def test_first_same_changed_reordered_and_source_bound(self):
        self.payload["entries"].append({"id": "2", "ie_key": "Vimeo"})
        first = self.invoke()
        self.assertEqual(first["outcome"], "changed")
        self.assertEqual(self.invoke(first["validator"])["outcome"], "unchanged")
        self.assertEqual(self.invoke(first["validator"], source=self.source + "?other=1")["outcome"], "changed")
        self.payload["entries"].reverse()
        self.assertEqual(self.invoke(first["validator"])["outcome"], "changed")
        self.assertNotIn(self.source, first["validator"])

    def test_multiple_extractor_families_and_overlapping_ids(self):
        validators = set()
        for family in ["Youtube", "Vimeo", "Soundcloud", "Generic"]:
            with self.subTest(family=family):
                row = {"id": "same-id", "extractor_key": family}
                result = self.invoke(payload=row)
                self.assertEqual(result["outcome"], "changed")
                self.assertNotIn("source_updated_at", result)
                self.assertEqual(self.invoke(result["validator"], payload=row)["outcome"], "unchanged")
                validators.add(result["validator"])
        self.assertEqual(len(validators), 4)

    def test_sample_boundary_and_empty_source(self):
        self.payload["entries"] = [{"id": str(i)} for i in range(51)]
        first = self.invoke()["validator"]
        self.payload["entries"][50]["title"] = "Outside window"
        self.assertEqual(self.invoke(first)["outcome"], "unchanged")
        self.payload["entries"][49]["title"] = "Inside window"
        self.assertEqual(self.invoke(first)["outcome"], "changed")
        self.payload["entries"] = []
        empty = self.invoke(first)
        self.assertEqual(empty["outcome"], "changed")
        self.assertEqual(self.invoke(empty["validator"])["outcome"], "unchanged")

    def test_stable_metadata_and_volatile_fields(self):
        first = self.invoke()["validator"]
        for key in ["title", "description", "channel", "uploader_id"]:
            changed = dict(self.payload, **{key: "Changed"})
            self.assertEqual(self.invoke(first, payload=changed)["outcome"], "changed")
        self.payload.update(view_count=100, playlist_count=900, thumbnail="https://example.test/temp")
        self.payload["entries"][0].update(url="https://example.test/signed", like_count=100)
        self.assertEqual(self.invoke(first)["outcome"], "unchanged")
        for key, value in [("title", "New"), ("description", "New"), ("duration", 42),
                           ("availability", "private"), ("timestamp", 1700000000),
                           ("release_timestamp", 1700000000), ("ie_key", "Soundcloud")]:
            changed = json.loads(json.dumps(self.payload))
            changed["entries"][0][key] = value
            self.assertEqual(self.invoke(first, payload=changed)["outcome"], "changed", key)

    def test_timestamps_are_exact_distinct_bounded_utc(self):
        self.payload["entries"] = [{"id": str(i), "timestamp": 1700000000 + i} for i in range(25)]
        self.payload["entries"] += [
            {"id": "duplicate", "release_timestamp": 1700000024},
            {"id": "approximate", "timestamp": 1800000000, "approximate_date": True},
            {"id": "future", "timestamp": 253402300799},
            {"id": "date-only", "upload_date": "20260901", "release_date": "20260901"},
            {"id": "invalid", "timestamp": "1700000000", "release_timestamp": -62135596801},
        ]
        result = self.invoke()
        dates = result["source_updated_at"]
        self.assertEqual(len(dates), 16)
        self.assertEqual(len(set(dates)), 16)
        self.assertTrue(all(date.startswith("2023-") and date.endswith("Z") for date in dates))
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_historical_exact_timestamp_and_host_request_byte_bound(self):
        result = self.invoke(payload={"id": "historic", "release_timestamp": -1})
        self.assertEqual(result["source_updated_at"], ["1969-12-31T23:59:59.000Z"])
        # Exercise encoded stdin size without exceeding the Windows .cmd fake's
        # 8191-character command-line limit: only the source becomes tool argv.
        # JSON Unicode/quote escaping expands these host-bounded fields past
        # 16 KiB while the decoded source stays below the fake's command limit.
        source = "https://example.test/" + "\u00e9" * 4000
        validator = '"' * 4096
        encoded = json.dumps({"source_url": source, "validator": validator}).encode("utf-8")
        self.assertLessEqual(len(source.encode("utf-8")), 8192)
        self.assertLessEqual(len(validator.encode("utf-8")), 4096)
        self.assertGreater(len(encoded), 16 * 1024)
        self.assertLessEqual(len(encoded), 64 * 1024)
        result = self.invoke(validator, source=source)
        self.assertEqual(result["outcome"], "changed", result)

    def test_unknown_invalid_and_foreign_validators_are_cold(self):
        for previous in ["junk", "", "yt-dlp-window-v2:" + "a" * 129,
                         "yt-dlp-window-v1:" + "a" * 64 + ":" + "b" * 64, 1, {}]:
            self.assertEqual(self.invoke(previous)["outcome"], "changed")

    def test_incomplete_extraction_cannot_mean_unchanged(self):
        for payload in [{}, [], None, {"_type": "playlist", "id": "empty"},
                        {"entries": [None]}, {"_type": "url", "entries": []}, {"entries": [{"title": "No identity"}]},
                        {"entries": [{"id": "nested", "entries": []}]},
                        {"_type": "url", "id": "unresolved"}]:
            # None uses the regular fixture in invoke; send a JSON scalar explicitly.
            if payload is None:
                payload = False
            result = self.invoke(payload=payload)
            self.assertEqual(result, {"outcome": "transient_failure", "code": "source-check-invalid-extraction"})

    def test_execution_failures_and_output_limits_are_sanitized(self):
        for mode in ["failure", "malformed", "stdout-limit", "stderr-limit"]:
            with self.subTest(mode=mode):
                result = self.invoke(mode=mode)
                self.assertEqual(result["outcome"], "transient_failure")
                self.assertEqual(set(result), {"outcome", "code"})

    def test_overall_deadline(self):
        started = time.monotonic()
        result = self.invoke(mode="sleep")
        self.assertEqual(result["outcome"], "transient_failure")
        self.assertLess(time.monotonic() - started, 15)

    def test_arguments_are_bounded_metadata_only(self):
        self.invoke()
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        args = calls[0]
        for flag in ["--no-config", "--no-update", "--flat-playlist", "--skip-download",
                     "--simulate", "--abort-on-error", "--dump-single-json"]:
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--playlist-end") + 1], "50")
        for flag in ["--retries", "--extractor-retries", "--fragment-retries"]:
            self.assertEqual(args[args.index(flag) + 1], "0")
        self.assertEqual(args[-2:], ["--", self.source])
        for flag in ["--break-on-existing", "--download-archive", "--ignore-errors"]:
            self.assertNotIn(flag, args)

    def test_readiness_dispatch_is_preserved(self):
        result = subprocess.run(self.command, text=True, capture_output=True,
                                env=dict(self.env, ERSATZRS_ADDON_CAPABILITY="addon.check.v1"), timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready")
        self.assertFalse(self.calls.exists())

    def test_invalid_request_and_oversized_stdin(self):
        for request in ['{"source_url":"file:///fixture"}', '{"source_url":"https://example.test","extra":1}',
                        "x" * (64 * 1024 + 1), "{}"]:
            result = subprocess.run(self.command, input=request, text=True, capture_output=True,
                                    env=self.env, timeout=15)
            self.assertEqual(json.loads(result.stdout), {"outcome": "permanent_failure", "code": "invalid-source-check-request"})
        self.assertFalse(self.calls.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX process group fixture; host Job Object tests cover Windows")
    def test_cancellation_stops_the_process_group(self):
        self.data.write_text(json.dumps(self.payload))
        process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True,
                                   env=dict(self.env, FAKE_MODE="sleep"))
        try:
            process.stdin.write(json.dumps({"source_url": self.source}))
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic() + 5
            while not self.calls.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.calls.exists())
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertNotEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def test_manifest_and_bundle_include_source_check(self):
        manifest = tomllib.loads((ADDON / "addon.toml").read_text())
        self.assertIn({"id": "media-list.source-check.v1"}, manifest["capabilities"])
        archive = self.root / "candidate.zip"
        subprocess.run([sys.executable, str(ROOT / "tools/build_repository_bundle.py"),
                        "--output", str(archive)], check=True, capture_output=True)
        with zipfile.ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            path = "addons/org.ersatzrs.addon.yt-dlp/"
            for filename in ["libexec/source-check.ts", "libexec/item-options.ts", "addon.sh", "addon.bat"]:
                expected = (ADDON / filename).read_bytes()
                if filename == "addon.bat":
                    # Windows entrypoints have a platform-independent CRLF
                    # package contract; other source files remain byte-exact.
                    expected = expected.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                self.assertEqual(bundle.read(path + filename), expected)


if __name__ == "__main__":
    unittest.main()
