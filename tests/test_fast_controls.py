import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from fast_controls import FastControls


class FakeRecognizer:
    def Reset(self): pass


class FastTest(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.fast=FastControls('unused','Луна',lambda *cmd:self.events.append(cmd),recognizer=FakeRecognizer())

    def stable(self,text):
        for _ in range(5): self.fast.consider(text,.03)

    def test_eager_pause_once(self):
        self.stable('стоп');self.stable('стоп')
        self.assertEqual(self.events,[('pause','auto')])

    def test_wait_for_address(self):
        self.stable('останови')
        self.assertEqual(self.events,[])
        self.stable('останови музыку')
        self.assertEqual(self.events,[('pause','music')])

    def test_resume_waits_for_short_silence(self):
        self.stable('продолжи');self.assertEqual(self.events,[])
        self.fast.silence_seconds=.5
        self.stable('продолжи')
        self.assertEqual(self.events,[('resume','auto')])

    def test_false_start_and_non_command(self):
        self.fast.consider('стоп',.03)
        self.stable('[unk]')
        self.stable('скажи слово стоп')
        self.stable('продолжи рассказ')
        self.assertEqual(self.events,[])

    def test_reset_and_final(self):
        self.fast.consider('продолжи ответ',0,final=True)
        self.fast.begin()
        self.fast.consider('пауза',0,final=True)
        self.assertEqual(self.events,[('resume','speech'),('pause','auto')])


if __name__=='__main__':unittest.main()
