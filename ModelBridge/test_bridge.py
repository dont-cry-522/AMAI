"""Run: python ModelBridge/test_bridge.py (no key, game, or paid API needed)."""
import concurrent.futures
import argparse
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer

from bridge import Bridge, read_snapshot, team_view, validate_response, request_model, render_command, map_allows_voice, coordinate_orders


def fixture(path, chat_seq=1, tick=1, session=123456, manual=(-1,-1), mode='voice'):
    lines=[f'H|{session}|{tick}|{chat_seq}|0','V|5',f'M|{mode}','I|0',f'C|{chat_seq}|跟着我，等信号一起打不死族',
           f'Q|{manual[0]}|{manual[1]}','P|0|0|3|1|0','P|1|1|3|2|0','P|2|1|12|3|0','P|3|1|12|4|0']
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
        ordinary=fixture(folder/'state.txt',mode='llm')
        assert team_view(ordinary,3,{}) == ally  # identical tactical inputs and model behavior
        assert map_allows_voice(state) and not map_allows_voice(ordinary)
        for bad in ('M|invalid',''):
            content=(folder/'state.txt').read_text(encoding='utf-8')
            (folder/'invalid.txt').write_text(content.replace('M|llm',bad),encoding='utf-8')
            try: read_snapshot(folder/'invalid.txt')
            except ValueError: pass
            else: raise AssertionError('Invalid/missing v0.5 map mode accepted')
        enemy=team_view(state,12,{})
        assert enemy['instruction'] is None and enemy['allowed_players']==[2,3]
        assert set(enemy['observations'])=={2,3} and '跟着我' not in json.dumps(enemy,ensure_ascii=False)
        assert all(o['gold']==-1 for obs in enemy['observations'].values() for o in obs if o['player'] in (0,1))
        silent=team_view(state,3,{},autonomous=True)
        assert silent['instruction'] is None and '跟着我' not in json.dumps(silent,ensure_ascii=False)
        team_answer=validate_response(answer(silent,'attack',2),silent)
        assert coordinate_orders(silent,team_answer)['orders'][0]['action']=='auto'
        for row in silent['observations'][1]:
            if row['player'] in (0,1): row['combat_units']=8
            if row['player']==2: row.update(combat_units=5,army_xy=[100,200])
        assert coordinate_orders(silent,team_answer)['orders'][0]['action']=='attack'
        silent['observations'][1][1]['army_xy']=[3000,3000]
        assert coordinate_orders(silent,team_answer)['orders'][0]['action']=='follow'
        silent['observations'][1][1]['hp_percent']=25
        assert coordinate_orders(silent,team_answer)['orders'][0]['action']=='retreat'
        enemy_answer=validate_response(dict(orders=[dict(player=p,action='attack',target=p-2,say='嘴硬') for p in (2,3)],plan={}),enemy)
        for p in (2,3):
            for row in enemy['observations'][p]:
                if row['player'] in (2,3): row['combat_units']=8
        separated=coordinate_orders(enemy,enemy_answer)['orders']
        assert {o['action'] for o in separated}=={'attack'}
        assert len({o['target'] for o in separated})==1 and all(o['say']=='' for o in separated)
        enemy['observations'][3][3]['army_xy']=[5000,5000]
        enemy['observations'][2][3]['army_xy']=[5000,5000]
        rally=coordinate_orders(enemy,enemy_answer)['orders']
        assert {o['action'] for o in rally}=={'hold','follow'}
        good=validate_response(answer(ally),ally)
        waiting=team_view(state,3,dict(plan=good['plan'],orders=good['orders'],instruction_sequence=1))
        autonomous_attack=answer(waiting,action='attack',target=2)
        assert validate_response(autonomous_attack,waiting)['orders'][0]['action']=='follow'
        released=team_view({**state,'chat_seq':2},3,waiting['memory'])
        assert validate_response(autonomous_attack,released)['orders'][0]['action']=='follow'
        autonomous_attack['release_waiting']=True
        assert validate_response(autonomous_attack,released)['orders'][0]['action']=='attack'
        discussion={**autonomous_attack,'intent':'chat'}
        assert validate_response(discussion,released)['orders'][0]['action']=='follow'
        assert validate_response(discussion,released)['plan']['waiting']
        hero=answer(ally,'hero_attack',2)
        assert validate_response(hero,ally)['orders'][0]['action']=='hero_attack'
        old_map={**ally,'capabilities':{'heroes_only':False}}
        try: validate_response(hero,old_map)
        except ValueError: pass
        else: raise AssertionError('Hero action sent to an old map')
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
            ordinary_prompt=captured['body']['messages'][0]['content']
            request_model(dict(endpoint=f'http://127.0.0.1:{server.server_port}/chat/completions',model='test',autonomous_only=True),silent,'test-session')
            assert '不要聊天' in captured['body']['messages'][0]['content']
            assert '跟着我' not in captured['body']['messages'][1]['content']
        finally:
            server.shutdown();server.server_close();thread.join()
        assert result['orders'][0]['action']=='follow' and captured['ua']=='War3-AMAI-Bridge/0.5'
        assert captured['body']['model']=='test'
        assert '必须使用简体中文' in ordinary_prompt
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
        # New instructions bypass an obsolete running call, without a request queue.
        bridge=Bridge(folder,{},mock=True); bridge.reset(state)
        slow=concurrent.futures.Future(); slow.set_running_or_notify_cancel()
        bridge.pending[3]=(slow,state['session'],ally,120)
        newer=fixture(folder/'state.txt',chat_seq=2,tick=2)
        bridge.step(newer,121)
        assert bridge.pending[3][2]['instruction']['sequence']==2
        assert slow in bridge.retired
        bridge.step(newer,121.5)
        # A direct answer is not swallowed by the autonomous 30-second cooldown.
        direct=answer(team_view(newer,3,{}))
        direct_future=concurrent.futures.Future(); direct_future.set_result(direct)
        newest=fixture(folder/'state.txt',chat_seq=3,tick=3)
        bridge.last_say[1]=122
        bridge.pending[3]=(direct_future,state['session'],team_view(newest,3,{}),122)
        bridge.step(newest,123)
        assert bridge.orders[1]['say']=='准备跟上。'
        slow.set_result(good)
        bridge.pool.shutdown(wait=True)
        # Saturated model service: two obsolete requests plus the enemy request
        # occupy all three slots; keep only the latest unsubmitted human message.
        bridge=Bridge(folder,{})
        bridge.pool.shutdown(wait=True)
        submitted=[]
        def submit(*args):
            future=concurrent.futures.Future();future.set_running_or_notify_cancel()
            submitted.append(future)
            return future
        bridge.pool=SimpleNamespace(submit=submit)
        bridge.step(state,130)
        assert len(submitted)==2
        for seq in range(2,8):
            changing=fixture(folder/'state.txt',chat_seq=seq,tick=seq)
            bridge.step(changing,130+seq/10)
        assert len(submitted)==3 and 3 not in bridge.pending
        submitted[0].set_result(good)
        bridge.step(changing,131)
        assert len(submitted)==4 and bridge.pending[3][2]['instruction']['sequence']==7
        # A local wait/retreat must beat a delayed model attack, survive casual chat
        # and a bridge restart, leave enemies active, and release only explicitly.
        bridge=Bridge(folder,{},mock=True)
        bridge.step(state,200); bridge.step(state,200.5)
        before=(folder/'command1.txt').read_bytes()
        f=concurrent.futures.Future(); f.set_running_or_notify_cancel()
        bridge.pending[3]=(f,state['session'],ally,200.5)
        locked=fixture(folder/'state.txt',chat_seq=2,tick=2,manual=(2,-1))
        assert locked['manual_order']=={'action':2,'target':-1}
        assert 'manual_order' not in team_view(locked,12,{})
        bridge.step(locked,201)
        assert 3 not in bridge.pending and 3 not in bridge.memory and 1 not in bridge.orders
        f.set_result(answer(ally,action='attack',target=2))
        casual=fixture(folder/'state.txt',chat_seq=3,tick=12,manual=(2,-1))
        casual['chat']='好'; casual['chat_history'][-1]['text']='好'
        bridge.step(casual,203); bridge.step(casual,203.5)
        assert (folder/'command1.txt').read_bytes()==before
        assert 3 not in bridge.pending and 1 not in bridge.orders and 2 in bridge.orders
        bridge.pool.shutdown(wait=True)
        restarted=Bridge(folder,{},mock=True)
        restarted.step(casual,204); restarted.step(casual,204.5)
        assert 1 not in restarted.orders and 2 in restarted.orders
        released=fixture(folder/'state.txt',chat_seq=4,tick=13)
        released['chat']='[快捷指挥] 取消之前的安排，恢复自主行动'
        restarted.step(released,206); restarted.step(released,206.5)
        assert restarted.orders[1]['order']['action']=='auto'
        assert 'Player(12), "123456|13|4|' in (folder/'command1.txt').read_text(encoding='utf-8')
        restarted.pool.shutdown(wait=True)
        # Truncated writes cannot become valid observations.
        (folder/'state.txt').write_text('call Preload( "H|1|2|3|0" )',encoding='utf-8')
        try: read_snapshot(folder/'state.txt')
        except ValueError: pass
        else: raise AssertionError('Partial snapshot accepted')
    print('PASS: team isolation, command validation, manual priority/release/restart, Chinese prompt, stale response rejection, HTTP integration, string escaping, sequence recovery, stale snapshots and partial writes')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--compiled',type=Path,help='Optional generated TFT scripts directory for build verification')
    args=parser.parse_args()
    run()
    if args.compiled:
        script=(args.compiled/'Blizzard.j').read_text(encoding='utf-8')
        # The compiler can parse double-encoded strings without reporting an error.
        for text in ('string language = "Chinese"','[R] 撤回各自基地',
                     '跟随目标英雄','mb_chat == "撤退"','call Preload("Q|"',
                     'call Preload("V|5")','call Preload("M|llm")','call Preload("M|voice")',
                     'if mb_voice_enabled then','call MBReadVoice()','仅英雄跟随'):
            assert text in script, 'Compiled TFT text missing or incorrectly encoded: '+text
        assert b'string language = "Chinese"' in (args.compiled/'common.ai').read_bytes()
        assert b'function MBAIHeroStep' in (args.compiled/'common.ai').read_bytes()
        print('PASS: compiled Chinese menu, emergency commands and local control state')
