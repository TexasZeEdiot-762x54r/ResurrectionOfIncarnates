"""Provision private WireGuard lobby credentials without printing bearer tokens."""
from network_defaults import LOOPBACK
import argparse
import json
import os
from pathlib import Path
import re
import secrets
from deployment_config import vpn_endpoint


def provision(directory, identities, invite=False):
    endpoint=vpn_endpoint()
    if (not identities and not invite) or any(not re.fullmatch(r'7656119[0-9]{10}', uid) for uid in identities):
        raise ValueError('Supply one or more SteamID64 values')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    auth = directory / 'lobby-auth.json'
    values = json.loads(auth.read_text()) if auth.exists() else {}
    if not isinstance(values, dict) or any(not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token)
                                           for token in values.values()):
        raise ValueError('Existing credential file is invalid')
    for uid in set(identities):
        values.setdefault(uid, secrets.token_hex(16))
    if invite:
        # Credential slot 1 is not a real Steam account; invite-mode guests claim their own IDs.
        values.setdefault('1', secrets.token_hex(16))
    if len(set(values.values())) != len(values):
        raise ValueError('Duplicate credentials')
    temporary = auth.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        temporary.chmod(0o600)
        json.dump(values, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(auth)
    for uid in sorted(set(identities)):
        access = directory / f'lobby-access-{uid}.json'
        data = dict(lobby_mode='server', lobby_server=endpoint,
                    lobby_listen=LOOPBACK, lobby_steam_id=uid, lobby_token=values[uid])
        with access.open('w', encoding='utf-8') as stream:
            access.chmod(0o600)
            json.dump(data, stream, indent=2)
    if invite:
        access = directory / 'lobby-invitation.json'
        data = dict(lobby_mode='server', lobby_server=endpoint,
                    lobby_listen=LOOPBACK, lobby_token=values['1'])
        with access.open('w', encoding='utf-8') as stream:
            access.chmod(0o600)
            json.dump(data, stream, indent=2)
    return len(set(identities))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steam-id', action='append', default=[])
    parser.add_argument('--invite', action='store_true', help='Create an invitation without registering Steam IDs')
    parser.add_argument('--private-dir', type=Path, default=Path('private'))
    args = parser.parse_args()
    os.umask(0o077)
    count = provision(args.private_dir, args.steam_id, invite=args.invite)
    print(f'Provisioned {count} player(s). Private invitation created: {args.invite}. Never post access files publicly.')
