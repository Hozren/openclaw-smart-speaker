import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import operations as ops
from amenities import Amenities, Store, quick_parse
from fast_controls import FastControls


class AmenitiesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.a=Amenities(store=Store(self.temp.name))

    def test_volume_parser_and_no_mentions(self):
        self.assertEqual(quick_parse('Луна, громкость тридцать процентов'),('volume','30'))
        self.assertEqual(quick_parse('тише'),('volume_delta','-10'))
        for text in ('расскажи про громкость','скажи тише','громкость 101','громкость минус десять'):
            self.assertIsNone(quick_parse(text))

    def test_notes_persist_and_do_not_execute(self):
        payload='$(touch BAD); важная заметка'
        self.assertEqual(self.a.handle('запомни это '+payload),'Заметка сохранена.')
        second=Amenities(store=Store(self.temp.name))
        self.assertEqual(second.handle('прочитай заметки'),payload)
        second.handle('добавь молоко в покупки')
        self.assertEqual(self.a.handle('что в списке'), 'молоко')
        self.assertIsNone(self.a.handle('обсудим список покупок'))
        self.assertEqual(self.a.store.path.stat().st_mode & 0o777,0o600)

    def test_no_false_success_on_storage_failure(self):
        with patch.object(self.a.store,'entry',side_effect=OSError('full')):
            with self.assertRaises(OSError): self.a.handle('запомни это тест')

    def test_night_limits_and_schedule(self):
        with patch.object(self.a,'apply'):
            self.a.quick('volume','80')
            self.a.handle('включи ночной режим')
            self.assertEqual(self.a.volume(),30)
            self.a.quick('volume_delta','10')
            self.assertEqual(self.a.volume(),30)
            self.a.handle('ночной режим по расписанию')
            self.assertTrue(self.a.night(datetime.datetime(2026,1,1,23)))
            self.assertTrue(self.a.night(datetime.datetime(2026,1,1,7)))
            self.assertFalse(self.a.night(datetime.datetime(2026,1,1,8)))
            self.a.handle('выключи ночной режим')
            self.assertFalse(self.a.night())

    def test_duck_restoration_and_volume_change(self):
        volumes={ops.MUSIC_SOCKET:60,ops.SPEECH_SOCKET:60}
        def ipc(path,cmd):
            if cmd[0]=='get_property': return volumes[path]
            volumes[path]=cmd[2]
        with patch.object(ops,'ROOT',Path(self.temp.name)/'ops'),patch.object(ops,'ipc',side_effect=ipc),patch.object(self.a,'cue'):
            self.a.wake();self.assertEqual(volumes[ops.MUSIC_SOCKET],15)
            self.a.quick('volume','40');self.assertEqual(volumes[ops.MUSIC_SOCKET],15)
            self.a.release();self.assertEqual(volumes[ops.MUSIC_SOCKET],40)
            token=ops.new_speech();self.a.apply();self.assertEqual(volumes[ops.MUSIC_SOCKET],15)
            ops.finish_speech(token);self.a.apply();self.assertEqual(volumes[ops.MUSIC_SOCKET],40)

    def test_wake_does_not_consume_request_and_volume_once(self):
        class Rec:
            def Reset(self): pass
        events=[]; wakes=[]
        fast=FastControls('', 'Луна',lambda *x:events.append(x),Rec(),lambda:wakes.append(1))
        for _ in range(5): fast.consider('луна расскажи историю',.03)
        self.assertEqual(wakes,[1]);self.assertFalse(fast.fired)
        fast.begin()
        fast.consider('громкость тридцать',0,True)
        fast.consider('громкость тридцать',0,True)
        self.assertEqual(events,[('volume','30')])

    def test_music_context_and_local_repeat(self):
        from subprocess import CompletedProcess
        with patch('amenities.subprocess.run',return_value=CompletedProcess([],0,json.dumps({'status':'playing','title':'Song','artist':'Artist'}))) as run:
            self.assertIn('Song',self.a.handle('что играет'))
            self.assertEqual(self.a.handle('повтори'),'Повторяю.')
            self.assertEqual(run.call_args.args[0][-1],'repeat')
            self.assertIn('Artist', self.a.context('включи ещё этого исполнителя'))

if __name__=='__main__': unittest.main()
