#!/usr/bin/env python3
"""Linux music cache + yt-dlp + mpv. No shell execution of queries."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import unicodedata

ROOT = Path(os.environ.get('MUSIC_CACHE', '~/.cache/openclaw-music')).expanduser().resolve()
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/openclaw-music-{os.getuid()}')) / 'speaker-music'
SOCKET = RUNTIME / 'mpv.sock'


def key(query):
    normalized = ' '.join(unicodedata.normalize('NFKC', query).casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def ipc(command):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(2)
        conn.connect(str(SOCKET))
        conn.sendall((json.dumps({'command': command, 'request_id': 1}) + '\n').encode())
        with conn.makefile('r') as stream:
            for line in stream:
                reply = json.loads(line)
                if reply.get('request_id') == 1:
                    if reply.get('error') != 'success':
                        raise RuntimeError(reply.get('error'))
                    return reply.get('data')
    raise RuntimeError('mpv disconnected')


def player():
    try:
        ipc(['get_property', 'idle-active'])
        return
    except (OSError, RuntimeError):
        pass
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if RUNTIME.stat().st_uid != os.getuid():
        raise RuntimeError('Runtime directory has a different owner')
    RUNTIME.chmod(0o700)
    SOCKET.unlink(missing_ok=True)
    cmd = ['mpv', '--no-config', '--no-video', '--idle=yes', '--no-terminal',
           '--volume=60', f'--input-ipc-server={SOCKET}']
    device = os.environ.get('MUSIC_AUDIO_DEVICE')
    if device:
        cmd.append(f'--audio-device={device}')
    with (RUNTIME / 'mpv.log').open('ab') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
    for _ in range(50):
        if proc.poll() is not None:
            raise RuntimeError(f'mpv failed; inspect {RUNTIME / "mpv.log"}')
        try:
            ipc(['get_property', 'idle-active'])
            return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('mpv startup timeout')


def resolve(query):
    manifest = ROOT / (key(query) + '.json')
    if manifest.exists():
        data = json.loads(manifest.read_text())
        path = (ROOT / data['file']).resolve()
        if path.parent == ROOT and path.is_file() and path.stat().st_size:
            return path, data['title'], True
    if not shutil.which('yt-dlp'):
        raise RuntimeError('yt-dlp missing; run installer')
    # Print only final postprocessed filename. Partial files never enter the index.
    cmd = ['yt-dlp', '--ignore-config', '--no-playlist', '--no-progress',
           '--socket-timeout', '20', '--retries', '2', '-f', 'bestaudio/best',
           '-x', '--audio-format', 'opus', '--write-info-json',
           '-o', str(ROOT / '%(id)s.%(ext)s'),
           '--print', 'after_move:filepath', '--', 'ytsearch1:' + query]
    if shutil.which('node') and not shutil.which('deno'):
        cmd[1:1] = ['--js-runtimes', 'node']
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, timeout=240, check=True)
    files = result.stdout.strip().splitlines()
    if not files:
        raise RuntimeError('No track found')
    path = Path(files[-1]).resolve()
    if path.parent != ROOT or not path.is_file() or not path.stat().st_size:
        raise RuntimeError('Downloader did not produce a complete cache file')
    info_path = path.with_suffix('.info.json')
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    title = info.get('title', query)
    temp = manifest.with_suffix('.tmp')
    temp.write_text(json.dumps({'file': path.name, 'title': title, 'query': query}, ensure_ascii=False))
    temp.replace(manifest)
    return path, title, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('play').add_argument('query', help='Canonical artist - title, one argument')
    sub.add_parser('stop')
    sub.add_parser('status')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command in ('stop', 'status'):
            try:
                if args.command == 'stop':
                    ipc(['stop'])
                    data = {'status': 'stopped'}
                else:
                    idle = ipc(['get_property', 'idle-active'])
                    data = {'status': 'idle' if idle else 'playing'}
            except (OSError, RuntimeError):
                data = {'status': 'not_running'}
        else:
            if not args.query.strip() or len(args.query) > 500:
                raise ValueError('Query must contain 1–500 characters')
            if not shutil.which('mpv'):
                raise RuntimeError('mpv missing; run installer')
            path, title, cached = resolve(args.query.strip())
            player()
            ipc(['loadfile', str(path), 'replace'])
            for _ in range(50):
                try:
                    if ipc(['get_property', 'path']) == str(path) and ipc(['get_property', 'time-pos']) is not None:
                        break
                except RuntimeError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError(f'Playback did not start; inspect {RUNTIME / "mpv.log"}')
            data = {'status': 'playing', 'title': title, 'cached': cached, 'file': str(path)}
        print(json.dumps(data, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
