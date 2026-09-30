"""Run: python ModelBridge/test_bridge.py (no key, game, or paid API needed)."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from bridge import Bridge, read_snapshot, team_view, validate_response, request_model, render_command


def fixture(path, chat_seq=1, tick=1, session=123456):
    lines=[f'H|{session}|{tick}|{chat_seq}|0',f'C|{chat_seq}|跟着我，等信号一起打不死族',
           'P|0|0|3|1|0','P|1|1|3|2|0','P|2|1|12|3|0','P|3|1|12|4|0']
    for viewer in (1,2,3):
        mask=3 if viewer==1 else 12
        for owner in range(4):
            own=bool(mask & (1<<owner))
            lines.append(f'R|{viewer}|{owner}|4|1|{3 if own else 0}|90|100|200|100|200|{500 if own else -1}|{200 if own else -1}|{30 if own else -1}')
    lines += ['E|1|1|hero|2','E|2|1|hero|2',f'Z|{session}|{tick}']
    path.write_text('\n'.join(f'    call Preload( "{s}" )' for s in lines),encoding='utf-8')
    return read_snapshot(path)


def answer(view, action='follow', target=0):
    return dict(orders=[dict(player=p,action=action,target=target,say='准备跟上。')
                       for p in view['allowed_players']],
                plan=dict(leader=0,target_enemy=2,waiting=True,summary='等待真人信号'))


def run():
    with tempfile.TemporaryDirectory() as d:
        folder=Path(d)
        state=fixture(folder/'state.txt')
        ally=team_view(state,3,{})
        enemy=team_view(state,12,{})
        assert enemy['instruction'] is None and enemy['allowed_players']==[2,3]
        assert set(enemy['observations'])=={2,3} and '跟着我' not in json.dumps(enemy,ensure_ascii=False)
        assert all(o['gold']==-1 for obs in enemy['observations'].values() for o in obs if o['player'] in (0,1))
        good=validate_response(answer(ally),ally)
        waiting=team_view(state,3,dict(plan=good['plan'],orders=good['orders'],instruction_sequence=1))
        autonomous_attack=answer(waiting,action='attack',target=2)
        assert validate_response(autonomous_attack,waiting)['orders'][0]['action']=='follow'
        released=team_view({**state,'chat_seq':2},3,waiting['memory'])
        assert validate_response(autonomous_attack,released)['orders'][0]['action']=='attack'
        for mutation in [dict(player=2,action='retreat',target=-1,say=''),
                         dict(player=1,action='follow',target=2,say=''),
                         dict(player=1,action='attack',target=0,say=''),
                         dict(player=1,action='execute_code',target=-1,say='')]:
            try:
                validate_response(dict(orders=[mutation]),ally)
            except ValueError:
                pass
            else:
                raise AssertionError('Unsafe order accepted')
        # Delayed response to "follow" must not overwrite a later "retreat" instruction.
        bridge=Bridge(folder,{},mock=True)
        bridge.reset(state)
        f=concurrent.futures.Future(); f.set_result(good)
        bridge.pending[3]=(f,state['session'],ally,100)
        newer=fixture(folder/'state.txt',chat_seq=2,tick=2)
        bridge.step(newer,101)
        assert 1 not in bridge.orders
        bridge.pool.shutdown(wait=True)
        # Full request/response against an actual local HTTP server, with no credentials.
        captured={}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured['body']=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured['ua']=self.headers['User-Agent']
                content=json.dumps(dict(choices=[dict(message=dict(content=json.dumps(answer(ally),ensure_ascii=False)))]))
                self.send_response(200);self.end_headers();self.wfile.write(content.encode())
            def log_message(self,*args): pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=request_model(dict(endpoint=f'http://127.0.0.1:{server.server_port}/chat/completions',model='test'),ally,'test-session')
        finally:
            server.shutdown();server.server_close();thread.join()
        assert result['orders'][0]['action']=='follow' and captured['ua']=='War3-AMAI-Bridge/0.1'
        assert captured['body']['model']=='test'
        # Structured data must stay inside fixed string arguments, including hostile text.
        hostile='\");\ncall ExecuteFunc(\"bad\")\n//\\|cffff0000'
        script=render_command(state,good['orders'][0],5,hostile)
        assert len(script.splitlines())==5
        assert 'call ExecuteFunc' not in '\n'.join(s for s in script.splitlines() if not s.strip().startswith('call SetPlayerName'))
        # Process restart resumes sequence beyond the game's acknowledgement.
        state['players'][1]['ack']=50
        bridge=Bridge(folder,{},mock=True);bridge.step(state,100)
        bridge.step(state,100.5)
        assert bridge.orders[1]['seq']>50 and (folder/'command1.txt').exists()
        before=(folder/'command1.txt').read_bytes()
        bridge.step(state,110)
        assert (folder/'command1.txt').read_bytes()==before  # stale game state is not refreshed
        bridge.pool.shutdown(wait=True)
        # Truncated writes cannot become valid observations.
        (folder/'state.txt').write_text('call Preload( "H|1|2|3|0" )',encoding='utf-8')
        try: read_snapshot(folder/'state.txt')
        except ValueError: pass
        else: raise AssertionError('Partial snapshot accepted')
    print('PASS: team isolation, command validation, stale response rejection, HTTP integration, string escaping, sequence recovery, stale snapshots and partial writes')


if __name__=='__main__': run()
