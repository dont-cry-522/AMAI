"""Build separate personal hero-port maps; never overwrite the input maps.

Requires the verified Blizzard SD resources prepared in the private work folder.
The live AMAI bridge scripts and original terrain/units are preserved verbatim.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import shutil
import struct
import subprocess
import sys


def slk(path):
    cells = {}
    x = y = 0
    for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
        if not line.startswith('C;'):
            continue
        for token in re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', line)[1:]:
            if token.startswith('X'):
                x = int(token[1:])
            elif token.startswith('Y'):
                y = int(token[1:])
            elif token.startswith('K'):
                cells[x, y] = token[1:].strip('"')
    headers = {x: value for (x, y), value in cells.items() if y == 1}
    rows = {}
    for (x, y), value in cells.items():
        if y > 1:
            rows.setdefault(y, {})[headers.get(x, str(x))] = value
    return list(rows.values())


def i32(n):
    return struct.pack('<i', n)


def cstr(s):
    assert '\0' not in s
    return s.encode('utf-8') + b'\0'


def object_file(records, extended=False, metadata=None):
    out = i32(2) + i32(0) + i32(len(records))
    for base, new, mods in records:
        out += base.encode('ascii') + new.encode('ascii') + i32(len(mods))
        for field, value, level, pointer in mods:
            kind = 3 if isinstance(value, str) else 1 if isinstance(value, float) else 0
            if metadata is not None:
                assert field in metadata, 'Unknown object field: '+field
                declared = metadata[field]['type']
                if declared in ('real','unreal'):
                    assert isinstance(value,(int,float)), field
                    kind = 1 if declared=='real' else 2
                elif declared in ('int','bool'):
                    assert isinstance(value,int), field
                    kind = 0
            out += field.encode('ascii') + i32(kind)
            if extended:
                out += i32(level) + i32(pointer)
            out += cstr(value) if kind == 3 else struct.pack('<f', value) if kind in (1,2) else i32(value)
            out += b'\0' * 4
    return out


def mods(values, level=0):
    return [(field, value, level, 0) for field, value in values.items()]


def hero_objects():
    model = r'Units\Creeps\HeroForsakenPaladin\HeroForsakenPaladin.mdx'
    hero = {
        'unam': '被遗忘者圣骑士', 'upro': '加雷克·班达里昂', 'upru': 1,
        'utip': '招募被遗忘者圣骑士',
        'utub': '近战力量英雄。拥有正义之怒、奉献、神圣光环和净化之火。|n|cffffcc00旧版兼容测试：治疗修正为近似实现。|r',
        'umdl': model, 'uico': r'ReplaceableTextures\CommandButtons\BTNForsakenPaladin.tga',
        'usnd': '', 'uhab': 'ANcp,AHcr,AHpa,AHcl', 'uabi': 'AInv',
        'umvs': 300, 'umvr': 0.6, 'uacq': 500.0, 'urac': 'creeps', 'utyp': 'undead',
        'ustr': 22, 'uagi': 13, 'uint': 17, 'ustp': 2.7, 'uagp': 1.5, 'uinp': 1.8,
        'upra': 'STR', 'uhpm': 100, 'umpm': 0, 'umpi': 100, 'uhpr': 0.25, 'umpr': 0.01,
        'udef': 2, 'ua1b': 0, 'ua1d': 2, 'ua1s': 6, 'ua1c': 2.0, 'ua1r': 100,
        'udp1': 0.433, 'ubs1': 0.567, 'ua1t': 'normal', 'ua1w': 'MetalHeavySlice',
        'usca': 1.2, 'ussc': 1.25, 'uwal': 250.0, 'urun': 250.0, 'ucol': 32.0,
        'uarm': 'Metal', 'ucpt': 0.5, 'ucbs': 1.25, 'umxp': 10.0, 'umxr': 10.0,
        'ushh': 170.0, 'ushw': 170.0, 'ushx': 65.0, 'ushy': 65.0, 'ushu': 'Shadow',
        'ugol': 425, 'ulum': 135, 'ufoo': 5, 'ubpx': 3, 'ubpy': 0, 'uhot': 'Y',
        'usit': 1, 'usma': 1, 'usrg': 0, 'usst': 135,
        'ussi': r'UI\Glues\ScoreScreen\scorescreen-hero-forsakenpaladin.tga',
    }
    dummy = {'unam': '技能辅助单位', 'umdl': '', 'uabi': 'Aloc,Avul', 'ushh': 0.0,
             'ushw': 0.0, 'ushu': '', 'ucol': 0.0, 'umpm': 10000, 'umpi': 10000,
             'ufoo': 0, 'umvs': 0, 'ucpt': 0.0, 'ucbs': 0.0, 'uacq': 0.0,
             'uaen': 0, 'usnd': '', 'umvh': 0.0}
    return [('Nplh', 'Npal', mods(hero)), ('hfoo', 'fPdm', mods(dummy))]


def ability_objects():
    records = []
    names = [('ANcp', '正义之怒', 'RighteousFury', 'F', 0, 3, 10.0, 100, 'channel', 2),
             ('AHcr', '奉献', 'Consecration', 'C', 1, 3, 8.0, 100, 'berserk', 0),
             ('AHcl', '净化之火', 'CleansingFire', 'R', 3, 1, 150.0, 150, 'roar', 0)]
    for raw, name, art, key, column, levels, cooldown, mana, order, target in names:
        changes = mods({'anam': name, 'aher': 1, 'aite': 0, 'alev': levels,
                        'arlv': 6 if levels == 1 else 1, 'alsk': 2,
                        'aart': f'ReplaceableTextures\\CommandButtons\\BTN{art}.tga',
                        'arar': f'ReplaceableTextures\\CommandButtons\\BTN{art}.tga',
                        'abpx': column, 'abpy': 2, 'arpx': column, 'arpy': 0,
                        'arhk': key, 'ahky': key, 'arac': 'creeps', 'areq': '',
                        'aret': f'学习{name}', 'arut': '旧版兼容实现，数值以 3.0.0.24268 为基准。具体差异见测试说明。',
                        'acat': '', 'atat': '', 'aeat': '', 'asat': '', 'aefs': '', 'aefl': '',
                        'aani': 'spell'})
        for level in range(1, levels+1):
            if raw == 'ANcp':
                tip = f'向目标点冲锋，最远725，沿途造成{50+50*level}魔法伤害；移动速度降低{10+10*level}%，攻击速度降低{20+10*level}%，持续5秒（英雄3秒）。受地形阻挡。'
            elif raw == 'AHcr':
                tip = f'在脚下留下300范围的祝福，持续5秒。每秒治疗友方非亡灵单位{[25,35,50][level-1]}点，伤害敌方亡灵{10+10*level}点，降低其受到的治疗{[25,33,50][level-1]}%。|n旧版治疗修正近似实现；不影响空中和机械单位。'
            else:
                tip = '移除500范围内友军的普通魔法减益和敌军的普通魔法增益。治疗友军125点，每移除一个减益额外治疗50点；增加25%攻击力，每个减益额外15%，持续25秒。敌军昏迷3秒，召唤物受到400伤害。|n额外攻击加成最多计19个减益；驱散遵循旧版规则。'
            changes += mods({'atp1': f'{name} [{key}] - 等级{level}', 'aub1': tip,
                             'acdn': cooldown, 'amcs': mana,
                             'aran': 725.0 if target else 0.0, 'adur': 0.0, 'ahdu': 0.0,
                             'atar': 'air,ground,enemy,friend,self', 'abuf': ''}, level)
            for field, value, pointer in [('Ncl1', 0.0, 1), ('Ncl2', target, 2),
                                           ('Ncl3', 1, 3), ('Ncl4', 0.0, 4),
                                           ('Ncl5', 0, 5), ('Ncl6', order, 6)]:
                changes.append((field, value, level, pointer))
        records.append(('ANcl', raw, changes))
    aura = mods({'anam': '神圣光环', 'aher': 1, 'alev': 3, 'arlv': 1, 'alsk': 2,
                 'abpx': 2, 'abpy': 2, 'arpx': 2, 'arpy': 0, 'arhk': 'E',
                 'aart': r'ReplaceableTextures\PassiveButtons\PASBTNSacredAura.tga',
                 'arar': r'ReplaceableTextures\CommandButtons\BTNSacredAura.tga',
                 'aret': '学习神圣光环', 'arut': '为附近友军提供魔法抗性和受到的治疗加成。旧版治疗修正近似实现。',
                 'areq': ''})
    resistance = mods({'anam': '神圣光环魔抗', 'aher': 0, 'aite': 1, 'alev': 3, 'aart': ''})
    slow = mods({'anam': '正义之怒减速', 'aher': 0, 'alev': 3, 'areq': '', 'acat': '', 'atat': ''})
    for level in range(1, 4):
        aura += mods({'aare': 900.0, 'abuf': 'Bfsa', 'atar': 'air,ground,friend,self',
                      'atp1': f'神圣光环 - 等级{level}',
                      'aub1': f'900范围内友军获得{[15,25,35][level-1]}%魔法抗性和{10+5*level}%治疗效果加成。治疗修正为近似实现。'}, level)
        aura += [('Had1', 0.0, level, 1), ('Had2', 0, level, 2)]
        resistance += [('isr2', [0.15,0.25,0.35][level-1], level, 2)]
        slow += mods({'amcs': 0, 'acdn': 0.0, 'aran': 99999.0, 'adur': 5.0, 'ahdu': 3.0,
                      'atar': 'ground,enemy,organic,neutral', 'abuf': 'Bfrs'}, level)
        slow += [('Cri1', 0.1+0.1*level, level, 1), ('Cri2', 0.2+0.1*level, level, 2), ('Cri3', 0.0, level, 3)]
    records += [('AHad', 'AHpa', aura), ('AIsr', 'Afmr', resistance), ('Acri', 'Afsl', slow)]
    bonus = mods({'anam': '净化之火强化', 'aher': 0, 'alev': 20, 'areq': '', 'atat': '', 'acat': ''})
    for level in range(1, 21):
        bonus += mods({'amcs': 0, 'acdn': 0.0, 'aran': 99999.0, 'adur': 25.0, 'ahdu': 25.0,
                       'atar': 'air,ground,friend,self,organic', 'abuf': 'Bfcl'}, level)
        bonus += [('Inf1', 0.25+0.15*(level-1), level, 1), ('Inf2', 0, level, 2), ('Inf3', 0.0, level, 3)]
    stun = mods({'anam': '净化之火昏迷', 'aher': 0, 'alev': 1, 'areq': '', 'amat': '', 'atat': ''})
    stun += mods({'amcs': 0, 'acdn': 0.0, 'aran': 99999.0, 'adur': 3.0, 'ahdu': 3.0,
                  'atar': 'air,ground,enemy,organic,neutral'}, 1)
    stun += [('Htb1', 0.0, 1, 1)]
    records += [('Ainf', 'Afbn', bonus), ('AHtb', 'Afst', stun)]
    return records


def inject_script(script):
    hero = Path(__file__).with_name('forsaken.j').read_text(encoding='utf-8')
    match = re.fullmatch(r'.*?globals\n(.*?)endglobals\n(.*)', hero, re.S)
    assert match
    script = script.replace('\r\r\n', '\n').replace('\r\n', '\n')
    assert not re.search(r'\bFP_\w+', script), 'Hero port already present or namespace collision'
    assert script.count('endglobals') == 1
    assert script.count('function main takes nothing returns nothing') == 1
    script = script.replace('endglobals', match[1]+'endglobals\n'+match[2], 1)
    begin = script.index('function main takes nothing returns nothing')
    end = script.index('endfunction', begin)
    return script[:end]+'    call TimerStart(CreateTimer(), 0.0, false, function FP_Init)\n'+script[end:]


def build(args):
    sys.path.insert(0, str(args.mpyq))
    import mpyq
    base = args.base.resolve()
    output = args.output.resolve()
    if base == output or output.exists():
        raise ValueError('Output must be a new test map, never an existing map')
    raw = base.read_bytes()
    archive = mpyq.MPQArchive(io.BytesIO(raw[raw.index(b'MPQ\x1a'):]), listfile=False)
    for name in ('war3map.w3u', 'war3map.w3a', 'war3map.w3h'):
        if archive.read_file(name):
            raise ValueError('Input already contains custom object data: '+name)
    stage = output.parent/(output.stem+'-imports')
    stage.mkdir(parents=True, exist_ok=False)
    editor = str(args.editor.resolve())
    script = inject_script(archive.read_file('war3map.j').decode('utf-8-sig'))
    (stage/'war3map.j').write_text(script, encoding='utf-8')
    # Original maps can use PKWARE/Huffman compression unsupported by mpyq.
    base_read = stage.parent/(output.stem+'-original-strings')
    base_read.mkdir(exist_ok=False)
    subprocess.run([editor,'e',str(base),'war3map.wts',str(base_read),'/fp'],check=True,capture_output=True)
    strings = (base_read/'war3map.wts').read_text(encoding='utf-8-sig')
    mode = '语音' if 'voice' in base.stem.lower() else '普通'
    for key,value in [(20,f'新英雄测试·{mode}·海龟岛'),(22,'经典版兼容测试：酒馆新增被遗忘者圣骑士。保留 AMAI 与 DeepSeek。按 Esc 开启指挥模式。技能存在兼容差异，尚未实机验证。')]:
        strings, count = re.subn(r'(STRING\s+0*'+str(key)+r'\s*\{\s*)(.*?)(\s*\})',lambda m:m[1]+value+m[3],strings,count=1,flags=re.S)
        assert count==1, 'Map display string not found'
    (stage/'war3map.wts').write_text(strings,encoding='utf-8')
    metadata_path = args.research/'official-3.0.0.24268/Units'
    unit_meta = {r['ID']:r for r in slk(metadata_path/'UnitMetaData.slk')}
    ability_meta = {r['ID']:r for r in slk(metadata_path/'AbilityMetaData.slk')}
    buff_meta = {r['ID']:r for r in slk(metadata_path/'AbilityBuffMetaData.slk')}
    (stage/'war3map.w3u').write_bytes(object_file(hero_objects(), metadata=unit_meta))
    (stage/'war3map.w3a').write_bytes(object_file(ability_objects(), extended=True, metadata=ability_meta))
    buffs = [('BHad','Bfsa',mods({'fnam':'神圣光环','ftip':'神圣光环','fube':'受到魔法抗性和治疗加成。',
                 'fart':r'ReplaceableTextures\PassiveButtons\PASBTNSacredAura.tga',
                 'ftat':r'Abilities\Spells\Other\SacredAura\SacredAura.mdx','ftac':1,'fta0':'origin'})),
             ('Bcri','Bfrs',mods({'fnam':'正义之怒减速','ftip':'正义之怒','fube':'移动速度和攻击速度降低。','ftat':''})),
             ('Binf','Bfcl',mods({'fnam':'净化之火','ftip':'净化之火','fube':'攻击力提高。','ftat':''}))]
    (stage/'war3map.w3h').write_bytes(object_file(buffs, metadata=buff_meta))
    needed_textures = set()
    for model_path in args.assets.rglob('*.mdx'):
        model_bytes = model_path.read_bytes()
        cursor = 4
        while cursor < len(model_bytes):
            tag, size = struct.unpack_from('<4sI', model_bytes, cursor)
            body = model_bytes[cursor+8:cursor+8+size]
            if tag == b'TEXS':
                for offset in range(0, len(body), 268):
                    texture = body[offset+4:offset+264].split(b'\0')[0].decode('ascii')
                    if texture:
                        needed_textures.add(texture.replace('\\','/').lower())
            cursor += 8+size
    for path in args.assets.rglob('*'):
        relative = path.relative_to(args.assets).as_posix()
        include_texture = relative.lower() in needed_textures or relative.startswith('ReplaceableTextures/CommandButtons') or relative.startswith('ReplaceableTextures/PassiveButtons') or relative.startswith('UI/Glues/ScoreScreen')
        if path.is_file() and (path.suffix.lower() in ('.mdx','.wav') or path.suffix.lower()=='.tga' and include_texture):
            target = stage/path.relative_to(args.assets)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    imported = sorted(p.relative_to(stage).as_posix().replace('/','\\') for p in stage.rglob('*') if p.is_file() and not p.name.startswith('war3map.'))
    (stage/'war3map.imp').write_bytes(i32(1)+i32(len(imported))+b''.join(b'\r'+cstr(p) for p in imported))
    shutil.copy2(base, output)
    subprocess.run([editor,'htsize',str(output),'1024'], check=True, capture_output=True)
    for path in sorted(stage.rglob('*')):
        if path.is_file():
            name = path.relative_to(stage).as_posix().replace('/','\\')
            subprocess.run([editor,'a',str(output),str(path),name,'/c'], check=True, capture_output=True)
    subprocess.run([editor,'f',str(output)], check=True, capture_output=True)
    data = output.read_bytes()
    checked = mpyq.MPQArchive(io.BytesIO(data[data.index(b'MPQ\x1a'):]), listfile=False)
    extracted = stage.parent/(output.stem+'-verified')
    extracted.mkdir(exist_ok=False)
    subprocess.run([editor,'e',str(output),'*',str(extracted),'/fp'],check=True,capture_output=True)
    for path in stage.rglob('*'):
        if path.is_file():
            assert (extracted/path.relative_to(stage)).read_bytes() == path.read_bytes(), path
    for name in ('war3mapUnits.doo','war3map.w3e','war3map.w3i','Scripts\\Blizzard.j',
                 'Scripts\\common.ai','Scripts\\human.ai','Scripts\\orc.ai','Scripts\\elf.ai','Scripts\\undead.ai'):
        assert checked.read_file(name) == archive.read_file(name), 'Original changed: '+name
    assert len(data) < 8*1024*1024, 'Map exceeds classic multiplayer size limit'
    report = {'map':str(output),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
              'base_sha256':hashlib.sha256(raw).hexdigest(),'import_files':len(imported),
              'original_terrain_units_bridge_preserved':True,'in_game_verified':False}
    output.with_suffix('.validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for key in ('base','output','assets','research','editor','mpyq'):
        parser.add_argument('--'+key,type=Path,required=True)
    build(parser.parse_args())
