"""Load operator settings from an ignored local JSON file; never embed a host."""
import json
import os
from pathlib import Path
import re

CLIENT_KEYS={'steam_path','depot_path','game_path','internet_host','lan_host','port',
             'certificate_sha256','vpn_lobby_host','vpn_lobby_port'}
SERVER_KEYS={'public_bind_host','public_port','vpn_bind_host','vpn_interface','vpn_network','python_base'}
PROGRESSION_MODES={'faithful','fully_unlocked','match_xp'}


def pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('Duplicate deployment setting: '+key)
        result[key]=value
    return result


def load(path=None, required=True):
    explicit=path or os.environ.get('ROI_DEPLOYMENT_FILE')
    component=Path(__file__).resolve().parent
    if component.name=='tools': component=component.parent
    choices=[Path(explicit)] if explicit else [component/'deployment.local.json',component.parent/'deployment.local.json']
    selected=next((p for p in choices if p.exists()),None)
    if selected is None:
        if required or explicit:
            raise ValueError('Copy deployment.example.json to deployment.local.json and configure your deployment first')
        return {'version':1,'client':{},'server':{}}
    if selected.is_symlink() or selected.stat().st_size>32768:
        raise ValueError('Unsafe deployment settings file')
    value=json.loads(selected.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs)
    version=value.get('version') if isinstance(value,dict) else None
    if type(version) is not int or version not in (1,2):
        raise ValueError('Unsupported deployment settings')
    allowed={'version','client','server'} | ({'policy'} if version==2 else set())
    if set(value)-allowed:
        raise ValueError('Unsupported deployment settings')
    if version==2:
        policy=value.get('policy')
        if (not isinstance(policy,dict) or set(policy)!={'progression_mode'}
                or not isinstance(policy.get('progression_mode'),str)
                or policy.get('progression_mode') not in PROGRESSION_MODES):
            raise ValueError('Choose a supported policy.progression_mode in deployment.local.json')
    for section,keys in (('client',CLIENT_KEYS),('server',SERVER_KEYS)):
        fields=value.get(section,{})
        if not isinstance(fields,dict) or set(fields)-keys:
            raise ValueError('Unknown deployment '+section+' settings')
        for key,item in fields.items():
            if key in ('port','public_port','vpn_lobby_port'):
                port(item)
            elif not isinstance(item,str) or any(ord(c)<32 for c in item):
                raise ValueError('Invalid deployment field: '+key)
        value.setdefault(section,{})
    return value


def port(value):
    if type(value) is not int or not 1024<=value<=65535:
        raise ValueError('Invalid deployment port')
    return value


def host(value):
    if not isinstance(value,str) or len(value)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',value):
        raise ValueError('Set an IPv4 address or DNS hostname in deployment.local.json')
    return value


def public_settings():
    value=load()['client']
    fingerprint=value.get('certificate_sha256','')
    if not re.fullmatch('[0-9a-fA-F]{64}',fingerprint):
        raise ValueError('Configure your own TLS certificate fingerprint in deployment.local.json')
    # Either route can be omitted; only the route actually selected must exist.
    for key in ('internet_host','lan_host'):
        if value.get(key): host(value[key])
    return value


def vpn_endpoint():
    client=load()['client']
    return host(client.get('vpn_lobby_host',''))+':'+str(port(client.get('vpn_lobby_port',52711)))
