import importlib.util
import os
import shutil
import zipfile
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

installed = os.environ.get('YT_DLP_TEST_ZIP') or shutil.which('yt-dlp')
if not installed or not zipfile.is_zipfile(installed):
    raise RuntimeError('The stock Python-zip yt-dlp executable is required')
sys.path.insert(0, installed)
import yt_dlp
plugin = (pathlib.Path(__file__).resolve().parents[1] / 'addons' /
          'org.ersatzrs.addon.yt-dlp' / 'libexec' / 'plugins' / 'ersatzrs' /
          'yt_dlp_plugins' / 'postprocessor' / 'ersatzrs_chapters.py')
spec = importlib.util.spec_from_file_location('ersatzrs_caption_test_plugin', plugin)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ModifyChaptersPP = module.ModifyChaptersPP


class CaptionCuts(unittest.TestCase):
    def test_required_guard_rejects_builtin_fallback_before_download(self):
        from yt_dlp.postprocessor.modify_chapters import ModifyChaptersPP as Native
        from yt_dlp.utils import PostProcessingError
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            guard = module.ErsatzRSChapterGuardPP(ydl)
            with patch.object(module, 'get_postprocessor', return_value=Native):
                with self.assertRaises(PostProcessingError):
                    guard.run({'title': 'Fixture'})

    def test_required_guard_preserves_plain_preparation_metadata(self):
        info = {'title': 'Fixture', 'requested_subtitles': {}}
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            with patch.object(module, 'get_postprocessor', return_value=ModifyChaptersPP):
                files, result = module.ErsatzRSChapterGuardPP(ydl).run(info)
        self.assertEqual(files, [])
        self.assertIs(result, info)

    def cut(self, text, intervals):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'captions.srt'
            path.write_text(text, encoding='utf-8')
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                output = ModifyChaptersPP(ydl).remove_srt_chapters(str(path), intervals)
            self.assertEqual(path.read_text(encoding='utf-8'), text)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()),
                             ['captions.srt', 'captions.temp.srt'])
            return pathlib.Path(output).read_text(encoding='utf-8')

    def test_crossing_both_cut_boundaries(self):
        output = self.cut('1\n00:00:03,500 --> 00:00:06,500\nAcross\n\n',
                          [{'inpoint': '2', 'outpoint': '4'},
                           {'inpoint': '6', 'outpoint': '10'}])
        self.assertIn('00:00:01,500 --> 00:00:02,000\nAcross', output)
        self.assertIn('00:00:02,000 --> 00:00:02,500\nAcross', output)
        self.assertEqual(output.count('Across'), 2)

    def test_all_cues_removed(self):
        self.assertEqual(self.cut('1\n00:00:04,000 --> 00:00:06,000\nRemoved\n\n',
                                  [{'outpoint': '4'}, {'inpoint': '6'}]), '')

    def test_open_tail_preserves_gap_unicode_and_italics(self):
        output = self.cut('1\n00:00:07,000 --> 00:00:08,000\n<i>Olá 世界</i>\nSecond line\n\n',
                          [{'outpoint': '4'}, {'inpoint': '6'}])
        self.assertIn('00:00:05,000 --> 00:00:06,000', output)
        self.assertIn('<i>Olá 世界</i>\nSecond line', output)

    def test_no_cut_preserves_initial_silence(self):
        output = self.cut('1\n00:00:02,500 --> 00:00:03,000\nRetained\n\n', [{}])
        self.assertIn('00:00:02,500 --> 00:00:03,000', output)

    def test_rich_payload_and_position_are_not_converted(self):
        text = '{\\an8}<font color="#ff0000" face="serif" size="22"><s>Red</s></font>'
        output = self.cut(f'1\n00:00:07,000 --> 00:00:08,000 X1:10 X2:20 Y1:30 Y2:40\n{text}\n\n',
                          [{'outpoint': '4'}, {'inpoint': '6'}])
        self.assertIn('00:00:05,000 --> 00:00:06,000 X1:10 X2:20 Y1:30 Y2:40', output)
        self.assertIn(text, output)

    def test_repeated_blank_separators(self):
        output = self.cut('1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n \n\n'
                          '2\n00:00:03,000 --> 00:00:04,000\nSecond\n\n \n', [{}])
        self.assertIn('First', output)
        self.assertIn('Second', output)

    def test_invalid_input_fails_without_partial_output(self):
        from yt_dlp.utils import PostProcessingError
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'captions.srt'
            original = '1\n00:00:01,000 --> 00:00:02,000\nValid\n\ninvalid'
            path.write_text(original, encoding='utf-8')
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                with self.assertRaises(PostProcessingError):
                    ModifyChaptersPP(ydl).remove_srt_chapters(str(path), [{}])
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_source_and_split_cue_amplification_limits_preserve_original(self):
        from yt_dlp.utils import PostProcessingError
        source = '1\n00:00:00,000 --> 00:01:40,000\nSpanning 世界\n\n'
        cases = [
            (len(source.encode('utf-8')) - 1, [{}], 'source'),
            (200, [{'inpoint': str(n), 'outpoint': str(n + 1)}
                   for n in range(0, 100, 2)], 'Edited'),
        ]
        for limit, intervals, expected in cases:
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory) / 'captions.srt'
                original = source.encode('utf-8')
                path.write_bytes(original)
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    processor = ModifyChaptersPP(ydl)
                    processor.MAXIMUM_SRT_BYTES = limit
                    with self.assertRaisesRegex(PostProcessingError, expected):
                        processor.remove_srt_chapters(str(path), intervals)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_exact_byte_limit_accepts_unicode_and_crlf_source(self):
        source = '1\r\n00:00:01,000 --> 00:00:02,000\r\n世界\r\n\r\n'
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'captions.srt'
            path.write_bytes(source.encode('utf-8'))
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                processor = ModifyChaptersPP(ydl)
                processor.MAXIMUM_SRT_BYTES = len(source.encode('utf-8'))
                output = pathlib.Path(processor.remove_srt_chapters(str(path), [{}]))
            self.assertEqual(path.read_bytes(), source.encode('utf-8'))
            self.assertIn('世界', output.read_text(encoding='utf-8'))
            self.assertLessEqual(output.stat().st_size, processor.MAXIMUM_SRT_BYTES)


if __name__ == '__main__':
    unittest.main(verbosity=2)
