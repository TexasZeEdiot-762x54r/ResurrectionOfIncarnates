"""Validate private deployment JSON and generate an ignored Compose .env file."""
import argparse
from datetime import datetime,timezone
from ipaddress import IPv4Address,IPv4Network
import os
from pathlib import Path
import re
import shutil
import tempfile

from deployment_config import load,port
from network_defaults import ANY_IPV4


def vpn_settings(value):
    server=value['server']
    address=IPv4Address(server.get('vpn_bind_host',''))
    network=IPv4Network(server.get('vpn_network',''),strict=True)
    interface=server.get('vpn_interface','')
    if address.is_unspecified or address.is_multicast or address not in network or network.prefixlen<8:
        raise ValueError('VPN bind address must belong to the configured restricted VPN network')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,14}',interface):
        raise ValueError('Configure a valid VPN interface name')
    return str(address),str(network),interface


def environment(value,mode):
    server=value['server']
    image=server.get('python_base','')
    if not re.fullmatch(r'python:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}',image):
        raise ValueError('Set python_base to a reviewed official Python image pinned by sha256 digest')
    env={'PYTHON_BASE':image}
    if mode=='public':
        address=server.get('public_bind_host','')
        bind=ANY_IPV4 if address=='any' else str(IPv4Address(address))
        if IPv4Address(bind).is_multicast:raise ValueError('Public bind cannot be multicast')
        env.update(ROI_PUBLIC_BIND_HOST=bind,ROI_PUBLIC_PORT=str(port(server.get('public_port',52714))))
    elif mode=='vpn':
        bind,network,interface=vpn_settings(value)
        env.update(ROI_VPN_BIND_HOST=bind,ROI_VPN_NETWORK=network,ROI_VPN_INTERFACE=interface)
    else:raise ValueError('Unknown deployment mode')
    return env


def write_env(values,destination):
    path=Path(destination)
    if path.is_symlink():raise ValueError('Refusing a symlink .env')
    text=''.join(key+'='+value+'\n' for key,value in values.items())
    if path.exists():
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        backup=path.with_name(path.name+'.backup-'+stamp)
        shutil.copyfile(path,backup)
        backup.chmod(0o600)
    fd,temporary=tempfile.mkstemp(prefix='.deployment-',suffix='.tmp',dir=path.parent)
    temporary=Path(temporary)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:stream.write(text)
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('public','vpn'),required=True)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    try:
        values=environment(load(args.config),args.mode)
        write_env(values,Path(__file__).resolve().parent/'.env')
        print('Generated private server/.env. No service was started and no firewall rule was changed.')
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')
