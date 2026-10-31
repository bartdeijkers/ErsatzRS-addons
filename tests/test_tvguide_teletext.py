"""Production TV-guide producer: supplied context only; no provider/network calls."""
from __future__ import annotations
import copy
import json
import os
import platform
import pathlib
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addons/org.ersatzrs.addon.tvguide-teletext"
RUNTIME = os.environ.get("ERSATZRS_TVGUIDE_TEST_RUNTIME") or (
    "node" if platform.machine().lower().startswith("arm") and platform.machine().lower() != "arm64" else "deno")
CULTURES = {"en-US", "nl", "de-DE", "fr-FR", "it-IT", "pl", "pt-BR", "es-419", "es-ES"}


def programme(item: int, start: str, title: str) -> dict:
    stop = (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    return {"identity": {"playout_id": 1, "first_item_id": item}, "start": start,
            "stop": stop, "title": title,
            "custom_title": None, "sub_title": None, "description": None,
            "segments": [{"item_id": item, "media_item_id": item, "start": start,
                          "finish": stop,
                          "in_point_milliseconds": 0, "out_point_milliseconds": 900000}]}


def request() -> dict:
    programmes = [programme(1, "2026-10-25T00:30:00Z", "Café – Émission"),
                  programme(2, "2026-10-25T01:30:00Z", "Later programme")]
    return {"schema_version": 3, "generation": "synthetic-exact-generation",
            "locale": "nl", "timezone": "Europe/Amsterdam", "captured_at": "2026-10-25T00:35:00Z",
            "window": {"start": "2026-10-24T22:00:00Z", "finish": "2026-10-27T23:00:00Z"},
            "channels": [{"id": 1, "number": "1", "name": "Synthetic channel",
                          "programmes": programmes,
                          "context": {"current": programmes[0]["identity"],
                                      "next": programmes[1]["identity"],
                                      "continuing": programmes[0]["identity"],
                                      "later_today": [programmes[1]["identity"]], "ambiguous": False}}]}


@unittest.skipUnless(shutil.which(RUNTIME), "Selected JavaScript runtime is required for the production producer")
class TvGuideTeletextTests(unittest.TestCase):
    def invoke(self, value=None, settings=None, operation="pages", raw=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ERSATZRS_ADDON_SETTING_")}
        env.update({"ERSATZRS_ADDON_SETTING_" + k: str(v) for k, v in (settings or {}).items()})
        if RUNTIME == "node" and os.name == "nt":
            cmd = [shutil.which("node"), str(PACKAGE / "libexec/pages.mts"), operation]
        elif os.name == "nt":
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(PACKAGE / "addon.bat"), operation]
        else:
            cmd = [str(PACKAGE / ("addon-node.sh" if RUNTIME == "node" else "addon.sh")), operation]
        if raw is None:
            raw = json.dumps(value if value is not None else request(), ensure_ascii=False).encode()
        return subprocess.run(cmd, input=raw, capture_output=True, env=env,
                              cwd=ROOT, timeout=20, check=False)

    def produce(self, value=None, settings=None):
        run = self.invoke(value, settings)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        return json.loads(run.stdout)

    def reject(self, code, value=None, settings=None, raw=None):
        run = self.invoke(value, settings, raw=raw)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.stdout, b"")
        error = json.loads(run.stderr)
        self.assertEqual(error["code"], code)
        self.assertEqual(set(error), {"code", "message"})

    @staticmethod
    def text(result):
        return "\n".join(run["content"]["text"] for page in result["service"]["pages"]
                         for row in page["rows"] for run in row["runs"])

    def test_ready_and_unsupported_operation(self):
        run = self.invoke(operation="check")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "ready")
        unknown = self.invoke(operation="unknown")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertEqual(unknown.stdout, b"")
        self.assertEqual(json.loads(unknown.stderr)["code"], "unsupported-operation")

    def test_real_entrypoint_complete_v3_context_and_navigation(self):
        result = self.produce()
        self.assertEqual(result["schema_version"], 3)
        service = result["service"]
        self.assertEqual(service["schema_version"], 2)
        self.assertEqual(service["generation"], request()["generation"])
        self.assertEqual(service["initial_page"], 200)
        self.assertEqual(service["language"], "nld")
        text = self.text(result)
        for value in ["Now: Café – Émission", "Next: Later programme", "Continuing: Café – Émission", "Later: Later programme"]:
            self.assertIn(value, text)
        addresses = {(p["address"]["page"], p["address"]["subcode"]) for p in service["pages"]}
        for page in service["pages"]:
            self.assertTrue(all(run["content"]["text"] for row in page["rows"] for run in row["runs"]))
            self.assertEqual({link["role"] for link in page["navigation"]}, {"index", "red", "green", "yellow", "cyan"})
            for link in page["navigation"]:
                target = link["target"]
                self.assertIn((target["page"], target["subcode"]), addresses)
        self.assertEqual(addresses, {(p["page"]["page"], p["page"]["subcode"]) for p in result["authoring"]["pages"]})
        for field in ["page_enhancements", "magazines", "objects", "drcs", "mots", "empty_object_pages"]:
            self.assertEqual(service[field], [])
        self.assertEqual(service["mot_selections"],
                         [{"display": page["address"], "mot": None} for page in service["pages"]])

    def test_two_profiles_keep_range_theme_zone_and_input_isolated(self):
        guide = request()
        original = copy.deepcopy(guide)
        day = self.produce(guide, {"HEADER": "DAY"})
        night = self.produce(guide, {"PAGE_START": 400, "PAGE_END": 499, "INDEX_PAGE": 410, "THEME": "night", "HEADER": "NIGHT"})
        self.assertEqual(guide, original)
        self.assertEqual(day["authoring"]["theme"]["id"], "classic")
        self.assertEqual(night["authoring"]["theme"]["id"], "night")
        self.assertTrue(all(200 <= p["address"]["page"] <= 299 for p in day["service"]["pages"]))
        self.assertTrue(all(400 <= p["address"]["page"] <= 499 for p in night["service"]["pages"]))
        for result, expected_header in [(day, "DAY"), (night, "NIGHT")]:
            headers = [run["content"]["text"] for page in result["service"]["pages"]
                       for row in page["rows"] if row["row"] == 1 for run in row["runs"]]
            self.assertTrue(headers)
            self.assertEqual(set(headers), {expected_header})
        self.assertEqual(day, self.produce(guide, {"HEADER": "DAY"}))

    def test_dst_fold_keeps_both_local_times_and_offsets(self):
        result = self.produce()
        self.assertIn("02:30 GMT+2", self.text(result))
        self.assertIn("02:30 GMT+1", self.text(result))

    def test_long_multilingual_title_is_wrapped_without_loss(self):
        guide = request()
        title = "Café Καλημέρα Warszawa München " * 5
        guide["channels"][0]["programmes"][0]["title"] = title
        result = self.produce(guide)
        # A long title's exact code-point sequence survives consecutive wrapped rows.
        flattened = "".join(run["content"]["text"] for p in result["service"]["pages"]
                            if p["address"]["page"] == 201 for r in p["rows"]
                            if 5 <= r["row"] < 20 for run in r["runs"])
        self.assertIn(title, flattened)
        self.assertTrue(all(len(run["content"]["text"]) <= 36 for p in result["service"]["pages"]
                            for r in p["rows"] for run in r["runs"]))

    def test_empty_guide_and_unlisted_context(self):
        guide = request(); guide["channels"] = []
        self.assertIn("No guide channels", self.text(self.produce(guide)))
        guide = request(); channel = guide["channels"][0]; channel["programmes"] = []
        channel["context"] = {"current": None, "next": None, "continuing": None, "later_today": [], "ambiguous": False}
        text = self.text(self.produce(guide))
        self.assertIn("Now: No listed programme", text)
        self.assertIn("No listed programmes", text)
        self.assertNotIn("Café", text)

    def test_explicit_theme_overrides_and_edit_boundaries(self):
        result = self.produce(settings={"THEME": "night", "ACCENT": "yellow", "LAYOUT": "standard", "FOOTER": "My footer"})
        theme = result["authoring"]["theme"]
        self.assertEqual(theme["overrides"], [{"key": "accent", "value": {"kind": "colour", "red": 15, "green": 15, "blue": 0}}, {"key": "layout", "value": {"kind": "layout", "id": "standard"}}])
        self.assertEqual(result["authoring"]["template"], {"id": "tvguide", "revision": "1"})
        for page in result["authoring"]["pages"]:
            regions = {r["id"]: r for r in page["regions"]}
            self.assertEqual(regions["header"]["kind"], "zone")
            self.assertEqual(regions["footer"]["kind"], "zone")
            self.assertEqual(regions["custom"]["kind"], "free")
            self.assertEqual(regions["guide"]["kind"], "generated")
            self.assertEqual(regions["navigation"]["kind"], "generated")
            self.assertEqual({d["region"] for d in page["dynamic_fields"]}, {"title", "guide"})

        blank = self.produce(settings={"HEADER": "", "FOOTER": ""})
        for page in blank["service"]["pages"]:
            self.assertTrue({1, 22}.isdisjoint({row["row"] for row in page["rows"]}))
        for page in blank["authoring"]["pages"]:
            self.assertTrue({"header", "footer"} <= {region["id"] for region in page["regions"]})

    def test_invalid_settings_reject_whole_response(self):
        cases = [("invalid-page-range", {"PAGE_START": 300, "PAGE_END": 299}),
                 ("invalid-page-range", {"INDEX_PAGE": 400}),
                 ("invalid-page-range", {"PAGE_START": 99}),
                 ("invalid-theme", {"THEME": "missing"}),
                 ("invalid-theme-override", {"ACCENT": "black"}),
                 ("invalid-layout", {"LAYOUT": "unknown"}),
                 ("invalid-zone-value", {"HEADER": "x" * 37}),
                 ("invalid-zone-value", {"FOOTER": "bad\nvalue"})]
        for code, values in cases:
            with self.subTest(values=values): self.reject(code, settings=values)

    def test_capacity_and_invalid_input_emit_no_partial_map(self):
        self.reject("guide-capacity", settings={"PAGE_END": 200})
        bad = request(); bad["schema_version"] = 1
        self.reject("invalid-guide-request", bad)
        bad = request(); bad["channels"][0]["context"]["current"] = {"playout_id": 1, "first_item_id": 999}
        self.reject("invalid-guide-reference", bad)
        self.reject("invalid-guide-request", raw=b"\xff")
        self.reject("guide-request-limit", raw=b" " * (4 * 1024 * 1024 + 1))

    def test_complete_multi_day_guide_crosses_subpage_mask_boundary(self):
        guide = request()
        beginning = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
        programmes = [programme(i + 1, (beginning + timedelta(minutes=20 * i)).isoformat().replace("+00:00", "Z"),
                                f"Programme-{i:03d} " + "Long complete title " * 15) for i in range(150)]
        guide["channels"][0]["programmes"] = list(reversed(programmes))
        result = self.produce(guide)
        pages = [p for p in result["service"]["pages"] if p["address"]["page"] == 201]
        self.assertGreater(len(pages), 80)
        self.assertEqual(pages[79]["address"]["subcode"], 0x79)
        self.assertEqual(pages[80]["address"]["subcode"], 0x100)
        self.assertTrue(all(p["address"]["subcode"] & ~0x3F7F == 0 for p in pages))
        text = self.text(result)
        for i in range(150): self.assertIn(f"Programme-{i:03d}", text)
        for day in ["2026-10-25", "2026-10-26", "2026-10-27"]: self.assertIn(day, text)
        self.assertLess(text.index("2026-10-25"), text.index("2026-10-26"))
        self.assertLess(text.index("2026-10-26"), text.index("2026-10-27"))

    def test_lossless_i64_guide_identities(self):
        guide = request()
        channel = guide["channels"][0]
        channel["id"] = 9223372036854775807
        channel["programmes"][0]["identity"] = {"playout_id": 9223372036854775807, "first_item_id": 9007199254740992}
        channel["programmes"][1]["identity"] = {"playout_id": 9223372036854775807, "first_item_id": 9007199254740993}
        channel["context"] = {"current": channel["programmes"][1]["identity"], "next": None,
                              "continuing": channel["programmes"][1]["identity"],
                              "later_today": [], "ambiguous": False}
        result = self.produce(guide)
        self.assertIn("Now: Later programme", self.text(result))
        self.assertNotIn("Now: Café", self.text(result))
        self.assertTrue(any(field["binding"] == "guide.channel-9223372036854775807"
                            for page in result["authoring"]["pages"] for field in page["dynamic_fields"]))
        bad = request(); bad["channels"][0]["context"]["later_today"] *= 10000
        self.reject("invalid-guide-reference", bad)

    def test_manifest_labels_and_permissions(self):
        manifest = tomllib.loads((PACKAGE / "addon.toml").read_text())
        self.assertEqual(manifest["id"], PACKAGE.name)
        self.assertEqual(manifest["permissions"]["network_hosts"], [])
        self.assertFalse(manifest["permissions"]["media_read"])
        self.assertFalse(manifest["permissions"]["managed_ffmpeg"])
        self.assertEqual(manifest["permissions"]["external_commands"], ["deno", "node"])
        self.assertEqual(manifest["entrypoints"]["linux-arm"]["path"], "addon-node.sh")
        for rid in ["linux-x64", "linux-arm64"]:
            self.assertEqual(manifest["entrypoints"][rid]["path"], "addon.sh")
        self.assertEqual(manifest["entrypoints"]["win-x64"]["path"], "addon.bat")
        for setting in manifest["settings"]:
            self.assertEqual(set(setting["label"]), CULTURES)
        self.assertEqual(set(manifest["name"]), CULTURES)
        self.assertEqual(set(manifest["summary"]), CULTURES)
        batch = (PACKAGE / "addon.bat").read_bytes()
        self.assertNotIn(b"\n", batch.replace(b"\r\n", b""))
