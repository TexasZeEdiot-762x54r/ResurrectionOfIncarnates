"""Honor saved video preferences instead of startup and legacy GPU overrides."""
import hashlib
import struct


BASE_SHA256 = 'a97217b7ccfd1c374961507097d2e4099e8cb46b52494abfdd4a248f2a0a13da'
PATCHES = (
    (0x1400153DA, bytes.fromhex('c78740b4050001000000'), b'\x90' * 10),
    (0x1400166B0, bytes.fromhex('41c70601000000'), b'\x90' * 7),
    (0x1401E584D, bytes.fromhex('7e0e'), bytes.fromhex('eb0e')),
)


def file_offset(data, address):
    if data[:2] != b'MZ':
        raise ValueError('Not a PE executable')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Invalid PE signature')
    optional = pe + 24
    if struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected a PE32+ executable')
    base = struct.unpack_from('<Q', data, optional + 24)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    table = optional + struct.unpack_from('<H', data, pe + 20)[0]
    for index in range(count):
        _, rva, size, offset = struct.unpack_from('<IIII', data, table + index * 40 + 8)
        if rva <= address - base < rva + size:
            return offset + address - base - rva
    raise ValueError('Patch address is not backed by file data')


def patched_bytes(original):
    # Validate every site before producing changed bytes, including idempotent installs.
    locations = [(file_offset(original, va), expected, replacement) for va, expected, replacement in PATCHES]
    for offset, expected, replacement in locations:
        if len(expected) != len(replacement):
            raise ValueError('Patch must not change instruction size')
        if original[offset:offset + len(expected)] not in (expected, replacement):
            raise ValueError('Unexpected instruction at a display-mode override')
    restored = bytearray(original)
    for offset, expected, replacement in locations:
        restored[offset:offset + len(expected)] = expected
    if hashlib.sha256(restored).hexdigest() != BASE_SHA256:
        raise ValueError('Not the reviewed multiplayer test executable')
    result = bytearray(original)
    for offset, expected, replacement in locations:
        result[offset:offset + len(expected)] = replacement
    return bytes(result)
