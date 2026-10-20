"""Restore only hash-verified browser files from the player's own Steam install."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
SOURCE_SHA='34a46fbc9e2ea6c6c9eebfddd0d6e4bef388a3eea5088838dd134588225cedbb'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repair(steam,game,manifest=None,source_sha=SOURCE_SHA):
    steam,game=Path(steam).resolve(),Path(game).resolve()
    if checksum(steam/'exe/roi.exe')!=source_sha:
        raise ValueError('Library browser repair requires the supported original Steam executable')
    if manifest is None:
        manifest=json.loads((HERE/'library-browser-files.json').read_text(encoding='utf-8'))
    source_root,target_root=steam/'exe/bin',game/'exe/bin'
    plan=[]
    for name,expected in manifest.items():
        relative=PurePosixPath(name)
        if (relative.is_absolute() or '\\' in name or ':' in name
                or any(part in ('','.','..') for part in name.split('/'))):
            raise ValueError('Unsafe Library browser manifest path')
        source,target=source_root/name,target_root/name
        for path,root in ((source,steam),(target,game)):
            if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in (path,*path.parents)):
                raise ValueError('Unsafe Library browser file path')
        if (not source.is_file() or source.stat().st_size!=expected['bytes'] or checksum(source)!=expected['sha256']):
            raise ValueError('Missing/unsupported original Steam browser file: '+name)
        if target.exists():
            if not target.is_file() or target.stat().st_size!=expected['bytes'] or checksum(target)!=expected['sha256']:
                raise ValueError('Existing browser file differs; preserve and review before repair: '+name)
        else:
            plan.append((name,source,target,expected))
    installed=[]
    try:
        for name,source,target,expected in plan:
            target.parent.mkdir(parents=True,exist_ok=True)
            fd,temporary=tempfile.mkstemp(prefix='library-browser-',suffix='.tmp',dir=target.parent)
            import os
            os.close(fd)
            temporary=Path(temporary)
            try:
                shutil.copyfile(source,temporary)
                if checksum(temporary)!=expected['sha256']:
                    raise OSError('Library browser copy verification failed')
                if target.exists():
                    raise OSError('Library browser destination changed during repair')
                temporary.rename(target)
                installed.append(target)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        for target in installed:
            if target.resolve().is_relative_to(game):
                target.unlink()
        raise
    return dict(verified_files=len(manifest),copied_files=len(installed),
                binaries_shipped=False,game_executable_changed=False)


def main():
    import paths
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',
        '@(Get-Process roi,cefserver -ErrorAction SilentlyContinue).Count'],
        capture_output=True,text=True,check=True,timeout=15)
    if int(result.stdout.strip()):
        raise RuntimeError('Close the game and its browser helper before repairing Library files')
    print(json.dumps(repair(paths.STEAM,paths.GAME),indent=2))


if __name__=='__main__':
    main()
