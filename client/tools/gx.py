"""Read Rise of Incarnates GxArchived archives (masterWindows/GxArchivedTable*.csh + GxArchivedFile*.dat).

A .csh table is a 0x80-byte header plus a BILZ (zlib) blob. Near its end the blob holds 12-byte
big-endian records (name_hash, type_hash, index); index selects an (offset, size) pair in the
matching .dat (header: 'GDAT', count, then count x (u32 offset, u32 size)). Entries may themselves
be BILZ-compressed. name_hash = h=37; h = h*37 + byte, over the resource path (e.g. 'sound/se_group/SE_BATTLE').

    python gx.py inventory                   # writes claude/gx-inventory.json (all entries, names where known)
    python gx.py find <regex>                # known names matching regex
    python gx.py types                       # entry count per type hash (with guessed type names)
    python gx.py get <name|0xhash> <out>     # extract one entry (decompressed)
    python gx.py has <name> [<name> ...]     # is this exact path in the archives?
"""
import json
import pathlib
import re
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

RES = paths.GAME_RES
EXE = paths.STEAM_EXE
INV = HERE / "gx-inventory.json"
NAMES = HERE / "gx-names.json"


def unbilz(b):
    i = b.find(b"BILZ")
    if 0 <= i < 256:
        try:
            return b[:i], zlib.decompress(b[i + 16:])
        except zlib.error:
            pass
    return b"", b


def name_hash(s):
    h = 37
    for c in s.encode() if isinstance(s, str) else s:
        h = (h * 37 + c) & 0xFFFFFFFF
    return h


def table_blob(n):
    return unbilz((RES / f"GxArchivedTable{n:03d}.csh").read_bytes())[1]


def records(n):
    """(name_hash, type_hash, index) triples of table n: the longest run with index 0,1,2,..."""
    b = table_blob(n)
    best = []
    for start in range(0, len(b) - 12, 4):
        if struct.unpack_from(">I", b, start + 8)[0] != 0:
            continue
        run = []
        p = start
        while p + 12 <= len(b) and struct.unpack_from(">I", b, p + 8)[0] == len(run):
            run.append(struct.unpack_from(">III", b, p))
            p += 12
        if len(run) > len(best):
            best = run
    return best


def dat_index(n):
    with (RES / f"GxArchivedFile{n:03d}.dat").open("rb") as h:
        sig, count = struct.unpack("<4sI", h.read(8))
        assert sig == b"GDAT", sig
        return [struct.unpack_from("<II", h.read(8)) for _ in range(count)]


def candidate_strings():
    blobs = [EXE.read_bytes()]
    scripts = HERE.parent / "backup-scripts"
    blobs += [p.read_bytes() for p in scripts.glob("*.nut")]
    extra = HERE / "extracted"
    if extra.exists():
        blobs += [p.read_bytes() for p in extra.rglob("*") if p.is_file() and p.stat().st_size < 4_000_000]
    seen = set()
    for b in blobs:
        for m in re.finditer(rb"[A-Za-z0-9_./%-]{3,160}", b):
            seen.add(m.group().decode())
    return seen


def expand(strings):
    out = set()
    tokens = {s for s in strings if re.fullmatch(r"[A-Za-z0-9_]{3,64}", s)}
    for s in strings:
        out.add(s)
        out.add(s.strip("/"))
        if s.endswith((".nut", ".cnut")):
            out.add(s.rsplit(".", 1)[0])
    for t in tokens:
        if t.startswith(("SE_", "VO_", "BGM", "se_", "vo_")):
            out.add("sound/se_group/" + t)
            out.add("sound/voice/" + t)
            out.add("sound/" + t)
    return out


def inventory():
    known = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    cands = expand(candidate_strings())
    hashes = {}
    for s in cands:
        hashes.setdefault(name_hash(s), s)
    entries = []
    for n in range(1, 15):
        idx = dat_index(n)
        for nh, th, i in records(n):
            name = known.get(f"{nh:#010x}") or hashes.get(nh)
            off, size = idx[i]
            entries.append(dict(table=n, index=i, hash=f"{nh:#010x}", type=f"{th:#010x}", off=off, size=size, name=name))
    INV.write_text(json.dumps(entries, indent=1))
    named = sum(1 for e in entries if e["name"])
    print(f"{len(entries)} entries, {named} named -> {INV}")


def load():
    if not INV.exists():
        inventory()
    return json.loads(INV.read_text())


def extract(e):
    with (RES / f"GxArchivedFile{e['table']:03d}.dat").open("rb") as h:
        h.seek(e["off"])
        raw = h.read(e["size"])
    return unbilz(raw)[1]


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "inventory":
        inventory()
    elif cmd == "find":
        rx = re.compile(args[0], re.I)
        for e in load():
            if e["name"] and rx.search(e["name"]):
                print(f"{e['name']}  [{e['table']}:{e['index']} {e['type']} {e['size']}]")
    elif cmd == "types":
        from collections import Counter
        inv = load()
        c = Counter(e["type"] for e in inv)
        named = Counter(e["type"] for e in inv if e["name"])
        for t, k in c.most_common():
            ex = next((e["name"] for e in inv if e["type"] == t and e["name"]), "")
            print(f"{t} {k:6} named {named[t]:5}  e.g. {ex}")
    elif cmd == "get":
        key = args[0]
        inv = load()
        h = key if key.startswith("0x") else f"{name_hash(key):#010x}"
        e = next(e for e in inv if e["hash"] == h)
        pathlib.Path(args[1]).write_bytes(extract(e))
        print("wrote", args[1], e)
    elif cmd == "has":
        inv = {e["hash"]: e for e in load()}
        for s in args:
            e = inv.get(f"{name_hash(s):#010x}")
            print(s, "->", f"[{e['table']}:{e['index']} {e['type']} {e['size']}]" if e else "absent")


if __name__ == "__main__":
    main()
