"""Build the offline test client: clean Steam roi.exe + patches + an appended '.offline' code section.

    python build.py [--out PATH] [--dry]

Starts from the unmodified Steam executable (SHA-256 checked) and writes roi-backup-test/exe/roi.exe.
Patch set = Codex's verified offline patches (see ../full-patch-manifest.json) + local server data (roi_data.py).
"""
import hashlib
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from network_defaults import LOOPBACK
import paths  # noqa: E402

sys.path.insert(0, str(paths.LIBS))
import capstone  # noqa: E402,F401
import pefile  # noqa: E402

import roi_data  # noqa: E402
import native_video  # noqa: E402
import native_commendations  # noqa: E402
from build_safety import ensure_distinct_output  # noqa: E402

SRC = paths.STEAM_EXE
SRC_SHA = "34a46fbc9e2ea6c6c9eebfddd0d6e4bef388a3eea5088838dd134588225cedbb"
OUT = paths.GAME_EXE

# Globals in the shutdown build
G_GAMEDATA = 0x141B87458
G_SCENEMGR = 0x141B874E0
G_FILEMGR = 0x141B87478
G_UNITMGR = 0x141B87508
G_CHARCFG = 0x141B87500
G_RESCTRL_OWNER = 0x141B874B8
G_PRELOADERS = 0x141B941F0
DESC_MAKERLOGO = 0x141B98880


def align(n, a):
    return (n + a - 1) // a * a


class Asm:
    def __init__(self, base):
        self.base = base
        self.code = bytearray()
        self.labels = {}
        self.fixups = []  # (pos, label) rel32 fixups to labels

    @property
    def here(self):
        return self.base + len(self.code)

    def emit(self, h):
        self.code += bytes.fromhex(h)

    def raw(self, b):
        self.code += b

    def rel(self, op, target):
        """op bytes followed by a rel32 to an absolute VA (call/jmp/rip-relative)."""
        self.emit(op)
        if isinstance(target, str):
            self.fixups.append((len(self.code), target))
            self.code += b"\0\0\0\0"
        else:
            self.code += struct.pack("<i", target - (self.here + 4))

    def label(self, name):
        self.labels[name] = self.here

    def pad_to(self, n):
        assert len(self.code) <= n, (hex(len(self.code)), hex(n))
        self.code += b"\xcc" * (n - len(self.code))

    def finish(self):
        for pos, name in self.fixups:
            struct.pack_into("<i", self.code, pos, self.labels[name] - (self.base + pos + 4))
        return bytes(self.code)

    # helpers -------------------------------------------------------------
    def mov_rcx_global(self, g):
        self.rel("48 8b 0d", g)

    def create_unit(self, meta):
        """rax = unitmgr->Create(6, 0, meta); mark persistent (flag 8)."""
        self.mov_rcx_global(G_UNITMGR)
        self.emit("ba 06 00 00 00 45 31 c0")
        self.rel("4c 8d 0d", meta)
        self.rel("e8", 0x1407D8850)
        self.emit("83 48 20 08")

    def store_imm(self, reg_rcx_disp, data):
        """mov dword/byte [rcx+disp], imm for each 4-byte chunk of data (rcx = base pointer)."""
        off = reg_rcx_disp
        i = 0
        while i < len(data):
            chunk = data[i:i + 4]
            if len(chunk) == 4:
                if chunk != b"\0\0\0\0" or True:
                    self.emit("c7 81")
                    self.code += struct.pack("<I", off + i) + chunk
                i += 4
            else:
                for j, byte in enumerate(chunk):
                    self.emit("c6 81")
                    self.code += struct.pack("<I", off + i + j) + bytes([byte])
                i += len(chunk)


SERVER_URL = f'http://{LOOPBACK}:52710/'
# Off: count == 1 is not enough (a bank can be held by its preloader entry alone); freeing one crashed the
# battle-exit preloader clear (0x140b5de86). Needs a check that no preloader entry holds the bank.
SOUND_GC = False
# Codex's sync_preload loads a queued resource on the main thread while the async loader thread loads it too:
# every such resource loads twice, textures get a second GPU object (screens already built keep the first and
# draw white), sound banks register twice. Off: rely on the async loader.
SYNC_PRELOAD = False
MULTI_INSTANCE = False  # True: skip the single-instance check so two copies can run on one PC (testing only)


def build(out, dry=False, server=False):
    out = ensure_distinct_output(SRC, out)
    b = bytearray(SRC.read_bytes())
    assert hashlib.sha256(b).hexdigest() == SRC_SHA, "unexpected source roi.exe"
    pe = pefile.PE(data=bytes(b))
    image_base = pe.OPTIONAL_HEADER.ImageBase
    changes = []

    def patch(va, data, why):
        if isinstance(data, str):
            data = bytes.fromhex(data)
        p = pe.get_offset_from_rva(va - image_base)
        changes.append(dict(va=hex(va), old=b[p:p + len(data)].hex(), new=data.hex(), reason=why))
        b[p:p + len(data)] = data

    def jmp(frm, to, total):
        return b"\xe9" + struct.pack("<i", to - (frm + 5)) + b"\x90" * (total - 5)

    for va, expected, replacement in native_video.PATCHES:
        offset = pe.get_offset_from_rva(va - image_base)
        assert bytes(b[offset:offset + len(expected)]) == expected, hex(va)
        patch(va, replacement, 'Honor saved video settings instead of startup window-mode/GPU-preset overrides')

    for va, expected, replacement in native_commendations.PATCHES:
        offset = pe.get_offset_from_rva(va - image_base)
        assert bytes(b[offset:offset + len(expected)]) == expected, hex(va)
        patch(va, replacement, 'Remove the native 20-click commendation quota')

    # Heap 0 (default heap, 128 MB) fills up once the offline startup keeps every preload resident and the
    # master data arrives; heap table at 0x1401f42c0. 512 MB is still small for a 64-bit process.
    # Heaps (table in 0x1401f42c0) are one contiguous block from ~0x5f80000 in table order and must END BELOW
    # 2 GB: parts of the engine keep heap pointers in 32 bits (a 1.1 GB heap 4 broke battle start at 0x1407c2900).
    # A VS Bot match takes ~150 MB of heap 4 and ~35 MB of heap 3, only part comes back afterwards, so the second
    # match in a row ran out. (Heaps 2 and 8 look empty but hold renderer resources: shrinking them breaks
    # shader setup at boot.) Total 1898 MB (was 1500): ends at ~0x7c980000, ~50 MB under 2 GB.
    patch(0x1401F43B1, "48 c7 45 a4 00 00 00 0c", "Heap 3: 110 MB -> 192 MB")
    patch(0x1401F43D1, "48 c7 45 bc 00 00 00 24", "Heap 4: 260 MB -> 576 MB")
    if MULTI_INSTANCE:
        # Startup (0x1401d91a0) creates "ROI mutex" and quits with "multiple starts error" when it already exists.
        assert pe.get_data(0x1D91CD, 2) == bytes.fromhex("753f"), pe.get_data(0x1D91CD, 2).hex()
        patch(0x1401D91CD, "eb 3f", "Allow several copies at once (in-house online testing)")

    p = pe.get_offset_from_rva(0x1401DBE37 - image_base)
    assert b[p:p + 6] == bytes.fromhex("40387b437446"), b[p:p + 6].hex()

    if server:
        # --- talk to the local stand-in server instead of gdragon.vs765.nbgi-amnet.jp ------------
        url_va = 0x141850858
        p = pe.get_offset_from_rva(url_va - image_base)
        old = bytes(b[p:p + 64]).split(b"\0")[0]
        assert old == b"https://gdragon.vs765.nbgi-amnet.jp/", old
        new = SERVER_URL.encode()
        assert len(new) <= len(old)
        patch(url_va, new + bytes(len(old) - len(new) + 1), "Game server URL -> local stand-in server")
        # Login step 3 (profile loaded) ends the login in the shutdown build; continue with step 4
        # (account -> realtime server -> master data) like the original flow: call 0x1401042d0.
        p3 = pe.get_offset_from_rva(0x140101065 - image_base)
        assert bytes(b[p3:p3 + 21]).hex() == "c78584020000" "0b000000" "898588020000" "e9dd000000", bytes(b[p3:p3 + 21]).hex()
        code3 = bytes.fromhex("48 89 e9") + b"\xe8" + struct.pack("<i", 0x1401042D0 - (0x140101068 + 5))
        code3 += b"\xe9" + struct.pack("<i", 0x140101161 - (0x14010106D + 5))
        patch(0x140101065, code3 + b"\x90" * (21 - len(code3)), "Login step 3 -> step 4 (full login with master data)")
    else:
        # --- Codex's verified patches (login/offline gates) -----------------------------------
        patch(0x1401038E0, "c7 81 88 02 00 00 03 00 00 00 c3", "Local login state; do not start remote authorization")
        patch(0x140103910, "b8 02 00 00 00 c3", "Report local login completion")
        patch(0x140142070, "c7 01 01 00 00 00 48 89 c8 c3", "Allow initial scene without downloaded player status map")
        patch(0x140100E60, "c3", "Disable backend service tick")
        patch(0x140777188, jmp(0x140777188, 0x1407771F0, 5), "Use initialized local tutorial profile when downloaded profile is absent")
        patch(0x1401E4BE9, "90 90 90 90 90 90", "Allow local asset loading without server flag")

    # --- appended section --------------------------------------------------------------------
    last = pe.sections[-1]
    secva = align(last.VirtualAddress + last.Misc_VirtualSize, pe.OPTIONAL_HEADER.SectionAlignment)
    base = image_base + secva
    a = Asm(base)

    # Startup: replaces the shutdown build's "switch to CSceneClosed" (0x1401f3b60).
    a.label("startup")
    a.emit("48 83 ec 28")
    for i in range(6):  # persistent resource preloaders
        a.create_unit(0x141BEFD80)
        a.emit("c7 80 84 00 00 00")
        a.raw(struct.pack("<I", i))
        a.rel("48 89 05", G_PRELOADERS + i * 8)
    a.create_unit(0x141B98FC0)                          # sound unit
    a.mov_rcx_global(G_CHARCFG)
    a.rel("e8", 0x1400347C0)                            # player resource initialization
    a.mov_rcx_global(G_GAMEDATA)
    for slot in range(4):                               # player slots start as character 1
        a.emit("c6 81")
        a.raw(struct.pack("<I", 0x22 + slot * 0xF2C8))
        a.emit("01")
    a.rel("e8", "chara_master")                        # local chara_master rows
    a.mov_rcx_global(0x141C00500)
    a.rel("e8", 0x140545EE0)                            # DeuterosData loader
    a.mov_rcx_global(0x141C00528)
    a.rel("e8", 0x140585460)                            # SubCharaData loader
    a.mov_rcx_global(0x141C00368)
    a.rel("e8", 0x140552D40)                            # LaminaData loader
    a.mov_rcx_global(0x141C00458)
    a.rel("e8", 0x140544880)                            # ChainObjectData loader (orphaned in shutdown build)
    a.mov_rcx_global(0x141C00498)
    a.rel("e8", 0x14054EA30)                            # demo/demo_resource script (orphaned)
    a.create_unit(0x141BB0B70)                          # game resource controller
    a.mov_rcx_global(G_RESCTRL_OWNER)
    a.emit("48 89 41 28")
    a.mov_rcx_global(G_SCENEMGR)                        # scenemgr->Change(&tmp, MakerLogo)
    a.rel("4c 8d 05", DESC_MAKERLOGO)
    a.emit("48 8d 54 24 20 48 8b 01 ff 50 30 48 83 c4 28 c3")

    # Finish unfinished preload requests synchronously (patched in at 0x140b5c358).
    a.label("sync_preload")
    a.emit("48 8b 47 d8 83 b8 b0 00 00 00 00 75 1b 48 83 ec 20 48 89 c2")
    a.mov_rcx_global(G_FILEMGR)
    a.rel("e8", 0x1407BF0F0)
    a.emit("48 83 c4 20 48 8b 47 d8 44 39 b8 b0 00 00 00")
    a.rel("e9", 0x140B5C363)

    # Skip resource-registry cleanup for unregistered (-1) entries (patched in at 0x1407f551c).
    a.label("unregister_guard")
    orig = pe.get_data(0x7F551C, 15)
    assert orig[:3] == bytes.fromhex("8b4750")
    a.raw(orig[:3])
    a.emit("83 f8 ff 74 0c")
    a.raw(orig[3:])
    a.rel("e9", 0x1407F552B)

    # Owner-stat refresh 0x14062a780(rcx = unit+0xfb20): dereferences the owner from the per-slot table at
    # *(0x141b87490) + slot*0x25d0 + 0x18 without a null check; in VS Bot battles started from the menu it runs
    # before the owner is registered. Skip it when the slot is invalid or empty.
    a.label("owner_guard")
    orig_a = pe.get_data(0x62A780, 7)
    assert orig_a == bytes.fromhex("488bc448895808"), orig_a.hex()
    a.emit("0f b6 41 08")              # movzx eax, byte [rcx+8]
    a.emit("84 c0 78 2a")              # test al, al ; js skip
    a.emit("3c 06 7d 26")              # cmp al, 6 ; jge skip
    a.emit("48 0f be c0")              # movsx rax, al
    a.emit("48 69 c0 d0 25 00 00")     # imul rax, rax, 0x25d0
    a.rel("4c 8b 15", 0x141B87490)     # mov r10, [rip -> 0x141b87490]
    a.emit("4a 83 7c 10 18 00")        # cmp qword [rax + r10 + 0x18], 0
    a.emit("74 0c")                    # je skip
    a.raw(orig_a)                      # mov rax, rsp ; mov [rax+8], rbx
    a.rel("e9", 0x14062A787)
    a.emit("c3")                       # skip: ret

    # Unload sound banks nobody uses any more. A loaded bank registers in the sound manager (*0x141b874f0, 32 slots
    # at +0x1e8, entry+8 = bank resource) and keeps one reference there; the bank only unloads (slot 3 -> unregister
    # 0x140ba27d0, frees the ACB and the slot) when its count reaches 0, which never happens for battle banks, so
    # every round added its characters' voice banks to heap 3 until loading stalled. Release that last reference
    # for every registered bank whose count is 1 (no preloader and no sound player holds it).
    # Runs when the Briefing ends (0x1401451e9): the new round's banks are loaded (count >= 2, reused ones too) and
    # the previous round has been torn down (at battle exit CRI still holds its banks, so the count is still 2).
    # Battle exit (0x1401dbdc0) clears the battle resources (0x1405680e0: per-player sets + preloader 0) and the HUD
    # preloaders 4/5 only when [scene+0x43] is set (leaving VS Bot). Between rounds it is not, so every round's
    # characters stayed loaded and heap 4 ran out by round 2-3 (white enemy textures). Clear the battle resources
    # between rounds too, but keep the original handling of the HUD preloaders (4/5 are requested once per VS Bot
    # session; clearing them left round 2's intro and HUD white). Patched in at 0x1401dbe37.
    a.label("round_exit")
    a.emit("40 38 7b 43")                               # cmp byte [rbx+0x43], dil (rdi = 0)
    a.emit("74 05")                                     # je +5 (between rounds)
    a.rel("e9", 0x1401DBE3D)                            # leaving VS Bot: original full clear
    a.rel("48 8b 0d", 0x141B874B8)                      # mov rcx, [resource controller owner]
    a.emit("48 8b 49 28")                               # mov rcx, [rcx+0x28]
    a.rel("e8", 0x1405680E0)                            # clear battle resources (preloader 0)
    a.rel("e9", 0x1401DBE83)                            # original between-rounds path (HUD preloaders)

    # UNUSED (not patched in; the real cause of the white Briefing was double loading, see SYNC_PRELOAD).
    # Briefing: the scene requests its HUD/texture preload lists (0x1405690d0(ctrl, 4) -> preloader 5, ~190 textures)
    # and builds its panels a frame later, while the preloader update (0x140b5c2a0) starts at most 8 loads per
    # frame; the panel textures are looked up before they exist and stay white for the whole Briefing. Finish
    # preloader 5 right after the request (each pass loads synchronously via sync_preload). Called from 0x14014508d.
    a.label("briefing_preload")
    a.emit("53 48 83 ec 20")                            # push rbx; sub rsp, 0x20 (aligned)
    a.rel("e8", 0x1405690D0)                            # the original request (rcx, edx from the caller)
    a.emit("bb 30 00 00 00")                            # mov ebx, 48 passes
    loop_p = len(a.code)
    a.rel("48 8b 0d", G_PRELOADERS + 5 * 8)             # mov rcx, [preloader 5]
    a.emit("48 85 c9 74 00")                            # test rcx, rcx; jz done
    jz_p = len(a.code) - 1
    a.rel("e8", 0x140B5C2A0)                            # preloader update
    a.emit("ff cb 75 00")                               # dec ebx; jnz loop
    a.code[-1] = (loop_p - len(a.code)) & 0xFF
    a.code[jz_p] = len(a.code) - (jz_p + 1)
    a.emit("48 83 c4 20 5b c3")                         # add rsp, 0x20; pop rbx; ret
    assert pe.get_data(0x14508D, 5) == bytes.fromhex("e83e404200"), pe.get_data(0x14508D, 5).hex()

    # Sound manager register 0x140ba26a0(mgr, bank): a new entry keeps the bank without a reference; registering a
    # bank that is already registered adds one (AddRef on entry+8). Every bank gets loaded twice here (the async
    # loader, then sync_preload's synchronous load), so each bank kept one extra reference and never unloaded.
    # Re-registering the same bank now does nothing (patched in at 0x140ba26d2; rcx = entry, rbx = bank).
    a.label("register_once")
    a.emit("48 8b 41 08 48 85 c0 74 0a")                # mov rax, [rcx+8]; test rax, rax; jz ret
    a.emit("48 39 d8 74 05")                            # cmp rax, rbx; je ret
    a.rel("e9", 0x140BA26DD)                            # different bank: original AddRef path
    a.rel("e9", 0x140BA27BF)                            # ret: original return path
    assert pe.get_data(0xBA26D2, 11) == bytes.fromhex("4883790800 0f84e2000000".replace(" ", ""))

    a.label("briefing_gc")                              # site: rsp 16-aligned
    a.rel("e8", "sound_gc")
    a.emit("48 8b 46 60 48 85 c0")                      # original: mov rax, [rsi+0x60]; test rax, rax
    a.rel("e9", 0x1401451F0)

    a.label("sound_gc")                                 # callable; preserves rbx/rsi/rdi
    a.emit("53 56 57 48 83 ec 20")                      # push rbx/rsi/rdi; sub rsp, 0x20
    a.rel("48 8b 35", 0x141B874F0)                      # mov rsi, [sound manager]
    a.emit("48 85 f6 74 00")                            # test rsi, rsi; jz done
    jz_done = len(a.code) - 1
    a.emit("48 81 c6 e8 01 00 00 bf 20 00 00 00")       # add rsi, 0x1e8; mov edi, 32
    loop = len(a.code)
    a.emit("48 8b 06 48 85 c0 74 00")                   # mov rax, [rsi]; test rax, rax; jz next
    jz_next1 = len(a.code) - 1
    a.emit("48 8b 58 08 48 85 db 74 00")                # mov rbx, [rax+8]; test rbx, rbx; jz next
    jz_next2 = len(a.code) - 1
    a.emit("48 8b 03 48 89 d9 ff 50 30")                # eax = bank->GetRefCount()
    a.emit("83 f8 01 75 00")                            # cmp eax, 1; jne next
    jne_next = len(a.code) - 1
    a.emit("48 8b 03 48 89 d9 ff 50 28")                # bank->Release()
    nxt = len(a.code)
    a.emit("48 83 c6 08 ff cf 75 00")                   # add rsi, 8; dec edi; jnz loop
    a.code[-1] = (loop - len(a.code)) & 0xFF
    done = len(a.code)
    a.emit("48 83 c4 20 5f 5e 5b c3")                   # add rsp, 0x20; pop rdi/rsi/rbx; ret
    for pos, target in ((jz_done, done), (jz_next1, nxt), (jz_next2, nxt), (jne_next, nxt)):
        a.code[pos] = target - (pos + 1)
    assert pe.get_data(0x1451E9, 7) == bytes.fromhex("488b46604885c0"), pe.get_data(0x1451E9, 7).hex()

    # chara_master rows: rcx = gamedata on entry.
    a.label("chara_master")
    a.mov_rcx_global(G_GAMEDATA)
    for cid in sorted(roi_data.CHARACTERS):
        row = roi_data.CHARA_TABLE + cid * roi_data.CHARA_ROW
        for off, kind, value in roi_data.chara_row_fields(cid):
            if kind == "u32":
                data = struct.pack("<I", value)
            elif kind == "u8":
                data = bytes([value])
            elif kind == "str64":
                data = value.encode() + b"\0"
                assert len(data) <= 64
                data += bytes((-len(data)) % 4)
            a.store_imm(row + off, data)
    a.emit("c3")

    code = a.finish()
    labels = a.labels

    patch(0x1401F3B60, jmp(0x1401F3B60, labels["startup"], 5), "Run offline startup initialization, then MakerLogo (instead of CSceneClosed)")
    if SYNC_PRELOAD:
        patch(0x140B5C358, jmp(0x140B5C358, labels["sync_preload"], 11), "Synchronously finish pending preload requests")
    patch(0x1407F551C, jmp(0x1407F551C, labels["unregister_guard"], 15), "Avoid indexing resource registry with unregistered -1")
    patch(0x14062A780, jmp(0x14062A780, labels["owner_guard"], 7), "Skip owner-stat refresh when the owner slot is not registered")
    # Preloader update 0x140b5c2a0 starts at most 8 new loads per call (once per frame). Lists hold the HUD layouts
    # first and their textures after them, so a screen (Briefing, result, battle intro) is built as soon as its
    # layouts are in while its big textures are still queued, and the panels stay white. With sync_preload every
    # started load finishes at once, so start all of them in the same update.
    assert pe.get_data(0xB5C32C, 5) == bytes.fromhex("83fe087353"), pe.get_data(0xB5C32C, 5).hex()
    patch(0x140B5C32F, "90 90", "Preloader: start every queued load in one update (no 8-per-frame limit)")
    patch(0x1401DBE37, jmp(0x1401DBE37, labels["round_exit"], 6), "Battle exit between rounds: also clear the battle resources (preloader 0), not the HUD")
    # Sound bank Unload (slot 3, 0x140ba4fa0): releases the data object found via 0x1407c95a0([bank+0xd8]) without a
    # null check; a bank dropped before its async load finished has none (crash at 0x140ba4fd5). Skip the release.
    assert pe.get_data(0xBA4FCC, 2) == bytes.fromhex("7405"), pe.get_data(0xBA4FCC, 2).hex()
    patch(0x140BA4FCC, "74 14", "Sound bank unload: skip releasing data that never loaded")
    patch(0x140BA26D2, jmp(0x140BA26D2, labels["register_once"], 11), "Sound manager: registering the same bank twice does not add a reference")
    if SOUND_GC:
        patch(0x1401451E9, jmp(0x1401451E9, labels["briefing_gc"], 7), "Briefing end: unload sound banks only the sound manager still holds")

    # --- add the section header ------------------------------------------------------------
    rawoff = align(len(b), pe.OPTIONAL_HEADER.FileAlignment)
    rawsize = align(len(code), pe.OPTIONAL_HEADER.FileAlignment)
    header = last.get_file_offset() + 40
    assert header + 40 <= pe.OPTIONAL_HEADER.SizeOfHeaders
    assert b[header:header + 40] == bytes(40)
    b[header:header + 40] = struct.pack("<8sIIIIIIHHI", b".offline", len(code), secva, rawsize, rawoff, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", b, pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"), len(pe.sections) + 1)
    struct.pack_into("<I", b, pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"), align(secva + len(code), pe.OPTIONAL_HEADER.SectionAlignment))
    b.extend(bytes(rawoff - len(b)) + code + bytes(rawsize - len(code)))

    manifest = dict(source_sha256=SRC_SHA, section_va=hex(base), section_size=len(code),
                    labels={k: hex(v) for k, v in labels.items()}, patches=changes)
    if dry:
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        for addr, size, mn, op in md.disasm_lite(code[:labels["chara_master"] - base + 0x40], base):
            print(f"{addr:x} {mn} {op}")
        print(json.dumps(manifest, indent=1)[:3000])
        return
    out.write_bytes(b)
    (HERE / "build-manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {out} ({len(changes)} patches, section {base:#x} +{len(code):#x})")


if __name__ == "__main__":
    out = OUT
    if "--out" in sys.argv:
        out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
    build(out, dry="--dry" in sys.argv, server="--server" in sys.argv)
