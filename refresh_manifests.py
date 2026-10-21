"""Refresh public source hashes after intentional edits; never includes local data."""
import json
from pathlib import Path

from audit_public import digest,scan,strict_json_loads

ROOT=Path(__file__).resolve().parent


def main():
    inventory=strict_json_loads((ROOT/'PUBLIC-MANIFEST.json').read_text(encoding='utf-8'))['sha256']
    files={name:(ROOT/name).read_bytes() for name in inventory}
    issues=scan(files)
    if issues:raise ValueError('Resolve publication findings before refreshing hashes: '+repr(issues))
    for kind in ('client','server'):
        name=kind+'/PACKAGE-MANIFEST.json'
        hashes={n[len(kind)+1:]:digest(raw) for n,raw in files.items() if n.startswith(kind+'/') and n!=name}
        value={'version':'public-rebuild-v1','kind':kind,'hash_mode':'sha256-crlf-normalized-to-lf','sha256':hashes}
        raw=(json.dumps(value,indent=2)+'\n').encode('utf-8')
        (ROOT/name).write_bytes(raw)
        files[name]=raw
    value={'format':'roi-anonymized-source','version':'public-rebuild-v1',
           'hash_mode':'sha256-crlf-normalized-to-lf','sha256':{n:digest(raw) for n,raw in sorted(files.items())}}
    (ROOT/'PUBLIC-MANIFEST.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print('Refreshed public/component manifests without including new or ignored files.')


if __name__=='__main__':main()
