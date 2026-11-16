#!/usr/bin/env python3
"""Deterministic media control. Records are data, never executable commands."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import time
import uuid

BASE = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/openclaw-music-{os.getuid()}'))
ROOT = BASE / 'speaker-operations'
MUSIC_SOCKET = BASE / 'speaker-music/mpv.sock'
SPEECH_SOCKET = ROOT / 'speech.sock'


def ipc(path, command):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(1)
        conn.connect(str(path))
        conn.sendall((json.dumps({'command': command, 'request_id': 1})+'\n').encode())
        with conn.makefile('r') as stream:
            for line in stream:
                response = json.loads(line)
                if response.get('request_id') == 1:
                    if response.get('error') != 'success':
                        raise RuntimeError(response.get('error'))
                    return response.get('data')
    raise RuntimeError('Player disconnected')


@contextmanager
def locked():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or ROOT.stat().st_uid != os.getuid():
        raise RuntimeError('Unsafe operation directory')
    ROOT.chmod(0o700)
    with (ROOT / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(kind):
    try:
        return json.loads((ROOT / (kind+'.json')).read_text())
    except FileNotFoundError:
        return None


def save(record):
    path = ROOT / (record['kind']+'.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(record))
    temp.chmod(0o600)
    temp.replace(path)


def process_stamp(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def current_speech():
    record = read('speech')
    if record and record['state'] in ('running', 'paused'):
        if process_stamp(record.get('owner_pid', 0)) != record.get('owner_stamp') or not record.get('owner_stamp'):
            record.update(state='finished', updated=time.monotonic())
            save(record)
    return record


def new_speech():
    with locked():
        record = dict(version=1, id=uuid.uuid4().hex, kind='speech', handler='speech-v1',
                      state='running', phase='generating', updated=time.monotonic(),
                      owner_pid=os.getpid(), owner_stamp=process_stamp(os.getpid()),
                      actions=['pause', 'resume', 'stop'])
        save(record)
        return record['id']


def speech_state(token):
    with locked():
        record = read('speech')
        return record['state'] if record and record['id'] == token else 'stopped'


def finish_speech(token):
    with locked():
        record = read('speech')
        if record and record['id'] == token:
            record.update(state='finished', updated=time.monotonic())
            save(record)


def refresh_music():
    old = read('music')
    try:
        if ipc(MUSIC_SOCKET, ['get_property', 'idle-active']):
            state = 'finished'
        else:
            state = 'paused' if ipc(MUSIC_SOCKET, ['get_property', 'pause']) else 'running'
    except (OSError, RuntimeError):
        state = 'finished'
    record = old or dict(version=1, id='music', kind='music', handler='mpv-v1',
                         actions=['pause', 'resume', 'stop'])
    if record.get('state') != state:
        record.update(state=state, updated=time.monotonic())
    save(record)
    return record


def parse(text, wake='Луна'):
    text = text.casefold().replace('\u0301', '')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = ' '.join(text.split())
    prefix = wake.casefold() + ' '
    if text.startswith(prefix):
        text = text[len(prefix):]
    verbs = {'стоп':'pause', 'пауза':'pause', 'останови':'pause', 'приостанови':'pause',
             'замолчи':'pause', 'молчи':'pause', 'хватит':'pause',
             'продолжи':'resume', 'продолжим':'resume', 'продолжай':'resume', 'возобнови':'resume',
             'отмени':'stop', 'отмена':'stop'}
    parts = text.split()
    if not parts or parts[0] not in verbs:
        return None
    target = ' '.join(parts[1:])
    targets = {'':'auto', 'музыку':'music', 'музыка':'music', 'воспроизведение':'music',
               'речь':'speech', 'ответ':'speech', 'озвучку':'speech'}
    if target not in targets:
        return None
    return verbs[parts[0]], targets[target]


def dispatch(action, target='auto'):
    if action not in ('pause', 'resume', 'stop') or target not in ('auto', 'speech', 'music'):
        raise ValueError('Unsupported action or target')
    with locked():
        music = refresh_music()
        speech = current_speech()
        candidates = [r for r in (speech, music) if r and r['state'] in ('running', 'paused')]
        if target != 'auto':
            candidates = [r for r in candidates if r['kind'] == target]
        elif action == 'resume':
            candidates = sorted((r for r in candidates if r['state'] == 'paused'),
                                key=lambda r: r['updated'], reverse=True)
        else:
            candidates = [r for r in candidates if r['state'] == 'running']
        if not candidates:
            return {'status':'no_target'}
        record = candidates[0]
        path = SPEECH_SOCKET if record['kind'] == 'speech' else MUSIC_SOCKET
        # Pending speech has no player yet. The worker observes state before audio starts.
        if record['kind'] == 'music' or record.get('phase') == 'playing':
            try:
                ipc(path, ['stop'] if action == 'stop' else ['set_property', 'pause', action == 'pause'])
                if action != 'stop' and ipc(path, ['get_property', 'pause']) != (action == 'pause'):
                    raise RuntimeError('Pause state not acknowledged')
            except (OSError, RuntimeError) as error:
                return {'status':'error', 'error':str(error), 'target':record['kind']}
        record.update(state={'pause':'paused','resume':'running','stop':'stopped'}[action],
                      updated=time.monotonic())
        save(record)
        return {'status':record['state'], 'target':record['kind'], 'id':record['id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['pause', 'resume', 'stop', 'status', 'text'])
    parser.add_argument('target', nargs='?', default='auto')
    args = parser.parse_args()
    if args.action == 'status':
        with locked():
            refresh_music()
            result = [current_speech(), read('music')]
    elif args.action == 'text':
        command = parse(args.target, os.environ.get('VOICE_WAKE', 'Луна'))
        result = dispatch(*command) if command else {'status':'unrecognized'}
    else:
        result = dispatch(args.action, args.target)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
