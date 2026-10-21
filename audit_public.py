"""Read-only publication audit; never starts services or changes Git state."""
import hashlib
from ipaddress import ip_address
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
IPV4=re.compile(rb'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
IPV6=re.compile(rb'(?<![\w:])(?:[A-Fa-f0-9]{0,4}:){2,}[A-Fa-f0-9:.]*(?![\w:])')
PATTERNS={
    'private-key':rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
    'account-id':rb'(?<![0-9])7656119[0-9]{10}(?![0-9])',
    'personal-path':rb'(?i)(?:[A-Z]:[\\/]Users[\\/][^\s"\x27]+|/'+rb'home/[^\s"\x27/]+)',
    'email':rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'bearer-token':rb'(?:lobby_token|Bearer)[\x20\x22\x27:=]+[0-9a-fA-F]{32}(?![0-9a-fA-F])',
}


def strict_json_loads(raw):
    def object_from_pairs(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate JSON object key: '+key)
            value[key]=item
        return value
    return json.loads(raw,object_pairs_hook=object_from_pairs)


def digest(raw):
    return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()


def jpeg_metadata(raw):
    cursor=2
    while cursor+4<len(raw) and raw[cursor]==255:
        marker=raw[cursor+1]
        if marker in (0xD9,0xDA):return False
        size=int.from_bytes(raw[cursor+2:cursor+4],'big')
        if size<2 or cursor+2+size>len(raw):return True
        if marker in (0xE1,0xED):return True
        cursor+=2+size
    return False


def scan(files):
    issues=[]
    for name,raw in files.items():
        if name.endswith('.jpg'):
            if jpeg_metadata(raw):issues.append((name,'image-metadata'))
            continue
        for kind,pattern in PATTERNS.items():
            if re.search(pattern,raw):issues.append((name,kind))
        for pattern in (IPV4,IPV6):
            for match in pattern.finditer(raw):
                if match[0]==b':'*2 and raw[max(0,match.start()-1):match.start()]==b'[':
                    continue  # Python reverse slices are not address literals.
                try:ip_address(match[0].decode('ascii'))
                except ValueError:continue
                issues.append((name,'literal-ip-address'));break
    return issues


def audit(root=ROOT):
    root=Path(root)
    manifest=strict_json_loads((root/'PUBLIC-MANIFEST.json').read_text(encoding='utf-8'))
    files={}
    for name,expected in manifest['sha256'].items():
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('Unsafe manifest path')
        raw=path.read_bytes()
        if digest(raw)!=expected:raise ValueError('Public file differs from manifest: '+name)
        files[name]=raw
    issues=scan(files)
    # The allowlist deliberately excludes private local files; make sure Git is
    # not about to publish any additional tracked or unignored files.
    if (root/'.git').is_dir():
        result=subprocess.run(['git','-C',str(root),'ls-files','--cached','--others','--exclude-standard','-z'],capture_output=True,check=True,timeout=15)
        candidates={n.decode('utf-8') for n in result.stdout.split(b'\0') if n}
        if candidates!=set(files)|{'PUBLIC-MANIFEST.json'}:
            raise ValueError('Git publication inventory differs from the reviewed manifest')
    if issues:raise ValueError('Publication scan findings (values withheld): '+repr(issues))
    return len(files)


if __name__=='__main__':
    try:print('Publication audit passed:',audit(),'public files; no literal IPs or flagged private data; no services started.')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(1)
