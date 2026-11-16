import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('music', Path(__file__).parents[1] / 'skills/speaker-music/scripts/speaker_music.py')
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


class MusicTest(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(music.key(' ABBA  - SOS '), music.key('abba - sos'))

    def test_offline_cache_hit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(music, 'ROOT', Path(temp)), patch.object(music.subprocess, 'run') as run:
            root = Path(temp)
            (root / 'track.opus').write_bytes(b'test')
            (root / (music.key('artist - song') + '.json')).write_text(json.dumps({'file': 'track.opus', 'title': 'Song'}))
            self.assertEqual(music.resolve('artist - song'), (root / 'track.opus', 'Song', True))
            run.assert_not_called()

    def test_download_and_repeat(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(music, 'ROOT', Path(temp)), patch.object(music.shutil, 'which', return_value='/bin/yt-dlp'):
            root = Path(temp)
            track = root / 'id.opus'
            query = 'Artist - $(touch BAD); Song'
            def download(cmd, **kwargs):
                self.assertEqual(cmd[-1], 'ytsearch1:' + query)
                self.assertEqual(cmd[-2], '--')
                self.assertNotIn('shell', kwargs)
                track.write_bytes(b'test')
                return type('Result', (), {'stdout': str(track) + '\n'})()
            with patch.object(music.subprocess, 'run', side_effect=download) as run:
                self.assertFalse(music.resolve(query)[2])
                self.assertTrue(music.resolve(query)[2])
                self.assertEqual(run.call_count, 1)

    def test_partial_not_indexed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(music, 'ROOT', Path(temp)), patch.object(music.shutil, 'which', return_value='/bin/yt-dlp'):
            root = Path(temp)
            with patch.object(music.subprocess, 'run', return_value=type('Result', (), {'stdout': str(root / 'missing.opus')})()):
                with self.assertRaises(RuntimeError):
                    music.resolve('missing')
                self.assertFalse((root / (music.key('missing') + '.json')).exists())


if __name__ == '__main__':
    unittest.main()
