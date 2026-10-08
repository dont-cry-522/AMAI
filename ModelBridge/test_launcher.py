"""Offline installer regression check; fake game files and an in-memory registry."""
from contextlib import nullcontext,redirect_stdout
import io
import json
import msvcrt
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import bridge
import voice
from launcher import discover_game,find_games,game_executable


def run():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        package=root/'package'; (package/'Maps').mkdir(parents=True)
        source=package/'Maps'/'sample.w3x'; source.write_bytes(b'new map')
        for name in ('AMAI_DeepSeek','AMAI_DeepSeek_Voice'):
            target=package/'Maps'/name/'sample.w3x'
            target.parent.mkdir()
            target.write_bytes(name.encode())
        for name in ('AMAI','AMAI_酒馆'):
            folder=package/'Maps'/name
            folder.mkdir()
            (folder/'sample.w3x').write_bytes(name.encode())
        solo=package/'Maps'/'AMAI_DeepSeek'/'双人协同_海龟岛_v06.w3x'
        solo.write_bytes(b'autonomous map')
        game=root/'Games'/'Warcraft III'; game.mkdir(parents=True)
        for name in ('war3.exe','Game.dll','war3.mpq'):
            (game/name).write_bytes(b'fixture, never executed')
        decoy=root/'tools'; decoy.mkdir(); (decoy/'war3.exe').write_bytes(b'decoy')
        assert find_games([root])==[game.resolve()]
        assert game_executable(decoy) is None
        assert discover_game({'game_dir':str(game)})==game.resolve()
        assert discover_game({},str(game/'war3.exe'))==game.resolve()
        maps=game/'Maps'/'AMAI_ModelBridge_Test'; maps.mkdir(parents=True)
        original=maps/'sample.w3x'; original.write_bytes(b'keep this old map')
        values={}
        def query(key,name):
            if name not in values: raise FileNotFoundError(name)
            return values[name]
        fake=SimpleNamespace(HKEY_CURRENT_USER=1,REG_DWORD=4,
             CreateKey=lambda *args:nullcontext(None),OpenKey=lambda *args:nullcontext(None),
             QueryValueEx=query,SetValueEx=lambda key,name,reserved,kind,value:values.update({name:(value,kind)}),
             DeleteValue=lambda key,name:values.pop(name))
        config=package/'config.local.json'
        config.write_text(json.dumps(dict(game_dir=str(game),endpoint='https://example.invalid/chat',
                            model='saved-model',api_key='local-test-token')),encoding='utf-8')
        with patch.dict('sys.modules',{'winreg':fake}),patch.object(bridge,'ROOT',package),patch.object(bridge,'CONFIG',config):
            bridge.install_game(game)
            assert original.read_bytes()==b'keep this old map'
            copies=list(maps.glob('sample_*.w3x'))
            assert len(copies)==1 and copies[0].read_bytes()==source.read_bytes()
            for name in ('AMAI_DeepSeek','AMAI_DeepSeek_Voice'):
                assert (game/'Maps'/name/'sample.w3x').read_bytes()==name.encode()
            bridge.install_game(game,autonomous=True)
            assert (game/'Maps'/'AMAI_DeepSeek'/solo.name).read_bytes()==b'autonomous map'
            assert len(list((game/'Maps'/'AMAI_DeepSeek').glob('*.w3x')))==2  # prior legacy map retained
            assert (game/'Maps'/'AMAI'/'sample.w3x').read_bytes()==b'AMAI'
            assert (game/'Maps'/'AMAI_酒馆'/'sample.w3x').read_bytes()=='AMAI_酒馆'.encode()
            backup=game/'AMAI_Bridge'/'registry-backup.local.json'
            assert json.loads(backup.read_text())=={'existed':False}
            bridge.install_game(game)
            assert len(list(maps.glob('sample_*.w3x')))==1
            assert json.loads(backup.read_text())=={'existed':False}
            assert values['Allow Local Files']==(1,4)
            output=io.StringIO()
            with patch('builtins.input',side_effect=['','','']),patch.object(bridge.getpass,'getpass',return_value=''),redirect_stdout(output):
                bridge.setup()
            saved=json.loads(config.read_text(encoding='utf-8'))
            assert saved['api_key']=='local-test-token' and saved['model']=='saved-model'
            assert saved['endpoint']=='https://example.invalid/chat'
            assert 'local-test-token' not in output.getvalue()
            bridge.restore()
            assert 'Allow Local Files' not in values and original.read_bytes()==b'keep this old map'
        # A second launch cannot run two controllers against the same game.
        guard=(game/'AMAI_Bridge'/'bridge.lock').open('w+b')
        guard.write(b'0'); guard.flush(); guard.seek(0)
        msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
        try:
            try: bridge.run_bridge(saved,mock=True)
            except ValueError as error: assert '已经在运行' in str(error)
            else: raise AssertionError('Duplicate controller was allowed')
        finally:
            guard.close()
        with patch.object(bridge.time,'sleep',side_effect=KeyboardInterrupt),redirect_stdout(io.StringIO()):
            bridge.run_bridge(saved,mock=True)
        # One real bridge loop, fake game/model/audio: ordinary -> voice -> ordinary.
        # No recognizer is created for the first map, and switching back stops it.
        (game/'AMAI_Bridge'/'state.txt').write_text('fixture')
        observed=[];created=[]
        states=[dict(session=i,tick=1,version=5,mode=mode) for i,mode in enumerate(('llm','voice','llm'))]
        class FakeVoice:
            def __init__(self,*args): self.stop=threading.Event();created.append(self)
            def start(self): pass
            def step(self,state,now): assert state['mode']=='voice'
        def step(state,now):
            observed.append(state['mode'])
            if len(observed)==1: assert not created
            if len(observed)==2: assert len(created)==1 and not created[0].stop.is_set()
            if len(observed)==3: assert created[0].stop.is_set()
        fake_bridge=SimpleNamespace(mock=False,step=step,pool=SimpleNamespace(shutdown=lambda **kwargs:None))
        with patch.object(bridge,'Bridge',return_value=fake_bridge),patch.object(bridge,'read_snapshot',side_effect=states),patch.object(voice,'VoiceInput',FakeVoice),patch.object(bridge.time,'sleep',side_effect=[None,None,KeyboardInterrupt]),redirect_stdout(io.StringIO()):
            bridge.run_bridge({**saved,'voice_enabled':True})
        assert observed==['llm','voice','llm'] and len(created)==1 and created[0].stop.is_set()
    print('PASS: classic game discovery, decoy rejection, non-destructive installation, idempotence, credential retention, registry restore and duplicate-launch protection; no real game or registry modified')


if __name__=='__main__': run()
