"""Evidence-gated bot awards, native item encoding and atomic replay-safe persistence."""
from bisect import bisect_right
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import profile_store

POLICY_FILE = Path(__file__).with_name('award-policy.json')
MAX_INT = 2147483647
RECEIPT_LIMIT = 128


def integer(value, low=0, high=MAX_INT):
    if type(value) is str and value.isascii() and value.isdigit() and len(value) <= 10:
        value = int(value)
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid award integer')
    return value


def verified(row):
    if not isinstance(row, dict) or row.get('verified') is not True:
        raise ValueError('Unverified award data')
    evidence = row.get('evidence')
    if not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 2048:
        raise ValueError('Award data needs source evidence')


def curve(rows, maximum):
    if not isinstance(rows, list) or len(rows) > maximum:
        raise ValueError('Invalid XP curve')
    output = []
    for index, row in enumerate(rows):
        verified(row)
        level, xp = integer(row.get('level'), 0, maximum - 1), integer(row.get('total_xp'))
        if level != index or index == 0 and xp != 0 or output and xp < output[-1]:
            raise ValueError('XP levels must be contiguous and thresholds nondecreasing')
        # Native level lookup counts thresholds <= XP, then subtracts one.
        if index > 1 and xp == output[-1]:
            raise ValueError('Duplicate non-baseline XP threshold')
        output.append(xp)
    if output and len(output) < 2:
        raise ValueError('Incomplete XP curve')
    return output


def policy():
    if POLICY_FILE.stat().st_size > 512 * 1024:
        raise ValueError('Award policy exceeds limit')
    value = json.loads(POLICY_FILE.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or type(value.get('schema')) is not int
            or value['schema'] != 1 or type(value.get('enabled')) is not bool):
        raise ValueError('Invalid award policy')
    player = curve(value.get('player_levels'), 50)
    character_rows = value.get('character_levels')
    if not isinstance(character_rows, dict) or len(character_rows) > 21:
        raise ValueError('Invalid character XP curves')
    characters = {}
    for cid, rows in character_rows.items():
        canonical = str(integer(cid, 1, 21))
        if cid != canonical:
            raise ValueError('Noncanonical character ID')
        characters[cid] = curve(rows, 10)
    rules, seen = value.get('bot_rewards'), set()
    if not isinstance(rules, list) or len(rules) > 128:
        raise ValueError('Invalid bot reward table')
    normalized = []
    for row in rules:
        verified(row)
        bot, result = integer(row.get('bot_battle_id'), 0), integer(row.get('battle_result'), 0, 3)
        key = bot, result
        if key in seen:
            raise ValueError('Duplicate bot reward rule')
        seen.add(key)
        normalized.append(dict(bot_battle_id=bot, battle_result=result,
            reason_id=integer(row.get('reason_id'), 0, 10000),
            player_xp=integer(row.get('player_xp')), character_xp=integer(row.get('character_xp'))))
    return dict(enabled=value['enabled'], player=player, characters=characters, rules=normalized,
                digest=hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest())


def decode_item(item_id):
    """Decimal descriptor groups from native 0x1400fdc60, not a recovered item catalogue."""
    if type(item_id) not in (int, str) or isinstance(item_id, bool):
        raise ValueError('Invalid native reward ID')
    text = str(item_id)
    if not text.isascii() or not text.isdigit() or len(text) > 16:
        raise ValueError('Invalid native reward ID')
    text = text.zfill(16)
    return tuple(int(text[a:b]) for a, b in ((0,1),(1,2),(2,4),(4,6),(6,9),(9,10),(10,13),(13,16)))


def native_item(kind, amount, character=0):
    amount = integer(amount, 1)
    character = integer(character, 0, 21)
    # Protocol-compatible reconstructed IDs; unknown original database suffixes are zero.
    if kind == 'player_xp' and character == 0 or kind == 'character_xp' and character > 0:
        item_id = f'10{character:02d}010000000000'
    elif kind == 'grid_right' and character == 0:
        item_id = '1000020010000000'
    else:
        raise ValueError('Unsupported native award type')
    return {'sv_itemId': item_id, 'sv_count': str(amount), 'sv_additions': []}


def experience(saved, character=None):
    if character is None:
        return integer(saved.get('playerExperience', 0))
    return integer(saved.get('characterExperience', {}).get(str(character), 0))


def character_level(saved, cid):
    return integer(saved.get('characterLevels', {}).get(str(cid), 1), 1, 9)


def level_for(xp, thresholds):
    if not thresholds:
        raise ValueError('Original XP thresholds have not been recovered')
    return max(0, bisect_right(thresholds, integer(xp)) - 1)


def level_reward_items():
    import roi_grid_rewards
    return {level: [native_item('grid_right', rights)]
            for level, rights in roi_grid_rewards.level_rewards()}


def master_rows(kind, cid=None):
    current = policy()
    thresholds = current['player'] if kind == 'player' else current['characters'].get(str(cid), [])
    if not thresholds:
        return None
    rewards = level_reward_items() if kind == 'player' else {}
    return [dict(sv_level=str(level), sv_totalExp=str(xp), sv_openTime='0',
                 sv_rewardItems=rewards.get(level, []),
                 **({'sv_charaId': str(cid)} if cid is not None else {}))
            for level, xp in enumerate(thresholds)]


def request_digest(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid battle result')
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) > 65536:
        raise ValueError('Battle result exceeds limit')
    return hashlib.sha256(encoded).hexdigest()


def ledger(saved):
    value = deepcopy(saved.get('awardPipeline', {'schema': 1, 'sequence': 0, 'receipts': []}))
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('Invalid award ledger')
    integer(value.get('sequence'))
    if not isinstance(value.get('receipts'), list) or len(value['receipts']) > RECEIPT_LIMIT:
        raise ValueError('Invalid award receipts')
    return value


def aligned_experience(saved, thresholds, cid=None):
    xp = experience(saved, cid)
    level = integer(saved.get('playerLevel', 1), 1, 49) if cid is None else character_level(saved, cid)
    if level_for(xp, thresholds) != level:
        raise ValueError('Manual level override and XP must be aligned before enabling awards')
    return xp


def begin(path, owner, character, data):
    current = policy()
    if not current['enabled']:
        return None
    bot = integer(data.get('sv_botBattleId'), 0)
    context = dict(owner=str(owner), character=integer(character, 1, 21), bot=bot,
                   policy=current['digest'], request=request_digest(data))
    with profile_store.LOCK:
        saved = profile_store.read(path)
        candidates = [row for row in current['rules'] if row['bot_battle_id'] == bot]
        if any(row['player_xp'] for row in candidates):
            aligned_experience(saved, current['player'])
        if any(row['character_xp'] for row in candidates):
            aligned_experience(saved, current['characters'].get(str(character), []), character)
        state = ledger(saved)
        active = state.get('active')
        if active and all(active.get(key) == value for key, value in context.items()):
            return {'sv_battleId': active['battle_id']}
        state['sequence'] = integer(state['sequence'] + 1, 1)
        state['active'] = dict(context, battle_id=str(state['sequence']))
        profile_store.update(path, {'awardPipeline': state})
        return {'sv_battleId': state['active']['battle_id']}


def finish(path, owner, data):
    current = policy()
    if not current['enabled']:
        return None
    battle_id = str(integer(data.get('sv_battleId'), 1))
    fingerprint = request_digest(data)
    with profile_store.LOCK:
        saved = profile_store.read(path)
        state = ledger(saved)
        for receipt in state['receipts']:
            if receipt['battle_id'] == battle_id:
                if receipt['owner'] != str(owner) or receipt['request'] != fingerprint:
                    raise ValueError('Conflicting completed battle retry')
                return deepcopy(receipt['reply'])
        active = state.get('active')
        if not active or active['battle_id'] != battle_id or active['owner'] != str(owner):
            raise ValueError('Result has no matching active battle')
        if active['policy'] != current['digest'] or integer(data.get('sv_botBattleId'), 0) != active['bot']:
            raise ValueError('Battle reward context changed')
        result = integer(data.get('sv_battleResult'), 0, 3)
        rule = next((row for row in current['rules'] if
                     (row['bot_battle_id'], row['battle_result']) == (active['bot'], result)), None)
        changes, items = {}, []
        if rule:
            for kind, cid, field, level_field, thresholds in (
                    ('player_xp', None, 'playerExperience', 'playerLevel', current['player']),
                    ('character_xp', active['character'], 'characterExperience', 'characterLevels',
                     current['characters'].get(str(active['character']), []))):
                amount = rule[kind]
                if not amount:
                    continue
                before = aligned_experience(saved, thresholds, cid)
                after = integer(before + amount)
                level = level_for(after, thresholds)
                if cid is None:
                    changes.update({field: after, level_field: level})
                else:
                    xp_values, levels = deepcopy(saved.get(field, {})), deepcopy(saved.get(level_field, {}))
                    xp_values[str(cid)], levels[str(cid)] = after, level
                    changes.update({field: xp_values, level_field: levels})
                items.append(native_item(kind, amount, cid or 0))
            if 'playerLevel' in changes:
                import roi_skills
                if roi_skills.progression(saved):
                    changes['skillGrids'] = roi_skills.grids(dict(saved, **changes))
        reply = dict(sv_battleId=battle_id, sv_rewards=[dict(sv_reasonId=str(rule['reason_id']),
                     sv_items=items)] if items else [], sv_items=[], sv_mails=[])
        state['active'] = None
        state['receipts'] = (state['receipts'] + [dict(battle_id=battle_id, owner=str(owner),
                                                   request=fingerprint, reply=deepcopy(reply))])[-RECEIPT_LIMIT:]
        changes['awardPipeline'] = state
        profile_store.update(path, changes)
        return reply
