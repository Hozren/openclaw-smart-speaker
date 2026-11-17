"""Streaming fixed-vocabulary controls, independent of Whisper and the agent."""
import json
from pathlib import Path
import operations
from amenities import quick_parse, normalize

# Address-bearing verbs wait for a target or short silence. Stop is reserved/eager.
EAGER = {'стоп', 'пауза', 'замолчи', 'молчи', 'хватит'}


class FastControls:
    def __init__(self, model_path, wake, callback, recognizer=None, on_wake=None):
        self.on_wake = on_wake
        self.factory = None
        self.wake = wake
        self.callback = callback
        if recognizer is None:
            import vosk
            vosk.SetLogLevel(-1)
            if not Path(model_path).is_dir():
                raise FileNotFoundError('Install the local Vosk control model first')
            self.model = vosk.Model(str(model_path))
            # Full vocabulary avoids forcing unrelated speech into control phrases.
            self.factory = lambda: vosk.KaldiRecognizer(self.model, 16000)
            recognizer = self.factory()
        self.rec = recognizer
        self.begin()

    def begin(self):
        if self.factory:
            self.rec = self.factory()
        else:
            self.rec.Reset()
        self.woke = False
        self.fired = False
        self.candidate = None
        self.stable_seconds = 0
        self.silence_seconds = 0
        self.audio_seconds = 0

    def consider(self, text, duration, final=False):
        clean = normalize(text)
        if not self.woke and (clean == normalize(self.wake) or clean.startswith(normalize(self.wake)+' ')):
            self.woke = True
            if self.on_wake: self.on_wake()
        command = operations.parse(text, self.wake) or quick_parse(text, self.wake)
        if command != self.candidate:
            self.candidate = command
            self.stable_seconds = 0
        else:
            self.stable_seconds += duration
        if not command or self.fired:
            return
        words = text.casefold().split()
        if words and words[0] == self.wake.casefold(): words = words[1:]
        eager = words and words[0] in EAGER
        # Do not act on 'останови' before hearing 'музыку'. Final result is fallback.
        ready = (command[1] != 'auto' or eager or self.silence_seconds >= .45)
        if command[0] in ('volume', 'volume_delta'): ready = self.silence_seconds >= .3
        if final or (ready and self.stable_seconds >= .09):
            self.fired = True  # One event per utterance, even when no active target.
            self.callback(*command)

    def feed(self, pcm, active=True):
        duration = len(pcm) / 32000
        self.audio_seconds += duration
        self.silence_seconds = 0 if active else self.silence_seconds + duration
        if self.fired:
            return
        final = self.rec.AcceptWaveform(pcm)
        result = json.loads(self.rec.Result() if final else self.rec.PartialResult())
        self.consider(result.get('text' if final else 'partial', ''), duration, final)

    def finish(self):
        if not self.fired:
            self.consider(json.loads(self.rec.FinalResult()).get('text', ''), 0, True)
        return self.fired
