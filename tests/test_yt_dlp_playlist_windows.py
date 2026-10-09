"""Discover the provider-free Windows Remote Stream title regression in CI."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell required")
class WindowsPlaylistTests(unittest.TestCase):
    def test_missing_titles_preserve_addressable_entries(self):
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(ROOT / "tests" / "test_yt_dlp_playlist_windows.ps1")],
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: native Windows listing", result.stdout)


if __name__ == "__main__":
    unittest.main()
