"""Original enabled cube definitions; level-one local revival grants only.

The data retains shipped-client rates, not presumed final live-server overrides.
Leveling, consumption and synthesis are not restored by these grants.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).with_name('recovered-skillcube-master.json')


def enabled(saved):
    return saved.get('originalSkillCubes') is True


@lru_cache(maxsize=1)
def _rows():
    if DATA.stat().st_size > 2 * 1024**2:
        raise ValueError('Unexpected cube catalogue size')
    raw = DATA.read_bytes()
    if hashlib.sha256(raw).hexdigest() != 'c24ae4c64bcc5dc13ca223e5fca73769727ea5ff1f076dda35108fbbe5ae97ad':
        raise ValueError('Recovered catalogue changed; review before loading')
    rows = json.loads(raw)
    if len(rows) != 346 or len({row['sv_skillcubeId'] for row in rows}) != 346:
        raise ValueError('Unexpected enabled cube catalogue')
    for row in rows:
        if row['sv_skillcubeStatus'] != '1' or row['sv_skillcubeRank'] not in ('D', 'C', 'B', 'A'):
            raise ValueError('Invalid released cube record')
        if not 2 <= int(row['sv_cobeCount']) <= 5 or len(row['sv_effects']) != 3:
            raise ValueError('Invalid original cube shape/effect count')
        if not 1 <= int(row['sv_effects'][2]['sv_effectId']) <= 8:
            raise ValueError('Invalid original summary category')
    return rows


def master():
    return deepcopy(_rows())


def inventory():
    # Hold IDs are revival inventory keys, separate from the recovered item IDs.
    return [dict(sv_skillcubeHoldId=str(index), sv_skillcubeId=row['sv_skillcubeId'],
                 sv_triggerCount='0', sv_triggerLimit='100', sv_levelupCount='0',
                 sv_evolutionCount='0', sv_modificationCount='0', sv_recoveryCount='0',
                 sv_skillLevel='1', sv_skillExp='0', sv_status='0')
            for index, row in enumerate(_rows(), 2)]


def block_counts():
    return {index: int(row['sv_cobeCount']) for index, row in enumerate(_rows(), 2)}


def base_level_rows():
    # Native order is NUL,D,C,B,A; base grants require no invented XP curve.
    # 100 uses is a compatibility allowance, not a recovered consumption rule.
    return [dict(sv_rank=str(rank), sv_level='1', sv_totalExp='0', sv_gainExp='0', sv_triggerLimit='100')
            for rank in range(1, 5)]
