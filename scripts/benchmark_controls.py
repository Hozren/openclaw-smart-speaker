#!/usr/bin/env python3
"""Replay a test WAV in real time; report fast-control recognition without taking actions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np
import webrtcvad
from fast_controls import FastControls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav')
    parser.add_argument('--expect', help='pause:auto, resume:music, stop:speech, or none')
    args = parser.parse_args()
    root = Path(os.environ.get('VOICE_ROOT', '~/.local/share/openclaw-voice')).expanduser()
    model = os.environ.get('VOICE_CONTROL_MODEL', str(root/'vosk-model-small-ru-0.22'))
    pcm = subprocess.check_output(['ffmpeg','-v','error','-i',args.wav,'-ar','16000',
                                   '-ac','1','-f','s16le','-'])
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.int32)
    audible = np.where(np.abs(samples)>300)[0]
    # Approximation, not a forced-alignment measurement of spoken word boundaries.
    speech_end = (audible[-1]+1)/16000 if len(audible) else 0
    events = []
    detector = FastControls(model, os.environ.get('VOICE_WAKE','Луна'),
                            lambda *command: events.append((command,time.monotonic())))
    detector.begin()
    vad = webrtcvad.Vad(2)
    data = pcm + b'\0'*32000
    started = time.monotonic()
    for offset in range(0,len(data),960):
        frame = data[offset:offset+960].ljust(960,b'\0')
        time.sleep(max(0, started+(offset+960)/32000-time.monotonic()))
        detector.feed(frame,vad.is_speech(frame,16000))
    detector.finish()
    command = ':'.join(events[0][0]) if events else 'none'
    print(json.dumps({'command':command, 'events':len(events),
        'estimated_after_speech_ms':round((events[0][1]-started-speech_end)*1000) if events else None}))
    if args.expect and args.expect != command:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
