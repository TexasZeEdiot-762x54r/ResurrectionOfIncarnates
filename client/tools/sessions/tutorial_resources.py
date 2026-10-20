"""Keep the native tutorial resource cache across returns to its mission index."""
import struct

ADDRESS = 0x1401dbe37
BETWEEN = 0x1401dbe83
FULL_EXIT = 0x1401dbe3d
TUTORIAL_VTABLE = 0x1419c0780


def number(d, address, size):
    raw = d.read(address, size)
    return int.from_bytes(raw, 'little') if len(raw) == size else None


def keep_tutorial_cache(d, scene):
    if not scene or number(d, scene + 0x43, 1) != 0:
        return False
    tutorial = number(d, 0x141b874c0, 8)
    bot = number(d, 0x141b874c8, 8)
    loader = number(d, 0x141b941f0, 8)
    if not tutorial or not bot or not loader:
        return False
    # Native 0x140776c28 selects a character script when +14 is nonzero;
    # the system-script path fixes +18 to 1. Retain only that measured case.
    return (number(d, tutorial, 8) == TUTORIAL_VTABLE
            and number(d, tutorial + 8, 8) not in (None, 0)
            and number(d, tutorial + 0x14, 4) == 0
            and number(d, tutorial + 0x18, 4) == 1
            and number(d, bot + 0x18, 4) == 0
            and number(d, loader + 0x80, 4) == 1)


def cleanup_thunk(address):
    def relative(opcode, at, target):
        return opcode + struct.pack('<i', target - (at + len(opcode) + 4))
    return (bytes.fromhex('40387b437405')
            + relative(b'\xe9', address + 6, FULL_EXIT)
            + relative(bytes.fromhex('488b0d'), address + 11, 0x141b874b8)
            + bytes.fromhex('488b4928')
            + relative(b'\xe8', address + 22, 0x1405680e0)
            + relative(b'\xe9', address + 27, BETWEEN))


def setup(d):
    notices = [0]

    def guard(h):
        if keep_tutorial_cache(d, h.rbx):
            h.setreg('rip', BETWEEN)
            if notices[0] < 12:
                d.log('TUTORIAL_RESOURCES retained ready cache for tutorial index; full-exit cleanup unchanged')
                notices[0] += 1

    def arm(debugger):
        entry = debugger.read(ADDRESS, 6)
        if entry == bytes.fromhex('40387b437446'):
            debugger.log('TUTORIAL_RESOURCES native between-session retention already present')
            return
        if len(entry) != 6 or entry[0] != 0xe9 or entry[5] != 0x90:
            raise RuntimeError('Unexpected battle-exit cleanup entry')
        target = ADDRESS + 5 + struct.unpack('<i', entry[1:5])[0]
        if not 0x141000000 <= target < 0x142000000:
            raise RuntimeError('Battle-exit cleanup target outside reviewed image range')
        expected = cleanup_thunk(target)
        if debugger.read(target, len(expected)) != expected:
            raise RuntimeError('Unexpected battle-exit cleanup thunk')
        debugger.bp(ADDRESS, guard)
        debugger.log('TUTORIAL_RESOURCES guarded native cache retention armed')

    d.on_start(arm)
