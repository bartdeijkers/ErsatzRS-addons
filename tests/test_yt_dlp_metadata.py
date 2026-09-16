"""Metadata parity across normalized yt-dlp mapping paths; no network calls."""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBEXEC = ROOT / 'addons' / 'org.ersatzrs.addon.yt-dlp' / 'libexec'


@unittest.skipUnless(shutil.which('deno'), 'Deno is required')
class MetadataTests(unittest.TestCase):
    def map(self, script, document):
        result = subprocess.run(
            ['deno', 'run', '--quiet', '--allow-env', str(LIBEXEC / script)],
            input=json.dumps(document), text=True, capture_output=True, check=True,
            env={'PATH': str(pathlib.Path(shutil.which('deno')).parent) + ':/usr/bin:/bin',
                 'ERSATZRS_MEDIA_LIST_URL': 'https://media.example.test/list'},
        )
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_list_and_episode_preserve_source_metadata(self):
        video = dict(id='fixture', title='Episode', description='Full plot\nSecond paragraph',
                     webpage_url='https://media.example.test/video', upload_date='20260916',
                     language='en', channel='Fixture channel', categories=['Documentary'],
                     tags=['history'], age_limit=12)
        rows = self.map('media-list.ts', dict(title='Show', channel='Fixture channel',
                                             categories=['Education'], language='en', entries=[video]))
        metadata = rows[1]['metadata']
        self.assertEqual(metadata['plot'], video['description'])
        self.assertEqual(metadata['release_date'], '2026-09-16')
        self.assertEqual(metadata['genres'], ['Documentary'])
        self.assertEqual(metadata['languages'], ['en'])
        self.assertEqual(metadata['tags'], ['history'])
        self.assertEqual(metadata['studios'], ['Fixture channel'])
        self.assertEqual(metadata['content_ratings'], ['age:12'])
        self.assertEqual(rows[0]['metadata']['studios'], ['Fixture channel'])
        self.assertEqual(rows[0]['metadata']['genres'], ['Education'])

    def test_age_zero_is_not_missing_or_a_national_rating(self):
        for value, expected in [(0, 'age:0'), (18, 'age:18'), (None, None),
                                (-1, None), (2.5, None), ('18', None), (True, None)]:
            with self.subTest(value=value):
                row = self.map('item-metadata.ts', dict(id='fixture', age_limit=value))[0]
                self.assertEqual(row['content_rating'], expected)

    def test_uploader_is_studio_fallback_and_absent_age_stays_absent(self):
        rows = self.map('media-list.ts', dict(title='Show', entries=[dict(
            id='fixture', title='Episode', webpage_url='https://media.example.test/video',
            uploader='Fixture uploader')]))
        self.assertEqual(rows[1]['metadata']['studios'], ['Fixture uploader'])
        self.assertEqual(rows[1]['metadata']['content_ratings'], [])


if __name__ == '__main__':
    unittest.main()
