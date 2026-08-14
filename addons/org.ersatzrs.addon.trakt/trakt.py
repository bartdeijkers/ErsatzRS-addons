#!/usr/bin/env python3
"""Trakt public-list adapter for ErsatzRS' media-list NDJSON contract."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.trakt.tv"
SLUG = re.compile(r"^[A-Za-z0-9_-]+$")


def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def parse_locator(value: str) -> tuple[str, str] | None:
    trimmed = value.strip()
    if not trimmed:
        return None
    if "://" in trimmed:
        parsed = urllib.parse.urlsplit(trimmed)
        if parsed.scheme != "https" or parsed.hostname not in {"trakt.tv", "app.trakt.tv"}:
            return None
        segments = [segment for segment in parsed.path.split("/") if segment]
    else:
        segments = [segment for segment in trimmed.split("/") if segment]

    if len(segments) == 4 and segments[0] == "users" and segments[2] == "lists":
        user, slug = segments[1], segments[3]
    elif len(segments) == 3 and segments[0] in {"users", "lists"}:
        user, slug = segments[1], segments[2]
    elif len(segments) == 3 and segments[1] == "lists":
        user, slug = segments[0], segments[2]
    elif len(segments) == 2:
        user, slug = segments[0], segments[1]
    else:
        return None
    if not SLUG.fullmatch(user) or not SLUG.fullmatch(slug):
        return None
    return user, slug


def client_id() -> str:
    value = os.environ.get("ERSATZRS_ADDON_SECRET_CLIENT_ID", "").strip()
    if value:
        return value
    path = os.environ.get("ERSATZRS_ADDON_SECRET_FILE_CLIENT_ID", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    except OSError:
        return ""


def request_json(path: str) -> tuple[object, dict[str, str]]:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Accept": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": client_id(),
            "User-Agent": "ErsatzRS-Trakt-Addon/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response), dict(response.headers.items())


def guid_values(ids: dict[str, object]) -> list[str]:
    result: list[str] = []
    for source in ("imdb", "tmdb", "tvdb"):
        value = ids.get(source)
        if value not in (None, ""):
            result.append(f"{source}://{value}")
    return result


def project_item(record: dict[str, object], rank: int) -> dict[str, object] | None:
    media_kind = str(record.get("type", ""))
    if media_kind not in {"movie", "show", "season", "episode"}:
        return None
    payload = record.get(media_kind)
    if not isinstance(payload, dict):
        return None
    ids = payload.get("ids")
    if not isinstance(ids, dict) or ids.get("trakt") is None:
        return None

    title = str(payload.get("title") or "")
    year = payload.get("year")
    season = payload.get("number") if media_kind == "season" else None
    episode = payload.get("number") if media_kind == "episode" else None
    show = record.get("show")
    if media_kind in {"season", "episode"} and isinstance(show, dict):
        title = str(show.get("title") or title)
        if year is None:
            year = show.get("year")
    if not title:
        title = f"{media_kind.title()} {ids['trakt']}"

    display_title = title
    if media_kind == "season" and season is not None:
        display_title = f"{title} - Season {season}"
    elif media_kind == "episode" and episode is not None:
        season_number = payload.get("season")
        display_title = f"{title} - S{int(season_number or 0):02}E{int(episode):02}"
    elif year is not None:
        display_title = f"{title} ({year})"

    item: dict[str, object] = {
        "record_type": "item",
        "provider_id": f"{media_kind}:{ids['trakt']}",
        "rank": rank,
        "display_title": display_title,
        "title": title,
        "kind": media_kind,
        "guids": guid_values(ids),
    }
    if year is not None:
        item["year"] = year
    if season is not None:
        item["season"] = season
    if episode is not None:
        item["episode"] = episode
        if isinstance(payload.get("season"), int):
            item["season"] = payload["season"]
    return item


def list_operation() -> int:
    source_url = os.environ.get("ERSATZRS_MEDIA_LIST_URL", "").strip()
    locator = parse_locator(source_url)
    if locator is None:
        print("unsupported public Trakt list URL", file=sys.stderr)
        return 64
    if not client_id():
        print("Trakt client ID reference is not configured", file=sys.stderr)
        return 78

    raw_user, raw_slug = locator
    user, slug = (urllib.parse.quote(value, safe="") for value in locator)
    list_path = f"/lists/{slug}" if raw_user.lower() == "official" else f"/users/{user}/lists/{slug}"
    metadata, _ = request_json(list_path)
    if not isinstance(metadata, dict):
        raise ValueError("Trakt list metadata response is invalid")
    ids = metadata.get("ids") if isinstance(metadata.get("ids"), dict) else {}
    provider_id = str(ids.get("trakt") or f"{raw_user}/{raw_slug}")
    emit(
        {
            "record_type": "list",
            "provider_id": provider_id,
            "name": str(metadata.get("name") or raw_slug),
            "description": metadata.get("description"),
        }
    )

    rank = 0
    page = 1
    while page <= 100:
        item_path = (
            f"/lists/{slug}/items"
            if raw_user.lower() == "official"
            else f"/users/{user}/lists/{slug}/items"
        )
        records, headers = request_json(f"{item_path}?extended=full&limit=100&page={page}")
        if not isinstance(records, list):
            raise ValueError("Trakt list-items response is invalid")
        for record in records:
            if isinstance(record, dict):
                item = project_item(record, rank)
                if item is not None:
                    emit(item)
                    rank += 1
        page_count = int(headers.get("X-Pagination-Page-Count", page))
        if page >= page_count or not records:
            break
        page += 1
    return 0


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else ""
    if operation == "check":
        if not client_id():
            emit(
                {
                    "status": "unavailable",
                    "code": "missing-client-id-reference",
                    "message": "Configure the client ID as a secret reference.",
                }
            )
        else:
            emit({"status": "ready", "code": "ready", "message": "Trakt Lists is ready."})
        return 0
    if operation == "list":
        return list_operation()
    print("unsupported add-on operation", file=sys.stderr)
    return 64


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TypeError, ValueError, KeyError) as error:
        print(f"Trakt request failed: {error}", file=sys.stderr)
        raise SystemExit(69) from None
