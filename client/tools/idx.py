"""Cached static index of roi.exe (the shutdown build that the offline patch is applied to).

    python idx.py build                       # disassemble once, cache xrefs (claude/roi-index.pkl)
    python idx.py fn <va> [<va> ...]          # annotated disassembly of the function(s) containing va
    python idx.py refs <va> [<va> ...]        # code that calls/jumps to or rip-references va
    python idx.py str <regex>                 # strings matching regex, with the code that references them
    python idx.py stack <crashlog> [n]        # map return-address candidates of exception n to call sites
    python idx.py owner <va> [...]            # function start/end for va

Addresses are hex with or without 0x.
"""
import bisect
import pathlib
import json
import re
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

sys.path.insert(0, str(paths.LIBS))
import capstone  # noqa: E402
import pefile  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EXE = paths.STEAM_EXE
CACHE = HERE / "roi-index.json"
RIP = re.compile(r"\[rip ([+-]) (0x[0-9a-f]+)\]")

data = EXE.read_bytes()
pe = pefile.PE(data=data, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXCEPTION"],
                                       pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
BASE = pe.OPTIONAL_HEADER.ImageBase
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.skipdata = True
funcs = sorted({(BASE + e.struct.BeginAddress, BASE + e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION})
starts = [f[0] for f in funcs]
imports = {}
for imp in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    for x in imp.imports:
        imports[x.address] = f"{imp.dll.decode()}!{x.name.decode() if x.name else x.ordinal}"


def owner(va):
    i = bisect.bisect_right(starts, va) - 1
    if i >= 0 and va < funcs[i][1]:
        return funcs[i]
    return None


unwind_of = {BASE + e.struct.BeginAddress: e.struct.UnwindData for e in pe.DIRECTORY_ENTRY_EXCEPTION}


def parent_chunk(start):
    """Begin VA of the chunk this chunk's unwind info chains to (UNW_FLAG_CHAININFO), or None."""
    rva = unwind_of.get(start)
    if rva is None:
        return None
    u = pe.get_data(rva, 4)
    if not (u[0] >> 3) & 4:
        return None
    n = u[2] + (u[2] & 1)
    begin = struct.unpack("<I", pe.get_data(rva + 4 + 2 * n, 4))[0]
    return BASE + begin


def primary(va):
    f = owner(va)
    if not f:
        return None
    s = f[0]
    while (p := parent_chunk(s)) is not None and p != s:
        s = p
    return s


_chunks = None


def chunks_of(root):
    global _chunks
    if _chunks is None:
        _chunks = {}
        for f in funcs:
            _chunks.setdefault(primary(f[0]), []).append(f)
    return sorted(_chunks.get(root, []))


def read(va, n):
    try:
        return pe.get_data(va - BASE, n)
    except Exception:
        return b""


def cstr(va):
    raw = read(va, 160).split(b"\0")[0]
    if len(raw) >= 3 and all(32 <= c < 127 for c in raw):
        return raw.decode()
    # UTF-16LE
    raw = read(va, 240)
    chars = []
    for i in range(0, len(raw) - 1, 2):
        c = raw[i] | raw[i + 1] << 8
        if c == 0:
            break
        if not (32 <= c < 127):
            return None
        chars.append(chr(c))
    return "L" + "".join(chars) if len(chars) >= 3 else None


def code_ranges():
    for sec in pe.sections:
        if sec.Characteristics & 0x20000000:
            yield BASE + sec.VirtualAddress, sec.get_data()


def build():
    refs = {}
    n = 0
    for start, blob in code_ranges():
        for addr, size, mn, op in md.disasm_lite(blob, start):
            n += 1
            tgt = None
            if mn in ("call", "jmp") or (mn.startswith("j") and op.startswith("0x")):
                if op.startswith("0x"):
                    tgt = int(op, 16)
            m = RIP.search(op)
            if m:
                tgt = addr + size + int(m[2], 16) * (1 if m[1] == "+" else -1)
            if tgt is not None:
                refs.setdefault(tgt, []).append(addr)
            elif mn in ("mov", "lea", "cmp", "push") and "0x14" in op:
                for imm in re.findall(r"0x14[0-9a-f]{7}\b", op):
                    refs.setdefault(int(imm, 16), []).append(addr)
    CACHE.write_text(json.dumps(refs, separators=(",", ":")), encoding="utf-8")
    print(f"indexed {n} instructions, {len(refs)} targets -> {CACHE}")


def load():
    if not CACHE.exists():
        build()
    return {int(key): value for key, value in json.loads(CACHE.read_text(encoding="utf-8")).items()}


def note_for(addr, size, mn, op):
    notes = []
    m = RIP.search(op)
    tgt = None
    if m:
        tgt = addr + size + int(m[2], 16) * (1 if m[1] == "+" else -1)
    elif op.startswith("0x") and mn.startswith(("call", "j")):
        tgt = int(op, 16)
    if tgt is not None:
        notes.append(hex(tgt))
        if tgt in imports:
            notes.append(imports[tgt])
        else:
            s = cstr(tgt)
            if s:
                notes.append(repr(s))
    return "  ; " + " ".join(notes) if notes else ""


def disasm_fn(va, whole=True):
    root = primary(va) if whole else None
    parts = chunks_of(root) if root else [owner(va) or (va, va + 0x100)]
    print(f"FUNCTION {parts[0][0]:#x} ({len(parts)} chunk{'s' if len(parts) > 1 else ''})")
    for f in parts:
        if len(parts) > 1:
            print(f" -- chunk {f[0]:#x}-{f[1]:#x}")
        for addr, size, mn, op in md.disasm_lite(read(f[0], f[1] - f[0]), f[0]):
            mark = ">" if addr == va else " "
            print(f"{mark}{addr:x} {mn} {op}{note_for(addr, size, mn, op)}")


def show_refs(refs, va):
    hits = refs.get(va, [])
    print(f"REFS to {va:#x} ({len(hits)})")
    for a in hits:
        insn = next(md.disasm_lite(read(a, 16), a), None)
        f = owner(a)
        print(f"  {a:x} in {f[0]:#x} : {insn[2]} {insn[3]}" if f else f"  {a:x} : {insn[2]} {insn[3]}")


def find_strings(refs, pattern):
    rx = re.compile(pattern.encode())
    for sec in pe.sections:
        if sec.Characteristics & 0x20000000:
            continue
        blob = sec.get_data()
        for m in re.finditer(rb"[ -~]{3,}", blob):
            if rx.search(m.group()):
                va = BASE + sec.VirtualAddress + m.start()
                print(f"{va:#x} {m.group()[:120].decode()!r}")
                for a in refs.get(va, [])[:12]:
                    f = owner(a)
                    print(f"    ref {a:x} in {f[0]:#x}" if f else f"    ref {a:x}")


def stack(path, n):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    blocks = [i for i, l in enumerate(lines) if l.startswith("Exception ")]
    i = blocks[n]
    print(lines[i])
    for line in lines[i + 1:]:
        if line.startswith(("Exception ", "Exit=")):
            break
        m = re.match(r"^(?:stack|caller)\+([0-9A-F]+)=([0-9A-F]+)$", line)
        if not m:
            if re.match(r"^rip=", line):
                print("  rip", line[4:], "in", hex(owner(int(line[4:], 16))[0]) if owner(int(line[4:], 16)) else "?")
            continue
        v = int(m[2], 16)
        if not (0x140001000 <= v < 0x142000000):
            continue
        # a return address follows a call instruction
        for back in (5, 6, 2, 3, 7):
            insn = next(md.disasm_lite(read(v - back, back), v - back), None)
            if insn and insn[1] == back and insn[2] == "call":
                f = owner(v - back)
                print(f"  stack+{m[1]}: call at {v - back:x} ({insn[3]}{note_for(insn[0], insn[1], insn[2], insn[3])}) in fn {f[0]:#x}" if f else f"  stack+{m[1]}: call at {v - back:x}")
                break


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "build":
        build()
    elif cmd == "fn":
        for a in args:
            disasm_fn(int(a, 16))
    elif cmd == "refs":
        refs = load()
        for a in args:
            show_refs(refs, int(a, 16))
    elif cmd == "str":
        find_strings(load(), args[0])
    elif cmd == "stack":
        stack(args[0], int(args[1]) if len(args) > 1 else 0)
    elif cmd == "owner":
        for a in args:
            f = owner(int(a, 16))
            p = primary(int(a, 16))
            print(a, f and (hex(f[0]), hex(f[1])), "primary", p and hex(p))
    elif cmd == "svkeys":  # every sv_* protocol key, with the functions that use it
        refs = load()
        for sec in pe.sections:
            if sec.Characteristics & 0x20000000:
                continue
            blob = sec.get_data()
            for m in re.finditer(rb'(?<![A-Za-z0-9_])"?sv_[A-Za-z0-9_]+"?[:"]*', blob):
                va = BASE + sec.VirtualAddress + m.start()
                users = sorted({hex(primary(a) or a) for a in refs.get(va, [])})
                print(f"{va:#x} {m.group().decode():40} {' '.join(users)}")
    elif cmd == "disp":  # instructions using a displacement/immediate in [lo, hi]
        lo, hi = int(args[0], 16), int(args[1], 16)
        rx = re.compile(r"0x[0-9a-f]+")
        for start, blob in code_ranges():
            for addr, size, mn, op in md.disasm_lite(blob, start):
                if "rip" in op:
                    continue
                for v in rx.findall(op):
                    x = int(v, 16)
                    if lo <= x <= hi:
                        p = primary(addr)
                        print(f"{addr:x} (fn {p and hex(p)}) {mn} {op}")
                        break
    elif cmd == "ptr":  # where a VA is stored as a qword in data (vtables, function tables)
        for a in args:
            v = struct.pack("<Q", int(a, 16))
            for sec in pe.sections:
                blob = sec.get_data()
                i = blob.find(v)
                while i >= 0:
                    if i % 8 == 0:
                        va = BASE + sec.VirtualAddress + i
                        refs = load()
                        # find the start of the table: walk back over code pointers
                        t = va
                        while True:
                            prev = struct.unpack("<Q", read(t - 8, 8))[0]
                            if 0x140001000 <= prev < 0x140f00000:
                                t -= 8
                            else:
                                break
                        users = [hex(x) for x in refs.get(t, [])[:8]]
                        print(f"{a} stored at {va:#x} (slot {(va - t) // 8} of table {t:#x}; table used by {users})")
                    i = blob.find(v, i + 1)
    elif cmd == "chunk":  # only the pdata chunk containing va
        for a in args:
            disasm_fn(int(a, 16), whole=False)


if __name__ == "__main__":
    main()
