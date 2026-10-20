"""Master data the stand-in server sends for {"call":"load","data":{"name":"<master>"}}.

Keys and types come from the client's parsers (see mastermap.py / schema.py). Values are strings because the
client converts with strtoui64/strtod. Character HP and stock tiers have recovered
references; unknown HP and unrecovered experience curves remain placeholders.
"""
import importlib

import roi_data

S = str
FAR_FUTURE = "4102444800"   # 2100-01-01: not yet released
PAST = "1388534400"          # 2014-01-01

STAGES = {1: "NEWYORK", 2: "WASHINGTON", 3: "SANFRANCISCO", 5: "LONDON", 6: "PARIS"}
CAM = (0.0, 1.2, 3.5)  # experiment: x, y (height), z (distance)


def chara_param(title, grap, long_range, speed, icon="NULL"):
    # sv_title is a FULL common_text quote ID, not a short index or incarnate-type
    # enum. Consumer 0x14030332c reads the u32 and calls 0x14058ae70 unchanged.
    # The icon is a bare filename under the client's fixed character-select prefix.
    return {"sv_iconPath": icon, "sv_title": S(title),
            "sv_grap": S(grap), "sv_longRange": S(long_range), "sv_speed": S(speed)}


def chara_master():
    importlib.reload(roi_data)  # the server imports roi_data once; pick up edits (USE_VOICE) without a restart
    rows = []
    for cid in range(1, 22):  # the parser looks up every id 1..21 and reads out of bounds if one is missing
        real = cid in roi_data.CHARACTERS
        label, custom, se, voice = roi_data.CHARACTERS.get(cid, ("NULL", "NULL", "NULL", "NULL"))
        chara_type, grap, long_range, speed = roi_data.COMBAT.get(cid, (roi_data.BALANCED, 50, 50, 50))
        if cid in roi_data.PANELS:
            panels = [chara_param(t, g, r, s, icon) for t, g, r, s, icon in roi_data.PANELS[cid]]
        else:
            panels = [chara_param(0, grap, long_range, speed)] * 3
        rows.append({
            "sv_charaId": S(cid),
            "sv_cost": S(roi_data.STOCK_COST.get(cid, roi_data.DEFAULT_COST)),
            "sv_hp": S(roi_data.CHARACTER_HP.get(cid, roi_data.DEFAULT_HP)),
            "sv_age": "0",
            "sv_incarnateType": S(roi_data.INCARNATE_TYPE.get(cid, 0)),
            "sv_seFileName": se,
            "sv_voiceFileName": voice if (real and roi_data.USE_VOICE) else "NULL",
            "sv_labelName": label,
            "sv_customLabelName": custom,
            "sv_sizeType": "0",
            "sv_sort": S(cid),
            # camera for the profile / Customize 3D views (real values lost; 0,0,0 left the Customize view black)
            "sv_profCamPosX": S(CAM[0]), "sv_profCamPosY": S(CAM[1]), "sv_profCamPosZ": S(CAM[2]),
            "sv_cusCamPosX": S(CAM[0]), "sv_cusCamPosY": S(CAM[1]), "sv_cusCamPosZ": S(CAM[2]),
            "sv_appearanceTime": PAST if real else FAR_FUTURE,
            "sv_enableType": "0",
            "sv_enableTime": PAST if real else FAR_FUTURE,
            "sv_charaType": S(chara_type) if real else "0",
            "sv_moviePath": "NULL",
            "sv_paramCount": S(len(panels)) if real else "0",
            "sv_param": panels if real else [],
        })
    return rows


def playerlevel_master():
    import roi_awards
    recovered = roi_awards.master_rows('player')
    if recovered is not None:
        return recovered
    # 0-based levels: the parsers resize their table to the record count and then index it by sv_level
    rewards = roi_awards.level_reward_items()
    return [{"sv_level": S(lv), "sv_totalExp": S(lv * lv * 500), "sv_openTime": "0", "sv_rewardItems": rewards.get(lv, [])}
            for lv in range(50)]


def charalevel_master():
    import roi_awards
    rows = []
    for cid in range(1, 22):
        recovered = roi_awards.master_rows('character', cid)
        rows.extend(recovered if recovered is not None else [
            {"sv_charaId": S(cid), "sv_level": S(lv), "sv_totalExp": S(lv * lv * 300),
             "sv_openTime": "0", "sv_rewardItems": []} for lv in range(10)])
    return rows  # Retain placeholder rows for unrecovered characters, never grant XP from them.


def rank_master():
    # 14 ranks (hud/sequence/record/TEX/Record_Character_Rank_01..14) plus an entry for index 0
    return [{"sv_upPoint": S(100 * (i + 1)), "sv_downPoint": S(0 if i == 0 else 100 * i), "sv_downRatio": "0"}
            for i in range(15)]


def matching_range_master():
    return [{"sv_rank": S(i), "sv_range": [], "sv_min": S(max(0, i - 2)), "sv_max": S(min(14, i + 2))} for i in range(15)]


def stage_master():
    # Begin time 0: parser 0x1400a9920 stamps each stage with the response "time" / 1000 (it expects
    # milliseconds; we send seconds) and "stage open" checks compare that stamp, not the clock, with the
    # window. With 2014 as the begin no stage was open, the lobby's random stage pick (0x140135400) returned
    # 0 and BATTLE in a custom lobby waited on a black screen forever.
    return [{"_id": S(sid), "sv_beginTime": "0", "sv_endTime": FAR_FUTURE, "sv_sort": S(i)}
            for i, sid in enumerate(STAGES)]


def const():
    return [{
        "sv_clientVer": "2.06",          # compared with the client's own "2.06" (parser 0x1400aab10)
        "sv_circleSubLeaderExpandMax": "0", "sv_circleMemberExpandMax": "0",
        "sv_circleSubLeaderExpandCost": "0", "sv_circleMemberExpandCost": "0",
        "sv_circleAbsorptionCost": "0", "sv_changeTagNameCost": "0",
        "sv_disconnectCountSpan": "0", "sv_disconnectWarnPercent": "100",
        "sv_disconnectCriminalPercent": "100", "sv_disconnectReleaseCriminalPercent": "0",
        "sv_minorVer": "0",
    }]


def stage_status():
    return [{"_id": S(sid), "sv_cubifyStep": "0", "sv_freezingTime": "0"} for sid in STAGES]


# An empty list makes the client fail with error 9011 (0x2333), so every master below has records.

def customize_master():
    import roi_custom
    importlib.reload(roi_custom)
    return roi_custom.master_entries()


def skillcube_master():
    import roi_server_data
    import roi_skills
    import roi_skill_catalogue
    import profile_store
    with profile_store.LOCK:
        importlib.reload(roi_skill_catalogue)
        importlib.reload(roi_skills)
        saved = roi_server_data.saved()
        if roi_skills.enabled(saved):
            return roi_skills.master(saved)
    return [{"_id": "1", "sv_skillcubeId": "1", "sv_skillcubeIconId": "1", "sv_skillcubeRank": "1",
             "sv_skillcubeShape": "1", "sv_skillcubeName": "0", "sv_skillcubeDesc": "0", "sv_skillcubeRarityId": "1",
             "sv_effects": [], "sv_cobeCount": "1", "sv_skillcubePrice": "0", "sv_skillcubeStatus": "0",
             "sv_skillcubeCategory": "0", "sv_sort": "1"}]


def skillcubelevel_master():
    import roi_server_data
    import roi_skill_catalogue
    if roi_skill_catalogue.enabled(roi_server_data.saved()):
        return roi_skill_catalogue.base_level_rows()
    return [{"sv_rank": "1", "sv_level": S(lv), "sv_totalExp": S((lv - 1) * 100), "sv_gainExp": "10",
             "sv_triggerLimit": "0"} for lv in range(1, 11)]


def store_item_master():
    import roi_server_data
    import roi_skill_shop
    import roi_skills
    importlib.reload(roi_skill_shop)
    saved = roi_server_data.saved()
    rows = [{"_id": "1", "sv_items": [{"sv_itemId": "1"}], "sv_price": "0", "sv_basisPrice": "0", "sv_sort": "1",
             "sv_beginTime": PAST, "sv_thumbnail": "NULL", "sv_thumbnails": [], "sv_feature": "0",
             "sv_storeItemDesc": "0", "sv_itemNameId": "0"}]
    if roi_skills.progression(saved):
        rows.append(roi_skill_shop.store_master(saved))
    return rows


def banner_master():
    return [{"sv_bannerNum": "1", "sv_beginTime": PAST, "sv_endTime": PAST, "sv_sort": "1"}]


def bg_master():
    # main menu background, picked at random among currently valid entries (count 0 -> divide by zero);
    # path is relative to hud/sequenceResident/mainMenu/TEX/
    return [{"sv_bgPath": f"MainMenuBG/MainMenuBG_{sid:03d}stage_01", "sv_bgNum": S(i + 1), "sv_stageId": S(sid),
             "sv_beginTime": PAST, "sv_endTime": FAR_FUTURE, "sv_createTime": PAST, "sv_sort": S(i + 1)}
            for i, sid in enumerate(STAGES)]


def item_master():
    import roi_server_data
    import roi_skill_shop
    import roi_skills
    import roi_consumables
    importlib.reload(roi_skill_shop)
    rows = [{"sv_itemId": "1", "sv_name": "0", "sv_desc": "0", "sv_thumbnails": [], "sv_additions": [],
             "sv_sort": "1", "sv_createTime": PAST, "sv_hold": "0"}]
    if roi_skills.progression(roi_server_data.saved()):
        rows.append(roi_skill_shop.item_master())
    rows.extend(roi_consumables.master_rows())
    return rows


def gift_item_master():
    return store_item_master()


def chara_rote_schedule_master():
    # free character rotation: every released character, always
    return [{"sv_charaId": S(cid), "sv_beginTime": PAST, "sv_endTime": FAR_FUTURE} for cid in sorted(roi_data.CHARACTERS)]


def event_schedule_master():
    return [{"sv_eventId": "1", "sv_rewardGroupId": "0", "sv_botRewardGroupId": "0", "sv_rmmItemDropEventGroupId": "0",
             "sv_beginTime": PAST, "sv_endTime": PAST}]


def message_master():
    return [{"sv_messageId": "1", "sv_userLang": "english", "sv_title": "Local server", "sv_body": "Offline revival"}]


def video_card_master():
    return [{"sv_cardName": "Generic", "sv_score": "100"}]


def skillcube_mutation_master():
    return [{"sv_recipeId": "1", "sv_recipeName": "0", "sv_recipeDesc": "0", "sv_recipeIcon": "NULL",
             "sv_recipeCategory": "0", "sv_rarity": "1", "sv_nextSkillcubeId": "1", "sv_mainSkillcubeId": "1",
             "sv_subSkillcubeIds": [], "sv_mutationRate": "0", "sv_nextMutationSkillCubeIds": [], "sv_sort": "1",
             "sv_status": "0"}]


MASTERS = {
    "chara_master": chara_master,
    "customize_master": customize_master,
    "playerlevel_master": playerlevel_master,
    "charalevel_master": charalevel_master,
    "skillcube_master": skillcube_master,
    "skillcubelevel_master": skillcubelevel_master,
    "rank_master": rank_master,
    "matching_range_master": matching_range_master,
    "store_item_master": store_item_master,
    "stage_master": stage_master,
    "banner_master": banner_master,
    "const": const,
    "bg_master": bg_master,
    "item_master": item_master,
    "gift_item_master": gift_item_master,
    "chara_rote_schedule_master": chara_rote_schedule_master,
    "event_schedule_master": event_schedule_master,
    "message_master": message_master,
    "video_card_master": video_card_master,
    "stageStatus": stage_status,
    "skillcube_mutation_master": skillcube_mutation_master,
}


def master(name):
    fn = MASTERS.get(name)
    return fn() if fn else []
