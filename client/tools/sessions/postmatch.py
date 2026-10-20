"""Low-frequency protocol metadata and error stacks; no packet payload logging."""
import struct

from sessions import play


def frame_metadata(header, outgoing):
    minimum = 24 if outgoing else 26
    if len(header) < minimum:
        return None
    outer, body = struct.unpack_from('<HH', header)
    if outer != body + 4 or not minimum - 4 <= body <= 16378:
        return None
    seq, session, kind = struct.unpack_from('<QHH', header, 4)
    result = None if outgoing else struct.unpack_from('<H', header, 16)[0]
    return kind, seq, body - (20 if outgoing else 22), result


def setup(d):
    play.setup(d)
    from sessions import video_trace
    video_trace.setup(d)
    remaining = [600]

    def log_frame(h, outgoing):
        if remaining[0] <= 0:
            return
        metadata = frame_metadata(h.read(h.rdx, 24 if outgoing else 26), outgoing)
        if metadata is None:
            return
        kind, seq, size, result = metadata
        remaining[0] -= 1
        d.log(f"NRT {'SEND' if outgoing else 'RECV'} type={kind:04x} seq={seq} payload_bytes={size} result={result}")

    # One native Winsock send call; receive parser takes a complete framed packet.
    d.bp(0x1400E78E7, lambda h: log_frame(h, True))
    d.bp(0x1400E8160, lambda h: log_frame(h, False))

    def error_popup(h):
        d.log('SCENE create ErrorPopup; diagnostic call chain:')
        for offset, call, op in d.call_chain(h.rsp, 0x3000)[:24]:
            d.log(f'  stack+{offset:x}: call at {d.describe(call)} -> {op}')
        game = d.q(0x141B87450)
        nrt = d.q(game + 0x150) if game else 0
        if nrt:
            fields = {hex(off): d.d32(nrt + off) for off in (0x40, 0x44, 0x3fd0, 0x40c8, 0x40d0)}
            d.log(f'NRT error-state fields {fields}')

    d.bp(0x140147E40, error_popup)
