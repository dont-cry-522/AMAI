"""Offline, foreground-only push-to-talk. Audio stays in memory on this PC."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import re
import threading
import time

from bridge import atomic_write, clean_say, map_allows_voice


class WindowsPushToTalk:
    def __init__(self, game_dir):
        self.paths = {str((Path(game_dir)/n).resolve()).casefold() for n in
                      ('war3.exe', 'Frozen Throne.exe', 'Warcraft III.exe')}
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def held(self):
        return bool(self.user.GetAsyncKeyState(0x76) & 0x8000)  # F7 only

    def foreground(self):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            return bool(self.kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size))
                        and path.value.casefold() in self.paths)
        finally:
            self.kernel.CloseHandle(process)


def recognized_text(parts):
    # Vosk separates Chinese words with spaces; exact emergency commands need none.
    return clean_say(re.sub(r'\s+', '', ''.join(parts))).strip()


def capture(keys, active, stop, stream_factory, recognizer, max_blocks=300):
    """50 ms blocks, max 15 seconds. Losing focus/session discards the utterance."""
    if stop.is_set() or not keys.held() or not keys.foreground() or not active():
        return ''
    parts = []
    with stream_factory() as stream:
        for _ in range(max_blocks):
            if stop.is_set() or not keys.foreground() or not active():
                return ''
            if not keys.held():
                break
            data, overflow = stream.read(800)
            if overflow:
                return ''  # incomplete audio must not become a tactical order
            if recognizer.AcceptWaveform(bytes(data)):
                parts.append(json.loads(recognizer.Result()).get('text', ''))
        else:
            return ''  # holding beyond the limit cancels; never submit before release
        if stop.is_set() or not keys.foreground() or not active():
            return ''
        parts.append(json.loads(recognizer.FinalResult()).get('text', ''))
    return recognized_text(parts)


def render_voice(session, tick, sequence, text):
    payload = f'{session}|{tick}|{sequence}'
    return ('function PreloadFiles takes nothing returns nothing\n'
            f'    call SetPlayerName(Player(12), {json.dumps(payload)})\n'
            f'    call SetPlayerName(Player(13), {json.dumps(clean_say(text), ensure_ascii=False)})\n'
            '    call PreloadEnd(0.0)\nendfunction\n')


class VoiceInput:
    def __init__(self, root, folder, game_dir):
        self.root, self.folder, self.game_dir = Path(root), Path(folder), game_dir
        self.stop = threading.Event()
        self.state = None
        self.fresh_at = 0
        self.queue = queue.Queue(maxsize=8)
        self.pending = None
        self.sequence = 0

    def active(self, session):
        state = self.state
        return bool(map_allows_voice(state) and state['session'] == session
                    and time.monotonic()-self.fresh_at < 4)

    def step(self, state, now):
        old = self.state
        if not old or (old['session'], old['tick']) != (state['session'], state['tick']):
            self.fresh_at = now
        self.state = state
        if not map_allows_voice(state) or now-self.fresh_at >= 4:
            self.pending = None
            return
        if not old or old['session'] != state['session']:
            self.pending = None
            self.sequence = state.get('voice_ack', 0)
        self.sequence = max(self.sequence, state.get('voice_ack', 0))
        if self.pending:
            session, sequence, text, created = self.pending
            if session != state['session'] or state.get('voice_ack', 0) >= sequence or now-created > 15:
                self.pending = None
        while not self.pending:
            try:
                session, text, created = self.queue.get_nowait()
            except queue.Empty:
                break
            if session == state['session'] and now-created <= 15:
                self.sequence += 1
                self.pending = (session, self.sequence, text, created)
        if self.pending:
            session, sequence, text, _ = self.pending
            atomic_write(self.folder/'voice.txt', render_voice(session, state['tick'], sequence, text))

    def start(self):
        threading.Thread(target=self.worker, name='push-to-talk', daemon=True).start()

    def worker(self):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(self.root/'voice-model'))
            if self.stop.is_set():
                return
            keys = WindowsPushToTalk(self.game_dir)
            print('语音已准备：在新版测试地图内按住 F7 说话，松开提交。单次最多 15 秒。', flush=True)
            armed = False  # require a key-up before first capture, including after Alt-Tab
            while not self.stop.wait(0.03):
                if not keys.held():
                    armed = True
                    continue
                if not armed:
                    continue
                armed = False
                state = self.state
                session = state['session'] if state else None
                if not self.active(session) or not keys.foreground():
                    continue
                try:
                    text = capture(keys, lambda: self.active(session), self.stop,
                        lambda: sd.RawInputStream(samplerate=16000, blocksize=800,
                                                 dtype='int16', channels=1),
                        KaldiRecognizer(model, 16000))
                    if text and self.active(session):
                        self.queue.put_nowait((session, text, time.monotonic()))
                    else:
                        print('本次语音未提交：没有识别到完整语句，或已离开游戏。', flush=True)
                except (sd.PortAudioError, queue.Full):
                    print('本次语音未提交：请检查默认麦克风，或稍后重试。中文打字仍可用。', flush=True)
        except Exception as error:
            # No audio, recognized text, paths, or credentials are logged.
            print('语音未能启用（'+type(error).__name__+'）；中文打字和 Esc 指挥仍可用。', flush=True)
