"""Refresh own durable shared-server counts without blocking a game request."""
import threading

CONDITION = threading.Condition()
CURRENT = None
STARTED = False


def refresh(url, token, uid, path):
    import profile_relay
    import profile_store
    data = profile_relay.request(url, token)
    if not isinstance(data, dict) or data.get('uid') != str(uid):
        raise ValueError('Wrong commendation identity')
    counts = data.get('characters')
    if (not isinstance(counts, dict) or len(counts) > 14
            or any(key not in {str(i) for i in (1,2,3,4,5,6,7,8,9,10,13,14,20,21)}
                   or type(value) is not int or not 0 <= value <= 0x7fffffff
                   for key, value in counts.items())):
        raise ValueError('Invalid commendation totals')
    value = {'uid': str(uid), 'source': url, 'characters': counts}
    with profile_store.LOCK:
        if profile_store.read(path).get('commendations') != value:
            profile_store.update(path, {'commendations': value})


def worker():
    while True:
        with CONDITION:
            args = CURRENT
        try:
            if args:
                refresh(*args)
        except Exception:
            pass  # Preserve the last good snapshot during outages or old-server use.
        with CONDITION:
            CONDITION.wait(timeout=5)


def start(url, token, uid, path):
    global CURRENT, STARTED
    with CONDITION:
        CURRENT = (url, token, uid, path)
        if not STARTED:
            threading.Thread(target=worker, daemon=True).start()
            STARTED = True
        CONDITION.notify()


def counts(snapshot, uid):
    value = snapshot.get('commendations', {})
    if not isinstance(value, dict) or value.get('uid') != str(uid):
        return {}
    return {key: count for key, count in value.get('characters', {}).items()
            if type(count) is int and 0 <= count <= 0x7fffffff}


def records(total):
    # 0x1400fd386: native record index 1 = ranked, index 2 = custom.
    # Player Information 0x1403c24df sums the two Good counters.
    return [{}, {'sv_goodCount': '0'}, {'sv_goodCount': str(total)}]
