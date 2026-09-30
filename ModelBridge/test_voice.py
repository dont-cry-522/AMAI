"""Offline checks: no microphone, Windows hooks, game, registry, or paid API."""
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from voice import VoiceInput, capture, recognized_text, render_voice


class Keys:
    down = True
    focused = True
    def held(self): return self.down
    def foreground(self): return self.focused


class Recognizer:
    def AcceptWaveform(self, data): return False
    def FinalResult(self): return json.dumps({'text':'跟 我 走'},ensure_ascii=False)


def run():
    keys=Keys()
    opened=[]
    stop=threading.Event()
    class Stream:
        def __enter__(self): opened.append(1); return self
        def __exit__(self,*args): pass
        def read(self,frames): keys.down=False; return bytes(frames*2),False
    # Audio device is never opened without a new held key AND game focus.
    keys.down=False
    assert capture(keys,lambda:True,stop,Stream,Recognizer())=='' and not opened
    keys.down=True;keys.focused=False
    assert capture(keys,lambda:True,stop,Stream,Recognizer())=='' and not opened
    keys.focused=True
    assert capture(keys,lambda:True,stop,Stream,Recognizer())=='跟我走' and len(opened)==1
    class LostFocus(Stream):
        def read(self,frames): keys.focused=False; return bytes(frames*2),False
    keys.down=True
    assert capture(keys,lambda:True,stop,LostFocus,Recognizer())==''
    keys.focused=True
    class Overflow(Stream):
        def read(self,frames): return bytes(frames*2),True
    assert capture(keys,lambda:True,stop,Overflow,Recognizer())==''
    class LongSpeech(Stream):
        def read(self,frames): return bytes(frames*2),False
    assert capture(keys,lambda:True,stop,LongSpeech,Recognizer(),max_blocks=2)==''
    assert recognized_text(['快 撤'])=='快撤'
    assert len(render_voice(10,2,3,'"\ncall ExecuteFunc("bad")\\|').splitlines())==5
    with tempfile.TemporaryDirectory() as tmp:
        voice=VoiceInput(tmp,tmp,tmp)
        old=dict(session=10,tick=1,version=0,voice_ack=0)
        voice.step(old,100)
        assert not (Path(tmp)/'voice.txt').exists()
        current={**old,'version':4,'tick':2}
        voice.queue.put((10,'跟我走',101))
        voice.step(current,101)
        first=(Path(tmp)/'voice.txt').read_text(encoding='utf-8')
        assert '10|2|1' in first and '跟我走' in first
        voice.step({**current,'tick':3,'voice_ack':1},102)
        assert voice.pending is None
        voice.queue.put((10,'重复指令',102))
        voice.queue.put((11,'过期',50))
        voice.queue.put((11,'快撤',103))
        voice.step({**current,'session':11,'tick':1},103)
        assert '快撤' in (Path(tmp)/'voice.txt').read_text(encoding='utf-8')
        assert voice.pending[0]==11 and voice.pending[1]==1
        before=(Path(tmp)/'voice.txt').read_bytes()
        voice.step({**current,'session':11,'tick':1},110)
        assert before==(Path(tmp)/'voice.txt').read_bytes()  # paused/exited game
        # A normal map must neither publish queued speech nor open the microphone.
        ordinary=dict(session=12,tick=1,version=5,mode='llm',voice_ack=0)
        voice.queue.put((12,'不能发送的语音',111))
        voice.step(ordinary,111)
        with patch('voice.time.monotonic',return_value=111):
            assert not voice.active(12)
            keys.down=True;keys.focused=True
            count=len(opened)
            assert capture(keys,lambda:voice.active(12),stop,Stream,Recognizer())==''
            assert len(opened)==count
        assert before==(Path(tmp)/'voice.txt').read_bytes()
        new_voice=dict(session=13,tick=1,version=5,mode='voice',voice_ack=0)
        voice.queue.put((13,'新的语音局',112))
        voice.step(new_voice,112)
        assert '新的语音局' in (Path(tmp)/'voice.txt').read_text(encoding='utf-8')
        assert '不能发送的语音' not in (Path(tmp)/'voice.txt').read_text(encoding='utf-8')
    print('PASS: push-to-talk focus/key gating, cancellation, overflow, time limit, Chinese text, fixed transport, acknowledgements, old maps/sessions and expiry')


if __name__=='__main__':
    run()
