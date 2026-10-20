"""Apply the narrowly validated click-quota patch, backing up the executable."""
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
import native_commendations


def install():
    path = paths.GAME_EXE
    original = path.read_bytes()
    patched = native_commendations.patched_bytes(original)
    if patched == original:
        return {'changed':False, 'sha256':hashlib.sha256(original).hexdigest()}
    backup = Path(__file__).parent/'compatibility-backups'/('commendations-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    shutil.copy2(path, backup/'roi.exe')
    temporary = path.with_name('roi.commendations.tmp')
    try:
        temporary.write_bytes(patched)
        if temporary.read_bytes() != patched:
            raise OSError('Executable verification failed')
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {'changed':True,'backup':str(backup),'sha256':hashlib.sha256(patched).hexdigest()}


if __name__ == '__main__':
    import json
    print(json.dumps(install()))
