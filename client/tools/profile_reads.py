"""Bound optional friend-profile reads without consuming the gateway's whole budget."""
from collections import OrderedDict, deque
from copy import deepcopy
import hashlib
import threading
import time

import profile_relay

MAX_STARTS = 8
WINDOW = 10
MAX_INFLIGHT = 2
MAX_CACHED = 32
FOUND_TTL = 2
MISSING_TTL = 5


class ProfileReads:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.pending = set()
        self.starts = deque()

    def get(self, url, token, uid):
        key = (url, hashlib.sha256(token.encode()).digest(), str(uid))
        now = time.monotonic()
        with self.lock:
            for old, (deadline, _) in list(self.entries.items()):
                if deadline <= now:
                    self.entries.pop(old)
            if key in self.entries:
                self.entries.move_to_end(key)
                return deepcopy(self.entries[key][1])
            while self.starts and self.starts[0] <= now-WINDOW:
                self.starts.popleft()
            # These are optional appearance reads. Never queue a long wait in
            # the native menu or relax TLS admission limits to serve a burst.
            if key in self.pending or len(self.pending) >= MAX_INFLIGHT or len(self.starts) >= MAX_STARTS:
                return None
            self.pending.add(key)
            self.starts.append(now)
        value = None
        try:
            result = profile_relay.request(url, token)
            if profile_relay.valid_profile(result, uid):
                value = result
        except Exception:
            pass
        finally:
            with self.lock:
                self.pending.discard(key)
                self.entries[key] = (time.monotonic()+(FOUND_TTL if value is not None else MISSING_TTL),
                                     deepcopy(value))
                self.entries.move_to_end(key)
                while len(self.entries) > MAX_CACHED:
                    self.entries.popitem(last=False)
        return deepcopy(value)


CACHE = ProfileReads()
