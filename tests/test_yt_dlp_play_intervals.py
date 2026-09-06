"""Offline argv and lifecycle checks; synthetic stdout is not a NUT media proof."""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import unittest

import test_yt_dlp_item_operations as fixtures


@unittest.skipUnless(os.name == "posix" and shutil.which("deno"), "POSIX and Deno required")
class PlayIntervalsTests(unittest.TestCase):
    def setUp(self) -> None:
        fixtures.ItemOperationsTests.setUp(self)
        # Change only this class's generated fake, not shared operation fixtures.
        program = self.root / "fixture.py"
        source = program.read_text(encoding="utf-8")
        source = source.replace('    sys.stdout.buffer.write(b"synthetic media stream")',
                                '    prefix = b"nut/multimedia container\\0"\n'
                                '    if mode == "native-truncated": prefix = prefix[:12]\n'
                                '    if mode == "native-mismatch": prefix = b"x" + prefix[1:]\n'
                                '    sys.stdout.buffer.write(prefix + (b"" if mode == "native-truncated" else b"synthetic media stream"))\n'
                                '    if mode == "native-failure":\n'
                                '        sys.stderr.write("SYNTHETIC_PRIVATE_DIAGNOSTIC")\n'
                                '        sys.exit(1)')
        program.write_text(source, encoding="utf-8")

    invoke = fixtures.ItemOperationsTests.invoke
    options = fixtures.ItemOperationsTests.options
    arguments = fixtures.ItemOperationsTests.arguments

    def request(self) -> dict:
        return {"source_url": "https://www.youtube.com/watch?v=fixture&start=2&end=18",
                "provider_id": "fixture", "context_fingerprint": "a" * 64,
                "source_duration_milliseconds": 20000, "max_video_height": 720,
                "options": self.options("none", True),
                "retained_intervals_milliseconds": [{"start": 1000, "end": 3000}, {"start": 10000, "end": 12000}]}

    def media(self) -> dict:
        return {"id": "fixture", "duration": 20, "live_status": "not_live", "is_live": False,
                "vcodec": "h264", "acodec": "aac", "height": 720, "dynamic_range": "SDR",
                "url": "https://cdn.example.invalid/media?signature=fixture-placeholder"}

    def play(self, media: dict | None = None, request: dict | None = None):
        self.environment["FIXTURE_RESOLVE"] = json.dumps(self.media() if media is None else media)
        return self.invoke("play-intervals", self.request() if request is None else request)

    def assert_failed(self, result) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        for private in ("https://", "fixture-placeholder", "SYNTHETIC_PRIVATE_DIAGNOSTIC", str(self.root)):
            self.assertNotIn(private, result.stderr)

    def test_one_extraction_sequential_raw_sections_and_private_file_cleanup(self) -> None:
        result = self.play()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "nut/multimedia container\0" + "synthetic media stream" * 2)
        extraction, first, second = self.arguments()
        self.assertIn("--dump-single-json", extraction)
        self.assertEqual(extraction[-1], "https://www.youtube.com/watch?v=fixture")
        selector = extraction[extraction.index("--format") + 1]
        self.assertIn("bestvideo[protocol^=m3u8][vcodec^=avc1][height<=720]+bestaudio[protocol^=m3u8]", selector)
        self.assertIn("bestvideo[height<=720]+bestaudio", selector)
        self.assertNotIn("--version", extraction)
        info_paths = []
        for args, section, preroll, offset in [(first, "*0.000-3.000", "1.000", "0.000"),
                                               (second, "*8.000-12.000", "2.000", "2.000")]:
            self.assertEqual(args[args.index("--download-sections") + 1], section)
            self.assertEqual(args[args.index("--output") + 1], "-")
            self.assertIn("--force-keyframes-at-cuts", args)
            self.assertIn("ffmpeg_i:-threads 1", args)
            self.assertIn(f"ffmpeg_o:-threads 1 -xerror -ss {preroll} -c:v rawvideo -pix_fmt yuv420p -c:a pcm_f32le -f nut -write_index 0 -output_ts_offset {offset}", args)
            for forbidden in ("--dump-single-json", "--sponsorblock-remove", "--sponsorblock-mark"):
                self.assertNotIn(forbidden, args)
            self.assertFalse(any(arg.startswith("https://") for arg in args))
            info_paths.append(pathlib.Path(args[args.index("--load-info-json") + 1]))
        self.assertEqual(info_paths[0], info_paths[1])
        self.assertFalse(info_paths[0].parent.exists())

    def test_separate_formats_and_browser_enums_stay_owned_by_yt_dlp(self) -> None:
        info = self.media()
        video, audio = copy.deepcopy(info), copy.deepcopy(info)
        video["acodec"] = "none"
        audio["vcodec"] = "none"
        info["requested_formats"] = [video, audio]
        for browser in ("none", "firefox", "chrome", "chromium"):
            self.log.unlink(missing_ok=True)
            request = self.request()
            request["options"] = self.options(browser, True)
            result = self.play(info, request)
            self.assertEqual(result.returncode, 0, result.stderr)
            for args in self.arguments():
                if browser == "none":
                    self.assertNotIn("--cookies-from-browser", args)
                else:
                    self.assertEqual(args[args.index("--cookies-from-browser") + 1], browser)

    def test_large_native_metadata_and_audio_without_codec_fields_are_preserved(self) -> None:
        info = self.media()
        video = copy.deepcopy(info)
        video["acodec"] = "none"
        info["requested_formats"] = [video, {
            "format_id": "234-12", "protocol": "m3u8_native",
            "url": "https://cdn.example.invalid/audio.m3u8",
        }]
        info["automatic_captions"] = {"en": [{"url": "https://cdn.example.invalid/captions",
                                               "fixture_padding": "x" * (5 * 1024 * 1024)}]}
        metadata = self.root / "native-metadata.json"
        metadata.write_text(json.dumps(info), encoding="utf-8")
        self.assertGreater(metadata.stat().st_size, 4 * 1024 * 1024)
        self.environment["FIXTURE_METADATA_FILE"] = str(metadata)
        # Large payloads belong in a fixture file, not an OS environment value.
        # Each fake section also verifies the private --load-info-json bytes
        # preserve the entire native metadata document, including captions.
        program = self.root / "fixture.py"
        lines = program.read_text(encoding="utf-8").splitlines()
        lines = ["    print(pathlib.Path(os.environ['FIXTURE_METADATA_FILE']).read_text())"
                 if 'print(os.environ.get("FIXTURE_RESOLVE"' in line else line for line in lines]
        source = "\n".join(lines) + "\n"
        source = source.replace('elif "--output" in args:\n',
                                'elif "--output" in args:\n'
                                '    assert pathlib.Path(args[args.index("--load-info-json") + 1]).read_bytes() == pathlib.Path(os.environ["FIXTURE_METADATA_FILE"]).read_bytes() + b"\\n"\n')
        program.write_text(source, encoding="utf-8")
        result = self.invoke("play-intervals", self.request())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "nut/multimedia container\0" + "synthetic media stream" * 2)
        self.assertEqual(len(self.arguments()), 3)
        metadata.write_text(" " * (16 * 1024 * 1024) + json.dumps(self.media()), encoding="utf-8")
        self.log.unlink()
        self.assert_failed(self.invoke("play-intervals", self.request()))
        self.assertEqual(len(self.arguments()), 1)

    def test_invalid_requests_do_not_extract_or_emit_media(self) -> None:
        for change in ({"context_fingerprint": "bad"}, {"source_duration_milliseconds": 0},
                       {"max_video_height": 4321}, {"unknown": True},
                       {"retained_intervals_milliseconds": []},
                       {"retained_intervals_milliseconds": [{"start": 0, "end": 21000}]},
                       {"retained_intervals_milliseconds": [{"start": 1, "end": 1}]},
                       {"retained_intervals_milliseconds": [{"start": 2, "end": 5}, {"start": 4, "end": 6}]},
                       {"retained_intervals_milliseconds": [{"start": 0.5, "end": 3}]},
                       {"options": self.options("firefox:private-profile", True)}):
            self.log.unlink(missing_ok=True)
            self.assert_failed(self.play(request=dict(self.request(), **change)))
            self.assertEqual(self.arguments(), [])

    def test_native_identifier_validation_and_section_failure_cleanup(self) -> None:
        for mode in ("native-truncated", "native-mismatch", "native-failure"):
            self.log.unlink(missing_ok=True)
            self.environment["FIXTURE_MODE"] = mode
            result = self.play()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", result.stderr)
            if mode != "native-failure":
                self.assertEqual(result.stdout, "")
            extraction, section = self.arguments()
            self.assertIn("--dump-single-json", extraction)
            path = pathlib.Path(section[section.index("--load-info-json") + 1])
            self.assertFalse(path.parent.exists())

    def test_native_identifier_transform_fragmentation_and_fail_closed(self) -> None:
        module = (fixtures.ADDON / "libexec" / "stream-playback.ts").as_uri()
        script = 'import { nativeNutSection } from ' + json.dumps(module) + ';\n' + r'''
const id = new TextEncoder().encode("nut/multimedia container\0");
const payload = new Uint8Array([...id, 1, 2, 3]);
const full = new Uint8Array([...id, ...payload]);
async function convert(bytes, drop, fragmented) {
  const input = new ReadableStream({start(c) {
    if (fragmented) for (const byte of bytes) c.enqueue(new Uint8Array([byte]));
    else c.enqueue(bytes);
    c.close();
  }});
  return new Uint8Array(await new Response(input.pipeThrough(nativeNutSection(drop))).arrayBuffer());
}
function equal(actual, expected) {
  if (actual.length !== expected.length || actual.some((value, i) => value !== expected[i])) {
    throw new Error("native boundary output mismatch");
  }
}
async function rejected(operation) {
  try { await operation(); } catch { return; }
  throw new Error("invalid native boundary accepted");
}
for (const fragmented of [false, true]) for (const drop of [false, true]) {
  equal(await convert(full, drop, fragmented), drop ? payload : full);
  for (let count = 0; count < id.length; count++) {
    await rejected(() => convert(id.slice(0, count), drop, fragmented));
    const bad = full.slice(); bad[count] ^= 1;
    await rejected(() => convert(bad, drop, fragmented));
  }
}
const broken = new ReadableStream({start(c) { c.error(new Error("synthetic stream failure")); }});
await rejected(() => new Response(broken.pipeThrough(nativeNutSection(false))).arrayBuffer());
'''
        result = subprocess.run(["deno", "eval", script], text=True, capture_output=True,
                                env=self.environment, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_oversized_playback_request_does_not_spawn_a_child(self) -> None:
        # Valid JSON whitespace keeps the decoded request otherwise valid, so
        # the byte limit, rather than field validation, must reject it.
        import subprocess
        result = subprocess.run(
            ["sh", str(fixtures.ADDON / "addon.sh"), "play-intervals"],
            input=" " * (512 * 1024) + json.dumps(self.request()),
            text=True, capture_output=True, env=self.environment, timeout=20,
        )
        self.assert_failed(result)
        self.assertEqual(self.arguments(), [])

    def test_retained_interval_limit_matches_1024_exclusions_plus_one(self) -> None:
        # Stop at synthetic extraction: prove admission without spawning a
        # thousand section processes or emitting media.
        self.environment["FIXTURE_MODE"] = "resolve-failure"
        for count, expected_extractions in [(1025, 1), (1026, 0)]:
            self.log.unlink(missing_ok=True)
            request = self.request()
            request["retained_intervals_milliseconds"] = [
                {"start": index * 2, "end": index * 2 + 1} for index in range(count)
            ]
            self.assert_failed(self.play(request=request))
            self.assertEqual(len(self.arguments()), expected_extractions)

    def test_changed_duration_live_hdr_and_failed_extraction_never_emit_media(self) -> None:
        for change in ({"duration": 19.999}, {"duration": "20"}, {"live_status": "is_live"},
                       {"is_live": True}, {"dynamic_range": "HDR10"}, {"color_transfer": "arib-std-b67"},
                       {"height": 1080}, {"vcodec": "none"}):
            self.log.unlink(missing_ok=True)
            self.assert_failed(self.play(dict(self.media(), **change)))
            self.assertEqual(len(self.arguments()), 1)
        self.environment["FIXTURE_MODE"] = "resolve-failure"
        self.assert_failed(self.play())


if __name__ == "__main__":
    unittest.main()
