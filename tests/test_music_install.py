import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'skills/speaker-music/scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTest(unittest.TestCase):
    def test_latest_assets_and_install(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            for name, data in [('SKILL.md', b'release skill'), ('scripts/speaker_music.py', b'# release CLI')]:
                entry = tarfile.TarInfo('speaker-music/' + name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        archive = buf.getvalue()
        release = {'tag_name': 'music-vTEST', 'assets': [
            {'name': 'speaker-music.tar.gz', 'browser_download_url': 'https://test/archive'},
            {'name': 'speaker-music.sha256', 'browser_download_url': 'https://test/hash'}]}
        urls = []
        def fetch(url):
            urls.append(url)
            if url.endswith('/latest'):
                return json.dumps(release).encode()
            return archive if url.endswith('/archive') else hashlib.sha256(archive).hexdigest().encode()
        with tempfile.TemporaryDirectory(prefix='music install ') as temp:
            home = Path(temp)
            dest = home / 'skills/music'
            with patch.object(installer.Path, 'home', return_value=home), patch.object(installer, 'fetch', side_effect=fetch), patch.object(installer.shutil, 'which', return_value='/bin/tool'), patch.object(installer.subprocess, 'run'), patch('sys.argv', ['install.py', '--skill-dir', str(dest)]):
                installer.main()
            self.assertEqual((dest / 'SKILL.md').read_text(), 'release skill')
            self.assertEqual((home / '.local/share/speaker-music/speaker_music.py').read_text(), '# release CLI')
            self.assertIn('/releases/latest', urls[0])
            self.assertTrue((home / '.local/bin/speaker-music').stat().st_mode & 0o100)


if __name__ == '__main__':
    unittest.main()
