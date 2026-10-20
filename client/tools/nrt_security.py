"""Admission and resource bounds for the native lobby protocol.

Bound mode requires a provisioned Steam ID. Invite mode also accepts new identities
using an existing valid invitation token, binding their identity on first use for
this server lifetime. Tokens travel over WireGuard, never public TCP. Neither mode
verifies Steam tickets. Existing provisioned identities retain their original keys.
"""
from collections import deque
import hmac
import json
import os
from pathlib import Path
import threading
import time

MAX_FRAME = 16384
MAX_CONNECTIONS = 32
MAX_PER_ADDRESS = 4
MAX_ROOMS = 128
MAX_MEMBERS = 4
IDLE_SECONDS = 150
FRAME_SECONDS = 15
MAX_PER_SECOND = 120
AUTH_TOKENS = {}
AUTH_MODE = os.environ.get('ROI_AUTH_MODE', 'bound')
INVITED_IDENTITIES = {}
MAX_INVITED_IDENTITIES = 128
ACTIVE = {}
LOCK = threading.RLock()


class ProtocolError(ValueError):
    pass


def load_auth(filename=None):
    if AUTH_MODE not in ('bound', 'invite'):
        raise ValueError('ROI_AUTH_MODE must be bound or invite')
    filename = filename or os.environ.get("ROI_AUTH_FILE")
    if not filename:
        return False
    data = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
    tokens = {}
    for key, value in data.items():
        uid = int(key)
        token = bytes.fromhex(value)
        if not 0 < uid < 2 ** 64 or len(token) != 16:
            raise ValueError("Invalid lobby credential record")
        tokens[uid] = token
    if not tokens or len(set(tokens.values())) != len(tokens):
        raise ValueError("Lobby credentials must be nonempty and unique")
    with LOCK:
        AUTH_TOKENS.clear()
        AUTH_TOKENS.update(tokens)
        INVITED_IDENTITIES.clear()
    return True


def valid_token(token):
    return (isinstance(token, bytes) and len(token) == 16
            and any(hmac.compare_digest(key, token) for key in AUTH_TOKENS.values()))


def identity_token(uid, token):
    """Admit a key holder without pre-listing new IDs; never rebind an existing identity."""
    if not valid_token(token) or not 0 < uid < 2 ** 64:
        return False
    with LOCK:
        expected = AUTH_TOKENS.get(uid)
        if expected is None and AUTH_MODE == 'invite':
            expected = INVITED_IDENTITIES.get(uid)
            if expected is None:
                if len(INVITED_IDENTITIES) >= MAX_INVITED_IDENTITIES:
                    return False
                INVITED_IDENTITIES[uid] = token
                return True
        return expected is not None and hmac.compare_digest(expected, token)


def profile_access(uid, token, write=False):
    """HTTP status for the same admission policy used by native login."""
    if not valid_token(token):
        return 401
    if AUTH_MODE == 'invite':
        return 200 if not write or identity_token(uid, token) else 403
    caller = next(identity for identity, key in AUTH_TOKENS.items() if hmac.compare_digest(key, token))
    return 200 if uid in AUTH_TOKENS and (not write or caller == uid) else 403


def login(session, uid, payload):
    if not 0 < uid < 2 ** 64:
        raise ProtocolError("Invalid identity")
    with LOCK:
        if session.get("uid", uid) != uid:
            raise ProtocolError("Identity cannot change")
        if uid in ACTIVE and ACTIVE[uid] is not session:
            raise ProtocolError("Identity already connected")
        if AUTH_TOKENS and not identity_token(uid, payload):
            raise ProtocolError("Login rejected")
        ACTIVE[uid] = session
        session["uid"] = uid


def release(session):
    with LOCK:
        uid = session.get("uid")
        if ACTIVE.get(uid) is session:
            ACTIVE.pop(uid, None)


def check_message(session, uid):
    if session.get("uid") != uid:
        raise ProtocolError("Login required; identity must match")


def rate_limit(session, now=None):
    now = time.monotonic() if now is None else now
    times = session.setdefault("recent_messages", deque())
    while times and times[0] <= now - 1:
        times.popleft()
    if len(times) >= MAX_PER_SECOND:
        raise ProtocolError("Message rate exceeded")
    times.append(now)
