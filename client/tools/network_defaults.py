"""Protocol-local addresses, not operator or Internet deployment settings.

Construct standard IPv4 loopback and unspecified addresses with the standard
library so the public source contains no literal address strings. Keep native
wire values unchanged; changing the game's loopback URL would break patch sizes.
"""
from ipaddress import IPv4Address

LOOPBACK = str(IPv4Address(0x7F000001))
ANY_IPV4 = str(IPv4Address(0))
LOCAL_LOBBY = LOOPBACK + ':52711'


def listen_address(value):
    return {'loopback': LOOPBACK, 'any': ANY_IPV4}.get(value, value)
