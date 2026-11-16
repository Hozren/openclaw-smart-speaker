#!/usr/bin/env python3
import argparse, collections, json, logging, os, re, signal, subprocess, tempfile, time, wave
from pathlib import Path
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

def listen():
 if not MIC or not SINK: raise ValueError('Set VOICE_MIC and VOICE_SINK from pw-dump')
 vad=webrtcvad.Vad(2)
 followup_until=0
 while True:
  if not available():
   followup_until=0
   log.info('Waiting for configured microphone and speaker');time.sleep(10);continue
  rec=None
  try:
   rec=subprocess.Popen(['pw-record','--target',MIC,'--rate','16000','--channels','1','--format','s16','-'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
   pre=collections.deque(maxlen=10);frames=[];silence=0;voiced=0
   log.info('Listening for follow-up (no wake word)' if time.monotonic()<followup_until else f'Listening for wake word: {WAKE}')
   while True:
    frame=rec.stdout.read(960)
    if len(frame)!=960: raise RuntimeError('Microphone disconnected')
    samples=np.frombuffer(frame,dtype=np.int16).astype(np.float32)
    # Bounded input gain for the quiet USB microphone; no stored recordings.
    frame=np.clip(samples*GAIN,-32768,32767).astype(np.int16).tobytes()
    active=vad.is_speech(frame,16000)
    if not frames:
     pre.append(frame)
     voiced=voiced+1 if active else 0
     if voiced>=3:
      frames=list(pre);silence=0
      followup=time.monotonic()<followup_until
     continue
    frames.append(frame);silence=0 if active else silence+1
    if silence<20 and len(frames)<600: continue
    rec.terminate();rec.wait(timeout=3);rec=None
    audio=np.frombuffer(b''.join(frames),dtype=np.int16).astype(np.float32)/32768
    text=transcribe(audio)
    command=command_from_text(text,followup)
    if command is not None:
     if re.fullmatch(r'(стоп|молчи|отмена|хватит|конец разговора)[.!? ]*',command,re.I):
      followup_until=0
      speak('Хорошо.')
      log.info('Conversation closed; wake word required')
     else:
      if not command:
       speak('Слушаю.')
      else:
       log.info('Voice command accepted; sending voice turn')
       speak(ask(command))
       log.info('Voice turn completed')
      followup_until=time.monotonic()+FOLLOWUP_SECONDS
      log.info('Follow-up window opened for %s seconds',FOLLOWUP_SECONDS)
    else: log.info('Empty speech or speech without wake word ignored')
    break
  except Exception as e:
   followup_until=0
   log.error('%s: %s',type(e).__name__,e);time.sleep(3)
  finally:
   if rec is not None:
    rec.terminate()
    try:rec.wait(timeout=3)
    except subprocess.TimeoutExpired:rec.kill();rec.wait()

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
