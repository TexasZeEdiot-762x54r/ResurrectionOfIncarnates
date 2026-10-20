"""Lobby rooms of the realtime-server stand-in, in the record format of the client's parser 0x1400ED1F0.

State lives here because nrt_logic is hot-reloaded by the server on every message (this module is reloaded too
and keeps its state). Two ways to share rooms between players (config lobby_mode, see paths.py):
  "steam"  each PC's own lobby server publishes its host's room as a Steam lobby (steam_dir.py) and Search
           Lobby lists everyone's Steam lobbies; no addresses needed.
  "server" one shared lobby server for everyone (online.ps1 host/join); rooms are simply shared in ROOMS.
Battle traffic never passes through here: members connect to the host's endpoint over Steam.

Record (see MODLOG "Room record, full"):
  u64 room id (low u16 != 0), u8, u8, u8 flags, u64 owner (E611: == own id -> "my room"), u32,
  u16 n + n x u32 rank limits (0 = none), u8, u16 members,
  per member: u64 Steam id, u8, u8, u32, u16 len + name, u32,
  u16 n2 + per entry: 8 bytes, 16 hex chars (entry 0 -> host endpoint; 0 drops the room from search),
  16 bytes, u8 room status (2/3 accepted by 0x140103bb0),
  u16 n3 + n3 x u64 invited.
"""
import struct
import threading
import lobby_settings
import nrt_security as security

LOCK = globals().get('LOCK', threading.RLock())
ROOMS = globals().get('ROOMS', {})          # room id -> room; own rooms and (steam mode) rooms found on Steam
BY_LOBBY = globals().get('BY_LOBBY', {})    # Steam lobby id -> room id of a remote room
NEXT_ROOM = globals().get('NEXT_ROOM', 1)
LOG = globals().get('LOG', print)
MAX_MEMBERS = security.MAX_MEMBERS


def steam_mode():
    import paths
    return paths.LOBBY_MODE == "steam"


def steam():
    import steam_dir
    return steam_dir.get(LOG)


def _new_id(wanted=None):
    """Room ids are random 16-bit numbers (1..65535): the game keeps the id as a u16 (record field +0x1fa is
    overlapped at +0x1fc; 0xE616 carries only the low 16 bits) and copies it into its own Steam lobby ("room"),
    where an invited friend's lobby server finds the room by it, so ids should not collide between players.
    `wanted` keeps a host's id for a remote room when it is free here."""
    import random
    if wanted and 0 < wanted <= 0xFFFF and wanted not in ROOMS:
        return wanted
    for _ in range(64):
        rid = random.randrange(1, 0x10000)
        if rid not in ROOMS:
            return rid
    for rid in range(1, 0x10000):
        if rid not in ROOMS:
            return rid
    raise RuntimeError("no free room id")


def record(room):
    owner = room['members'][0]
    settings = bytes.fromhex(room.get('settings', '')) or lobby_settings.DEFAULT
    # The settings' owner value is a client hint, not the room's authority.
    data = lobby_settings.room_prefix(room['id'], settings, owner=owner)
    data += struct.pack('<H', len(room['members']))
    for uid in room['members']:
        import player_names
        # Native parser uses a 257-byte temporary buffer. Truncate on a UTF-8 boundary.
        name = player_names.get(uid).encode('utf-8')[:255].decode('utf-8', 'ignore').encode('utf-8')
        data += struct.pack('<QBBIH', uid, 0, 0, 0, len(name)) + name + struct.pack('<I', 0)
    endpoint = room.get('platform_lobby_id', 0)
    data += struct.pack('<HQ', 1, owner)
    data += f'{endpoint:016x}'.encode('ascii') + bytes(16) + b'\x02'
    data += struct.pack('<H', 0)
    return data


def create(session, uid, settings=b""):
    settings = settings or lobby_settings.DEFAULT
    lobby_settings.decode(settings)
    with LOCK:
        leave(session)
        if len(ROOMS) >= security.MAX_ROOMS:
            return None
        room = {'id': _new_id(), 'members': [uid], 'settings': settings.hex()}
        ROOMS[room['id']] = room
        session['room_id'] = room['id']
        return record(room)


def update_settings(session, uid, settings):
    lobby_settings.decode(settings)
    with LOCK:
        room = ROOMS.get(session.get('room_id'))
        if room is None or room.get('remote') or room['members'][0] != uid:
            return None
        room['settings'] = settings.hex()
        reply = record(room)
        lobby = room.get('steam_lobby')
    if isinstance(lobby, int) and steam_mode():
        threading.Thread(target=lambda: steam().update(lobby, {'roirev_set': settings.hex()}), daemon=True).start()
    return reply


def set_endpoint(session, endpoint):
    """The host reported its endpoint (0xE60A): the room becomes joinable; in steam mode publish it."""
    with LOCK:
        room = ROOMS.get(session.get('room_id'))
        if (room is None or room.get('remote') or not room['members']
                or room['members'][0] != session.get('uid') or not 0 < endpoint < 2 ** 64):
            return False
        room['platform_lobby_id'] = endpoint
        if not steam_mode() or room.get('steam_lobby') or room.get('remote'):
            return True
        room['steam_lobby'] = 'pending'

    def publish():
        lobby = steam().publish({"roirev_ep": f"{endpoint:016x}", "roirev_host": str(room['members'][0]),
                                 "roirev_set": room.get('settings', ''), "roirev_room": str(room['id'])})
        with LOCK:
            if ROOMS.get(room['id']) is room:
                room['steam_lobby'] = lobby
                LOG(f"room {room['id']} published as Steam lobby" if lobby else f"room {room['id']}: publish failed")
                return
        if lobby:  # closed while publishing
            steam().leave(lobby, close=True)

    threading.Thread(target=publish, daemon=True).start()
    return True


def search(uid=None):
    """Joinable rooms (host endpoint known) the searcher is not in, newest first, at most 32."""
    if steam_mode():
        _refresh_from_steam(uid)
    with LOCK:
        rooms = [r for r in ROOMS.values() if r.get('platform_lobby_id') and uid not in r['members']]
        rooms = sorted(rooms, key=lambda r: -r['id'])[:32]
        return struct.pack('<H', len(rooms)) + b''.join(record(r) for r in rooms)


def _refresh_from_steam(uid):
    rows = steam().search()
    seen = set()
    with LOCK:
        own = {r.get('steam_lobby') for r in ROOMS.values() if not r.get('remote')}
        for row in rows[:50]:
            try:
                host, ep = int(row['roirev_host'] or 0), int(row['roirev_ep'] or '0', 16)
                lobby = int(row['lobby'])
                owner = int(row['owner'])
            except (ValueError, TypeError, KeyError):
                continue
            if (not 0 < host < 2 ** 64 or not 0 < ep < 2 ** 64 or not 0 < lobby < 2 ** 64
                    or owner not in (0, host) or host == uid or lobby in own):
                continue
            # Steam returns owner=0 before membership. Recheck after real entry.
            seen.add(lobby)
            rid = BY_LOBBY.get(lobby)
            room = ROOMS.get(rid)
            if room is None:
                if len(ROOMS) >= security.MAX_ROOMS:
                    continue
                try:
                    wanted = int(row.get('roirev_room') or 0)
                except ValueError:
                    wanted = 0
                rid = _new_id(wanted)
                room = ROOMS[rid] = {'id': rid, 'members': [host], 'remote': True, 'steam_lobby': lobby}
                BY_LOBBY[lobby] = rid
            room['platform_lobby_id'] = ep
            try:
                settings = bytes.fromhex(row.get('roirev_set', '')) or lobby_settings.DEFAULT
                lobby_settings.decode(settings)
                room['settings'] = settings.hex()
            except ValueError:
                room['settings'] = lobby_settings.DEFAULT.hex()
        for lobby, rid in list(BY_LOBBY.items()):  # rooms that disappeared from Steam (keep the one we are in)
            room = ROOMS.get(rid)
            if lobby not in seen and room is not None and len(room['members']) <= 1:
                ROOMS.pop(rid, None)
                BY_LOBBY.pop(lobby, None)


def battle_info(session, uid, kind=0):
    """Reply to 0xE608 (sent by every player when a lobby battle starts; parser 0x1400ee330, only when the room
    status byte +0x14f3 is 3). Byte layout, decoded field by field from the parser (payload offsets):
      [0:2]   u16 kind (+0x14fc)
      [2:18]  16 raw bytes, also hex-encoded and stored as a display string (+0x1524); stored again as two
              raw qwords at +0x1500 ([2:10]) and +0x1508 ([10:18]) -- the cursor is NOT advanced by this read,
              so these same 16 bytes are read twice (display copy, then structured copy below)
      [18]    1 byte, skipped (cursor jumps 9 after the 8-byte read at [10:18], not 8)
      [19:27] u64 (+0xbd2)
      [27]    u8 (+0x14cc)
      [28]    u8 (+0x14cd)
      [29]    u8 (+0x14ce; bit0 -> +0x14d0, bit1 -> +0x14d4)
      [30:38] u64 (+0x14d8)
      [38:]   from here on, byte-for-byte the SAME tail a room record uses starting at its "stage" field:
              u32 stage, u16 n + n*u32 ranks, u8 battle rules, u16 members + per-member records, u16 tokens +
              per-token records (the name-length-prefixed strings live in the member records; the E608 parser
              handles them exactly like 0x1400ED1F0 does, so this is simply record(room) with its own leading
              19 bytes (room id + 3 flag bytes + owner, which this message does not carry) cut off.
    A wrong size anywhere in the 36-byte block before the tail shifts every field after it, including the
    member name lengths -- that misalignment, not an unchecked length by itself, is what overflowed the game's
    fixed-size name buffer and crashed it (2026-10-17: first fix only matched the head, not this layout).
    The header values are derived from the room so every player's own lobby server (steam mode) agrees.
    None when this player is in no room."""
    import hashlib
    with LOCK:
        room = ROOMS.get(session.get('room_id'))
        if room is None:
            return None
        lobby = room.get('steam_lobby')
    if steam_mode() and isinstance(lobby, int):  # who is in the room: the Steam lobby knows (host first)
        members = [m for m in steam().lobby_members(lobby) if m]
        with LOCK:
            for m in members:
                if m not in room['members'] and len(room['members']) < MAX_MEMBERS:
                    room['members'].append(m)
    seed = f"roi-battle:{room['id']}:{room.get('platform_lobby_id', 0)}".encode()
    ab = hashlib.md5(seed + b":ab", usedforsecurity=False).digest()
    ce = hashlib.md5(seed + b":ce", usedforsecurity=False).digest()
    header = (struct.pack('<H', kind) + ab[:8] + ab[8:16] + bytes(1)
              + ce[:8] + bytes(3) + ce[8:16])
    assert len(header) == 2 + 36
    with LOCK:
        return header + record(room)[19:]


def find_invited(uid, room_id):
    """An invited friend's game asks for the host's room by id (0xE616, id from the host game's Steam lobby).
    True when this lobby server knows the room, looking it up on Steam first in steam mode."""
    with LOCK:
        if room_id in ROOMS:
            return True
    if steam_mode():
        _refresh_from_steam(uid)
    with LOCK:
        return room_id in ROOMS


def join(session, uid, room_id):
    """Add uid to the room; returns its record, or None if it is gone or full."""
    with LOCK:
        room = ROOMS.get(room_id)
        if room is None or (uid not in room['members'] and len(room['members']) >= MAX_MEMBERS):
            return None
        lobby = room.get('steam_lobby') if room.get('remote') else None
        host = room['members'][0]
        already_joined = session.get('room_id') == room_id and uid in room['members']
    if lobby and not already_joined and not steam().join_verified(lobby, host):
        LOG('Steam room entry/owner verification rejected')
        return None
    with LOCK:
        # Steam entry runs outside the lock. Do not commit a vanished/full room.
        if (ROOMS.get(room_id) is not room or room['members'][0] != host
                or (uid not in room['members'] and len(room['members']) >= MAX_MEMBERS)):
            stale = True
        else:
            stale = False
            if session.get('room_id') != room_id:
                leave(session)
            if uid not in room['members']:
                room['members'].append(uid)
            session['room_id'] = room_id
            reply = record(room)
    if stale:
        if lobby and not already_joined:
            steam().leave(lobby)
        return None
    return reply


def leave(session):
    """Take this session's player out of its room; the room closes when its host leaves."""
    session.pop('result_context', None)
    with LOCK:
        room = ROOMS.get(session.pop('room_id', None))
        uid = session.get('uid')
        if room is None:
            return
        lobby = room.get('steam_lobby') if isinstance(room.get('steam_lobby'), int) else None
        if room.get('remote'):
            if uid in room['members']:
                room['members'].remove(uid)
            closing = False
        elif not room['members'] or room['members'][0] == uid or uid is None:
            ROOMS.pop(room['id'], None)
            closing = True
        else:
            if uid in room['members']:
                room['members'].remove(uid)
            return
    if lobby:
        threading.Thread(target=lambda: steam().leave(lobby, close=closing), daemon=True).start()
