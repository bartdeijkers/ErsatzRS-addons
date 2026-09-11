"""Native updater protocol fixtures only; never updates an installed yt-dlp."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "org.ersatzrs.addon.yt-dlp"
REQUEST = {"schema": "tool.update.v1", "tool_key": "YT_DLP_BIN"}


@unittest.skipUnless(shutil.which("deno"), "Deno required")
class ToolUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tool update ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.calls = self.root / "calls.jsonl"
        provider = self.root / "fixture.py"
        provider.write_text('''import json, os, pathlib, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as log:
    log.write(json.dumps(args) + "\\n")
mode = os.environ.get("FAKE_MODE", "updated")
state = pathlib.Path(os.environ["FAKE_STATE"])
if "--version" in args:
    if mode == "malformed" or (mode == "after-malformed" and state.exists()):
        print("SYNTHETIC_PRIVATE_DIAGNOSTIC")
    else:
        print("2026.09.08" if state.exists() else "2026.09.01")
elif "-U" in args:
    if os.environ.get("FAKE_RELEASE_OUTPUT"):
        print(os.environ["FAKE_RELEASE_OUTPUT"])
    if mode == "timeout":
        time.sleep(60)
    if mode == "manual":
        print("ERROR: You installed yt-dlp from a manual build or with a package manager; Use that to update", file=sys.stderr)
        sys.exit(100)
    if mode == "pip":
        print("ERROR: You installed yt-dlp with pip or using the wheel from PyPi; Use that to update", file=sys.stderr)
        sys.exit(100)
    if mode == "readonly":
        print("ERROR: Insufficient permissions to write to SYNTHETIC_PRIVATE_PATH", file=sys.stderr)
        sys.exit(100)
    if mode == "network":
        print("ERROR: Unable to obtain version info: SYNTHETIC_PRIVATE_DIAGNOSTIC", file=sys.stderr)
        sys.exit(100)
    if mode == "unknown":
        print("ERROR: network text mentions package manager and permissions", file=sys.stderr)
        sys.exit(100)
    if mode == "limit":
        sys.stdout.write("x" * 17000)
    if mode in ("updated", "after-malformed"):
        state.write_text("updated")
else:
    sys.exit(90)
''', encoding="utf-8")
        if os.name == "nt":
            fake = self.root / "fake yt-dlp.cmd"
            fake.write_text('@echo off\n"%PYTHON%" "%FAKE_PROVIDER%" %*\n')
            self.command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ADDON / "addon.bat"), "update"]
        else:
            fake = self.root / "fake yt-dlp"
            fake.write_text('#!/bin/sh\nexec "$PYTHON" "$FAKE_PROVIDER" "$@"\n')
            fake.chmod(0o755)
            self.command = ["/bin/sh", str(ADDON / "addon.sh"), "update"]
        self.env = dict(os.environ, PYTHON=sys.executable, FAKE_PROVIDER=str(provider),
                        FAKE_CALLS=str(self.calls), FAKE_STATE=str(self.root / "state"),
                        ERSATZRS_ADDON_SETTING_YT_DLP_BIN=str(fake), YT_DLP_BIN=str(fake))
        self.fake = fake

    def release_output(self, channel="stable", current="2026.09.01", latest="2026.09.08"):
        origin = {"stable": "yt-dlp/yt-dlp", "nightly": "yt-dlp/yt-dlp-nightly-builds", "master": "yt-dlp/yt-dlp-master-builds"}[channel]
        return f"Current version: {channel}@{current} from {origin}\nLatest version: {channel}@{latest} from {origin}"

    def enable_health(self):
        data = self.root / "provider data"
        data.mkdir()
        self.env["ERSATZRS_ADDON_DATA_DIR"] = str(data)
        self.env["FAKE_RELEASE_OUTPUT"] = self.release_output()
        self.env["FFMPEG_BIN"] = str(self.fake)
        return data / "tool-update-health.json"

    def readiness(self):
        completed = subprocess.run(self.command[:-1] + ["check"], text=True, capture_output=True,
                                   env=self.env, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        return json.loads(completed.stdout)

    def test_failed_confirmed_stale_warns_without_network_on_readiness(self):
        state = self.enable_health()
        for channel in ("stable", "nightly", "master"):
            self.env["FAKE_RELEASE_OUTPUT"] = self.release_output(channel)
            self.assertEqual(self.invoke("manual")["outcome"], "manual_update_required")
            self.assertEqual(self.readiness()["code"], "tool-update-failed-stale")
            payload = state.read_text()
            self.assertLess(len(payload), 1024)
            self.assertNotIn(str(self.fake), payload)
            self.assertNotIn("SYNTHETIC_PRIVATE", payload)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(sum("-U" in args for args in calls), 3)

    def test_unknown_conflicting_cross_channel_and_nonstale_evidence_clears_warning(self):
        self.enable_health()
        invalid = ["", "Latest version: unknown", self.release_output() + "\n" + self.release_output(),
                   self.release_output().replace("Latest version: stable", "Latest version: nightly"),
                   self.release_output(latest="2026.09.01"), self.release_output(latest="2026.08.01"),
                   self.release_output(current="2026.09.02"), self.release_output().replace("Latest version:", "Requested version:")]
        for output in invalid:
            with self.subTest(output=output):
                self.env["FAKE_RELEASE_OUTPUT"] = self.release_output()
                self.invoke("network")
                self.assertEqual(self.readiness()["status"], "warning")
                self.env["FAKE_RELEASE_OUTPUT"] = output
                self.invoke("network")
                self.assertEqual(self.readiness()["status"], "ready")

    def test_success_manual_repair_and_next_attempt_clear_warning(self):
        self.enable_health()
        self.invoke("manual")
        self.assertEqual(self.readiness()["status"], "warning")
        self.invoke("noop")
        self.assertEqual(self.readiness()["status"], "ready")
        self.invoke("manual")
        Path(self.env["FAKE_STATE"]).write_text("manually repaired")
        self.assertEqual(self.readiness()["status"], "ready")
        Path(self.env["FAKE_STATE"]).unlink()
        self.assertEqual(self.readiness()["status"], "ready")

    def test_missing_directory_identity_malformed_and_oversized_state(self):
        state = self.enable_health()
        self.invoke("manual")
        valid = json.loads(state.read_text())
        for content in ("invalid", "x" * 1025, json.dumps(dict(valid, identity="0" * 64))):
            state.write_text(content)
            self.assertEqual(self.readiness()["status"], "ready")
        self.env["ERSATZRS_ADDON_DATA_DIR"] = str(self.root / "missing" / "nested provider data")
        self.assertEqual(self.invoke("manual")["outcome"], "manual_update_required")
        self.assertEqual(self.readiness()["status"], "warning")

    def test_missing_command_precedes_update_warning(self):
        self.enable_health()
        self.invoke("manual")
        self.env["FFMPEG_BIN"] = str(self.root / "missing-ffmpeg")
        self.assertEqual(self.readiness()["code"], "missing-command")

    def test_failed_atomic_write_invalidates_previous_warning(self):
        state = self.enable_health()
        self.invoke("manual")
        self.assertEqual(self.readiness()["status"], "warning")
        temporary = Path(str(state) + ".tmp")
        temporary.mkdir()
        (temporary / "synthetic blocker").write_text("fixture")
        self.env["FAKE_RELEASE_OUTPUT"] = ""
        self.assertEqual(self.invoke("noop")["outcome"], "already_current")
        self.assertFalse(state.exists())
        self.assertEqual(self.readiness()["status"], "ready")

    def test_valid_warning_requires_only_read_permission(self):
        state = self.enable_health()
        self.invoke("manual")
        completed = subprocess.run(
            ["deno", "run", "--quiet", "--no-prompt", "--allow-env=YT_DLP_BIN,ERSATZRS_ADDON_DATA_DIR,ERSATZRS_ADDON_CHECK_CONTEXT_VERSION",
             "--allow-run", "--allow-read=" + str(state.parent), str(ADDON / "libexec/tool-health.ts")],
            text=True, capture_output=True, env=self.env, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout)["code"], "tool-update-failed-stale")

    def test_warning_context_requires_host_advertisement(self):
        self.enable_health()
        self.env.pop("ERSATZRS_ADDON_CHECK_CONTEXT_VERSION", None)
        self.invoke("manual")
        legacy = self.readiness()
        self.assertEqual(set(legacy), {"status", "code", "message"})
        for text in ("yt-dlp", "2026.09.01", "2026.09.08"):
            self.assertIn(text, legacy["message"])
        self.env["ERSATZRS_ADDON_CHECK_CONTEXT_VERSION"] = "1"
        self.assertEqual(self.readiness()["tool_update"], {
            "program": "yt-dlp", "installed_version": "2026.09.01", "latest_version": "2026.09.08"})
        self.env["ERSATZRS_ADDON_CHECK_CONTEXT_VERSION"] = "2"
        self.assertNotIn("tool_update", self.readiness())
        self.env["ERSATZRS_ADDON_CHECK_CONTEXT_VERSION"] = "1"
        self.invoke("noop")
        self.assertEqual(set(self.readiness()), {"status", "code", "message"})

    def invoke(self, mode="updated", request=REQUEST, command=None):
        completed = subprocess.run(command or self.command, input=json.dumps(request), text=True,
                                   capture_output=True, env=dict(self.env, FAKE_MODE=mode), timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertLessEqual(len(completed.stdout.encode()), 2048)
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        self.assertNotIn("SYNTHETIC_PRIVATE", completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema"], "tool.update.v1")
        self.assertEqual(result["tool_key"], "YT_DLP_BIN")
        return result

    def test_update_uses_native_arguments_and_before_after_versions(self):
        result = self.invoke()
        self.assertEqual(result["outcome"], "updated")
        self.assertEqual(result["before_version"], "2026.09.01")
        self.assertEqual(result["after_version"], "2026.09.08")
        self.assertIsNone(result["diagnostic_code"])
        args = [json.loads(line) for line in self.calls.read_text().splitlines()]
        probe = ["--no-config", "--no-plugin-dirs", "--no-update", "--version"]
        self.assertEqual(args, [probe, ["--no-config", "--no-plugin-dirs", "-U"], probe])

    def test_unchanged_version_is_already_current(self):
        result = self.invoke("noop")
        self.assertEqual(result["outcome"], "already_current")
        self.assertEqual(result["before_version"], result["after_version"])
        self.assertIsNone(result["diagnostic_code"])

    def test_native_manual_and_readonly_diagnostics(self):
        for mode in ("manual", "pip", "readonly"):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result["outcome"], "manual_update_required")
                self.assertEqual(result["diagnostic_code"], "unsupported_installation")

    def test_network_unknown_and_output_limit_fail_closed(self):
        for mode in ("network", "unknown", "limit"):
            with self.subTest(mode=mode):
                result = self.invoke(mode)
                self.assertEqual(result["outcome"], "failed")
                self.assertEqual(result["diagnostic_code"], "update_failed")

    def test_malformed_version_never_updates(self):
        result = self.invoke("malformed")
        self.assertEqual(result["diagnostic_code"], "version_probe_failed")
        self.assertIsNone(result["before_version"])
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)

    def test_failed_after_probe_is_not_reported_updated(self):
        result = self.invoke("after-malformed")
        self.assertEqual(result["outcome"], "failed")
        self.assertIsNone(result["after_version"])

    def test_invalid_request_never_invokes_tool(self):
        result = self.invoke(request={"schema": "tool.update.v1", "tool_key": "FFMPEG_BIN"})
        self.assertEqual(result["outcome"], "failed")
        self.assertFalse(self.calls.exists())

    @unittest.skipUnless(os.name == "posix", "Windows native deadline counterpart is in PowerShell")
    def test_real_subprocess_deadline_fails_without_unsafe_diagnostics(self):
        # Dependency injection shortens only the synthetic test. Production
        # request/environment input cannot override its fixed 60-second deadline.
        driver = self.root / "deadline.ts"
        driver.write_text(
            'import { updateTool } from ' + json.dumps((ADDON / "libexec/tool-update.ts").as_uri()) + ';\n'
            'import { boundedCommand } from ' + json.dumps((ADDON / "libexec/item-options.ts").as_uri()) + ';\n'
            'const run = (exe: string, args: string[], _ms?: number, cap?: number) => '
            'boundedCommand(exe, args, args.includes("-U") ? 50 : 10000, cap);\n'
            'console.log(JSON.stringify(await updateTool(' + json.dumps(REQUEST) +
            ', Deno.env.get("YT_DLP_BIN")!, run)));\n')
        result = self.invoke("timeout", command=["deno", "run", "--quiet", "--allow-env=YT_DLP_BIN",
                                                 "--allow-run", str(driver)])
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["diagnostic_code"], "update_failed")


if __name__ == "__main__":
    unittest.main()
