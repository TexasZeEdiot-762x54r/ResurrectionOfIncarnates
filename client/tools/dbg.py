"""Minimal Win32 debugger for the isolated Rise of Incarnates test client (ctypes, no dependencies).

    python dbg.py <session.py> [--exe PATH] [--seconds N] [--log FILE]

A session module defines `setup(d)`; it calls d.bp(addr, fn) / d.on_crash(fn) / d.patch(addr, bytes).
Breakpoint handlers get a Hit with .rax/.rcx/... (read/write), .read(addr, n), .str(addr), .q(addr), .d(addr),
.stack(n) and .ret() helpers. Handlers may return "remove" to drop the breakpoint.
Everything is logged to the log file (default claude/logs/<session>.log).
"""
import ctypes
import ctypes.wintypes as wt
import importlib.util
import os
import pathlib
import struct
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

sys.path.insert(0, str(paths.LIBS))
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DEBUG_ONLY_THIS_PROCESS = 2
CREATE_NEW_CONSOLE = 0x10
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_BREAKPOINT = 0x80000003
EXCEPTION_SINGLE_STEP = 0x80000004
CONTEXT_FULL = 0x10000B
REGS = ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                               ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFO),
                               ctypes.POINTER(PROCESS_INFORMATION)]
k32.WaitForDebugEvent.argtypes = [ctypes.c_void_p, wt.DWORD]
k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.FlushInstructionCache.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.SetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
k32.DebugSetProcessKillOnExit.argtypes = [wt.BOOL]
k32.SuspendThread.argtypes = [wt.HANDLE]
k32.ResumeThread.argtypes = [wt.HANDLE]


class Context:
    """Aligned x64 CONTEXT buffer."""

    def __init__(self):
        self.raw = ctypes.create_string_buffer(1232 + 16)
        self.addr = (ctypes.addressof(self.raw) + 15) & ~15
        ctypes.memset(self.addr, 0, 1232)
        struct.pack_into("<I", self.buf(), 0x30, CONTEXT_FULL)

    def buf(self):
        return (ctypes.c_char * 1232).from_address(self.addr)

    def get(self, off, fmt="<Q"):
        return struct.unpack_from(fmt, self.buf(), off)[0]

    def set(self, off, value, fmt="<Q"):
        struct.pack_into(fmt, self.buf(), off, value)

    def reg_off(self, name):
        if name == "rip":
            return 0xF8
        return 0x78 + REGS.index(name) * 8


class Hit:
    def __init__(self, dbg, tid, ctx, addr):
        self.dbg, self.tid, self.ctx, self.addr = dbg, tid, ctx, addr
        self.dirty = False

    def __getattr__(self, name):
        if name in REGS or name == "rip":
            return self.ctx.get(self.ctx.reg_off(name))
        if name == "eflags":
            return self.ctx.get(0x44, "<I")
        raise AttributeError(name)

    def setreg(self, name, value):
        self.ctx.set(self.ctx.reg_off(name), value & 0xFFFFFFFFFFFFFFFF)
        self.dirty = True

    def read(self, a, n):
        return self.dbg.read(a, n)

    def q(self, a):
        return struct.unpack("<Q", self.dbg.read(a, 8))[0]

    def d(self, a):
        return struct.unpack("<I", self.dbg.read(a, 4))[0]

    def str(self, a, n=256):
        return self.dbg.cstr(a, n)

    def wstr(self, a, n=512):
        b = self.dbg.read(a, n)
        for i in range(0, len(b) - 1, 2):
            if b[i] == 0 and b[i + 1] == 0:
                b = b[:i]
                break
        return b.decode("utf-16le", "replace")

    def stack(self, n=8):
        return [self.q(self.rsp + 8 * i) for i in range(n)]

    def ret(self):
        return self.q(self.rsp)

    def skip_call(self, value=0):
        """At a function's first instruction: return immediately with rax=value."""
        r = self.ret()
        self.setreg("rsp", self.rsp + 8)
        self.setreg("rip", r)
        self.setreg("rax", value)


class Debugger:
    def __init__(self, exe, log):
        self.exe = pathlib.Path(exe)
        self.logf = open(log, "w", encoding="utf-8", buffering=1)
        self.bps = {}           # addr -> [orig_byte, handler]
        self.patches = []       # (addr, bytes) applied at process start
        self.rearm = {}         # tid -> addr
        self.crash_handlers = []
        self.start_handlers = []
        self.hproc = None
        self.pid = None
        self.t0 = time.time()
        self.seen_initial_bp = False
        self.stop = False
        self.idx = None
        self.pollers = []
        self.poll_every = 10.0
        self.export_bps = []

    def sample(self, tid=None, depth=12):
        """Suspend a thread (default: main), log rip and call chain, resume."""
        tid = tid or self.main_tid
        h = k32.OpenThread(0x1FFFFF, False, tid)
        if not h:
            return
        k32.SuspendThread(h)
        c = Context()
        try:
            if k32.GetThreadContext(h, ctypes.c_void_p(c.addr)):
                rip, rsp = c.get(0xF8), c.get(0x98)
                chain = self.call_chain(rsp, 0x2000)[:depth]
                self.log(f"SAMPLE tid={tid} rip={self.describe(rip) if 0x140000000 <= rip < 0x142000000 else hex(rip)} "
                         + " <- ".join(f"{call:x}" for _, call, _ in chain))
        finally:
            k32.ResumeThread(h)
            k32.CloseHandle(h)

    def poll(self, fn, every=10.0):
        """Call fn(debugger) every `every` seconds while the game runs (memory reads only)."""
        self.pollers.append(fn)
        self.poll_every = every

    def q(self, a):
        d = self.read(a, 8)
        return struct.unpack("<Q", d)[0] if len(d) == 8 else 0

    def d32(self, a):
        d = self.read(a, 4)
        return struct.unpack("<I", d)[0] if len(d) == 4 else 0

    def log(self, *a):
        line = f"[{time.time() - self.t0:8.2f}] " + " ".join(str(x) for x in a)
        self.logf.write(line + "\n")

    # --- memory
    def read(self, a, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.hproc, ctypes.c_void_p(a), buf, n, ctypes.byref(got)):
            return b""
        return buf.raw[:got.value]

    def cstr(self, a, n=256):
        return self.read(a, n).split(b"\0")[0].decode("latin-1")

    def write(self, a, data):
        old = wt.DWORD()
        k32.VirtualProtectEx(self.hproc, ctypes.c_void_p(a), len(data), 0x40, ctypes.byref(old))
        got = ctypes.c_size_t()
        ok = k32.WriteProcessMemory(self.hproc, ctypes.c_void_p(a), data, len(data), ctypes.byref(got))
        k32.VirtualProtectEx(self.hproc, ctypes.c_void_p(a), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(self.hproc, ctypes.c_void_p(a), len(data))
        return ok

    def alloc(self, n):
        return k32.VirtualAllocEx(self.hproc, None, n, 0x3000, 0x40)

    # --- registration
    def bp(self, addr, handler):
        self.bps[addr] = [None, handler]
        if self.hproc:
            self._arm(addr)

    def patch(self, addr, data):
        self.patches.append((addr, bytes(data)))

    def threads(self):
        """Thread ids of the game process (Toolhelp snapshot)."""
        class THREADENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                        ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG),
                        ("dwFlags", wt.DWORD)]
        k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        snap = k32.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        te = THREADENTRY32()
        te.dwSize = ctypes.sizeof(te)
        out = []
        ok = k32.Thread32First(wt.HANDLE(snap), ctypes.byref(te))
        while ok:
            if te.th32OwnerProcessID == self.pid:
                out.append(te.th32ThreadID)
            ok = k32.Thread32Next(wt.HANDLE(snap), ctypes.byref(te))
        k32.CloseHandle(wt.HANDLE(snap))
        return out

    def watch_all(self, addr, size=4, rw="w", hits=16):
        """watch() on every thread of the game (a reference count may change on any of them)."""
        for tid in self.threads():
            self.watch(addr, size, rw, hits, tid)
        self.log(f"WATCH set on all threads")

    def watch(self, addr, size=4, rw="rw", hits=8, tid=None):
        """Hardware watchpoint (DR0) on the main thread: log rip + call chain on the first `hits` accesses."""
        tid = tid or self.main_tid
        self.watch_addr = addr
        h, c = self.ctx(tid)
        c.set(0x48, addr)                       # Dr0
        rwbits = {"w": 1, "rw": 3}[rw]
        lenbits = {1: 0, 2: 1, 4: 3, 8: 2}[size]
        dr7 = c.get(0x70) & ~0xF000F
        dr7 |= 1 | (rwbits << 16) | (lenbits << 18)
        c.set(0x70, dr7)                        # Dr7
        c.set(0x30, CONTEXT_FULL | 0x10, "<I")  # CONTEXT_DEBUG_REGISTERS
        self.setctx(h, c)
        k32.CloseHandle(h)
        self.watch_left = hits
        self.watch_seen = set()
        self.log(f"WATCH {addr:#x} size {size} {rw} on tid {tid}")

    def _watch_hit(self, tid):
        h, c = self.ctx(tid)
        rip = c.get(0xF8)
        chain = " <- ".join(f"{call:x}" for _, call, _ in self.call_chain(c.get(0x98), 0x800)[:8])
        if self.watch_left > 0 and (rip, chain) not in self.watch_seen:  # same code reached from elsewhere counts
            self.watch_seen.add((rip, chain))
            now = int.from_bytes(self.read(self.watch_addr, 4), "little")
            self.log(f"WATCH hit tid={tid} value={now} at "
                     f"{self.describe(rip) if 0x140000000 <= rip < 0x142000000 else hex(rip)} {chain}")
            self.watch_left -= 1
        c.set(0x68, 0)  # clear Dr6 status
        if self.watch_left <= 0:
            c.set(0x70, c.get(0x70) & ~0xF000F)
            c.set(0x30, CONTEXT_FULL | 0x10, "<I")
            self.log("WATCH done")
        self.setctx(h, c)
        k32.CloseHandle(h)

    def rtti(self, obj):
        """MSVC x64 RTTI class name of an object (via vtable[-1] -> complete object locator), or None."""
        vt = self.q(obj)
        if not (0x140000000 <= vt < 0x142000000):
            return None
        col = self.q(vt - 8)
        if not (0x140000000 <= col < 0x142000000) or self.d32(col) != 1:
            return None
        td = 0x140000000 + self.d32(col + 12)
        return self.cstr(td + 16, 128)

    def _cpp_exception(self, ev, tid, first):
        """Log the thrown C++ type (MSVC x64 ThrowInfo) and where it was thrown from."""
        nparams = struct.unpack_from("<I", ev, 40)[0]
        info = struct.unpack_from("<4Q", ev, 48) if nparams >= 4 else (0, 0, 0, 0)
        throw_info, image = info[2], info[3]
        name = "?"
        try:
            cta_rva = self.d32(throw_info + 12)
            n = self.d32(image + cta_rva)
            ct_rva = self.d32(image + cta_rva + 4)
            td_rva = self.d32(image + ct_rva + 4)
            name = self.cstr(image + td_rva + 16, 128)
            if n > 1:
                name += f" (+{n - 1} bases)"
        except Exception:
            pass
        key = (name, first)
        self.cpp_seen = getattr(self, "cpp_seen", {})
        self.cpp_seen[key] = self.cpp_seen.get(key, 0) + 1
        if self.cpp_seen[key] > 3:
            return
        self.log(f"C++ EXCEPTION {name} first={first}")
        h, c = self.ctx(tid)
        for i, call, op in self.call_chain(c.get(0x98), 0x1800)[:14]:
            self.log(f"  stack+{i:x}: call at {self.describe(call)} -> {op}")
        k32.CloseHandle(h)

    def bp_export(self, dll, name, handler):
        """Breakpoint on an exported function of a DLL, armed when the DLL loads."""
        self.export_bps.append((dll.lower(), name, handler))

    def _on_dll(self, hfile, base):
        if not self.export_bps:
            return
        buf = ctypes.create_unicode_buffer(520)
        k32.GetFinalPathNameByHandleW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD]
        if not hfile or not k32.GetFinalPathNameByHandleW(wt.HANDLE(hfile), buf, 520, 0):
            return
        path = buf.value.replace("\\\\?\\", "")
        fname = os.path.basename(path).lower()
        wanted = [(n, h) for d, n, h in self.export_bps if d == fname]
        if not wanted:
            return
        import pefile
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        exports = {e.name.decode(): e.address for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
        for n, h in wanted:
            if n in exports:
                self.bp(base + exports[n], h)
                self.log(f"armed {fname}!{n} at {base + exports[n]:#x}")

    def on_crash(self, fn):
        self.crash_handlers.append(fn)

    def on_start(self, fn):
        self.start_handlers.append(fn)

    def _arm(self, addr):
        orig = self.read(addr, 1)
        if not orig:
            self.log(f"cannot arm {addr:#x}")
            return
        if self.bps[addr][0] is None:
            self.bps[addr][0] = orig
        self.write(addr, b"\xcc")

    # --- threads
    def ctx(self, tid):
        h = k32.OpenThread(0x1FFFFF, False, tid)
        c = Context()
        if not k32.GetThreadContext(h, ctypes.c_void_p(c.addr)):
            self.log("GetThreadContext failed", ctypes.get_last_error())
        return h, c

    def setctx(self, h, c):
        if not k32.SetThreadContext(h, ctypes.c_void_p(c.addr)):
            self.log("SetThreadContext failed", ctypes.get_last_error())

    def describe(self, va):
        if self.idx is None:
            import idx
            self.idx = idx
        p = self.idx.owner(va)
        return f"{va:x} (fn {self.idx.primary(va):#x})" if p else f"{va:x}"

    def call_chain(self, rsp, depth=0x1000):
        """Return addresses on the stack that follow a call instruction."""
        if self.idx is None:
            import idx
            self.idx = idx
        # A large read can cross the committed stack boundary and lose all frames.
        chunks = []
        address = rsp
        remaining = depth
        while remaining > 0:
            size = min(remaining, 0x1000 - (address & 0xfff))
            chunk = self.read(address, size)
            chunks.append(chunk)
            if len(chunk) != size:
                break
            address += size
            remaining -= size
        data = b''.join(chunks)
        out = []
        for i in range(0, len(data) - 7, 8):
            v = struct.unpack_from("<Q", data, i)[0]
            if not (0x140001000 <= v < 0x142000000):
                continue
            for back in (5, 6, 2, 3, 7):
                ins = next(self.idx.md.disasm_lite(self.idx.read(v - back, back), v - back), None)
                if ins and ins[1] == back and ins[2] == "call":
                    out.append((i, v - back, ins[3]))
                    break
        return out

    def dump_crash(self, tid, code, addr, first):
        h, c = self.ctx(tid)
        regs = {r: c.get(c.reg_off(r)) for r in REGS + ["rip"]}
        self.log(f"EXCEPTION {code:08X} at {self.describe(addr)} first={first}")
        self.log("  " + " ".join(f"{k}={v:X}" for k, v in regs.items()))
        for r, v in regs.items():
            s = self.read(v, 64) if v > 0x10000 else b""
            if len(s) >= 4 and all(32 <= ch < 127 for ch in s[:4]):
                self.log(f"  {r} -> {s.split(b'\0')[0][:64]!r}")
            elif len(s) >= 8:
                name = self.rtti(v)
                if name:
                    self.log(f"  {r} -> object {name}")
        for i, call, op in self.call_chain(regs["rsp"], 0x20000)[:30]:
            self.log(f"  stack+{i:x}: call at {self.describe(call)} -> {op}")
        for fn in self.crash_handlers:
            try:
                fn(self, tid, c, code, addr)
            except Exception:
                self.log(traceback.format_exc())
        k32.CloseHandle(h)

    # --- main loop
    def start_shots(self, every=10.0, scale=0.34):
        """Background thread: save a screenshot of the game window every `every` seconds."""
        import threading
        import shot
        outdir = pathlib.Path(self.logf.name).with_suffix("")
        outdir = outdir.parent / (outdir.name + "-shots")
        outdir.mkdir(exist_ok=True)
        for old in outdir.glob("*.png"):
            old.unlink()

        def loop():
            import subprocess
            while self.pid and not getattr(self, "exited", False):
                time.sleep(every)
                p = outdir / f"{int(time.time() - self.t0):04d}.png"
                try:  # separate process: PrintWindow can block on a busy game window
                    subprocess.run([sys.executable, "-I", str(HERE / "shot.py"), str(self.pid), str(p), str(scale)],
                                   timeout=15, capture_output=True)
                except Exception as e:
                    self.log("shot failed", e)

        threading.Thread(target=loop, daemon=True).start()

    def run(self, seconds, args=""):
        si = STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        env = os.environ.copy()
        env["SteamAppId"] = "258160"
        env["SteamGameId"] = "258160"
        block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        envbuf = ctypes.create_unicode_buffer(block)
        cmd = ctypes.create_unicode_buffer(f'"{self.exe}" {args}'.strip())
        if not k32.CreateProcessW(str(self.exe), cmd, None, None, False, DEBUG_ONLY_THIS_PROCESS | 0x400,
                                  envbuf, str(self.exe.parent), ctypes.byref(si), ctypes.byref(pi)):
            raise OSError(ctypes.get_last_error(), "CreateProcess")
        self.hproc, self.pid = pi.hProcess, pi.dwProcessId
        self.log("PID", self.pid, self.exe)
        print("PID", self.pid, flush=True)
        ev = ctypes.create_string_buffer(256)
        deadline = time.time() + seconds
        exit_code = None
        next_poll = time.time() + self.poll_every if self.pollers else None
        while True:
            if next_poll and time.time() > next_poll:
                next_poll = time.time() + self.poll_every
                for fn in self.pollers:
                    try:
                        fn(self)
                    except Exception:
                        self.log("poll error\n" + traceback.format_exc())
            if time.time() > deadline or self.stop:
                self.log("time limit reached; terminating" if not self.stop else "stop requested; terminating")
                k32.TerminateProcess(self.hproc, 1)
                deadline = time.time() + 30
                self.stop = False
            if not k32.WaitForDebugEvent(ev, 200):
                continue
            kind, pid, tid = struct.unpack_from("<III", ev, 0)
            status = DBG_CONTINUE
            if kind == 3:  # CREATE_PROCESS
                self.main_tid = tid
                for a, data in self.patches:
                    self.write(a, data)
                for a in list(self.bps):
                    self._arm(a)
                for fn in self.start_handlers:
                    fn(self)
                self.log(f"process started; {len(self.patches)} runtime patches, {len(self.bps)} breakpoints")
            elif kind == 1:  # EXCEPTION
                code, flags = struct.unpack_from("<II", ev, 16)
                addr = struct.unpack_from("<Q", ev, 32)[0]
                first = struct.unpack_from("<I", ev, 168)[0]
                if code == EXCEPTION_BREAKPOINT and addr in self.bps:
                    status = self._hit(tid, addr)
                elif code == EXCEPTION_BREAKPOINT and not self.seen_initial_bp:
                    self.seen_initial_bp = True
                elif code == EXCEPTION_SINGLE_STEP and tid in self.rearm:
                    a = self.rearm.pop(tid)
                    if a in self.bps:
                        self.write(a, b"\xcc")
                elif code == EXCEPTION_SINGLE_STEP and getattr(self, "watch_addr", None) is not None:
                    self._watch_hit(tid)
                elif code == 0xE06D7363:
                    status = DBG_EXCEPTION_NOT_HANDLED
                    self._cpp_exception(ev, tid, first)
                else:
                    status = DBG_EXCEPTION_NOT_HANDLED
                    if code in (0xC0000005, 0xC0000094, 0xC00000FD, 0xC0000409, 0xC000001D) or not first:
                        self.dump_crash(tid, code, addr, first)
                    elif code not in (0xE06D7363, 0x406D1388, 0x40010006, 0x4001000A):
                        self.log(f"exception {code:08X} at {addr:x} first={first}")
            elif kind == 5:  # EXIT_PROCESS
                exit_code = struct.unpack_from("<I", ev, 16)[0]
                self.exited = True
                self.log(f"EXIT {exit_code:08X}")
                k32.ContinueDebugEvent(pid, tid, DBG_CONTINUE)
                break
            elif kind == 8:  # OUTPUT_DEBUG_STRING
                sa, wide, n = struct.unpack_from("<QHH", ev, 16)
                raw = self.read(sa, n * (2 if wide else 1))
                s = raw.decode("utf-16le" if wide else "cp932", "replace").rstrip("\0\r\n ")
                if s and "S_API WARN" not in s:
                    self.log("ODS:", s)
            elif kind == 6:  # LOAD_DLL
                hfile, base = struct.unpack_from("<QQ", ev, 16)
                self._on_dll(hfile, base)
                if hfile:
                    k32.CloseHandle(wt.HANDLE(hfile))
            k32.ContinueDebugEvent(pid, tid, status)
        return exit_code

    def _hit(self, tid, addr):
        h, c = self.ctx(tid)
        orig, handler = self.bps[addr]
        hit = Hit(self, tid, c, addr)
        result = None
        try:
            result = handler(hit)
        except Exception:
            self.log(f"handler error at {addr:#x}\n" + traceback.format_exc())
        redirected = c.get(0xF8) != addr + 1
        if result == "remove":
            del self.bps[addr]
            self.write(addr, orig)
            if not redirected:
                c.set(0xF8, addr)
        elif redirected:
            pass  # handler moved rip elsewhere; the int3 stays armed
        else:
            # execute the original instruction once, then re-arm on the single-step trap
            self.write(addr, orig)
            c.set(0xF8, addr)
            c.set(0x44, c.get(0x44, "<I") | 0x100, "<I")
            self.rearm[tid] = addr
        self.setctx(h, c)
        k32.CloseHandle(h)
        return DBG_CONTINUE


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--exe", default=str(paths.GAME_EXE))
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--log")
    ap.add_argument("--args", default="")
    ap.add_argument("--shots", type=float, default=0, help="screenshot every N seconds")
    ap.add_argument("--shot-scale", type=float, default=0.34)
    a = ap.parse_args()
    sess_path = pathlib.Path(a.session)
    if not sess_path.exists():
        sess_path = HERE / "sessions" / (a.session if a.session.endswith(".py") else a.session + ".py")
    spec = importlib.util.spec_from_file_location(sess_path.stem, sess_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (HERE / "logs").mkdir(exist_ok=True)
    log = a.log or str(HERE / "logs" / f"{sess_path.stem}.log")
    d = Debugger(a.exe, log)
    mod.setup(d)
    if a.shots:
        d.on_start(lambda dd: dd.start_shots(a.shots, a.shot_scale))
    code = d.run(a.seconds, a.args)
    print("exit", hex(code) if code is not None else None, "log", log)


if __name__ == "__main__":
    main()
