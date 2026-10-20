"""Customize items for the stand-in server: the customize_master records and each character's owned items
(everything that exists in the archives is owned).

What the client expects (found 2026-10-17, see MODLOG "Customize"):
- sv_category: 1 Head, 2 Costume, 3 Weapon, 4 Accessory (other values are listed nowhere). sv_equipPart = the same.
- sv_modelId / sv_textureId pick the model: cos/cus_<c>_cos_parts{m:03}_t{t:02}, head/cus_<c>_head_all{m:03}_t{t:02},
  weap/cus_<c>_weap_all{m:03}_t{t:02}_wepA, accessories: m < 500 -> acce/cus_<c>_acce_all{m:03},
  m >= 500 -> acce/cus_<c>_head_acce{m-500:03} (0x140035040).
- sv_thumbnails[0] is loaded as hud/sequence/store/TEX/Thumbnail/<name> (the client adds that prefix; without
  a picture it shows the Loding_image_Item tile). The game's own shop pictures are still in the archive:
  Skin/ (costumes), Head/, Weapon/ and Accesary/ (sic) + the model name, e.g. Skin/cus_01mephi_cos_parts000_t01
  and Accesary/cus_01mephi_acce_all001_02 (_02 = worn, _01 = the item alone). customize_thumbs.py write picks
  one per item (own picture, else the same model in the nearest colour) into customize-thumb-plan.json.
  Confirmed in game 2026-10-18.
- Owned items: sv_customItems [{sv_customItemHoldId, sv_customItemId}]; outfits: sv_customSlots
  [{sv_customItemHoldIds: [head, costume, weapon, acce, acce, acce, 0, 0, 0]}] + sv_activeCustomSlotNum.

Item id = hold id = charaId * 1000000 + category * 100000 + modelId * 100 + textureId.
"""
import json
import pathlib

PARTS_FILE = pathlib.Path(__file__).resolve().parent / "customize-parts.json"
THUMB_PLAN_FILE = pathlib.Path(__file__).resolve().parent / "customize-thumb-plan.json"
LABELS_FILE = pathlib.Path(__file__).resolve().parent / "customize-labels.json"
THUMB = "Other/Store_Thumbnail_Other_Exp_001"  # only if customize-thumb-plan.json is missing (before setup)
HEAD, COSTUME, WEAPON, ACCESSORY = 1, 2, 3, 4
_thumb_plan = None
_label_plan = None


def _thumbs():
    global _thumb_plan
    if _thumb_plan is None:
        try:
            _thumb_plan = json.loads(THUMB_PLAN_FILE.read_text())
        except OSError:
            _thumb_plan = {}
    return _thumb_plan


def thumbnail_for(cid, category, model, texture):
    return _thumbs().get(f"{cid}|{category}|{model}|{texture}", THUMB)


def label_ids(cid, category, model, texture):
    global _label_plan
    if _label_plan is None:
        try:
            _label_plan = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _label_plan = {}
    quote = _label_plan.get("items", {}).get(f"{cid}|{category}|{model}|{texture}")
    if quote is not None:
        description = _label_plan.get("descriptions", {}).get(
            f"{cid}|{category}|{model}|{texture}", _label_plan["description_quote"])
        return int(quote), int(description)
    # Safe original category quotes if setup has not generated/installed the full labels.
    quote = {HEAD: 170002, COSTUME: 170003, WEAPON: 170004, ACCESSORY: 170005}[category]
    return quote, quote


def entry(cid, category, model, texture, sort):
    # Native parser 0x14009ee60 converts both fields to numeric common_text quote IDs.
    name, description = label_ids(cid, category, model, texture)
    return {"sv_customizeId": str(item_id(cid, category, model, texture)), "sv_name": str(name),
            "sv_characterId": str(cid), "sv_category": str(category), "sv_modelId": str(model),
            "sv_textureId": str(texture), "sv_equipPart": str(category), "sv_desc": str(description), "sv_sort": str(sort),
            "sv_camPosX": "0.0", "sv_camPosY": "0.0", "sv_camPosZ": "0.0",
            "sv_thumbnails": [thumbnail_for(cid, category, model, texture)]}


def item_id(cid, category, model, texture):
    return cid * 1000000 + category * 100000 + model * 100 + texture


def parts(cid):
    return json.loads(PARTS_FILE.read_text()).get(str(cid), {})


def real(pairs):
    """customize_scan matches 32-bit name hashes, so a few hits are coincidences (models like 517 or 920 without a
    _t00 base colour). Real parts are numbered 0..99 (and 100), each with a t00 variant."""
    have = {tuple(p) for p in pairs}
    return sorted((m, t) for m, t in have if m <= 100 and (m, 0) in have)


def character_items(cid):
    p = parts(cid)
    out = []
    for cat, key in ((COSTUME, "cos"), (HEAD, "head"), (WEAPON, "weap")):
        out += [(cat, m, t) for m, t in real(p.get(key, []))]
    out += [(ACCESSORY, m, 0) for m, t in p.get("acce", []) if 1 <= m <= 99]
    out += [(ACCESSORY, 500 + m, 0) for m, t in p.get("headacce", []) if 1 <= m <= 99]
    return out


def master_entries():
    import roi_data
    out = []
    for cid in sorted(roi_data.CHARACTERS):
        for sort, (cat, m, t) in enumerate(character_items(cid), 1):
            out.append(entry(cid, cat, m, t, sort))
    return out


def owned(cid):
    return [{"sv_customItemHoldId": str(item_id(cid, c, m, t)), "sv_customItemId": str(item_id(cid, c, m, t))}
            for c, m, t in character_items(cid)]
