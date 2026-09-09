"""Provision pinned, checksum-verified media fixtures in the hosted runner temp directory."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile


def download(url: str, target: Path, sha256: str) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    with target.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != sha256:
        raise RuntimeError(f"Checksum mismatch for {target.name}")


def main() -> None:
    # This is CI fixture setup, never an installer for the operator's tools.
    system = platform.system()
    if system not in ("Windows", "Linux") or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("This fixture setup supports the workflow's Windows/Linux x64 runners")
    root = Path(tempfile.mkdtemp(prefix="addon-test-tools-", dir=os.environ["RUNNER_TEMP"]))
    yt_dlp = root / "yt-dlp"
    download("https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp", yt_dlp,
             "1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6")
    if system == "Windows":
        name = "ersatzrs-ffmpeg-2.0.0-win-x64.zip"
        digest = "176c11d8aceb20eb05025609d91335e7b8d23861567b1099337d0579c19f479a"
    else:
        name = "ersatzrs-ffmpeg-2.0.0-linux-x64.tar.gz"
        digest = "b95a3afe004b542e482c60c99499fdb4441c0115778bcfa9dbf07a9f6b5ea7f7"
    archive_path = root / name
    download(f"https://github.com/bartdeijkers/ErsatzRS-ffmpeg/releases/download/v2.0.0/{name}",
             archive_path, digest)
    if system == "Windows":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(root)
    else:
        with tarfile.open(archive_path) as archive:
            archive.extractall(root, filter="data")
    suffix = ".exe" if system == "Windows" else ""
    ffmpeg, = root.rglob("ffmpeg" + suffix)
    ffprobe, = root.rglob("ffprobe" + suffix)
    values = {"YT_DLP_TEST_ZIP": yt_dlp, "FFMPEG_BIN": ffmpeg, "FFPROBE_BIN": ffprobe}
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
