"""Steam as the lobby directory: publish this PC's custom room as a Steam lobby and list other players' rooms.

Uses the game's own steam_api64.dll (2014 SDK: SteamMatchMaking009, SteamUtils007, no flat API) through the
interfaces' method tables, logged in as the player running Steam, for app 258160 (which they own). Nothing is
emulated or bypassed. One worker thread makes all Steam calls; call results are polled with
ISteamUtils::IsAPICallCompleted / GetAPICallResult (no callback objects).

Lobby data keys (own namespace, the game's own Steam lobbies use name/type/room/vip):
  roirev = protocol version, roirev_ep = host endpoint (hex, from 0xE60A), roirev_host = host Steam id,
  roirev_set = the Create Lobby payload (hex), roirev_room = the host's room id (the game's own Steam lobby
  carries the same id as "room"; invited friends look the room up by it)

    python steam_dir.py list                 list published rooms
    python steam_dir.py publish [seconds]    publish a test room (fake endpoint) and hold it
"""
import ctypes
import os
import pathlib
import queue
import sys
import threading
import time

PROTOCOL = "1"
APP_ID = 258160
# ISteamMatchmaking009 slots (checked against roi.exe's own calls)
MM_REQUEST_LOBBY_LIST, MM_ADD_STRING_FILTER, MM_ADD_DISTANCE_FILTER, MM_ADD_RESULT_COUNT = 4, 5, 9, 10
MM_GET_LOBBY_BY_INDEX, MM_CREATE_LOBBY, MM_JOIN_LOBBY, MM_LEAVE_LOBBY = 12, 13, 14, 15
MM_GET_NUM_MEMBERS, MM_GET_LOBBY_DATA, MM_SET_LOBBY_DATA, MM_SET_JOINABLE, MM_GET_OWNER = 17, 19, 20, 34, 35
# ISteamUtils007 slots
UT_IS_CALL_COMPLETED, UT_GET_CALL_RESULT = 11, 13
# callbacks (id, size with Steam's 8-byte packing)
LOBBY_ENTER, LOBBY_MATCH_LIST, LOBBY_CREATED = (504, 24), (510, 4), (513, 16)
LOBBY_PUBLIC, COMPARE_EQUAL, DISTANCE_WORLDWIDE = 2, 0, 3

c_bool, c_int, c_u64, c_vp, c_char_p = ctypes.c_bool, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_char_p


def _vcall(obj, slot, restype, *args):
    """Call method `slot` of a C++ interface; args are (ctype, value) pairs."""
    vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(ctypes.c_void_p(vtbl), ctypes.POINTER(ctypes.c_void_p))[slot]
    proto = ctypes.CFUNCTYPE(restype, c_vp, *[t for t, _ in args])
    return proto(fn)(obj, *[v for _, v in args])


class SteamDirectory:
    def __init__(self, dll, log=print):
        self.log = log
        self.jobs = queue.Queue()
        self.ok = False
        ready = threading.Event()
        threading.Thread(target=self._run, args=(pathlib.Path(dll), ready), daemon=True).start()
        ready.wait(20)

    # --- worker ---------------------------------------------------------------------------------------
    def _run(self, dll, ready):
        try:
            os.environ["SteamAppId"] = os.environ["SteamGameId"] = str(APP_ID)
            here = os.getcwd()
            os.chdir(dll.parent)  # steam_appid.txt lives next to the game's exe
            try:
                api = ctypes.CDLL(str(dll))
                api.SteamAPI_Init.restype = c_bool
                self.ok = bool(api.SteamAPI_Init())
            finally:
                os.chdir(here)
            if self.ok:
                for name in ("SteamMatchmaking", "SteamUtils"):
                    getattr(api, name).restype = c_vp
                self.api, self.mm, self.ut = api, api.SteamMatchmaking(), api.SteamUtils()
                self.ok = bool(self.mm and self.ut)
            self.log(f"steam directory: {'ready' if self.ok else 'Steam API not available (is Steam running?)'}")
        except Exception as e:  # noqa: BLE001
            self.log(f"steam directory: init failed: {e!r}")
            self.ok = False
        ready.set()
        while self.ok:
            fn, box, done = self.jobs.get()
            try:
                box["result"] = fn()
            except Exception as e:  # noqa: BLE001
                box["error"] = e
            done.set()

    def _do(self, fn, timeout=15):
        if not self.ok:
            return None
        box, done = {}, threading.Event()
        self.jobs.put((fn, box, done))
        if not done.wait(timeout):
            self.log("steam directory: call timed out")
            return None
        if "error" in box:
            self.log(f"steam directory: {box['error']!r}")
            return None
        return box.get("result")

    def _wait_call(self, handle, cb, timeout=10):
        cb_id, size = cb
        failed = c_bool()
        end = time.time() + timeout
        while time.time() < end:
            if _vcall(self.ut, UT_IS_CALL_COMPLETED, c_bool, (c_u64, handle), (ctypes.POINTER(c_bool), ctypes.byref(failed))):
                buf = ctypes.create_string_buffer(size)
                got = _vcall(self.ut, UT_GET_CALL_RESULT, c_bool, (c_u64, handle), (c_vp, ctypes.cast(buf, c_vp)),
                             (c_int, size), (c_int, cb_id), (ctypes.POINTER(c_bool), ctypes.byref(failed)))
                return buf.raw if got and not failed.value else None
            time.sleep(0.05)
        return None

    def _data(self, lobby, key):
        p = _vcall(self.mm, MM_GET_LOBBY_DATA, c_char_p, (c_u64, lobby), (c_char_p, key.encode()))
        return (p or b"").decode("utf-8", "replace")

    # --- API (any thread) -----------------------------------------------------------------------------
    def persona_name(self, uid):
        """Read Steam's cached UTF-8 name; no messages or invitations are sent."""
        def job():
            self.api.SteamFriends.restype = c_vp
            friends = self.api.SteamFriends()
            if not friends:
                return ''
            raw = _vcall(friends, 7, c_char_p, (c_u64, int(uid)))
            name = (raw or b'').decode('utf-8', 'replace')
            return '' if name == '[unknown]' else name
        return self._do(job, timeout=2) or ''

    def lobby_members(self, lobby):
        """Steam ids in a Steam lobby (GetNumLobbyMembers slot 17, GetLobbyMemberByIndex slot 18)."""
        def job():
            out = []
            for i in range(min(4, max(0, _vcall(self.mm, MM_GET_NUM_MEMBERS, c_int, (c_u64, lobby))))):
                sid = ctypes.c_uint64()
                _vcall(self.mm, 18, c_vp, (c_vp, ctypes.cast(ctypes.byref(sid), c_vp)), (c_u64, lobby), (c_int, i))
                out.append(sid.value)
            return out
        return self._do(job, timeout=5) or []

    def friends_in_game(self):
        """{Steam id: in_a_lobby} for this player's Steam friends who are running Rise of Incarnates.
        ISteamFriends014: GetFriendCount(flags) slot 3, GetFriendByIndex slot 4 (CSteamID via hidden pointer),
        GetFriendGamePlayed slot 8 (FriendGameInfo_t: u64 game id, u32 ip, u16, u16, u64 lobby)."""
        def job():
            self.api.SteamFriends.restype = c_vp
            friends = self.api.SteamFriends()
            out = {}
            if not friends:
                return out
            for i in range(min(512, max(0, _vcall(friends, 3, c_int, (c_int, 4))))):
                sid = ctypes.c_uint64()
                _vcall(friends, 4, c_vp, (c_vp, ctypes.cast(ctypes.byref(sid), c_vp)), (c_int, i), (c_int, 4))
                info = ctypes.create_string_buffer(24)
                if _vcall(friends, 8, c_bool, (c_u64, sid.value), (c_vp, ctypes.cast(info, c_vp))):
                    if int.from_bytes(info.raw[:8], "little") & 0xFFFFFF == APP_ID:
                        out[sid.value] = int.from_bytes(info.raw[16:24], "little") != 0
            return out
        return self._do(job, timeout=5) or {}

    def publish(self, data, max_members=4):
        """Create a public Steam lobby carrying data (dict of str); returns its id or None."""
        def job():
            h = _vcall(self.mm, MM_CREATE_LOBBY, c_u64, (c_int, LOBBY_PUBLIC), (c_int, max_members))
            res = self._wait_call(h, LOBBY_CREATED)
            if not res or int.from_bytes(res[:4], "little") != 1:  # EResult k_EResultOK
                self.log(f"steam directory: CreateLobby failed ({res[:4].hex() if res else 'no result'})")
                return None
            lobby = int.from_bytes(res[8:16], "little")
            for k, v in {"roirev": PROTOCOL, **data}.items():
                _vcall(self.mm, MM_SET_LOBBY_DATA, c_bool, (c_u64, lobby), (c_char_p, k.encode()), (c_char_p, str(v).encode()))
            return lobby
        return self._do(job)

    def update(self, lobby, data):
        def job():
            for k, v in data.items():
                _vcall(self.mm, MM_SET_LOBBY_DATA, c_bool, (c_u64, lobby), (c_char_p, k.encode()), (c_char_p, str(v).encode()))
        self._do(job)

    def search(self, max_results=50, keys=("roirev_ep", "roirev_host", "roirev_set", "roirev_room"), only_ours=True):
        """Published rooms: list of dicts {lobby, members, <keys>...}. only_ours=False lists every lobby of the app."""
        def job():
            if only_ours:
                _vcall(self.mm, MM_ADD_STRING_FILTER, None, (c_char_p, b"roirev"), (c_char_p, PROTOCOL.encode()), (c_int, COMPARE_EQUAL))
            _vcall(self.mm, MM_ADD_DISTANCE_FILTER, None, (c_int, DISTANCE_WORLDWIDE))
            _vcall(self.mm, MM_ADD_RESULT_COUNT, None, (c_int, max_results))
            res = self._wait_call(_vcall(self.mm, MM_REQUEST_LOBBY_LIST, c_u64), LOBBY_MATCH_LIST)
            out = []
            for i in range(min(max_results, int.from_bytes(res[:4], "little")) if res else 0):
                sid = ctypes.c_uint64()
                _vcall(self.mm, MM_GET_LOBBY_BY_INDEX, c_vp, (c_vp, ctypes.cast(ctypes.byref(sid), c_vp)), (c_int, i))
                lobby = sid.value
                row = {k: self._data(lobby, k) for k in keys}
                row["lobby"] = lobby
                owner = ctypes.c_uint64()
                _vcall(self.mm, MM_GET_OWNER, c_vp, (c_vp, ctypes.cast(ctypes.byref(owner), c_vp)), (c_u64, lobby))
                row["owner"] = owner.value
                row["members"] = _vcall(self.mm, MM_GET_NUM_MEMBERS, c_int, (c_u64, lobby))
                out.append(row)
            return out
        return self._do(job) or []

    def join(self, lobby):
        def job():
            res = self._wait_call(_vcall(self.mm, MM_JOIN_LOBBY, c_u64, (c_u64, lobby)), LOBBY_ENTER)
            return bool(res) and int.from_bytes(res[16:20], "little") == 1  # k_EChatRoomEnterResponseSuccess
        return self._do(job)

    def join_verified(self, lobby, expected_owner):
        """GetLobbyOwner is only authoritative AFTER entering the lobby."""
        deadline = time.monotonic() + 8
        def job():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            handle = _vcall(self.mm, MM_JOIN_LOBBY, c_u64, (c_u64, lobby))
            res = self._wait_call(handle, LOBBY_ENTER, timeout=min(6, remaining))
            entered = bool(res) and int.from_bytes(res[16:20], "little") == 1
            owner = ctypes.c_uint64()
            if entered:
                _vcall(self.mm, MM_GET_OWNER, c_vp,
                       (c_vp, ctypes.cast(ctypes.byref(owner), c_vp)), (c_u64, lobby))
            if not entered or owner.value != expected_owner or time.monotonic() >= deadline:
                _vcall(self.mm, MM_LEAVE_LOBBY, None, (c_u64, lobby))
                self.log('steam directory: join/owner verification failed')
                return False
            return True
        return bool(self._do(job, timeout=9))

    def leave(self, lobby, close=False):
        def job():
            if close:
                _vcall(self.mm, MM_SET_JOINABLE, c_bool, (c_u64, lobby), (c_bool, False))
                _vcall(self.mm, MM_SET_LOBBY_DATA, c_bool, (c_u64, lobby), (c_char_p, b"roirev"), (c_char_p, b"closed"))
            _vcall(self.mm, MM_LEAVE_LOBBY, None, (c_u64, lobby))
        self._do(job)


_INSTANCE = None
_LOCK = threading.Lock()


def get(log=print):
    """The process-wide directory (created on first use)."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
            import paths
            _INSTANCE = SteamDirectory(paths.GAME_EXE.parent / "steam_api64.dll", log)
        return _INSTANCE


if __name__ == "__main__":
    d = get()
    if sys.argv[1:2] == ["publish"]:
        # made-up host id and endpoint (nothing on Steam answers to them): a game that joins gets as far as
        # connecting to the host and then gives up
        lobby = d.publish({"roirev_ep": "0140cae400000001", "roirev_host": str(0x011000017FFFFF01), "roirev_set": ""})
        print("published lobby", hex(lobby) if lobby else None)
        time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 120)
        if lobby:
            d.leave(lobby, close=True)
    elif sys.argv[1:2] == ["all"]:  # every lobby of the app, including the game's own (keys name/type/room/vip)
        rows = d.search(keys=("roirev", "type", "room", "vip", "name"), only_ours=False)
        print(f"{len(rows)} lobby(s)")
        for r in rows:
            name = "set" if r["name"] else ""
            print(f"  lobby {r['lobby']:#x} members {r['members']} roirev={r['roirev']!r} type={r['type']!r} "
                  f"room={r['room']!r} vip={r['vip']!r} name={name}")
    else:
        rows = d.search()
        print(f"{len(rows)} room(s)")
        for r in rows:
            print(f"  lobby {r['lobby']:#x} members {r['members']} endpoint {r['roirev_ep']} host {'set' if r['roirev_host'] not in ('', '0') else r['roirev_host']}")
