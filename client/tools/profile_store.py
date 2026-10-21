"""Atomic profile updates with a lock that survives HTTP-handler reloads."""
import json
import os
from pathlib import Path
import tempfile
import threading

LOCK = threading.RLock()


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key: ' + key)
        result[key] = value
    return result


def read(path):
    with LOCK:
        try:
            value = Path(path).read_text()
        except FileNotFoundError:
            return {}
        result = json.loads(value, object_pairs_hook=_strict_object)
        if not isinstance(result, dict):
            raise ValueError('Saved profile is not an object')
        return result


def update(path, changes):
    path = Path(path)
    with LOCK:
        data = read(path)
        data.update(changes)
        fd, name = tempfile.mkstemp(prefix='profile-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=1)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
