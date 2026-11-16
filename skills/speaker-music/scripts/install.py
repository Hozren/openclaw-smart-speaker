#!/usr/bin/env python3
"""Install latest published music skill, CLI and dependencies (Linux)."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

REPO = 'Hozren/openclaw-smart-speaker'


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'openclaw-speaker-music-installer'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skill-dir', type=Path, required=True, help='Agent-visible skill destination')
    args = p.parse_args()
    app = Path.home() / '.local/share/speaker-music'
    missing = [name for name in ('mpv', 'ffmpeg') if not shutil.which(name)]
    if missing:
        if not shutil.which('apt-get'):
            raise SystemExit('Install mpv and ffmpeg with your package manager, then rerun.')
        prefix = [] if os.geteuid() == 0 else ['sudo']
        subprocess.run(prefix + ['apt-get', 'update'], check=True)
        subprocess.run(prefix + ['apt-get', 'install', '-y'] + missing, check=True)
    release = json.loads(fetch(f'https://api.github.com/repos/{REPO}/releases/latest'))
    assets = {a['name']: a['browser_download_url'] for a in release['assets']}
    archive = fetch(assets['speaker-music.tar.gz'])
    expected = fetch(assets['speaker-music.sha256']).decode().split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit('Release checksum mismatch')
    with tempfile.TemporaryDirectory() as temp:
        dest = Path(temp)
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for member in tar.getmembers():
                path = (dest / member.name).resolve()
                if not path.is_relative_to(dest) or not (member.isfile() or member.isdir()):
                    raise SystemExit('Unsafe release archive')
            tar.extractall(dest, filter='data')
        source = dest / 'speaker-music'
        if not (source / 'SKILL.md').is_file() or not (source / 'scripts/speaker_music.py').is_file():
            raise SystemExit('Incomplete release')
        app.mkdir(parents=True, exist_ok=True)
        venv = app / 'venv'
        subprocess.run(['python3', '-m', 'venv', str(venv)], check=True)
        subprocess.run([str(venv / 'bin/pip'), 'install', '--upgrade', 'yt-dlp[default]'], check=True)
        shutil.copytree(source, args.skill_dir.expanduser(), dirs_exist_ok=True)
        shutil.copy2(source / 'scripts/speaker_music.py', app / 'speaker_music.py')
    bindir = Path.home() / '.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    launcher = bindir / 'speaker-music'
    launcher.write_text('#!/bin/sh\nexport PATH=' + shlex.quote(str(venv / 'bin')) + ':"$PATH"\nexec ' + shlex.quote(str(venv / 'bin/python')) + ' ' + shlex.quote(str(app / 'speaker_music.py')) + ' "$@"\n')
    launcher.chmod(0o755)
    (app / 'release.txt').write_text(release['tag_name'] + '\n')
    print(f'Installed {release["tag_name"]}: {launcher}; skill: {args.skill_dir}')
    if not any(shutil.which(name) for name in ('deno', 'node')):
        print('YouTube may require a supported JS runtime (Deno recommended by yt-dlp); install it before the online acceptance test.')


if __name__ == '__main__':
    main()
