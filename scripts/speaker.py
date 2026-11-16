#!/usr/bin/env python3
import argparse, collections, json, logging, os, re, signal, subprocess, tempfile, time, wave
from pathlib import Path
import queue, threading
import operations
from voice_turn import VoiceTurn
from fast_controls import FastControls
import numpy as np
from faster_whisper import WhisperModel
from local_tts import synth
import webrtcvad
ROOT=Path(os.environ.get('VOICE_ROOT', str(Path.home()/'.local/share/openclaw-voice'))).expanduser()
AGENT=os.environ.get('VOICE_AGENT','voice')
WAKE=os.environ.get('VOICE_WAKE','Луна')
OPENCLAW=os.environ.get('VOICE_OPENCLAW','openclaw')
SESSION=os.environ.get('VOICE_SESSION',f'agent:{AGENT}:voice-speaker')
GAIN=float(os.environ.get('VOICE_GAIN','1'))
THREADS=int(os.environ.get('VOICE_THREADS','4'))
MIC=os.environ.get('VOICE_MIC','')
SINK=os.environ.get('VOICE_SINK','')
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
log=logging.getLogger('speaker')
whisper=None
FOLLOWUP_SECONDS=float(os.environ.get('VOICE_FOLLOWUP_SECONDS','15'))

def transcribe(audio):
 started=time.monotonic()
 global whisper
 if whisper is None: whisper=WhisperModel(str(ROOT/'whisper-small'),device='cpu',compute_type='int8',cpu_threads=THREADS)
 segments,_=whisper.transcribe(audio,language='ru',beam_size=3,condition_on_previous_text=False,vad_filter=True,initial_prompt=f'{WAKE} — имя голосового помощника.')
 text=' '.join(s.text.strip() for s in segments).strip()
 log.info('ASR completed in %.2fs',time.monotonic()-started)
 return text

def speak(text):
 with tempfile.TemporaryDirectory(prefix='openclaw-speech-') as d:
  started=time.monotonic()
  path=Path(d)/'reply.wav'; synth(text,path)
  log.info('TTS ready in %.2fs; starting playback',time.monotonic()-started)
  subprocess.run(['mpv','--no-video','--really-quiet','--audio-device=pipewire/'+SINK,str(path)],check=True,timeout=180)

def ask(text):
 started=time.monotonic()
 prompt='Голосовой запрос с домашней USB-гарнитуры. Ответь по-русски, кратко, обычным текстом без разметки для озвучки. Запрос пользователя: '+text
 result=subprocess.run([OPENCLAW,'agent','--agent',AGENT,'--session-key',SESSION,'--thinking','low','--message',prompt,'--json','--timeout','180'],capture_output=True,text=True,timeout=195)
 if result.returncode: raise RuntimeError('OpenClaw request failed')
 raw=result.stdout
 try: data=json.loads(raw)
 except json.JSONDecodeError: data=json.loads(raw[raw.index('{'):])
 if data.get('status') in ('error','timeout'): raise RuntimeError('OpenClaw returned error')
 body=data.get('result',data)
 reply=' '.join(p.get('text','') for p in body.get('payloads',[]) if p.get('text')) or body.get('final','')
 if not reply: raise RuntimeError('Empty reply')
 log.info('Agent completed in %.2fs',time.monotonic()-started)
 return reply

def available():
 try: nodes=json.loads(subprocess.check_output(['pw-dump'],timeout=10))
 except (subprocess.CalledProcessError,subprocess.TimeoutExpired,FileNotFoundError): return False
 names={x.get('info',{}).get('props',{}).get('node.name') for x in nodes}
 return MIC in names and SINK in names

def wake_match(text):
 return re.search(r'^\s*'+re.escape(WAKE)+r'\b[\s,.:!?—-]*',text.replace('\u0301',''),re.I)

def command_from_text(text, followup):
 match=wake_match(text)
 if match: return text[match.end():].strip()
 return text.strip() if followup and text.strip() else None

def capture(utterances, turns, fast):
 vad=webrtcvad.Vad(2)
 while True:
  if not available():
   turns.followup_until=0
   log.info('Waiting for configured microphone and speaker');time.sleep(3);continue
  rec=None
  try:
   rec=subprocess.Popen(['pw-record','--target',MIC,'--rate','16000','--channels','1','--format','s16','-'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
   pre=collections.deque(maxlen=10);frames=[];silence=0;voiced=0
   while True:
    frame=rec.stdout.read(960)
    if len(frame)!=960: raise RuntimeError('Microphone disconnected')
    samples=np.frombuffer(frame,dtype=np.int16).astype(np.float32)
    frame=np.clip(samples*GAIN,-32768,32767).astype(np.int16).tobytes()
    active=vad.is_speech(frame,16000)
    if not frames:
     pre.append(frame)
     voiced=voiced+1 if active else 0
     if voiced>=3:
      frames=list(pre);silence=0
      onset=time.monotonic()
      followup=onset<turns.followup_until
      if fast:
       fast.begin()
       fast.feed(b''.join(frames),active=True)
     continue
    frames.append(frame);silence=0 if active else silence+1
    if fast: fast.feed(frame,active)
    if silence<20 and len(frames)<600: continue
    audio=np.frombuffer(b''.join(frames),dtype=np.int16).astype(np.float32)/32768
    handled=fast.finish() if fast else False
    if not handled:
     try: utterances.put_nowait((audio,followup))
     except queue.Full: log.warning('ASR queue full; utterance discarded')
    frames=[];pre.clear();silence=0;voiced=0
  except Exception as e:
   turns.followup_until=0
   log.error('Capture %s',type(e).__name__);time.sleep(1)
  finally:
   if rec is not None:
    rec.terminate()
    try:rec.wait(timeout=3)
    except subprocess.TimeoutExpired:rec.kill();rec.wait()

def listen():
 if not MIC or not SINK: raise ValueError('Set VOICE_MIC and VOICE_SINK from pw-dump')
 turns=VoiceTurn(ask,synth,SINK,FOLLOWUP_SECONDS)
 utterances=queue.Queue(maxsize=2)
 def control(action,target):
  started=time.monotonic()
  result=operations.dispatch(action,target)
  if action in ('pause','stop'): turns.followup_until=0
  log.info('Fast control action=%s target=%s status=%s dispatch_ms=%.1f',action,target,result['status'],(time.monotonic()-started)*1000)
 fast=None
 if os.environ.get('VOICE_FAST_CONTROLS','1') != '0':
  model=Path(os.environ.get('VOICE_CONTROL_MODEL',str(ROOT/'vosk-model-small-ru-0.22')))
  fast=FastControls(model,WAKE,control)
  log.info('Streaming local controls loaded; Whisper bypass enabled')
 threading.Thread(target=capture,args=(utterances,turns,fast),daemon=True).start()
 log.info('Continuous command listening enabled; wake word: %s',WAKE)
 while True:
  audio,followup=utterances.get()
  try:
   text=transcribe(audio)
   control=operations.parse(text,WAKE)
   if control:
    result=operations.dispatch(*control)
    if control[0] in ('pause','stop'): turns.followup_until=0
    log.info('Local control action=%s target=%s status=%s',*control,result['status'])
    continue
   command=command_from_text(text,followup)
   if command is not None:
    if not turns.start(command): log.info('Busy; only local controls accepted')
  except Exception as e:
   log.error('Recognition/control failed: %s',type(e).__name__)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--tts',nargs=2,metavar=('TEXT','OUTPUT'));p.add_argument('--asr');p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.tts:synth(*a.tts)
 elif a.asr:print(transcribe(a.asr))
 elif a.self_test:
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'test.wav';synth(f'{WAKE}, скажи сколько будет два плюс два.',f)
   text=transcribe(str(f));print('ASR:',text,flush=True)
   assert ('два' in text.lower() or '2' in text) and 'плюс' in text.lower(),text
   match=wake_match(text);assert match is not None, 'Wake word not detected'
   assert wake_match('Привет, как дела?') is None
   reply=ask(text[match.end():].strip());print('AGENT:',reply,flush=True);synth(reply,Path(d)/'answer.wav');print('END_TO_END_OK',flush=True)
 else:
  transcribe(np.zeros(16000,dtype=np.float32));log.info('Whisper loaded');listen()
