"""Validate session imports without starting the game or reading private config."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


def strict_json_loads(raw):
    def object_from_pairs(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate JSON object key: '+key)
            value[key]=item
        return value
    return json.loads(raw,object_pairs_hook=object_from_pairs)


def validate(root=None,session='play'):
    root=Path(root) if root is not None else Path(__file__).resolve().parent
    pending=['__init__',session]
    seen=set()
    while pending:
        name=pending.pop()
        if name in seen:
            continue
        if not all(part.isidentifier() for part in name.split('.')):
            raise ValueError('Invalid session module name')
        path=root/'sessions'/Path(*name.split('.')).with_suffix('.py')
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing launcher dependency: sessions/'+name.replace('.','/')+'.py. Reapply the complete client update.')
        raw=path.read_bytes()
        if len(raw)>262144:
            raise ValueError('Unexpectedly large session source')
        tree=ast.parse(raw,filename=str(path))
        compile(tree,str(path),'exec')
        seen.add(name)
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                if node.module=='sessions':
                    pending.extend(a.name for a in node.names)
                elif node.module and node.module.startswith('sessions.'):
                    pending.append(node.module.removeprefix('sessions.'))
            elif isinstance(node,ast.Import):
                pending.extend(a.name.removeprefix('sessions.') for a in node.names if a.name.startswith('sessions.'))
    return sorted(seen)


def validate_package(root=None):
    root = (Path(root) if root is not None else Path(__file__).resolve().parent.parent).resolve()
    manifest_path = root / 'PACKAGE-MANIFEST.json'
    if manifest_path.stat().st_size > 262144:
        raise ValueError('Unexpectedly large package manifest')
    manifest = strict_json_loads(manifest_path.read_text(encoding='utf-8-sig'))
    hashes = manifest.get('sha256')
    if manifest.get('kind') != 'client' or not isinstance(hashes, dict) or not 1 <= len(hashes) <= 500:
        raise ValueError('Invalid client package manifest')
    mode = manifest.get('hash_mode', 'sha256')
    if mode not in ('sha256', 'sha256-crlf-normalized-to-lf'):
        raise ValueError('Unsupported package hash mode')
    for name, expected in hashes.items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '\\' in name or ':' in name
                or any(part in ('', '.', '..') for part in name.split('/'))
                or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('Unsafe package manifest entry')
        path = root.joinpath(*relative.parts)
        if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root)
                or path.stat().st_size > 4194304):
            raise ValueError('Missing/unsafe package file: ' + name)
        raw = path.read_bytes()
        if mode == 'sha256-crlf-normalized-to-lf':
            raw = raw.replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Package file differs from this release: ' + name + '. Extract the complete ZIP again.')
    return manifest['version'], len(hashes)


if __name__=='__main__':
    try:
        if sys.argv[1:] == ['--package']:
            version, count = validate_package()
            print('Client package verified: ' + version + ' (' + str(count) + ' files)')
        elif sys.argv[1:]:
            raise ValueError('Usage: check_launch.py [--package]')
        modules=validate()
        print('Launch session dependencies verified: '+str(len(modules))+' modules')
    except (OSError,SyntaxError,ValueError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
