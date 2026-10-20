"""Back up and label cosmetics without modifying original translations or item IDs."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent
LIMIT = 4 * 1024**2


def read_cells(blob):
    if len(blob) < 12:
        raise ValueError('Truncated common_text')
    version, columns, rows = struct.unpack_from('>III', blob)
    end = 12 + rows * 16
    if version != 0 or columns != 2 or not 1 < rows <= 50000 or end > len(blob):
        raise ValueError('Unexpected common_text layout')
    result = {}
    for row in range(1, rows):
        number, kind, offset, words = struct.unpack_from('>IIII', blob, 12 + row * 16)
        if kind != 0x40000001 or words & 0xc0000000:
            raise ValueError('Unexpected common_text cell type')
        if not end <= number <= len(blob) - 4 or not end <= offset < len(blob):
            raise ValueError('Invalid common_text offset')
        stop = blob.find(b'\0', offset, min(len(blob), offset + 65536))
        if stop < 0:
            raise ValueError('Unterminated common_text cell')
        quote = struct.unpack_from('>I', blob, number)[0]
        if quote in result:
            raise ValueError('Duplicate common_text quote')
        result[quote] = (offset, words * 4, blob[offset:stop].decode('utf-8'))
    return result


def patch_blob(blob, plan):
    if plan.get('schema') != 1:
        raise ValueError('Unsupported cosmetic-label plan')
    cells = read_cells(blob)
    if cells.get(150016, (0, 0, None))[2] != 'Default':
        raise ValueError('Unexpected default-item quote')
    for key, row in plan.get('verified_names', {}).items():
        if cells.get(row['quote'], (0, 0, None))[2] != row['text'] or plan['items'].get(key) != row['quote']:
            raise ValueError('Verified original name does not match the original quote or item record')
    for key, row in plan.get('reviewed_names', {}).items():
        description = {'user_reference': 'Player-reported name.',
                       'visual_match': 'Provisional match.'}.get(row.get('kind'))
        if (row.get('kind') not in ('user_reference', 'visual_match') or not row.get('evidence')
                or row.get('original_join_recovered') is not False
                or key in plan.get('verified_names', {})
                or cells.get(row['quote'], (0, 0, None))[2] != row['text']
                or plan['items'].get(key) != row['quote']
                or plan.get('descriptions', {}).get(key) != row['description_quote']
                or plan['replacements'].get(str(row['description_quote']), {}).get('text') != description):
            raise ValueError('Provisional name association or evidence is inconsistent')
    output = bytearray(blob)
    for key, replacement in plan['replacements'].items():
        if not re.fullmatch(r'TXT_CUSTOMIZE_(?:COSTUME|HEAD|WEAPON)_[A-Z]+_\d{3}', replacement['expected']):
            raise ValueError('Label plan would overwrite a non-placeholder quote')
        quote = int(key)
        if quote not in cells:
            raise ValueError('Reserved cosmetic quote is missing')
        offset, capacity, current = cells[quote]
        if current not in (replacement['expected'], replacement['text']):
            raise ValueError(f'Reserved cosmetic quote {quote} has unexpected text')
        value = replacement['text'].encode('ascii') + b'\0'
        if len(value) > capacity or offset + capacity > len(blob):
            raise ValueError('Cosmetic label does not fit the original allocation')
        output[offset:offset + capacity] = value.ljust(capacity, b'\0')
    after = read_cells(output)
    expected = {k: v[2] for k, v in cells.items()}
    expected.update({int(k): v['text'] for k, v in plan['replacements'].items()})
    if {k: v[2] for k, v in after.items()} != expected or len(output) != len(blob):
        raise ValueError('Cosmetic update would change unrelated text')
    return bytes(output)


def prepare(raw, plan):
    start = raw.find(b'BILZ', 0, 256)
    if start != 128:
        raise ValueError('Unexpected text-resource wrapper')
    size, packed, flags = struct.unpack_from('>III', raw, start + 4)
    if not 0 < size <= LIMIT or flags != 7 or packed > len(raw) - start - 16:
        raise ValueError('Unexpected compressed text size/flags')
    inflater = zlib.decompressobj()
    blob = inflater.decompress(raw[start + 16:start + 16 + packed], LIMIT + 1)
    if not inflater.eof or inflater.unconsumed_tail or len(blob) != size:
        raise ValueError('Truncated or oversized common_text')
    patched = patch_blob(blob, plan)
    if patched == blob:
        return raw
    compressed = zlib.compress(patched, 9)
    output = bytearray(raw[:start + 16])
    struct.pack_into('>II', output, start + 4, len(patched), len(compressed))
    output.extend(compressed)
    if len(output) > len(raw):
        raise ValueError('Cosmetic labels exceed the original archive allocation; no files changed')
    return bytes(output).ljust(len(raw), b'\0')


def install(game, tools=HERE, dry_run=False):
    game, tools = Path(game).resolve(), Path(tools).resolve()
    plan = json.loads((tools / 'customize-labels.json').read_text(encoding='utf-8'))
    # Exact reviewed resource, not a scan or an arbitrary caller-selected file offset.
    inventory = json.loads((tools / 'gx-inventory.json').read_text(encoding='utf-8'))
    entry = next(e for e in inventory if e.get('name') == 'text/common_text')
    if (entry['table'], entry['index']) != (14, 245) or not 0 < entry['size'] < LIMIT:
        raise ValueError('Unexpected common_text index')
    archive = game / 'resource/masterWindows/GxArchivedFile014.dat'
    with archive.open('rb') as stream:
        if stream.read(4) != b'GDAT':
            raise ValueError('Unexpected archive signature')
        stream.seek(8 + entry['index'] * 8)
        offset, size = struct.unpack('<II', stream.read(8))
        if (offset, size) != (entry['off'], entry['size']):
            raise ValueError('Archive index differs from reviewed inventory')
        stream.seek(offset)
        raw = stream.read(size)
    modified = prepare(raw, plan)
    report = {'changed': modified != raw, 'dry_run': dry_run, 'items': len(plan['items']),
              'label_type': 'Partial original names with attributed evidence; remaining model/colour labels.',
              'verified_names': len(plan.get('verified_names', {})),
              'reviewed_names': len(plan.get('reviewed_names', {})),
              'profile_changed': False, 'executable_changed': False,
              'before_sha256': hashlib.sha256(raw).hexdigest(),
              'after_sha256': hashlib.sha256(modified).hexdigest()}
    if dry_run or modified == raw:
        return report
    # The caller must close the game before installation (Setup/Apply Update enforce this).
    if shutil.disk_usage(game).free < archive.stat().st_size + 64 * 1024**2:
        raise ValueError('Not enough space for the full text-archive backup')
    backup = tools / 'compatibility-backups' / datetime.now().strftime('customize-names-%Y%m%d_%H%M%S_%f')
    backup.mkdir(parents=True)
    shutil.copy2(archive, backup / archive.name)
    try:
        with archive.open('r+b') as stream:
            stream.seek(offset)
            if stream.read(size) != raw:
                raise ValueError('Text resource changed during backup; aborting')
            stream.seek(offset)
            stream.write(modified)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(offset)
            if stream.read(size) != modified:
                raise RuntimeError('Cosmetic-label write verification failed')
    except BaseException:
        with archive.open('r+b') as stream:
            stream.seek(offset)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        raise
    report['backup'] = str(backup)
    (backup / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    if os.name == 'nt':
        running = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq roi.exe', '/FO', 'CSV', '/NH'],
                                 capture_output=True, text=True, timeout=15, check=True)
        if '"roi.exe"' in running.stdout.lower():
            raise RuntimeError('Close Rise of Incarnates before updating customization text')
    sys.path.insert(0, str(HERE))
    import paths
    print(json.dumps(install(paths.GAME), indent=2))
