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

class MusicCommandsTest(unittest.TestCase):
    def test_repeat_and_metadata_without_network(self):
        import contextlib,io,sys
        with tempfile.TemporaryDirectory() as temp, patch.object(music,'RUNTIME',Path(temp)), patch.object(music,'register_operation'),patch.object(music.subprocess,'run') as download:
            (Path(temp)/'current.json').write_text(json.dumps({'file':'/cache/song.opus','title':'Song','artist':'Artist','query':'Artist - Song'}))
            calls=[]
            def ipc(cmd):
                calls.append(cmd)
                if cmd==['get_property','idle-active']:return False
                if cmd==['get_property','path']:return '/cache/song.opus'
                return False
            with patch.object(music,'ipc',side_effect=ipc),patch.object(sys,'argv',['speaker-music','repeat']),contextlib.redirect_stdout(io.StringIO()) as output:
                music.main()
            data=json.loads(output.getvalue())
            self.assertEqual(data['title'],'Song')
            self.assertIn(['seek',0,'absolute'],calls)
            download.assert_not_called()

    def test_stale_startup_policy_ignored(self):
        import time,os
        with tempfile.TemporaryDirectory() as temp, patch.object(music,'RUNTIME',Path(temp)/'speaker-music'):
            path=Path(temp)/'speaker-operations';path.mkdir()
            data={'owner_pid':os.getpid(),'owner_stamp':'wrong','updated':time.time(),'music_volume':15}
            (path/'audio-policy.json').write_text(json.dumps(data))
            self.assertEqual(music.policy_volume(),60)
            data['owner_stamp']=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19]
            (path/'audio-policy.json').write_text(json.dumps(data))
            self.assertEqual(music.policy_volume(),15)
