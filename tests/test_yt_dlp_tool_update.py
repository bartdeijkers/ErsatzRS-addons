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
