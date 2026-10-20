"""Treat an incomplete optional ambience bank as unavailable to native callers."""
import struct

ADDRESS = 0x140BA23D0
PROLOGUE = bytes.fromhex('4057488bfa4885d27505')
# Each caller already handles a negative lookup result before touching the bank.
SAFE_RETURNS = (
    0x140BA22E7, 0x140BA29A4, 0x140BA2AC6, 0x140BA2BE6,
    0x140BA2D15, 0x140BA2F8F, 0x140BA31AD, 0x140BA3395,
    0x140BA359A, 0x140BA37DD, 0x140BA3E8E, 0x140BA3FDE,
)


def read_q(d, address):
    data = d.read(address, 8)
    return struct.unpack('<Q', data)[0] if len(data) == 8 else None


def incomplete_ambience(d, manager, query):
    prefix_ptr = read_q(d, manager + 0x158)
    if not prefix_ptr:
        return None
    prefix = d.cstr(prefix_ptr, 80)
    if not prefix or query.lower() != (prefix + 'SE_STAGE_AMB').lower():
        return None
    for index in range(32):
        entry = read_q(d, manager + 0x1e8 + index * 8)
        descriptor = read_q(d, entry) if entry else None
        name = read_q(d, descriptor + 0x10) if descriptor else None
        if not name or d.cstr(name, 128).lower() != query.lower():
            continue
        wrapper = read_q(d, entry + 0x20)
        impl = read_q(d, wrapper + 8) if wrapper else None
        handle = read_q(d, impl) if impl else None
        if not handle:
            return None
        queue = read_q(d, handle + 0xa0)
        control = read_q(d, handle + 0x118)
        if queue is not None and control is not None and (queue == 0 or control == 0):
            return index, handle, queue, control
        return None
    return None


def setup(d):
    notices = [0]

    def guard(h):
        if h.ret() not in SAFE_RETURNS:
            return
        result = incomplete_ambience(d, h.rcx, h.str(h.rdx, 128))
        if result is not None:
            if notices[0] < 12:
                slot, handle, queue, control = result
                d.log(f'STAGE_AMBIENCE unavailable slot={slot} handle={handle:x} queue={queue} control={control}')
                notices[0] += 1
            # Enter the existing missing-bank path before locks or state changes.
            # Registry entries, reference counts and ownership remain untouched.
            h.skip_call(0xffffffff)

    def arm(debugger):
        if debugger.read(ADDRESS, len(PROLOGUE)) != PROLOGUE:
            raise RuntimeError('Unexpected sound-bank lookup code')
        for ret in SAFE_RETURNS:
            call = b'\xe8' + struct.pack('<i', ADDRESS - ret)
            branch = debugger.read(ret, 3)
            if debugger.read(ret - 5, 5) != call or branch not in (b'\x85\xc0\x78', b'\x85\xc0\x79'):
                raise RuntimeError('Sound-bank caller lacks verified missing-bank branch')
        debugger.bp(ADDRESS, guard)
        debugger.log('STAGE_AMBIENCE incomplete-bank guard v3 armed')

    d.on_start(arm)
