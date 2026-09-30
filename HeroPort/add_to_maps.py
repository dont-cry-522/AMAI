"""Add the verified private hero assets to every Tavern map in a source folder.

Preserve original object records, scripts, imports and map metadata. Work files
stay outside the delivery folder. Outputs must not exist; source maps are read only.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import struct
import subprocess

from build_test_maps import i32, inject_script


def object_tables(data, extended=False):
    version = struct.unpack_from('<I', data)[0]
    assert version in (1, 2), 'Unsupported object format'
    cursor = 4
    tables = []
    for _ in range(2):
        count = struct.unpack_from('<I', data, cursor)[0]
        cursor += 4
        records = []
        for _ in range(count):
            start = cursor
            base, new, modifications = struct.unpack_from('<4s4sI', data, cursor)
            cursor += 12
            for _ in range(modifications):
                field, kind = struct.unpack_from('<4sI', data, cursor)
                assert kind in (0, 1, 2, 3), (field, kind)
                cursor += 16 if extended else 8
                cursor = data.index(b'\0', cursor)+1 if kind == 3 else cursor+4
                assert data[cursor:cursor+4] in (b'\0'*4, base, new)
                cursor += 4
            records.append((new if new != b'\0'*4 else base, data[start:cursor]))
        tables.append(records)
    assert cursor == len(data), 'Unexpected object tail'
    return tables


def merge_objects(original, added, extended=False):
    old = object_tables(original, extended) if original else [[], []]
    new = object_tables(added, extended)
    old_ids = {raw for table in old for raw, _ in table}
    new_ids = {raw for table in new for raw, _ in table}
    assert not old_ids & new_ids, 'Custom object ID collision'
    return i32(2)+b''.join(i32(len(a)+len(b))+b''.join(record for _, record in a+b)
                          for a, b in zip(old, new))


def import_entries(data):
    version, count = struct.unpack_from('<II', data)
    assert version == 1
    cursor = 8
    entries = []
    for _ in range(count):
        end = data.index(b'\0', cursor+1)+1
        entries.append(data[cursor:end])
        cursor = end
    assert cursor == len(data)
    return entries


def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True)
    if result.returncode:
        message = (result.stdout+result.stderr).decode('utf-8', errors='replace')
        raise RuntimeError(message[:1000]+'\n'+message[-2000:])


def build_one(base, args):
    relative = base.relative_to(args.source)
    work = args.work/relative.parent/base.stem
    work.mkdir(parents=True, exist_ok=False)
    original = work/'original'
    original.mkdir()
    run([args.editor, 'e', base, '*', original, '/fp'])
    script_path = original/'war3map.j'
    if not script_path.exists():
        return {'source':relative.as_posix(), 'status':'skipped', 'reason':'no readable map script'}
    script = script_path.read_text(encoding='utf-8-sig')
    tavern_lines = [line for line in script.splitlines() if "'ntav'" in line and not line.lstrip().startswith('//')]
    if not tavern_lines:
        return {'source':relative.as_posix(), 'status':'skipped', 'reason':'no Tavern in map script'}
    stage = work/'changes'
    stage.mkdir()
    (stage/'war3map.j').write_text(inject_script(script), encoding='utf-8')
    for name, extended in [('war3map.w3u', False), ('war3map.w3a', True), ('war3map.w3h', False)]:
        before = (original/name).read_bytes() if (original/name).exists() else None
        (stage/name).write_bytes(merge_objects(before, (args.template/name).read_bytes(), extended))
    old_imports = import_entries((original/'war3map.imp').read_bytes()) if (original/'war3map.imp').exists() else []
    added_imports = import_entries((args.template/'war3map.imp').read_bytes())
    imports = list(dict.fromkeys(old_imports+added_imports))
    (stage/'war3map.imp').write_bytes(i32(1)+i32(len(imports))+b''.join(imports))
    resources = [p for p in args.template.rglob('*') if p.is_file() and not p.name.startswith('war3map.')]
    for path in resources:
        existing = original/path.relative_to(args.template)
        assert not existing.exists() or existing.read_bytes() == path.read_bytes(), 'Imported asset collision: '+str(existing)
    output = args.output/relative
    if output.suffix.lower() == '.w3m':
        output = output.with_suffix('.w3x')
    assert not output.exists(), 'Output already exists'
    output.parent.mkdir(parents=True, exist_ok=True)
    # Parse the resulting script with both bundled old-engine checkers before packing.
    # Private copies avoid old Windows parser file-sharing behavior across workers.
    references = [work/'Common.j', work/'Blizzard.j']
    for source, target in zip([args.repo/'TFT/Common.j', args.repo/'Scripts/TFT/Blizzard.j'], references):
        shutil.copyfile(source, target)
    for validator in ('pjass.exe', 'jassparser.exe'):
        run([args.repo/validator, *references, stage/'war3map.j'])
    shutil.copy2(base, output)
    run([args.editor, 'htsize', output, '1024'])
    for path in sorted(stage.iterdir()):
        run([args.editor, 'a', output, path, path.name, '/c'])
    for path in resources:
        run([args.editor, 'a', output, path, str(path.relative_to(args.template)), '/c'])
    run([args.editor, 'f', output])
    verified = work/'verified'
    verified.mkdir()
    run([args.editor, 'e', output, '*', verified, '/fp'])
    changes = {p.name for p in stage.iterdir()}
    for path in original.rglob('*'):
        if path.is_file() and path.relative_to(original).as_posix() not in changes and path.name not in ('(listfile)', '(attributes)'):
            assert (verified/path.relative_to(original)).read_bytes() == path.read_bytes(), 'Original file changed: '+str(path)
    for path in stage.iterdir():
        assert (verified/path.name).read_bytes() == path.read_bytes(), path
    for path in resources:
        assert (verified/path.relative_to(args.template)).read_bytes() == path.read_bytes(), path
    data = output.read_bytes()
    assert len(data) < 8*1024*1024, 'Map exceeds classic multiplayer limit'
    return {'source':relative.as_posix(), 'map':output.relative_to(args.output).as_posix(),
            'status':'built', 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
            'source_sha256':hashlib.sha256(base.read_bytes()).hexdigest(), 'tavern_script_lines':len(tavern_lines),
            'original_other_files_preserved':True, 'both_script_parsers_passed':True, 'in_game_verified':False}


def main(args):
    assert args.template.is_dir() and args.source.is_dir()
    assert not args.output.exists() and not args.work.exists(), 'Use new output and work directories'
    sources = sorted(p for p in args.source.rglob('*') if p.suffix.lower() in ('.w3x', '.w3m'))
    rows = []
    args.work.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(build_one, p, args):p for p in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                row = future.result()
            except Exception as error:
                row = {'source':source.relative_to(args.source).as_posix(), 'status':'failed', 'reason':str(error)}
            rows.append(row)
            print(json.dumps({'done':len(rows), 'total':len(sources), **row}, ensure_ascii=False), flush=True)
            (args.work/'report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not any(row['status']=='failed' for row in rows), 'Some maps failed; inspect report.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('source', 'output', 'work', 'template', 'repo', 'editor'):
        parser.add_argument('--'+name, type=Path, required=True)
    main(parser.parse_args())
