"""Real mpv IPC and worker integration, null audio output (no hardware required)."""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import unittest
import wave
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import operations as ops
from voice_turn import VoiceTurn


def wait_for(predicate, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.03)
    raise AssertionError('Condition timed out')


@unittest.skipUnless(shutil.which('mpv'), 'mpv not installed')
class PlaybackTest(unittest.TestCase):
    def test_real_speech_pause_resume_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ops, 'ROOT', root), patch.object(ops, 'SPEECH_SOCKET', root/'speech.sock'), patch.object(ops, 'MUSIC_SOCKET', root/'absent.sock'):
                def synth(text, path):
                    with wave.open(str(path), 'wb') as wav:
                        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                        wav.writeframes(b'\0\0' * 16000 * 6)
                original = subprocess.Popen
                def null_player(argv, **kwargs):
                    return original([arg if not arg.startswith('--audio-device=') else '--ao=null' for arg in argv], **kwargs)
                turn = VoiceTurn(lambda _: 'test', synth, 'unused')
                with patch('voice_turn.subprocess.Popen', side_effect=null_player):
                    turn.start('question')
                    try:
                        wait_for(lambda: ops.read('speech').get('phase') == 'playing')
                        self.assertEqual(ops.dispatch('pause')['status'], 'paused')
                        position = ops.ipc(ops.SPEECH_SOCKET, ['get_property', 'time-pos'])
                        time.sleep(.15)
                        self.assertEqual(position, ops.ipc(ops.SPEECH_SOCKET, ['get_property', 'time-pos']))
                        self.assertEqual(ops.dispatch('resume')['status'], 'running')
                        wait_for(lambda: ops.ipc(ops.SPEECH_SOCKET, ['get_property', 'time-pos']) > position)
                        self.assertEqual(ops.dispatch('stop', 'speech')['status'], 'stopped')
                    finally:
                        ops.dispatch('stop', 'speech')
                        turn.thread.join(3)
                    self.assertFalse(turn.busy())
                    self.assertEqual(turn.followup_until, 0)

    def test_real_music_priority_and_addressing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ops, 'ROOT', root), patch.object(ops, 'MUSIC_SOCKET', root/'music.sock'):
                audio = root/'music.wav'
                with wave.open(str(audio), 'wb') as wav:
                    wav.setparams((1,2,16000,0,'NONE','not compressed'))
                    wav.writeframes(b'\0\0' * 16000 * 6)
                proc = subprocess.Popen(['mpv','--no-config','--ao=null','--no-video','--idle=yes',
                    '--input-ipc-server='+str(ops.MUSIC_SOCKET),str(audio)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    def ready():
                        try: return ops.ipc(ops.MUSIC_SOCKET,['get_property','time-pos']) is not None
                        except (OSError,RuntimeError): return False
                    wait_for(ready)
                    token = ops.new_speech()
                    self.assertEqual(ops.dispatch('pause')['target'],'speech')
                    self.assertFalse(ops.ipc(ops.MUSIC_SOCKET,['get_property','pause']))
                    self.assertEqual(ops.dispatch('pause')['target'],'music')
                    self.assertTrue(ops.ipc(ops.MUSIC_SOCKET,['get_property','pause']))
                    self.assertEqual(ops.dispatch('resume')['target'],'music')
                    self.assertEqual(ops.speech_state(token),'paused')
                    self.assertEqual(ops.dispatch('stop','music')['status'],'stopped')
                    wait_for(lambda: ops.ipc(ops.MUSIC_SOCKET,['get_property','idle-active']))
                    self.assertEqual(ops.dispatch('resume','music')['status'],'no_target')
                finally:
                    proc.terminate(); proc.wait(timeout=3)


if __name__ == '__main__': unittest.main()

class ConveniencePlaybackTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('mpv'), 'mpv not installed')
    def test_real_duck_and_night(self):
        from amenities import Amenities, Store
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(ops,'ROOT',root/'ops'),patch.object(ops,'MUSIC_SOCKET',root/'music.sock'),patch.object(ops,'SPEECH_SOCKET',root/'speech.sock'):
                proc=subprocess.Popen(['mpv','--no-config','--ao=null','--idle=yes','--volume=60','--input-ipc-server='+str(ops.MUSIC_SOCKET)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try:
                    def ready():
                        try: return ops.ipc(ops.MUSIC_SOCKET,['get_property','volume'])==60
                        except OSError: return False
                    wait_for(ready)
                    a=Amenities(store=Store(root/'data'))
                    with patch.object(a,'cue'):
                        a.wake()
                    self.assertEqual(ops.ipc(ops.MUSIC_SOCKET,['get_property','volume']),15)
                    a.release()
                    self.assertEqual(ops.ipc(ops.MUSIC_SOCKET,['get_property','volume']),60)
                    a.handle('включи ночной режим')
                    self.assertEqual(ops.ipc(ops.MUSIC_SOCKET,['get_property','volume']),30)
                finally:
                    proc.terminate();proc.wait(timeout=3)
