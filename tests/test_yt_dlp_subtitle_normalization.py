"""Offline SRT boundary cases, using the shared production normalizer on both OSes."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('deno'), 'Deno required')
class SubtitleNormalizationTests(unittest.TestCase):
    def test_empty_cues_preserve_visible_text_timing_and_reject_invalid_content(self):
        module = (ROOT / 'addons/org.ersatzrs.addon.yt-dlp/libexec/subtitle-normalization.ts').as_uri()
        code = '''
import { removeEmptySrtCues } from MODULE;
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const empty = "1\\n00:00:01,000 --> 00:00:02,000\\n\\n";
const visible = "2\\n00:00:03,125 --> 00:00:05,750\\nVisible <i>fixture</i>\\nSecond line\\n\\n";
function assert(value, message) { if (!value) throw new Error(message); }
const bytes = encoder.encode(visible);
assert(decoder.decode(removeEmptySrtCues(encoder.encode(visible + "\\n\\n" + empty))).trim() === visible.trim(), "extra cue separators hid an empty cue");
assert(removeEmptySrtCues(bytes) === bytes, "valid bytes changed");
assert(decoder.decode(removeEmptySrtCues(encoder.encode(empty + visible))).trim() === visible.trim(), "visible cue changed");
assert(decoder.decode(removeEmptySrtCues(encoder.encode((empty + visible).replaceAll("\\n", "\\r\\n")))).trim() === visible.trim(), "CRLF cue changed");
assert(decoder.decode(removeEmptySrtCues(encoder.encode("\\ufeff" + empty + visible))).trim() === visible.trim(), "BOM cue changed");
assert(removeEmptySrtCues(encoder.encode(empty)).length === 0, "empty track admitted");
for (const malformed of ["1\\ninvalid timing\\n\\n", "1\\n00:00:02,000 --> 00:00:01,000\\n\\n", "orphan text\\n\\n", "1\\n00:00:01,000 --> 00:00:01,000\\n\\n"]) {
  const data = encoder.encode(malformed);
  assert(removeEmptySrtCues(data) === data, "malformed cue hidden");
}
let rejected = false;
try { removeEmptySrtCues(new Uint8Array([255])); } catch { rejected = true; }
assert(rejected, "invalid UTF-8 accepted");
console.log("PASS: empty cues only; visible text, timestamps and malformed boundaries preserved");
'''.replace('MODULE', json.dumps(module))
        result = subprocess.run(['deno', 'eval', code], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS:', result.stdout)
