#!/usr/bin/env python3
"""Local Piper/Silero synthesis, shared by the speaker daemon and OpenClaw CLI.
No network downloads at runtime. Settings are reloaded for every utterance.
"""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import wave

ROOT = Path(os.environ.get('VOICE_ROOT', str(Path.home() / '.local/share/openclaw-voice'))).expanduser()
SETTINGS = ROOT / 'tts-settings.json'
SILERO_MODEL = ROOT / 'silero/v5_6_ru.pt'
VOICES = {
    'piper:denis': {'engine': 'piper', 'voice': 'denis', 'gender': 'male'},
    'piper:irina': {'engine': 'piper', 'voice': 'irina', 'gender': 'female'},
    **{f'silero:{name}': {'engine': 'silero', 'voice': name,
       'gender': 'female' if name in ('baya', 'kseniya', 'xenia') else 'male'}
       for name in ('baya', 'kseniya', 'xenia', 'aidar', 'eugene')},
}
DEFAULT = {'voice': 'silero:xenia', 'sample_rate': 24000}
_models = {}


def read_settings():
    settings = {**DEFAULT, **(json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {})}
    if settings['voice'] not in VOICES:
        raise ValueError('Unknown configured voice')
    if settings['sample_rate'] not in (8000, 24000, 48000):
        raise ValueError('Unsupported sample rate')
    return settings


def select_voice(voice):
    if voice not in VOICES:
        raise ValueError('Unknown voice: ' + voice)
    settings = {**read_settings(), 'voice': voice}
    descriptor = VOICES[voice]
    model_path = SILERO_MODEL if descriptor['engine'] == 'silero' else ROOT / f"ru_RU-{descriptor['voice']}-medium.onnx"
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    fd, name = tempfile.mkstemp(prefix='.tts-settings-', dir=ROOT)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(name, SETTINGS)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return settings


def load_silero():
    if 'silero' not in _models:
        import torch
        torch.set_num_threads(4)
        model = torch.package.PackageImporter(str(SILERO_MODEL)).load_pickle('tts_models', 'model')
        model.to(torch.device('cpu'))
        _models['silero'] = model
    return _models['silero']


def chunks(text, limit=700):
    # Keep individual inputs bounded, preferably splitting at sentence boundaries.
    while len(text) > limit:
        boundary = max(text.rfind(mark, 0, limit) for mark in '.!?;\n')
        if boundary < limit // 3:
            boundary = text.rfind(' ', 0, limit)
        if boundary < 1:
            boundary = limit - 1
        yield text[:boundary + 1].strip()
        text = text[boundary + 1:].strip()
    if text:
        yield text


def synth(text, output, voice=None):
    settings = read_settings()
    selected = voice or settings['voice']
    if selected not in VOICES:
        raise ValueError('Unknown voice: ' + selected)
    desc = VOICES[selected]
    text = re.sub(r'[*#`]', '', text).strip()
    if not text:
        raise ValueError('Empty speech text')
    if desc['engine'] == 'piper':
        from piper import PiperVoice
        if selected not in _models:
            _models[selected] = PiperVoice.load(str(ROOT / f"ru_RU-{desc['voice']}-medium.onnx"))
        with wave.open(str(output), 'wb') as wav:
            _models[selected].synthesize_wav(text, wav)
        return
    import numpy as np
    import torch
    model = load_silero()
    if desc['voice'] not in model.speakers:
        raise ValueError('Voice not present in downloaded Silero model')
    rate = settings['sample_rate']
    with wave.open(str(output), 'wb') as wav, torch.inference_mode():
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for piece in chunks(text):
            audio = model.apply_tts(text=piece, speaker=desc['voice'], sample_rate=rate,
                                    put_accent=True, put_yo=True)
            pcm = (np.clip(audio.detach().cpu().numpy(), -1, 1) * 32767).astype('<i2')
            wav.writeframes(pcm.tobytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--list-voices', action='store_true')
    p.add_argument('--set-voice', choices=VOICES)
    p.add_argument('--voice', choices=VOICES, help='Override this synthesis only')
    p.add_argument('--tts', nargs=2, metavar=('TEXT', 'OUTPUT'))
    a = p.parse_args()
    if a.list_voices:
        print(json.dumps({'selected': read_settings()['voice'], 'voices': VOICES}, ensure_ascii=False, indent=2))
    elif a.set_voice:
        print(json.dumps(select_voice(a.set_voice)))
    elif a.tts:
        synth(*a.tts, voice=a.voice)
    else:
        p.print_help()

if __name__ == '__main__':
    main()
