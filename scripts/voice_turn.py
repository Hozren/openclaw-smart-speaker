"""One asynchronous response; microphone and deterministic control remain independent."""
from pathlib import Path
import logging
import subprocess
import tempfile
import threading
import time
import operations as ops

log = logging.getLogger('speaker')


class VoiceTurn:
    def __init__(self, ask, synth, sink, followup_seconds=15):
        self.ask, self.synth, self.sink = ask, synth, sink
        self.followup_seconds = followup_seconds
        self.followup_until = 0
        self.thread = None
        self.token = None
        # A restart must not resurrect an old paused answer.
        with ops.locked():
            old = ops.read('speech')
            if old:
                old.update(state='finished', updated=time.monotonic())
                ops.save(old)

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, command):
        if self.busy():
            return False
        self.token = ops.new_speech()
        self.thread = threading.Thread(target=self.run, args=(command, self.token), daemon=True)
        self.thread.start()
        return True

    def ready(self, token):
        while True:
            state = ops.speech_state(token)
            if state != 'paused':
                return state == 'running'
            time.sleep(.05)

    def run(self, command, token):
        proc = None
        completed = False
        try:
            reply = self.ask(command) if command else 'Слушаю.'
            if not self.ready(token):
                return
            with tempfile.TemporaryDirectory(prefix='openclaw-speech-') as directory:
                path = Path(directory) / 'reply.wav'
                self.synth(reply, path)
                if not self.ready(token):
                    return
                # Player starts paused, eliminating the stop-vs-launch audio race.
                ops.SPEECH_SOCKET.unlink(missing_ok=True)
                proc = subprocess.Popen(['mpv', '--no-config', '--no-video', '--really-quiet',
                    '--pause=yes', '--keep-open=no', '--audio-device=pipewire/'+self.sink,
                    '--input-ipc-server='+str(ops.SPEECH_SOCKET), str(path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(100):
                    if proc.poll() is not None:
                        raise RuntimeError('Speech player exited before ready')
                    try:
                        ops.ipc(ops.SPEECH_SOCKET, ['get_property', 'pause'])
                        break
                    except OSError:
                        time.sleep(.05)
                else:
                    raise RuntimeError('Speech player startup timeout')
                with ops.locked():
                    record = ops.read('speech')
                    if record['id'] != token or record['state'] not in ('paused', 'running'):
                        return
                    record['phase'] = 'playing'
                    ops.ipc(ops.SPEECH_SOCKET, ['set_property', 'pause', record['state'] == 'paused'])
                    ops.save(record)
                while proc.poll() is None:
                    if ops.speech_state(token) == 'stopped':
                        return
                    time.sleep(.05)
                if proc.returncode:
                    raise RuntimeError('Speech playback failed')
                completed = ops.speech_state(token) == 'running'
        except Exception:
            log.exception('Voice turn failed')
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
            ops.finish_speech(token)
            if completed:
                self.followup_until = time.monotonic() + self.followup_seconds
            log.info('Voice turn finished; completed=%s', completed)
