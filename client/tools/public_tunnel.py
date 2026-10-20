"""Local-only game/relay listeners forwarding to the pinned public TLS gateway."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from network_defaults import LOOPBACK
from tls_transport import CHANNELS,HEALTH,Limits,bridge,close,pinned_connection
from deployment_config import public_settings, host as validate_host


def settings():
    config=json.loads((HERE/'config.json').read_text(encoding='utf-8-sig'))
    public=public_settings()
    if config.get('lobby_transport')!='tls-public':
        raise ValueError('Public TLS transport is not selected')
    host=config.get('public_lobby_host')
    if host not in (public.get('internet_host'),public.get('lan_host')):
        raise ValueError('Unexpected public gateway address')
    validate_host(host)
    port=public['port']
    if type(port) is not int or not 1024<=port<=65535:
        raise ValueError('Invalid gateway port')
    return host,port,public['certificate_sha256']


async def check(options):
    reader,writer=await pinned_connection(*options)
    try:
        writer.write(CHANNELS['health'])
        await writer.drain()
        if await asyncio.wait_for(reader.readline(),timeout=5)!=HEALTH:
            raise ValueError('Unexpected TLS gateway health response')
    finally:
        await close(writer)


async def run(options):
    await check(options)
    limits=Limits(maximum=24,per_ip=24)
    async def accept(reader,writer,channel):
        address=writer.get_extra_info('peername')[0]
        if address!=LOOPBACK:
            await close(writer)
            return
        if not limits.enter(address):
            print('public tunnel: local admission limit reached; connection deferred',flush=True)
            await close(writer)
            return
        remote_writer=None
        try:
            remote,remote_writer=await pinned_connection(*options)
            remote_writer.write(CHANNELS[channel])
            await remote_writer.drain()
            result=await bridge(reader,writer,remote,remote_writer)
            if channel=='nrt':
                print('public native stream closed',result,flush=True)
        except (OSError,asyncio.TimeoutError,ValueError):
            print('public tunnel: connection unavailable or certificate check failed',flush=True)
        finally:
            await close(remote_writer)
            await close(writer)
            limits.leave(address)
    native=await asyncio.start_server(lambda r,w:accept(r,w,'nrt'),LOOPBACK,52711,limit=65536,backlog=16)
    try:
        profile=await asyncio.start_server(lambda r,w:accept(r,w,'profile'),LOOPBACK,52713,limit=65536,backlog=16)
    except BaseException:
        native.close()
        await native.wait_closed()
        raise
    async with native,profile:
        print('public TLS tunnel ready on loopback 52711/52713',flush=True)
        await asyncio.gather(native.serve_forever(),profile.serve_forever())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        asyncio.run(check(settings()) if args.check else run(settings()))
        if args.check:
            print('Pinned public TLS gateway health check passed')
    except (OSError,ValueError,asyncio.TimeoutError):
        print('Public TLS gateway unavailable, wrong endpoint, or certificate mismatch. Check connectivity and TCP 52714 forwarding.',file=sys.stderr)
        raise SystemExit(1)
