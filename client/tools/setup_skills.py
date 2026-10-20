"""Initialize/upgrade local revival grids without replacing personal settings or levels."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_store
import roi_skills


def initialize(path):
    path = Path(path)
    with profile_store.LOCK:
        saved = profile_store.read(path)
        if saved.get('skillGridSchema') == 3:
            roi_skills.grids(saved)
            return {'changed': False, 'grids': len(roi_skills.grids(saved))}
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = path.parent / 'compatibility-backups' / ('grid-loadouts-' + stamp)
        backup.mkdir(parents=True)
        if path.exists():
            shutil.copy2(path, backup / path.name)
        saved.setdefault('originalSkillCubes', True)
        saved.setdefault('playerLevel', 1)
        value = roi_skills.migrate_progression(saved)
        value.setdefault('skillGridPriceLP', 1)
        # Offline test allowance only. No XP, premium currency, or real-money requests.
        if 'skillGridRevivalAllowanceLP' not in saved:
            value['gamePoint'] = roi_skills.integer(value.get('gamePoint', 0), 0, 2147483645) + 2
            value['skillGridRevivalAllowanceLP'] = 2
        value = roi_skills.migrate_original_rewards(value)
        roi_skills.grids(value)
        profile_store.update(path, value)
        return {'changed': True, 'backup': str(backup), 'grids': len(value['skillGrids']),
                'opened_cells': [row['sv_openedSlot'] for row in value['skillGrids']],
                'rules': 'Original reward-right mechanism; exact level schedule unrecovered, no guessed grants; five loadouts. Grid price remains a revival setting.'}


if __name__ == '__main__':
    print(json.dumps(initialize(Path(__file__).resolve().parent / 'player_profile.json'), indent=2))
