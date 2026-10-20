"""Pick a picture for every Customize item (sv_thumbnails, loaded as "hud/sequence/store/TEX/Thumbnail/<value>").

    python customize_thumbs.py write    # -> customize-thumb-plan.json, read by roi_custom (run by setup.ps1)

What's used: the game's own shop pictures under their original names (real_name / name_plan): Skin/, Head/,
Weapon/ and Accesary/ + the model name. Found from a live request log of the main menu
("Skin/cus_01mephi_cos_parts000_t01"), the other folders solved from the picture hashes below. Confirmed in
game 2026-10-18. Archive entries we insert ourselves are NOT shown by the client (it got the same resource
back for every such name), which is why archive_insert.py is no longer part of setup.

How the pictures were found and mapped before the names were known (portraits(); kept because it is how the
names were verified -- 1377 of 1409 agree, the rest were a base-number guess the real names corrected):
table 6 holds the original Customize thumbnails
(508x356, the character wearing the item), all unnamed. Their names mirror our model names (they end in
"<model>_t<tex:02d>"), and the archive is sorted by name, category block first, then character in id order.
For names sharing a prefix the rolling hash h = C + sum(char * 37^pos), so the base-37 digits of the hash
delta between neighbours say which trailing characters changed: +37^4 is the next model, +1 the next
texture, (+9, x) at the tens/ones positions is texture 9x. That lets us rebuild (model, texture) for every
entry without knowing a single name. Per-character model counts in each block match ours exactly
(head 6,6,6,6,4,5,6,4,6,4,4,5,4,4 etc). Accessories come in pairs: variant 0 = the item alone (640x448),
variant 1 = worn (508x356); body accessories then head accessories per character, Odin has 16 body only.

Source 2 (fallback) -- the item's own diffuse texture: every model's GxResMaterial (type 0x5e12de0d, same
hash as the model path) names the "_col" texture it binds.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gx  # noqa: E402
import roi_data  # noqa: E402
import roi_custom  # noqa: E402

PREFIX = "hud/sequence/store/TEX/Thumbnail/"
TEXTURE_TYPE = "0xfc397bb3"
MATERIAL_TYPE = "0x5e12de0d"
COL_RE = re.compile(rb"[ -~]{8,}")
PRIORITY = ["jkt", "shirt", "down", "coat", "body", "all", "wepA", "arm", "belt", "saya", "hair", "skin", "eyeref"]

CHAR_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 20, 21]
PORTRAIT_TABLE = 6
# hash of the first entry of each category block (shipped data), and how many prefix groups it has
BLOCKS = {"acce": (0x8ec30c6c, 27), "head": (0xc4116534, 14), "cos": (0x39be05fe, 28), "weap": (0x020ff567, 14)}


def _b37(delta, n=7):
    d = delta % (1 << 32)
    if d >= 1 << 31:
        d -= 1 << 32
    out = []
    for _ in range(n):
        r = d % 37
        if r > 18:
            r -= 37
        out.append(r)
        d = (d - r) // 37
    return out[::-1], d


def _groups(entries, start_pos, count):
    """Split table entries from start_pos into `count` same-prefix groups -> [[(coords, entry), ...], ...]."""
    groups, cur, prev = [], None, None
    pos = start_pos
    while pos < len(entries):
        e = entries[pos]
        h = int(e["hash"], 16)
        same = False
        if cur is not None:
            digits, rest = _b37(h - prev)
            if rest == 0 and digits[0] == 0 and digits[1] == 0 and all(abs(x) <= 10 for x in digits):
                cur.append(([a + b for a, b in zip(cur[-1][0], digits)], e))
                same = True
        if not same:
            if len(groups) == count:
                break
            cur = [([0] * 7, e)]
            groups.append(cur)
        prev = h
        pos += 1
    return groups if len(groups) == count else None


def _model_tex(group, model=None):
    """(model, texture) -> entry for a model/texture group (coords p5 = model digit, p2p1 = texture)."""
    tex_rel = [c[5] * 10 + c[6] for c, _ in group]
    base = -min(tex_rel)
    out = {}
    for (c, e), tr in zip(group, tex_rel):
        out[(model if model is not None else c[1] * 10 + c[2], tr + base)] = e
    return out


def portraits():
    """{(cid, category, model, texture): entry} from the game's own shop portraits, or {} if not found."""
    inv = gx.load()
    t6 = sorted((e for e in inv if e["table"] == PORTRAIT_TABLE), key=lambda e: e["index"])
    pos = {int(e["hash"], 16): i for i, e in enumerate(t6)}
    blocks = {}
    for name, (anchor, count) in BLOCKS.items():
        if anchor not in pos:
            return {}
        g = _groups(t6, pos[anchor], count)
        if g is None:
            return {}
        blocks[name] = g
    out = {}
    acce = iter(blocks["acce"])
    for cid in CHAR_ORDER:
        parts = roi_custom.parts(cid)
        for key, offset in (("acce", 0), ("headacce", 500)):
            if key == "headacce" and not parts.get("headacce"):
                continue
            group = next(acce)
            item0 = group[0][0]
            for c, e in group:
                item = 1 + (c[2] - item0[2]) * 10 + (c[3] - item0[3])
                if c[6] - item0[6] == 1:  # variant 1: the item worn on the character (508x356)
                    out[(cid, roi_custom.ACCESSORY, offset + item, 0)] = e
    for i, cid in enumerate(CHAR_ORDER):
        for (m, t), e in _model_tex(blocks["head"][i]).items():
            out[(cid, roi_custom.HEAD, m, t)] = e
        for (m, t), e in _model_tex(blocks["cos"][2 * i]).items():
            out[(cid, roi_custom.COSTUME, m, t)] = e
        for (m, t), e in _model_tex(blocks["cos"][2 * i + 1], model=100).items():
            out[(cid, roi_custom.COSTUME, m, t)] = e
        for (m, t), e in _model_tex(blocks["weap"][i]).items():
            out[(cid, roi_custom.WEAPON, m, t)] = e
    return out


def _base_name(cid, category, model, texture):
    folder, token, se, vo = roi_data.CHARACTERS[cid]
    if category == roi_custom.HEAD:
        return f"actor/player/{folder}/model/cus/head/cus_{token}_head_all{model:03d}_t{texture:02d}"
    if category == roi_custom.COSTUME:
        return f"actor/player/{folder}/model/cus/cos/cus_{token}_cos_parts{model:03d}_t{texture:02d}"
    if category == roi_custom.WEAPON:
        return f"actor/player/{folder}/model/cus/weap/cus_{token}_weap_all{model:03d}_t{texture:02d}_wepA"
    if category == roi_custom.ACCESSORY:
        if model >= 500:
            return f"actor/player/{folder}/model/cus/acce/cus_{token}_head_acce{model-500:03d}"
        return f"actor/player/{folder}/model/cus/acce/cus_{token}_acce_all{model:03d}"
    return None


def _rank(name):
    for i, kw in enumerate(PRIORITY):
        if name.endswith(f"_{kw}_col"):
            return i
    return len(PRIORITY)


def find_texture(hashes, cid, category, model, texture):
    """-> (texture_name, entry) for the item's own real diffuse map, or None if it can't be found."""
    base = _base_name(cid, category, model, texture)
    if base is None:
        return None
    mat = next((e for e in hashes.get(gx.name_hash(base), []) if e["type"] == MATERIAL_TYPE), None)
    if not mat:
        return None
    data = gx.extract(mat)
    names = sorted({m.group().decode() for m in COL_RE.finditer(data) if m.group().decode().endswith("_col")})
    names.sort(key=_rank)
    for name in names:
        tex = next((e for e in hashes.get(gx.name_hash(name), []) if e["type"] == TEXTURE_TYPE), None)
        if tex:
            return name, tex
    return None


def real_name(cid, category, model, texture):
    """The game's own thumbnail name (relative to PREFIX), found 2026-10-18 from a live request log
    ("Skin/cus_01mephi_cos_parts000_t01") and solved for the other folders from the portrait hashes.
    Accessories have two shots: _01 the item alone (640x448), _02 worn (508x356)."""
    folder, token, se, vo = roi_data.CHARACTERS[cid]
    if category == roi_custom.HEAD:
        return f"Head/cus_{token}_head_all{model:03d}_t{texture:02d}"
    if category == roi_custom.COSTUME:
        return f"Skin/cus_{token}_cos_parts{model:03d}_t{texture:02d}"
    if category == roi_custom.WEAPON:
        return f"Weapon/cus_{token}_weap_all{model:03d}_t{texture:02d}"
    if model >= 500:
        return f"Accesary/cus_{token}_head_acce{model - 500:03d}_02"
    return f"Accesary/cus_{token}_acce_all{model:03d}_02"


def name_plan():
    """-> {(cid, category, model, texture): (name relative to PREFIX, kind)} using the game's own thumbnails:
    the item's own picture, else (placeholder or none) the same model's picture in the nearest colour, else
    the placeholder the original game showed."""
    inv = gx.load()
    tex = {int(e["hash"], 16): e for e in inv if e["type"] == TEXTURE_TYPE}

    def lookup(key):
        return tex.get(gx.name_hash(PREFIX + real_name(*key)))

    items = [(cid, c, m, t) for cid in sorted(roi_data.CHARACTERS) for c, m, t in roi_custom.character_items(cid)]
    found = {k: lookup(k) for k in items}
    bad = placeholders([e for e in {e["hash"]: e for e in found.values() if e}.values()])
    by_model = {}
    for k, e in found.items():
        if e and e["hash"] not in bad:
            by_model.setdefault(k[:3], []).append(k)
    # other textures of the same model that exist as pictures but aren't items of ours (e.g. t91-t93)
    out = {}
    for k in items:
        e = found[k]
        if e and e["hash"] not in bad:
            out[k] = (real_name(*k), "own")
        elif k[:3] in by_model:
            near = min(by_model[k[:3]], key=lambda o: abs(o[3] - k[3]))
            out[k] = (real_name(*near), "nearest-colour")
        elif e:
            out[k] = (real_name(*k), "placeholder")
    return out


def thumb_suffix(cid, category, model, texture):
    """The deterministic new name (relative to PREFIX) a given item's thumbnail will be registered under."""
    return f"Customize/{cid}_{category}_{model}_{texture}"


def _fingerprint(data):
    """Coarse luminance grid of a BC1 texture, from a 12x8 sample of its blocks (no full decode)."""
    import struct
    w, h = struct.unpack_from("<HH", data, 0)
    bx, by = (w + 3) // 4, (h + 3) // 4
    out = []
    for j in range(8):
        for i in range(12):
            off = 12 + ((j * by // 8) * bx + i * bx // 12) * 8
            if off + 4 > len(data):
                out.append(0)
                continue
            c0, c1 = struct.unpack_from("<HH", data, off)
            lum = 0
            for c in (c0, c1):
                lum += ((c >> 11) & 31) * 8 * 0.3 + ((c >> 5) & 63) * 4 * 0.59 + (c & 31) * 8 * 0.11
            out.append(lum / 2)
    return out


def placeholders(entries):
    """Hashes of the devs' "Temporary image 508*356" placeholder portraits: any picture used 4+ times, and
    anything that looks like one of those (same image, different encoding)."""
    import collections
    import hashlib
    blobs = {}
    for e in entries:
        with (gx.RES / f"GxArchivedFile{e['table']:03d}.dat").open("rb") as f:
            f.seek(e["off"])
            blobs[e["hash"]] = gx.unbilz(f.read(e["size"]))[1]
    digest = {h: hashlib.md5(b).hexdigest() for h, b in blobs.items()}
    common = {d for d, n in collections.Counter(digest.values()).items() if n >= 4}
    refs = [_fingerprint(blobs[h]) for h in {next(h for h in digest if digest[h] == d) for d in common}]
    bad = {h for h, d in digest.items() if d in common}
    for h, b in blobs.items():
        fp = _fingerprint(b)
        if any(sum(abs(a - r) for a, r in zip(fp, ref)) / len(fp) < 6 for ref in refs):
            bad.add(h)
    return bad


def plan():
    """-> {(cid, category, model, texture): {"suffix", "table", "src", "kind"}} for every item we can picture:
    the game's own portrait; for a placeholder or missing one, the same model's portrait in the nearest other
    colour; else the item's diffuse texture."""
    inv = gx.load()
    hashes = {}
    for e in inv:
        hashes.setdefault(int(e["hash"], 16), []).append(e)
    shop = portraits()
    bad = placeholders(list({e["hash"]: e for e in shop.values()}.values()))
    by_model = {}
    for (cid, cat, m, t), e in shop.items():
        if e["hash"] not in bad:
            by_model.setdefault((cid, cat, m), []).append((t, e))
    out = {}
    for cid in sorted(roi_data.CHARACTERS):
        for cat, m, t in roi_custom.character_items(cid):
            key = (cid, cat, m, t)
            e = shop.get(key)
            if e is not None and e["hash"] not in bad:
                src, kind = e, "portrait"
            elif (cid, cat, m) in by_model:
                src, kind = min(by_model[(cid, cat, m)], key=lambda te: abs(te[0] - t))[1], "portrait-colour"
            else:
                found = find_texture(hashes, cid, cat, m, t)
                if not found:
                    continue
                src, kind = found[1], "diffuse"
            out[key] = {"suffix": thumb_suffix(cid, cat, m, t), "table": src["table"], "src": src, "kind": kind}
    return out


def write():
    """Write customize-thumb-plan.json ("cid|cat|model|tex" -> name relative to PREFIX) for roi_custom."""
    import collections
    import json
    p = name_plan()
    path = pathlib.Path(__file__).resolve().parent / "customize-thumb-plan.json"
    path.write_text(json.dumps({"|".join(map(str, k)): v[0] for k, v in p.items()}, indent=1))
    print(f"wrote {path}: {len(p)} items {dict(collections.Counter(v[1] for v in p.values()))}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["write"]:
        write()
        sys.exit()
    p = plan()
    kinds = {}
    for v in p.values():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    total = sum(len(roi_custom.character_items(cid)) for cid in roi_data.CHARACTERS)
    print(f"{len(p)}/{total} items pictured: {kinds}")
    missing = [k for cid in sorted(roi_data.CHARACTERS) for k in
               ((cid, c, m, t) for c, m, t in roi_custom.character_items(cid)) if p.get(k, {}).get("kind") != "portrait"]
    print("not from portraits:", missing[:40], "..." if len(missing) > 40 else "")
