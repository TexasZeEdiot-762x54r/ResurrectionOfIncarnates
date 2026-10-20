"""Remove only the reviewed native 20-click commendation quota."""
import native_video
import hashlib

PATCHES = ((0x1404bf1f1, bytes.fromhex('83f8147310'), bytes.fromhex('9090909090')),)


def patched_bytes(original):
    restored = bytearray(original)
    for address, expected, replacement in PATCHES:
        offset = native_video.file_offset(restored, address)
        if restored[offset:offset+len(expected)] not in (expected, replacement):
            raise ValueError('Unexpected commendation click-limit instructions')
        restored[offset:offset+len(expected)] = expected
    offset = native_video.file_offset(restored, 0x1404bf1d0)
    if hashlib.sha256(restored[offset:offset+0x3b]).hexdigest() != '174817bcfa78d2eac2834904a4c29f630d211ca3beb7e4dd2a16c045244b6c24':
        raise ValueError('Not the reviewed native commendation callback')
    result = bytearray(original)
    for address, expected, replacement in PATCHES:
        offset = native_video.file_offset(result, address)
        result[offset:offset+len(expected)] = replacement
    return bytes(result)
