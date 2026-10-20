"""TLS-only, fixed-destination gateway supervising a separate anonymous backend."""
from network_defaults import ANY_IPV4, LOOPBACK
import asyncio
import os
from pathlib import Path
import signal
import ssl
import sys

from tls_transport import CHANNELS,HEALTH,Limits,bridge,close

HERE=Path(__file__).resolve().parent


class Gateway:
    def __init__(self,context,ports=None,limits=None):
        self.context=context
        self.ports=ports or {CHANNELS['nrt']:52711,CHANNELS['profile']:52713}
        self.limits=limits or Limits()

    async def accept(self,reader,writer):
        address=writer.get_extra_info('peername')[0]
        if not self.limits.enter(address):
            await close(writer)
            return
        backend=None
        try:
            await writer.start_tls(self.context,ssl_handshake_timeout=5)
            channel=await asyncio.wait_for(reader.readexactly(8),timeout=5)
            if channel==CHANNELS['health']:
                writer.write(HEALTH)
                await asyncio.wait_for(writer.drain(),timeout=3)
                return
            port=self.ports.get(channel)
            if port is None:
                return
            remote,backend=await asyncio.wait_for(asyncio.open_connection(LOOPBACK,port,limit=65536),timeout=3)
            writer.transport.set_write_buffer_limits(high=65536,low=16384)
            backend.transport.set_write_buffer_limits(high=65536,low=16384)
            result=await bridge(reader,writer,remote,backend)
            if channel==CHANNELS['nrt']:
                print('public native stream closed',result,flush=True)
        except (OSError,ssl.SSLError,asyncio.TimeoutError,asyncio.IncompleteReadError):
            pass
        finally:
            await close(backend)
            await close(writer)
            self.limits.leave(address)


async def main():
    if os.environ.get('ROI_PUBLIC_ACCESS')!='1' or os.environ.get('ROI_AUTH_FILE'):
        raise ValueError('Explicit anonymous public opt-in is required; private credentials must not be mounted')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/run/secrets/public-cert.pem','/run/secrets/public-key.pem')
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,stop.set)
    backend=await asyncio.create_subprocess_exec(sys.executable,str(HERE/'public_backend.py'))
    try:
        for _ in range(60):
            if backend.returncode is not None:
                raise RuntimeError('Anonymous backend exited before startup')
            try:
                for port in (52711,52713):
                    _,writer=await asyncio.open_connection(LOOPBACK,port)
                    await close(writer)
                break
            except OSError:
                await asyncio.sleep(.1)
        else:
            raise RuntimeError('Anonymous backend startup timed out')
        gateway=Gateway(context)
        listener=await asyncio.start_server(gateway.accept,ANY_IPV4,52714,limit=65536,backlog=32)
        print('public TLS gateway listening on 52714; anonymous test identities, fixed internal destinations',flush=True)
        async with listener:
            tasks=[asyncio.create_task(stop.wait()),asyncio.create_task(backend.wait())]
            try:
                done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                if tasks[1] in done and not stop.is_set():
                    raise RuntimeError('Anonymous backend exited')
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
    finally:
        if backend.returncode is None:
            backend.terminate()
            try:
                await asyncio.wait_for(backend.wait(),timeout=3)
            except asyncio.TimeoutError:
                backend.kill()
                await backend.wait()


if __name__=='__main__':
    asyncio.run(main())
