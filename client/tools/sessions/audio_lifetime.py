"""Bounded, observational sound-player creation/destruction diagnostics."""
from collections import deque
import struct

HOOKS = {
    'created': (0x140D4362F, bytes.fromhex('4883c460')),
    'destroy': (0x140D487D0, bytes.fromhex('48895c24084889742410')),
    'volume': (0x140BA3ECF, b'\xe8' + struct.pack('<i',0x140d456b8-0x140ba3ed4)),
}


def q(d,address):
    raw=d.read(address,8)
    return struct.unpack('<Q',raw)[0] if len(raw)==8 else None


def fields(d,handle):
    return (q(d,handle+0xa0),q(d,handle+0x118)) if handle else (None,None)


def setup(d):
    counts={'created':0,'destroy':0,'volume':0}
    destroyed=deque(maxlen=128)

    def created(h):
        if not h.rax or counts['created']>=96:
            return
        counts['created']+=1
        queue,control=fields(d,h.rax)
        d.log(f'AUDIO_LIFETIME created handle={h.rax:x} queue={queue} control={control}')
        while h.rax in destroyed:
            destroyed.remove(h.rax)

    def destroy(h):
        destroyed.append(h.rcx)
        if counts['destroy']>=64:
            return
        counts['destroy']+=1
        queue,control=fields(d,h.rcx)
        # Raw native call sites only, bounded to this one diagnostic event.
        calls=[hex(call) for _,call,_ in d.call_chain(h.rsp,0x800)[:8]]
        d.log(f'AUDIO_LIFETIME destroy handle={h.rcx:x} queue={queue} control={control} callers={calls}')

    def volume(h):
        if counts['volume']>=96:
            return
        descriptor=q(d,h.rdi)
        name_ptr=q(d,descriptor+0x10) if descriptor else None
        name=d.cstr(name_ptr,128) if name_ptr else ''
        if name not in ('sound/BGM','sound/SE_STAGE_AMB'):
            return
        counts['volume']+=1
        queue,control=fields(d,h.rcx)
        d.log(f'AUDIO_LIFETIME volume bank={name} handle={h.rcx:x} queue={queue} control={control} previously_destroyed={h.rcx in destroyed}')

    def arm(debugger):
        for name,(address,expected) in HOOKS.items():
            if expected is not None and debugger.read(address,len(expected))!=expected:
                raise RuntimeError('Unexpected audio lifecycle code: '+name)
        debugger.bp(HOOKS['created'][0],created)
        debugger.bp(HOOKS['destroy'][0],destroy)
        debugger.bp(HOOKS['volume'][0],volume)
        debugger.log('AUDIO_LIFETIME bounded observational tracing armed')

    d.on_start(arm)
