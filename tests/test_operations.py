import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import operations as ops
from voice_turn import VoiceTurn


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = patch.object(ops, 'ROOT', Path(self.tmp.name))
        self.root.start(); self.addCleanup(self.root.stop)
        self.music = {'idle-active': False, 'pause': False}
        self.calls = []
        def ipc(path, command):
            self.calls.append((path, command))
            if path != ops.MUSIC_SOCKET:
                raise OSError('no speech player')
            if command[0] == 'get_property': return self.music[command[1]]
            if command[0] == 'set_property': self.music[command[1]] = command[2]
            if command[0] == 'stop': self.music['idle-active'] = True
        self.mock = patch.object(ops, 'ipc', side_effect=ipc)
        self.mock.start(); self.addCleanup(self.mock.stop)

    def test_exact_grammar_not_mentions_or_tasks(self):
        self.assertEqual(ops.parse('Луна, останови музыку!'), ('pause', 'music'))
        self.assertEqual(ops.parse('Продолжи.'), ('resume', 'auto'))
        self.assertEqual(ops.parse('Продолжим музыку.'), ('resume', 'music'))
        for text in ['скажи слово стоп', 'стоп таймер', 'стоп и включи песню', 'продолжи рассказ']:
            self.assertIsNone(ops.parse(text))

    def test_speech_priority_and_last_paused_resume(self):
        token = ops.new_speech()
        self.assertEqual(ops.dispatch('pause')['target'], 'speech')
        self.assertFalse(self.music['pause'])
        self.assertEqual(ops.speech_state(token), 'paused')
        self.assertEqual(ops.dispatch('pause')['target'], 'music')
        self.assertTrue(self.music['pause'])
        self.assertEqual(ops.dispatch('resume')['target'], 'music')
        self.assertEqual(ops.dispatch('resume')['target'], 'speech')
        self.assertEqual(ops.dispatch('pause', 'music')['target'], 'music')
        self.assertEqual(ops.speech_state(token), 'running')

    def test_missing_player_and_invalid_target(self):
        self.music['idle-active'] = True
        self.assertEqual(ops.dispatch('pause')['status'], 'no_target')
        with self.assertRaises(ValueError): ops.dispatch('pause', '../../evil')

    def test_failed_ack_does_not_claim_success(self):
        ops.new_speech()
        with ops.locked():
            record = ops.read('speech'); record['phase'] = 'playing'; ops.save(record)
        self.assertEqual(ops.dispatch('pause', 'speech')['status'], 'error')
        self.assertEqual(ops.read('speech')['state'], 'running')

    def test_pause_during_generation_blocks_audio_and_cancel_suppresses_reply(self):
        entered, release, synth_called = threading.Event(), threading.Event(), threading.Event()
        def ask(text):
            entered.set(); release.wait(2); return 'Answer'
        turn = VoiceTurn(ask, lambda *a: synth_called.set(), 'unused')
        self.assertTrue(turn.start('question')); self.assertTrue(entered.wait(1))
        self.assertFalse(turn.start('second question'))
        ops.dispatch('pause', 'speech')
        release.set(); time.sleep(.1)
        self.assertFalse(synth_called.is_set())
        ops.dispatch('stop', 'speech')
        turn.thread.join(2)
        self.assertFalse(turn.busy())
        self.assertFalse(synth_called.is_set())
        self.assertEqual(turn.followup_until, 0)

    def test_restart_invalidates_old_reply(self):
        old = ops.new_speech()
        VoiceTurn(None, None, 'unused')
        self.assertEqual(ops.speech_state(old), 'finished')


if __name__ == '__main__': unittest.main()
