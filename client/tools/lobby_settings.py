"""E610/E613 settings, traced from native writer 0x1400EB0E0.

The active-settings UI reads stage at +14C8, private slots +14CD,
and flags at +14D0/+14D4 (0x14039CD93 onwards).
"""
import struct

DEFAULT = struct.pack('<BBQIH', 0, 3, 0, 24, 0) + b'\x01\0\0'

def decode(payload):
    if len(payload) < 19:
        raise ValueError('truncated lobby settings')
    private, flags, owner, stage, count = struct.unpack_from('<BBQIH', payload)
    end = 16 + 4 * count
    if count > 128 or len(payload) != end + 3 or private > 7 or flags & ~3:
        raise ValueError('invalid lobby settings')
    ranks = struct.unpack_from('<' + 'I' * count, payload, 16)
    mode, extra = struct.unpack_from('<BH', payload, end)
    if extra != 0:
        raise ValueError('unsupported extra lobby settings')
    return dict(private=private, flags=flags, owner=owner, stage=stage, ranks=ranks, mode=mode)

def room_prefix(room_id, payload, owner):
    s = decode(payload)
    return (struct.pack('<QBBBQIH', room_id, 0, s['private'], s['flags'],
                        owner, s['stage'], len(s['ranks']))
            + struct.pack('<' + 'I' * len(s['ranks']), *s['ranks'])
            + bytes([s['mode']]))
