"""Copy chosen archive entries from the Steam install (shutdown build, matches roi.exe) into the test install.

The entry bytes are appended to the test install's GxArchivedFileNNN.dat and the entry's (offset, size) slot is
pointed at them. Before the first change the original index and file length are saved in overlay-backup/;
`restore` writes them back and cuts off the appended bytes. `apply` restores first, so it can be rerun.

    python overlay.py apply [name ...]   # default: OVERLAY
    python overlay.py restore
"""
import json
import pathlib
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gx  # noqa: E402

import paths  # noqa: E402

STEAM = paths.STEAM_RES
TEST = gx.RES
BACKUP = HERE / "overlay-backup"
# The depot's SubCharaData lacks the support-lamina entries (LoaShot, IfreShot, Loa hand, Dull head) that the
# shutdown exe asks for; a missing one is an empty name and crashes the battle.
SHELL_TABLES = [
    "plcm", "01Mephi", "02Ares", "03Zeus", "04Lilith", "05Fen", "06Utsu",
    "07Grim", "07Zombie", "08Efr", "09_Brun", "10_Odin", "13_Slay",
    "14_Kali", "20_Ra", "21_Rdd", "Lamina",
]
# The shutdown executable reads columns 102 and 103, absent in the old depot.
OVERLAY = ["actor/subcharacter/data/SubCharaData"] + [
    "shell/data/ShellDataList_" + name for name in SHELL_TABLES
]


def validate_source(name, blob):
    if not name.startswith("shell/data/ShellDataList_"):
        return
    data = gx.unbilz(blob)[1]
    if len(data) < 12:
        raise ValueError(f"Truncated shell table: {name}")
    columns, rows = struct.unpack_from(">II", data, 4)
    if columns != 104 or not 1 <= rows <= 4096 or len(data) < 12 + rows * columns * 8:
        raise ValueError(f"Incompatible shell table {name}: {columns} columns, {rows} rows")


def entries(root):
    gx.RES = root
    out = {}
    for n in range(1, 15):
        idx = gx.dat_index(n)
        for nh, th, i in gx.records(n):
            out[nh] = (n, i, idx[i])
    gx.RES = TEST
    return out


def dat(n):
    return TEST / f"GxArchivedFile{n:03d}.dat"


def restore():
    state = BACKUP / "state.json"
    if not state.exists():
        return
    for n, length in json.loads(state.read_text()).items():
        n = int(n)
        head = (BACKUP / f"GxArchivedFile{n:03d}.idx").read_bytes()
        with dat(n).open("r+b") as h:
            h.write(head)
            h.truncate(length)
        print(f"restored table {n}: index and length {length}")
    state.unlink()


def bilz(template, data):
    """Re-pack `data` like the archive entry `template` (128-byte prefix, BILZ, BE unpacked/packed size, flag)."""
    import zlib
    i = template.find(b"BILZ")
    z = zlib.compress(data, 9)
    flag = template[i + 12:i + 16]
    return template[:i] + b"BILZ" + struct.pack(">II", len(data), len(z)) + flag + z


def custom_blob(name, test):
    """Replacement bytes for CUSTOM entries (experiments that are not copies from the Steam install)."""
    n, i, (off, size) = test[gx.name_hash(name)]
    with dat(n).open("rb") as h:
        h.seek(off)
        orig = h.read(size)
    return bilz(orig, CUSTOM[name](gx.unbilz(orig)[1]))


# Experiments: name -> function(original unpacked bytes) -> new unpacked bytes.
# (Tried: BG_w, the 4x4 white Briefing texture, made transparent -> the Briefing panels stayed white.)
CUSTOM = {}


def apply(names):
    names = list(names)
    # Validate every donor before restore() changes any existing archive.
    steam = entries(STEAM)
    for name in names:
        if name in CUSTOM:
            continue
        sn, si, (soff, ssize) = steam[gx.name_hash(name)]
        with (STEAM / f"GxArchivedFile{sn:03d}.dat").open("rb") as h:
            h.seek(soff)
            validate_source(name, h.read(ssize))
    restore()
    steam, test = entries(STEAM), entries(TEST)
    BACKUP.mkdir(exist_ok=True)
    state = {}
    for name in names + list(CUSTOM):
        nh = gx.name_hash(name)
        tn, ti, _ = test[nh]
        if name in CUSTOM:
            blob = custom_blob(name, test)
            sn, si, ssize = "custom", "-", len(blob)
        else:
            sn, si, (soff, ssize) = steam[nh]
            with (STEAM / f"GxArchivedFile{sn:03d}.dat").open("rb") as h:
                h.seek(soff)
                blob = h.read(ssize)
        path = dat(tn)
        if tn not in state:
            with path.open("rb") as h:
                count = struct.unpack("<4sI", h.read(8))[1]
                h.seek(0)
                (BACKUP / f"GxArchivedFile{tn:03d}.idx").write_bytes(h.read(8 + 8 * count))
            state[tn] = path.stat().st_size
            (BACKUP / "state.json").write_text(json.dumps(state))
        with path.open("r+b") as h:
            h.seek(0, 2)
            off = (h.tell() + 15) & ~15
            h.seek(off)
            h.write(blob)
            h.seek(8 + 8 * ti)
            h.write(struct.pack("<II", off, len(blob)))
        print(f"{name}: steam table {sn}#{si} ({ssize} bytes) -> test table {tn}#{ti} at {off:#x}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["restore"]:
        restore()
    else:
        apply(sys.argv[2:] or OVERLAY)
