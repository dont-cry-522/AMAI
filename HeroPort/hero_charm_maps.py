"""Map-local Charm experiment: allow enemy heroes without patching the game.

The built-in Charm ability is unchanged outside these maps. All original map
files except its ability table are compared byte-for-byte after repacking.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

from add_to_maps import object_tables
from build_test_maps import i32, mods, object_file


def allow_hero_charm(original):
    old = object_tables(original, extended=True)
    assert b'ANch' not in {raw for table in old for raw, _ in table}
    changes = mods({'arut':'测试版：蛊惑可以选择敌方英雄；保留对高等级中立生物的限制。'})
    changes += mods({'atar':'air,ground,enemy,neutral,hero,nonhero,organic',
                     'aub1':'永久控制目标敌方单位，包括英雄。对高等级中立生物的原有限制仍适用。'}, 1)
    added = object_file([('ANch', '\0'*4, changes)], extended=True)
    edit = object_tables(added, extended=True)[1][0][1]
    return (i32(2)+i32(len(old[0])+1)+b''.join(record for _, record in old[0])+edit+
            i32(len(old[1]))+b''.join(record for _, record in old[1]))


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True)
    if result.returncode:
        raise RuntimeError((result.stdout+result.stderr).decode('utf-8', errors='replace')[-1500:])


def build_one(row, args):
    source = args.existing/row['path']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256'], source
    work = args.work/row['category']/Path(row['source']).stem
    work.mkdir(parents=True, exist_ok=False)
    oldroot = work/'original'
    oldroot.mkdir()
    run(args.editor, 'e', source, '*', oldroot, '/fp')
    payload = allow_hero_charm((oldroot/'war3map.w3a').read_bytes())
    ability = work/'war3map.w3a'
    ability.write_bytes(payload)
    target = args.output/row['path']
    assert not target.exists(), target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    run(args.editor, 'a', target, ability, 'war3map.w3a', '/c')
    run(args.editor, 'f', target)
    checked = work/'verified'
    checked.mkdir()
    run(args.editor, 'e', target, '*', checked, '/fp')
    assert (checked/'war3map.w3a').read_bytes()==payload
    for path in oldroot.rglob('*'):
        if path.is_file() and path.name not in ('war3map.w3a','(listfile)','(attributes)'):
            assert (checked/path.relative_to(oldroot)).read_bytes()==path.read_bytes(), path
    result = {'path':row['path'],'category':row['category'],'bytes':target.stat().st_size,
              'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'source_sha256':row['sha256'],'in_game_verified':False}
    assert result['bytes'] < 8*1024*1024, target
    return result


def main(args):
    assert not args.output.exists() and not args.work.exists()
    rows = json.loads((args.existing/'manifest.json').read_text(encoding='utf-8'))['maps']
    assert len(rows)==122
    results=[]
    for row in rows[args.start_index:]:
        if args.sample and not (row['category']=='原版电脑' and 'TurtleRock' in row['path']):
            continue
        result=build_one(row,args)
        results.append(result)
        print(json.dumps({'done':len(results),'total':len(rows),**result},ensure_ascii=False),flush=True)
    (args.work/'report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('existing','output','work','editor'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--sample',action='store_true')
    parser.add_argument('--start-index',type=int,default=0)
    main(parser.parse_args())
