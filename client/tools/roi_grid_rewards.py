"""Only evidence-backed level rewards; an empty recovered schedule grants nothing."""
import json
from pathlib import Path

POLICY_FILE = Path(__file__).with_name('grid-reward-policy.json')
MAX_EARNED_RIGHTS = 9  # Contemporary guide: four initial cells, thirteen through leveling.


def level_rewards():
    policy = json.loads(POLICY_FILE.read_text(encoding='utf-8'))
    rows = policy.get('level_rewards')
    if policy.get('schema') != 1 or not isinstance(rows, list) or len(rows) > MAX_EARNED_RIGHTS:
        raise ValueError('Invalid recovered grid-reward policy')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid recovered grid reward')
        level, rights, evidence = row.get('player_level'), row.get('rights'), row.get('evidence')
        if type(level) is not int or not 5 <= level <= 50 or level in seen:
            raise ValueError('Invalid or duplicated reward level')
        if type(rights) is not int or not 1 <= rights <= MAX_EARNED_RIGHTS:
            raise ValueError('Invalid expansion-right quantity')
        if row.get('verified') is not True or not isinstance(evidence, str) or not 1 <= len(evidence) <= 2048:
            raise ValueError('Unverified grid rewards cannot be activated')
        seen.add(level)
        result.append((level, rights))
    if sum(rights for _, rights in result) > MAX_EARNED_RIGHTS:
        raise ValueError('Level rewards exceed the documented level-earned allowance')
    return sorted(result)


def earned_rights(player_level):
    if type(player_level) is not int or not 1 <= player_level <= 50:
        raise ValueError('Invalid player level')
    return sum(rights for level, rights in level_rewards() if player_level >= level)
