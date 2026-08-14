#!/usr/bin/env python3
"""Project Schatkamer programme links onto the media-list NDJSON contract."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import urllib.parse


def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    source_url = os.environ.get("ERSATZRS_MEDIA_LIST_URL", "").strip()
    if not source_url:
        print("Schatkamer URL is required", file=sys.stderr)
        return 64
    script_dir = pathlib.Path(__file__).resolve().parent
    if os.name == "nt":
        command = ["cmd.exe", "/d", "/c", str(script_dir / "beeldengeluid.bat"), "list", source_url]
    else:
        command = ["/bin/sh", str(script_dir / "beeldengeluid.sh"), "list", source_url]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=os.environ)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode

    parsed = urllib.parse.urlsplit(source_url)
    provider_id = parsed.path.strip("/")
    if parsed.query:
        provider_id = f"{provider_id}?{parsed.query}"
    emit(
        {
            "record_type": "list",
            "provider_id": provider_id,
            "name": "Beeld & Geluid Schatkamer",
            "description": "Programmes selected by the supplied Schatkamer link.",
        }
    )
    rank = 0
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        item: dict[str, object] = {
            "record_type": "item",
            "provider_id": f"episode:{row['id']}",
            "rank": rank,
            "display_title": row.get("title") or str(row["id"]),
            "title": row.get("title") or str(row["id"]),
            "kind": "episode",
            "guids": [],
        }
        if isinstance(row.get("year"), int):
            item["year"] = row["year"]
        emit(item)
        rank += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
