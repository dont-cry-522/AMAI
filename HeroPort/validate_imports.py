"""Validate a built map's extracted assets and object references, without a game."""
from pathlib import Path
import argparse
import struct
import wave


def validate(root):
    files = {p.relative_to(root).as_posix().lower(): p for p in root.rglob('*') if p.is_file()}
    models = sounds = textures = 0
    for name, path in files.items():
        data = path.read_bytes()
        if name.endswith('.mdx'):
            assert data[:4] == b'MDLX', name
            cursor = 4
            while cursor < len(data):
                tag, size = struct.unpack_from('<4sI', data, cursor)
                assert cursor+8+size <= len(data), name
                body = data[cursor+8:cursor+8+size]
                if tag == b'VERS':
                    assert struct.unpack('<I', body)[0] == 800, name
                if tag == b'TEXS':
                    assert len(body)%268 == 0, name
                    for offset in range(0,len(body),268):
                        texture = body[offset+4:offset+264].split(b'\0')[0].decode('ascii')
                        if texture:
                            assert texture.replace('\\','/').lower() in files, (name,texture)
                assert tag not in (b'CORN',b'BPOS'), (name,tag)
                cursor += 8+size
            assert cursor == len(data), name
            models += 1
        elif name.endswith('.wav'):
            with wave.open(str(path),'rb') as sound:
                assert (sound.getnchannels(),sound.getsampwidth(),sound.getframerate()) == (1,2,22050), name
            sounds += 1
        elif name.endswith('.tga'):
            width,height=struct.unpack_from('<HH',data,12)
            assert 0 < width <= 512 and 0 < height <= 512, name
            assert not width&(width-1) and not height&(height-1), name
            textures += 1
    assert models == 7 and sounds >= 18 and textures >= 20
    unit_ids = set()
    ability_ids = set()
    hero_abilities = None
    for filename, extended, ids in [('war3map.w3u',False,unit_ids),('war3map.w3a',True,ability_ids),('war3map.w3h',False,set())]:
        data=(root/filename).read_bytes()
        assert struct.unpack_from('<II',data)==(2,0)
        count=struct.unpack_from('<I',data,8)[0]
        cursor=12
        for _ in range(count):
            base,new,mod_count=struct.unpack_from('<4s4sI',data,cursor);cursor+=12
            assert new not in ids and len(new)==4
            ids.add(new)
            seen=set()
            for _ in range(mod_count):
                field,kind=struct.unpack_from('<4sI',data,cursor);cursor+=8
                level=pointer=0
                if extended:
                    level,pointer=struct.unpack_from('<II',data,cursor);cursor+=8
                assert (field,level,pointer) not in seen,(filename,new,field,level)
                seen.add((field,level,pointer))
                if kind==3:
                    end=data.index(b'\0',cursor);value=data[cursor:end].decode('utf-8');cursor=end+1
                else:
                    assert kind in (0,1,2)
                    value=struct.unpack_from('<i' if kind==0 else '<f',data,cursor)[0];cursor+=4
                assert data[cursor:cursor+4] in (b'\0'*4,new);cursor+=4
                if new==b'Npal' and field==b'uhab':hero_abilities=value.split(',')
                if kind==3 and value.lower().endswith(('.tga','.mdx')):
                    assert value.replace('\\','/').lower() in files,(filename,field,value)
                if field==b'amcs':assert value in (0,100,150)
        assert cursor==len(data),filename
    assert unit_ids=={b'Npal',b'fPdm'}
    assert set(hero_abilities)=={'ANcp','AHcr','AHpa','AHcl'}
    assert all(raw.encode('ascii') in ability_ids for raw in hero_abilities)
    # Sound callbacks avoid replacing the game's global acknowledgement table.
    assert 'ui/soundinfo/unitacksounds.slk' not in files
    print(f'PASS: {models} legacy models, {textures} textures, {sounds} PCM sounds; object and asset references resolve')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('extracted',type=Path)
    validate(parser.parse_args().extracted)
