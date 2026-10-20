"""Point only the four retired Library web pages at the client loopback service."""
from network_defaults import LOOPBACK
import struct

URLS = (
    (0x1418CFE88, 'story'), (0x1418CFEB8, 'howtoplay'),
    (0x1418CFEF0, 'stages'), (0x1418CFF20, 'characters'),
)
POINTERS = ((0x141B37C60,0x1418CFF20), (0x141B37C68,0x1418CFEF0),
            (0x141B37C70,0x1418CFEB8), (0x141B37C78,0x1418CFE88),
            (0x141B37C80,0x1418CFE88))


def replacements():
    for address, page in URLS:
        original = ('http://live.game.riseofincarnates.com/%s/'+page).encode('ascii')+b'\0'
        local = (f'http://{LOOPBACK}:52710/library/%s/'+page).encode('ascii')+b'\0'
        if len(local)>len(original):
            raise ValueError('Library URL exceeds original string allocation')
        yield address, original, local.ljust(len(original), b'\0')


def setup(d):
    def arm(debugger):
        patches = list(replacements())
        for slot, target in POINTERS:
            if debugger.read(slot,8)!=struct.pack('<Q',target):
                raise RuntimeError('Unexpected Library URL pointer table')
        for address, original, local in patches:
            if debugger.read(address,len(original)) not in (original,local):
                raise RuntimeError('Unexpected Library URL string; no URLs changed')
        for address, original, local in patches:
            if not debugger.write(address,local) or debugger.read(address,len(local))!=local:
                raise RuntimeError('Could not install local Library URL')
        debugger.log('LIBRARY local Character/Stage/How-to-Play/Story URLs installed; native Credits unchanged')
    d.on_start(arm)
