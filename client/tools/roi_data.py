"""Local replacements for data the retired Rise of Incarnates server used to send.

chara_master rows live at *(0x141b87458) + 0x53f30 + id*0x280 (22 rows, id 0..21). Field offsets come from the
original parser at 0x1400a51f0 ('sv_*' keys); see MODLOG.md.
"""

# id: (labelName = actor/player folder, customLabelName, SE bank/se_group, voice bank)
CHARACTERS = {
    1: ("01_mephi", "01mephi", "SE_CHR_01MEPHISTO", "VO_01_MEPHISTO_ONMEMORY"),
    2: ("02_ares", "02ares", "SE_CHR_02ARES", "VO_02_ARES_ONMEMORY"),
    3: ("03_zeus", "03zeus", "SE_CHR_03ZEUS", "VO_03_ZEUS_ONMEMORY"),
    4: ("04_lilith", "04lilith", "SE_CHR_04LILITH", "VO_04_LILITH_ONMEMORY"),
    5: ("05_fen", "05fen", "SE_CHR_05FENRIR", "VO_05_FENRIR_ONMEMORY"),
    6: ("06_utsu", "06utsu", "SE_CHR_06UTSUTA", "VO_06_UTUTAHIME_ONMEMORY"),
    7: ("07_grim", "07grim", "SE_CHR_07GRIMREAPER", "VO_07_GRIMREAPER_ONMEMORY"),
    8: ("08_efr", "08efr", "SE_CHR_08LOKI", "VO_08_LOKI_ONMEMORY"),
    9: ("09_brun", "09brun", "SE_CHR_09BRUNHILD", "VO_09_BRUNHILD_ONMEMORY"),
    10: ("10_odin", "10odin", "SE_CHR_10ODIN", "VO_10_ODIN_ONMEMORY"),
    13: ("13_slay", "13slay", "SE_CHR_13SLAYER", "VO_13_SLAYER_ONMEMORY"),
    14: ("14_kali", "14kali", "SE_CHR_14KALI", "VO_14_KALI_ONMEMORY"),
    20: ("20_ra", "20ra", "SE_CHR_20RA", "VO_20_RA_ONMEMORY"),
    21: ("21_rdd", "21rdd", "SE_CHR_21RDD", "VO_21_REDDRAGON_ONMEMORY"),
}

# Fallbacks for unknown/unreleased rows; do not substitute testing-only HP.
DEFAULT_COST = 2500
DEFAULT_HP = 650
USE_VOICE = True

# Recovered from the earlier revival server's roi_battle_stats.py. Mephistopheles
# was footage-verified (580); the other eleven values came from the 2015 guide.
# Utsutahime (6) and Red Dragon (21) were supplied by the user on 2026-10-19;
# they are not independently footage-verified or taken from the old test data.
CHARACTER_HP = {
    1: 580, 2: 630, 3: 690, 4: 280, 5: 600, 6: 560, 7: 570,
    8: 650, 9: 570, 10: 670, 13: 330, 14: 510, 20: 640, 21: 500,
}

# sv_cost is the real "N-stock" tier, not a shop-style LP price -- confirmed 2026-10-18: the Character Select
# roster splits into 3 groups, each with its own "Stock" bar showing 1/2/3 filled segments, matching the
# 1-stock/2-stock/3-stock tiers Lumadurin's community Megaguide documents per character (see
# extracted/megaguide.txt). First attempt sent the literal numbers 1/2/3 -- the grouping DID split correctly
# (confirming the field), but every character slot came back empty, breaking character select. Disassembly
# of 0x140305510 (chara_master row +0x004, i.e. sv_cost) found the real check: three EXACT equality
# comparisons against 0x3e8/0x7d0/0xbb8 = 1000/2000/3000 (`cmp [...], 0x3e8` / `sete`), setting three
# separate "is 1/2/3-stock" UI flags -- the game expects sv_cost to literally be 1000, 2000 or 3000, not 1/2/3.
# Confirmed from the guide: Mephistopheles/Fenrir/Grim Reaper/Loki/Brynhildr/Kali=2, Lilith/Slayer=1,
# Ares/Odin/Ra=3. Zeus and Red Dragon have no "Cost:" line in the guide at all; Utsuta Hime isn't covered by
# it either -- these 3 are inferred (Zeus/Red Dragon=3, Utsuta Hime=2) from matching the reference
# screenshot's exact group sizes (2/7/5), not independently confirmed per-character.
STOCK_COST = {
    1: 2000, 2: 3000, 3: 3000, 4: 1000, 5: 2000, 6: 2000, 7: 2000, 8: 2000, 9: 2000, 10: 3000,
    13: 1000, 14: 2000, 20: 3000, 21: 3000,
}

# Battle Style (sv_charaType), Incarnate Type (sv_incarnateType) and the Character Select stat bars
# (sv_param: sv_grap/sv_longRange/sv_speed, 0-100). See MODLOG "Character Select text" for the full writeup.
#
# charaType (sv_charaType) is CONFIRMED: 0 Melee, 1 Ranged, 2 Balanced. All 14 characters' real charaType are
# now confirmed too -- 10 read directly off a 2015 gameplay video (youtube.com/watch?v=R8V4V-_t1jY), the
# remaining 4 (Ares, Zeus, Grim Reaper, Brynhildr) plus 2 corrections (Mephistopheles, Brynhildr) from
# reference screenshots the user supplied 2026-10-18 covering every character.
#
# incarnateType (sv_incarnateType): the word itself is confirmed for all 14 (quote table has 181 Summoner,
# 182 Transformer, 183 Deuteros, 185 Human). The client enum->word mapping is PARTIALLY confirmed: a live
# test on 2026-10-18 showed 1 -> Transformer (Lilith) and 2 -> Deuteros (Odin) both correct, while 0 was
# WRONG for both Human (Slayer) and (left at its default) Summoner (Grim Reaper) -- so 0 is not a valid type
# index, probably "unset". Testing 3 -> Summoner and 4 -> Human next (quote id - 181, same arithmetic that
# produced the confirmed 1 and 2). Red Dragon's Incarnate Type is genuinely "Unknown" in the real client too
# (not a bug) -- left unset (0) under this theory, which should render as the same "Unknown".
MELEE, RANGED, BALANCED = 0, 1, 2
COMBAT = {  # cid: (charaType, grap, longRange, speed)
    1: (BALANCED, 60, 55, 55),    # Mephistopheles -- CONFIRMED (user screenshot 2026-10-18, corrects video read)
    2: (RANGED, 30, 85, 40),      # Ares -- CONFIRMED (user screenshot 2026-10-18)
    3: (BALANCED, 65, 65, 55),    # Zeus -- CONFIRMED (user screenshot 2026-10-18, corrects megaguide estimate)
    4: (MELEE, 35, 55, 80),       # Lilith -- CONFIRMED (video + user screenshots)
    5: (BALANCED, 60, 60, 30),    # Fenrir -- CONFIRMED (video)
    6: (RANGED, 50, 50, 50),      # Utsutahime -- CONFIRMED charaType (video); stats still a placeholder
    7: (RANGED, 35, 70, 45),      # Grim Reaper -- CONFIRMED (user screenshot 2026-10-18)
    8: (MELEE, 95, 15, 15),       # Loki ("efr") -- CONFIRMED (video)
    9: (MELEE, 55, 55, 95),       # Brynhildr -- CONFIRMED (user screenshot 2026-10-18, corrects megaguide estimate)
    10: (RANGED, 20, 90, 25),     # Odin -- CONFIRMED (video)
    13: (MELEE, 85, 25, 60),      # Slayer -- CONFIRMED (video)
    14: (RANGED, 40, 75, 45),     # Kali -- CONFIRMED charaType (video); stats still a placeholder
    20: (BALANCED, 65, 65, 50),   # Ra -- CONFIRMED (video)
    21: (BALANCED, 50, 50, 50),   # Red Dragon -- CONFIRMED (video); Incarnate Type was "Unknown" in-game too
}

UNSET, TRANSFORMER, DEUTEROS, SUMMONER, HUMAN = 0, 1, 2, 3, 4
# enum = quote_id - 181 (181 Summoner, 182 Transformer, 183 Deuteros, 185 Human). CONFIRMED live for
# Transformer(1, Lilith), Deuteros(2, Odin) and Summoner(3, Grim Reaper); Human(4, Slayer) follows the same
# arithmetic but hasn't been independently re-confirmed since round 1 (where 0 was wrong for it).
INCARNATE_TYPE = {
    1: TRANSFORMER, 4: TRANSFORMER, 5: TRANSFORMER, 6: TRANSFORMER, 8: TRANSFORMER,  # Meph/Lilith/Fenrir/Utsu/Loki
    2: DEUTEROS, 3: DEUTEROS, 9: DEUTEROS, 10: DEUTEROS, 14: DEUTEROS, 20: DEUTEROS,  # Ares/Zeus/Brun/Odin/Kali/Ra
    7: SUMMONER,   # Grim Reaper
    13: HUMAN,     # Slayer
    # 21 Red Dragon: left UNSET (0) -- real client shows "Unknown" for him too, believed to be the same thing
}

# Character Select stat-panel layout (sv_param): (title_quote_id, grap, longRange, speed, icon) per panel.
# sv_title needs the FULL common_text ID: e.g. 590009 Human, 590011 Summon
# Deuteros. The old 181-193 values were short indices, absent from common_text;
# the earlier claim that these headings were unrecoverable was incorrect.
# Native parser 0x1400a6cd5 stores u32; UI 0x14030332c sends it unchanged to
# common_text lookup 0x14058ae70. IDs below were verified in text/common_text.
#
# ICON: the archive has real per-character, per-panel artwork at
# hud/sequenceResident/characterSelect/TEX/new/Charaselect_Charadata_<token>_0N (confirmed present via
# gx.py has(), and the number of "_0N" files per character matches the panel
# counts). Native UI 0x14030327c prepends the directory to the bare icon filename.
ICON_BASE = "hud/sequenceResident/characterSelect/TEX/new/Charaselect_Charadata_"
TOKENS = {1: "01Mephi", 2: "02Ares", 3: "03Zeus", 4: "04Lilith", 5: "05Fenrir", 6: "06Utsuta", 7: "07Grim",
          8: "08Loki", 9: "09_Brun", 10: "10Odin", 13: "13_Slayer", 14: "14Kali", 20: "20Ra", 21: "21Rdd"}


def _icon(cid, n):
    # sv_iconPath parses into a FIXED 0x40 (64)-byte buffer via strcpy_s (confirmed by direct disassembly of
    # 0x1400a51f0's sv_param parsing); the full archive path (ICON_BASE + name) is 78 bytes and overflows it
    # -- 2026-10-18 this crashed the game at the login/master-data load. Bare filename only (<=35 bytes for
    # every character here) is the only safe form; ICON_BASE is kept only as a reference for what the real
    # full path is, never concatenated into what's actually sent.
    return "Charaselect_Charadata_" + f"{TOKENS[cid]}_{n:02d}"


PANELS = {
    1: [(590009, 60, 55, 55, _icon(1, 1)), (590010, 85, 80, 70, _icon(1, 2))],  # Mephistopheles
    2: [(590009, 45, 60, 40, _icon(2, 1)), (590011, 35, 90, 35, _icon(2, 2))],  # Ares
    3: [(590007, 65, 65, 55, _icon(3, 1))],                                   # Zeus
    4: [(590009, 20, 35, 70, _icon(4, 1)), (590010, 50, 75, 90, _icon(4, 2))],  # Lilith
    5: [(590009, 50, 50, 30, _icon(5, 1)), (590010, 70, 70, 30, _icon(5, 2))],  # Fenrir
    6: [(590009, 40, 70, 45, _icon(6, 1)), (590010, 60, 90, 55, _icon(6, 2))],  # Utsutahime
    7: [(590005, 35, 70, 45, _icon(7, 1))],                                   # Grim Reaper
    8: [(590009, 70, 10, 15, _icon(8, 1)), (590010, 95, 20, 15, _icon(8, 2))],  # Loki
    9: [(590007, 55, 55, 95, _icon(9, 1))],                                   # Brynhildr
    10: [(590012, 15, 80, 20, _icon(10, 1)), (590013, 25, 90, 35, _icon(10, 2))],  # Odin
    13: [(590009, 85, 25, 60, _icon(13, 1))],                                  # Slayer
    14: [(590007, 40, 75, 45, _icon(14, 1))],                                  # Kali
    20: [(590015, 55, 80, 65, _icon(20, 1)), (590016, 85, 30, 45, _icon(20, 2)), (590017, 30, 60, 40, _icon(20, 3))],  # Ra
    21: [(590010, 60, 60, 60, _icon(21, 1))],                                  # Red Dragon
}

CHARA_TABLE = 0x53F30
CHARA_ROW = 0x280


def chara_row_fields(cid):
    """(offset, kind, value) for one chara_master row, mirroring what parser 0x1400a51f0 writes."""
    label, custom, se, voice = CHARACTERS[cid]
    return [
        (0x000, "u32", cid),             # sv_charaId
        (0x004, "u32", DEFAULT_COST),    # sv_cost
        (0x008, "u32", CHARACTER_HP.get(cid, DEFAULT_HP)),  # sv_hp
        (0x00C, "u32", 0),               # sv_age
        (0x010, "u32", 0),               # sv_incarnateType
        (0x014, "str64", se),            # sv_seFileName
        (0x054, "str64", voice if USE_VOICE else "NULL"),  # sv_voiceFileName
        (0x094, "str64", label),         # sv_labelName (actor/player/<label>/...)
        (0x0D4, "str64", custom),        # sv_customLabelName (cus_<custom>_...)
        (0x114, "u32", 0),               # sv_sizeType
        (0x118, "u32", cid),             # sv_sort
        (0x140, "u32", 1),               # released (parser: appearanceTime <= server time)
        (0x158, "u32", 0),               # sv_enableType
        (0x15C, "u8", 0),                # sv_charaType
        (0x15D, "str64", "NULL"),        # sv_moviePath
        (0x19D, "u8", 0),                # sv_paramCount
    ]
