#!/usr/bin/env python3
"""Build the complete ErsatzRS offline add-on repository bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import tempfile
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = pathlib.Path("dist") / "ErsatzRS-addons.zip"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def repository_files() -> list[pathlib.Path]:
    manifest = ROOT / "repository.toml"
    addons = ROOT / "addons"
    if not manifest.is_file():
        raise ValueError("repository.toml is missing from the repository root")
    if not addons.is_dir():
        raise ValueError("addons directory is missing from the repository root")

    files = [manifest]
    for path in sorted(addons.rglob("*"), key=lambda item: item.relative_to(ROOT).as_posix()):
        if path.is_symlink():
            raise ValueError(f"repository bundle cannot contain a symlink: {path}")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ValueError(f"repository bundle contains an unsupported entry: {path}")
    if len(files) == 1:
        raise ValueError("repository bundle contains no add-on files")
    return files


def git_file_modes() -> dict[str, int]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--stage",
                "-z",
                "--",
                "repository.toml",
                "addons",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return {}
    if result.returncode != 0:
        return {}

    modes: dict[str, int] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        modes[path] = int(metadata.split(" ", 1)[0], 8) & 0o777
    return modes


def fallback_mode(path: pathlib.Path) -> int:
    if path.suffix == ".sh":
        return 0o755
    return 0o644


def write_bundle(output: pathlib.Path) -> tuple[int, str]:
    files = repository_files()
    modes = git_file_modes()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = pathlib.Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = modes.get(relative, fallback_mode(path))
                info.external_attr = mode << 16
                contents = path.read_bytes()
                if path.suffix.lower() in {".bat", ".cmd"}:
                    # cmd.exe can lose CALL labels in LF-only batch files. Make
                    # published bytes independent of the checkout platform.
                    contents = contents.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                archive.writestr(info, contents, compresslevel=9)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return len(files), digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"output path relative to the repository root (default: {DEFAULT_OUTPUT})",
    )
    arguments = parser.parse_args()
    output = arguments.output
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if output == ROOT / "repository.toml" or ROOT / "addons" in output.parents:
        parser.error("output must be outside repository.toml and the addons tree")

    try:
        file_count, digest = write_bundle(output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(f"Created {output} with {file_count} files (sha256: {digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
