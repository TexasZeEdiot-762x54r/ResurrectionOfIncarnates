"""Bounded, read-only checks of saved settings and native display application."""
import struct


def setup(d):
    hooks = {
        0x1400153D7: bytes.fromhex('482bde'),
        0x1400166B7: bytes.fromhex('7416'),
        0x1401698CF: bytes.fromhex('488b742478'),
        0x1401694C0: bytes.fromhex('40555657'),
        0x1401692E0: bytes.fromhex('8b02898140b40500'),
    }
    budget = [32]

    def report(label, address):
        if budget[0] <= 0:
            return
        raw = d.read(address, 8)
        if len(raw) == 8:
            mode, resolution = struct.unpack('<II', raw)
            d.log(f'VIDEO {label}: displayMode={mode} resolution={resolution}')
            budget[0] -= 1

    def applied(h):
        report('applied settings', d.q(0x141b87458) + 0x5b440)
        renderer = d.q(0x141b874e8)
        raw = d.read(renderer + 0x130, 16) if renderer else b''
        if budget[0] > 0 and len(raw) == 16:
            d.log(f'VIDEO renderer: width,height,maxWidth,maxHeight={struct.unpack("<IIII", raw)}')
            budget[0] -= 1

    def resolution_change(h):
        if budget[0] <= 0 or d.d32(h.rcx + 8) == (h.rdx & 0xffffffff):
            return
        d.log(f'VIDEO resolution request: old={d.d32(h.rcx + 8)} requested={h.rdx & 0xffffffff} callers={d.call_chain(h.rsp, 0x800)[:4]}')
        budget[0] -= 1

    def settings_change(h):
        report('settings assignment', h.rdx)
        if budget[0] > 0:
            d.log(f'VIDEO settings assignment callers={d.call_chain(h.rsp, 0x800)[:4]}')
            budget[0] -= 1

    def arm(debugger):
        for address, expected in hooks.items():
            if debugger.read(address, len(expected)) != expected:
                raise ValueError(f'Video trace signature mismatch at {address:x}')
        debugger.bp(0x1400153D7, lambda h: report('settings read', h.rdi + 0x5b440))
        debugger.bp(0x1400166B7, lambda h: report('startup settings read', h.r14))
        debugger.bp(0x1401698CF, applied)
        debugger.bp(0x1401694C0, resolution_change)
        debugger.bp(0x1401692E0, settings_change)

    d.on_start(arm)
