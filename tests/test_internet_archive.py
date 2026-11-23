"""Internet Archive add-on: source parsing, listing, records and playback plans.

Every provider response is a synthetic fixture; no test contacts archive.org.
"""
from __future__ import annotations

import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addons" / "org.ersatzrs.addon.internet-archive"
HARNESS = ROOT / "tests" / "fixtures" / "internet-archive" / "harness.mts"
VALIDATOR = ROOT / "tools" / "validator" / "ersatzrs-addon-validator-x86_64-unknown-linux-gnu"
METADATA = "https://archive.org/metadata/"
SCRAPE = "https://archive.org/services/search/v1/scrape"

REMOTE_STREAM_V4_FIELDS = {
    "id", "url", "title", "duration_seconds", "thumbnail_url", "is_live", "plot",
    "year", "release_date", "content_rating", "genres", "tags", "collection",
    "people", "producers", "original_broadcasters", "broadcasters", "provider_id",
    "availability", "availability_reason", "content_kind", "original_title",
    "sort_title", "outline", "tagline", "show_title", "season", "episode", "guids",
    "additional_image_urls", "parent_provider_id", "fragment_start_seconds",
    "fragment_end_seconds", "liveness",
}


def video_item(identifier: str, files: list[dict], **metadata) -> dict:
    return {
        "metadata": {"identifier": identifier, "mediatype": "movies", **metadata},
        "files": files,
    }


SERIES = video_item(
    "fixture-series",
    [
        {"name": "episode_02.avi", "source": "original", "format": "Cinepack", "length": "1500.2"},
        {"name": "episode_02.mp4", "source": "derivative", "original": "episode_02.avi", "format": "h.264", "height": "480"},
        {"name": "episode_02.ogv", "source": "derivative", "original": "episode_02.avi", "format": "Ogg Video"},
        {"name": "episode_01.mpeg", "source": "original", "format": "MPEG2", "length": "1400"},
        {"name": "episode_01_512kb.mp4", "source": "derivative", "original": "episode_01.mpeg", "format": "512Kb MPEG4"},
        {"name": "episode_01.gif", "source": "derivative", "original": "episode_01.mpeg", "format": "Animated GIF"},
        {"name": "fixture-series.thumbs/episode_01_000001.jpg", "source": "derivative", "format": "Thumbnail"},
        {"name": "episode_01.srt", "source": "original", "format": "SubRip"},
    ],
    title="Fixture Series",
    date="1987-05-02",
    description="<div>First line.</div><div>Second &amp; last.</div>",
    subject="history; television;History",
    creator="Fixture Studio",
    collection=["classic_tv", "television"],
    language="eng",
)

SINGLE = video_item(
    "fixture-single",
    [
        {"name": "programme.mp4", "source": "original", "format": "h.264", "length": "61.5"},
        {"name": "programme.ogv", "source": "derivative", "original": "programme.mp4", "format": "Ogg Video"},
    ],
    title="Fixture Single",
    date="1994",
    runtime="25:47:00",
)

COLLECTION = {"metadata": {"identifier": "fixture-collection", "mediatype": "collection", "title": "Fixture Collection"}}
PAGE_ONE = {
    "items": [
        {"identifier": "first-item", "title": "First", "date": "1990-01-01T00:00:00Z", "runtime": "22:44",
         "collection": ["feature_films"]},
        {"identifier": "second-item", "title": "Second", "subject": ["a", "b"]},
    ],
    "cursor": "next-page",
}
PAGE_TWO = {"items": [{"identifier": "third-item", "title": "Third", "runtime": "1:05:12"}]}


def runtime_command() -> list[str] | None:
    deno = shutil.which("deno")
    if deno:
        return [deno, "run", "--quiet", "--no-prompt", "--allow-read", str(HARNESS)]
    node = shutil.which("node")
    if node:
        return [node, "--no-warnings", str(HARNESS)]
    return None


@unittest.skipUnless(runtime_command(), "Deno or Node.js is required")
class InternetArchiveTests(unittest.TestCase):
    def harness(self, request: dict):
        result = subprocess.run(
            runtime_command(), input=json.dumps(request), text=True,
            capture_output=True, check=False, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def records(self, op: str, url: str, responses: list, **extra) -> tuple[list[dict], list[str]]:
        result = self.harness({"op": op, "url": url, "responses": responses, **extra})
        return [json.loads(line) for line in result["lines"].splitlines()], result["fetched"]

    def test_accepts_item_file_collection_and_search_links_only(self) -> None:
        cases = {
            "https://archive.org/details/fixture-series": {"kind": "details", "identifier": "fixture-series"},
            "https://www.archive.org/details/fixture-series/episode_01.mpeg":
                {"kind": "details", "identifier": "fixture-series", "file": "episode_01.mpeg"},
            "https://archive.org/details/fixture/sub%20dir/a%20b.mp4":
                {"kind": "details", "identifier": "fixture", "file": "sub dir/a b.mp4"},
            "https://archive.org/search?query=bob+ross": {"kind": "search", "query": "bob ross"},
            "https://archive.org/search.php?query=collection%3Aprelinger": {"kind": "search", "query": "collection:prelinger"},
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(self.harness({"op": "source", "url": url}), expected)
        for url in [
            "https://example.test/details/fixture",
            "https://archive.org.example.test/details/fixture",
            "https://user:secret@archive.org/details/fixture",
            "https://archive.org/details/@uploader",
            "https://archive.org/details/fixture/../../etc",
            "https://archive.org/search?query=",
            "https://archive.org/about",
            "ftp://archive.org/details/fixture",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.harness({"op": "source", "url": url}), {"error": "unsupported-url"})

    def test_parses_free_text_runtime_and_dates(self) -> None:
        self.assertEqual(
            self.harness({"op": "runtime", "values": ["22:44", "1:05:12", "25:47:00", "1485.05", "25 min", "soon", "0:00"]}),
            [1364, 3912, 1547, 1485, 1500, None, None],
        )
        self.assertEqual(
            self.harness({"op": "date", "values": ["1994", "1994-03", "1994-03-12", "1990-01-01T00:00:00Z", "1994-02-30", "circa 1950", "0999"]}),
            [{"year": 1994}, {"year": 1994}, {"year": 1994, "date": "1994-03-12"},
             {"year": 1990, "date": "1990-01-01"}, {"year": 1994}, {}, {}],
        )

    def test_one_programme_per_uploaded_video_with_the_most_portable_file(self) -> None:
        found = self.harness({"op": "programmes", "files": SERIES["files"]})
        self.assertEqual([(p["original"], p["playable"]) for p in found], [
            ("episode_01.mpeg", "episode_01_512kb.mp4"),
            ("episode_02.avi", "episode_02.mp4"),
        ])
        self.assertEqual(found[1]["durationSeconds"], 1500)
        self.assertEqual(found[1]["height"], 480)

    def test_multi_video_item_lists_each_programme_with_shared_metadata(self) -> None:
        url = "https://archive.org/details/fixture-series"
        rows, fetched = self.records("media-list", url, [[METADATA, SERIES]])
        self.assertEqual(fetched, [METADATA + "fixture-series"])
        self.assertEqual(rows[0]["record_type"], "list")
        self.assertEqual(rows[0]["name"], "Fixture Series")
        items = rows[1:]
        self.assertEqual([item["provider_id"] for item in items],
                         ["fixture-series/episode_01.mpeg", "fixture-series/episode_02.avi"])
        self.assertEqual(items[0]["source_url"], url + "/episode_01.mpeg")
        self.assertEqual(items[0]["title"], "Fixture Series – episode 01")
        self.assertEqual([item["rank"] for item in items], [0, 1])
        self.assertTrue(all(item["kind"] == "remote_stream" and item["liveness"] == "finite" for item in items))
        self.assertEqual(items[1]["content_kind"], "television_episode")
        metadata = items[0]["metadata"]
        self.assertEqual(metadata["plot"], "First line.\n\nSecond & last.")
        self.assertEqual(metadata["release_date"], "1987-05-02")
        self.assertEqual(metadata["tags"], ["history", "television"])
        self.assertEqual(metadata["people"], [{"name": "Fixture Studio", "role": "Creator", "order": 0}])
        self.assertEqual(metadata["artwork"], [{"url": "https://archive.org/services/img/fixture-series", "role": "thumb"}])
        self.validate(rows)

    def test_file_link_selects_only_that_programme(self) -> None:
        rows, _ = self.records("media-list", "https://archive.org/details/fixture-series/episode_02.mp4",
                               [[METADATA, SERIES]])
        self.assertEqual([row["provider_id"] for row in rows[1:]], ["fixture-series/episode_02.avi"])

    def test_single_video_item_uses_the_item_identity(self) -> None:
        rows, _ = self.records("media-list", "https://archive.org/details/fixture-single", [[METADATA, SINGLE]])
        self.assertEqual(rows[1]["provider_id"], "fixture-single")
        self.assertEqual(rows[1]["source_url"], "https://archive.org/details/fixture-single")
        self.assertEqual(rows[1]["duration_seconds"], 62)
        self.assertEqual(rows[1]["year"], 1994)
        self.assertEqual(rows[1]["content_kind"], "auto")
        self.validate(rows)

    def test_withdrawn_item_stays_visible_as_unavailable(self) -> None:
        dark = {"is_dark": True, "metadata": {"identifier": "gone", "title": "Gone"}}
        rows, _ = self.records("media-list", "https://archive.org/details/gone", [[METADATA, dark]])
        self.assertEqual(rows[1]["availability"], "unavailable")
        self.assertEqual(rows[1]["availability_reason_code"], "unavailable")
        restricted = video_item("lent", SINGLE["files"], title="Lent", **{"access-restricted-item": "true"})
        rows, _ = self.records("media-list", "https://archive.org/details/lent", [[METADATA, restricted]])
        self.assertEqual(rows[1]["availability_reason_code"], "content_restricted")
        self.validate(rows)

    def test_collection_and_search_records_follow_both_contracts(self) -> None:
        # Discover the exact first-page URL, then serve the cursor page for it.
        first = self.harness({"op": "media-list", "url": "https://archive.org/details/fixture-collection",
                              "responses": [[METADATA, COLLECTION], [SCRAPE, PAGE_TWO]]})["fetched"][1]
        self.assertIn("q=%28collection%3A%28fixture-collection%29%29+AND+mediatype%3A%28movies%29", first)
        cursor_prefix = first + "&cursor=next-page"
        responses = [[METADATA, COLLECTION], [SCRAPE, PAGE_ONE], [cursor_prefix, PAGE_TWO]]
        rows, fetched = self.records("media-list", "https://archive.org/details/fixture-collection", responses)
        self.assertEqual(fetched[-1], cursor_prefix)
        self.assertEqual(rows[0]["name"], "Fixture Collection")
        self.assertEqual([row["provider_id"] for row in rows[1:]], ["first-item", "second-item", "third-item"])
        self.assertEqual(rows[1]["content_kind"], "movie")
        self.assertEqual(rows[1]["duration_seconds"], 1364)
        self.assertEqual(rows[3]["duration_seconds"], 3912)
        self.validate(rows)

        search = "https://archive.org/search?query=fixture"
        first = self.harness({"op": "remote-stream", "url": search, "responses": [[SCRAPE, PAGE_TWO]]})["fetched"][0]
        responses = [[SCRAPE, PAGE_ONE], [first + "&cursor=next-page", PAGE_TWO]]
        streams, _ = self.records("remote-stream", search, responses)
        self.assertEqual([row["id"] for row in streams], ["first-item", "second-item", "third-item"])
        for row in streams:
            self.assertLessEqual(set(row), REMOTE_STREAM_V4_FIELDS)
            self.assertEqual(row["liveness"], "finite")
        self.assertEqual(streams[0]["release_date"], "1990-01-01T00:00:00Z")
        self.assertEqual(streams[1]["tags"], ["a", "b"])
        compact, _ = self.records("remote-stream", search, responses, compact=True)
        self.assertNotIn("tags", compact[1])

    def test_playback_streams_the_chosen_file_with_the_host_seek(self) -> None:
        result = self.harness({"op": "play", "url": "https://archive.org/details/fixture-series/episode_02.avi",
                               "seek": "00:01:30.500", "responses": [[METADATA, SERIES]]})
        self.assertEqual(result["plan"]["input"], "https://archive.org/download/fixture-series/episode_02.mp4")
        args = result["args"]
        self.assertEqual(args[args.index("-ss") + 1], "00:01:30.500")
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertEqual(args[args.index("-c") + 1], "copy")
        self.assertEqual(args[args.index("-f") + 1], "mpegts")
        self.assertEqual(args[-1], "pipe:1")
        self.assertIn("ErsatzRS-InternetArchive/", args[args.index("-user_agent") + 1])

        first = self.harness({"op": "play", "url": "https://archive.org/details/fixture-series",
                              "seek": "0", "responses": [[METADATA, SERIES]]})
        self.assertEqual(first["plan"]["programme"]["original"], "episode_01.mpeg")
        self.assertNotIn("-ss", first["args"])

        ogg = video_item("ogg", [{"name": "a.ogv", "source": "original", "format": "Ogg Video"}])
        result = self.harness({"op": "play", "url": "https://archive.org/details/ogg", "responses": [[METADATA, ogg]]})
        self.assertEqual(result["args"][result["args"].index("-f") + 1], "matroska")

        dark = {"is_dark": True, "metadata": {}}
        self.assertEqual(self.harness({"op": "play", "url": "https://archive.org/details/gone",
                                       "responses": [[METADATA, dark]]}), {"error": "item-unavailable"})
        self.assertEqual(self.harness({"op": "play", "url": "https://archive.org/search?query=x",
                                       "responses": []}), {"error": "unsupported-url"})

    def test_repeated_search_results_are_listed_once(self) -> None:
        rows, fetched = self.records("media-list", "https://archive.org/search?query=fixture", [[SCRAPE, PAGE_ONE]])
        self.assertEqual(len(fetched), 2)
        self.assertEqual([row["provider_id"] for row in rows[1:]], ["first-item", "second-item"])
        self.assertEqual(rows[0]["name"], "Internet Archive: fixture")

    def test_seek_values(self) -> None:
        self.assertEqual(
            self.harness({"op": "seek", "values": ["", "{seek}", "0", "00:00:00.000", "12.5", "01:02:03.250", "-5", "1;rm"]}),
            [None, None, None, None, "12.5", "01:02:03.250", "invalid", "invalid"],
        )

    def validate(self, rows: list[dict]) -> None:
        if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64") or not VALIDATOR.is_file():
            return
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "output.ndjson"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            result = subprocess.run([str(VALIDATOR), "--kind", "media-list-output", str(path)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipIf(os.name == "nt", "POSIX entrypoint")
class InternetArchiveEntrypointTests(unittest.TestCase):
    def run_entrypoint(self, script: str, operation: str, **env) -> subprocess.CompletedProcess:
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env}
        return subprocess.run(["sh", str(PACKAGE / script), operation], capture_output=True,
                              text=True, check=False, env=environment)

    def test_check_reports_one_json_object(self) -> None:
        for script, runtime in [("addon.sh", "deno"), ("addon-node.sh", "node")]:
            with self.subTest(script=script):
                result = self.run_entrypoint(script, "check", FFMPEG_BIN=shutil.which("sh") or "/bin/sh")
                self.assertEqual(result.returncode, 0, result.stderr)
                document = json.loads(result.stdout)
                self.assertEqual(set(document), {"status", "code", "message"})
                expected = "ready" if shutil.which(runtime) else "unavailable"
                self.assertEqual(document["status"], expected)

    def test_missing_ffmpeg_is_unavailable(self) -> None:
        for script, runtime in [("addon.sh", "deno"), ("addon-node.sh", "node")]:
            if not shutil.which(runtime):
                continue
            with self.subTest(script=script):
                document = json.loads(self.run_entrypoint(script, "check").stdout)
                self.assertEqual((document["status"], document["code"]), ("unavailable", "missing-command"))

    def test_failures_end_with_one_structured_stderr_line(self) -> None:
        for script, runtime in [("addon.sh", "deno"), ("addon-node.sh", "node")]:
            if not shutil.which(runtime):
                continue
            with self.subTest(script=script):
                for operation, env, code in [
                    ("bogus", {}, "operation-failed"),
                    ("list", {}, "missing-setting"),
                    ("list", {"ERSATZRS_MEDIA_LIST_URL": "https://example.test/x"}, "unsupported-url"),
                ]:
                    result = self.run_entrypoint(script, operation, **env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stderr.strip().splitlines()[-1])["code"], code)

    def test_windows_entrypoint_routes_every_operation(self) -> None:
        text = (PACKAGE / "addon.bat").read_text(encoding="utf-8")
        for operation in ("check", "list", "play"):
            self.assertIn(f'if /i "%OPERATION%"=="{operation}" goto :{operation}', text)
        self.assertIn("--allow-net=archive.org", text)


if __name__ == "__main__":
    unittest.main()
