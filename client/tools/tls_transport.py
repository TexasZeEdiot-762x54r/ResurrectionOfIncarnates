"""Bounded stream forwarding with mandatory certificate pinning before application bytes."""
import asyncio
from collections import Counter, OrderedDict, deque
import hashlib
import hmac
import ssl
import time

CHANNELS = {'nrt':b'ROI1NRT\n','profile':b'ROI1PRF\n','health':b'ROI1CHK\n'}
HEALTH = b'ROI-PUBLIC-TLS-1\n'
IDLE_SECONDS = 90


def client_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    # Trust is the shipped exact SHA-256 certificate pin, checked before writes.
    context.verify_mode = ssl.CERT_NONE
    return context


async def pinned_connection(host, port, pin):
    if len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin.lower()):
        raise ValueError('Missing/invalid public TLS certificate pin')
    reader,writer = await asyncio.wait_for(asyncio.open_connection(
        host,port,ssl=client_context(),server_hostname=None,ssl_handshake_timeout=5,
        limit=65536),timeout=7)
    certificate = writer.get_extra_info('ssl_object').getpeercert(binary_form=True)
    if not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(),pin.lower()):
        await close(writer)
        raise ssl.SSLError('Public lobby certificate fingerprint mismatch')
    writer.transport.set_write_buffer_limits(high=65536,low=16384)
    return reader,writer


async def close(writer):
    if writer is None:
        return
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(),timeout=1)
    except (OSError,asyncio.TimeoutError,ssl.SSLError):
        pass


async def pipe(reader,writer,on_data):
    while True:
        data = await reader.read(16384)
        if not data:
            return
        on_data(len(data))
        writer.write(data)
        await asyncio.wait_for(writer.drain(),timeout=10)


async def bridge(left_reader,left_writer,right_reader,right_writer):
    loop=asyncio.get_running_loop()
    started=loop.time()
    last_activity=started
    counts={'left_to_right_bytes':0,'right_to_left_bytes':0}
    def received(direction,size):
        nonlocal last_activity
        last_activity=loop.time()
        counts[direction]+=size
    async def idle_watch():
        # A quiet reply direction is normal during combat; expire only if BOTH
        # directions have been inactive for the full interval.
        while True:
            remaining=IDLE_SECONDS-(loop.time()-last_activity)
            if remaining<=0:
                return
            await asyncio.sleep(remaining)
    tasks = [asyncio.create_task(pipe(left_reader,right_writer,
                 lambda size:received('left_to_right_bytes',size))),
             asyncio.create_task(pipe(right_reader,left_writer,
                 lambda size:received('right_to_left_bytes',size))),
             asyncio.create_task(idle_watch())]
    try:
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        index=next(i for i,task in enumerate(tasks) if task in done)
        error=tasks[index].exception()
        reason='idle' if index==2 else ('left','right')[index]+'-'+(type(error).__name__ if error else 'eof')
        result=dict(counts,reason=reason,duration_seconds=round(loop.time()-started,3),
                    idle_seconds=round(loop.time()-last_activity,3))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await close(left_writer)
        await close(right_writer)
    return result


class Limits:
    """Counts sockets before TLS, with bounded history for handshake-rate limits."""
    def __init__(self,maximum=32,per_ip=8):
        self.maximum,self.per_ip = maximum,per_ip
        self.active = Counter()
        self.history = OrderedDict()
        self.global_history = deque(maxlen=64)

    def enter(self,address,now=None):
        now = time.monotonic() if now is None else now
        if sum(self.active.values())>=self.maximum or self.active[address]>=self.per_ip:
            return False
        while self.global_history and self.global_history[0]<=now-10:
            self.global_history.popleft()
        if len(self.global_history)>=64:
            return False
        history = self.history.setdefault(address,deque(maxlen=20))
        self.history.move_to_end(address)
        while history and history[0]<=now-10:
            history.popleft()
        if len(history)>=20:
            return False
        history.append(now)
        self.global_history.append(now)
        while len(self.history)>256:
            self.history.popitem(last=False)
        self.active[address]+=1
        return True

    def leave(self,address):
        self.active[address]-=1
        if self.active[address]<=0:
            self.active.pop(address,None)
