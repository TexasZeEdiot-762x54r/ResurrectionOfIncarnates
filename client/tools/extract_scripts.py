"""Write the loose script/preload files the patched client loads (listed in loose-scripts.txt) by unpacking them
from the game folder's own archives. Only file names are shipped; the data comes from the player's copy.

    python extract_scripts.py            # into paths.GAME_RES
    python extract_scripts.py --list     # (development) regenerate loose-scripts.txt from the current game folder
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gx  # noqa: E402
import paths  # noqa: E402

LIST = HERE / "loose-scripts.txt"


def make_list():
    root = paths.GAME_RES
    names = sorted(f.relative_to(root).as_posix() for f in root.rglob("*.unk")
                   if not (paths.STEAM_RES / f.relative_to(root)).exists())
    LIST.write_text("\n".join(names) + "\n")
    print(len(names), "names written to", LIST.name)


def extract():
    index = {}
    for n in range(1, 15):
        idx = gx.dat_index(n)
        for nh, th, i in gx.records(n):
            index[nh] = (n, idx[i])
    done = missing = 0
    for rel in LIST.read_text().split():
        hit = index.get(gx.name_hash(rel[:-4] if rel.endswith(".unk") else rel))
        if not hit:
            missing += 1
            print("not in the archives:", rel)
            continue
        n, (off, size) = hit
        with (paths.GAME_RES / f"GxArchivedFile{n:03d}.dat").open("rb") as h:
            h.seek(off)
            data = gx.unbilz(h.read(size))[1]
        out = paths.GAME_RES / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        done += 1
    print(f"extracted {done} script files ({missing} missing)")
    return missing == 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        make_list()
    else:
        sys.exit(0 if extract() else 1)
