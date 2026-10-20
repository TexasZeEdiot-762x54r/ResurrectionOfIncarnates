"""Native 4x4 grids, diagnostic fallback and opt-in original level-one cubes."""
from copy import deepcopy

CELLS = tuple(f'sv_x{x}y{y}' for y in range(4) for x in range(4))
BASE_CELLS = frozenset(('sv_x1y1', 'sv_x2y1', 'sv_x1y2', 'sv_x2y2'))
MAX_GRIDS = 5  # Native profile storage and UI index checks both support five loadouts.
HOLD_ID = 1
CUBE_ID = 1


def enabled(saved):
    return saved.get('diagnosticSkillCube') is True or saved.get('originalSkillCubes') is True


def master(saved=None):
    rows = [{'_id': str(CUBE_ID), 'sv_skillcubeId': str(CUBE_ID),
             'sv_skillcubeIconId': 'at_suit_d', 'sv_skillcubeRank': 'D',
             'sv_skillcubeShape': 'D01',
             'sv_skillcubeName': '251000', 'sv_skillcubeDesc': '251001',
             'sv_skillcubeRarityId': '0', 'sv_effects': [],
             'sv_cobeCount': '2', 'sv_skillcubePrice': '0',
             'sv_skillcubeStatus': '1', 'sv_skillcubeCategory': '0', 'sv_sort': '0'}]
    if saved is not None and saved.get('diagnosticSkillCube') is not True:
        rows = []
    if saved and saved.get('originalSkillCubes') is True:
        import roi_skill_catalogue
        rows.extend(roi_skill_catalogue.master())
    return rows


def inventory(saved):
    if not enabled(saved):
        return []
    rows = [{'sv_skillcubeHoldId': str(HOLD_ID), 'sv_skillcubeId': str(CUBE_ID),
             'sv_triggerCount': '0', 'sv_triggerLimit': '100',
             'sv_levelupCount': '0', 'sv_evolutionCount': '0',
             'sv_modificationCount': '0', 'sv_recoveryCount': '0',
             'sv_skillLevel': '1', 'sv_skillExp': '0', 'sv_status': '0'}]
    if saved.get('diagnosticSkillCube') is not True:
        rows = []
    if saved.get('originalSkillCubes') is True:
        import roi_skill_catalogue
        rows.extend(roi_skill_catalogue.inventory())
    return rows


def empty_grid(grid_id=0, *, progressive=False):
    opened = BASE_CELLS if progressive else CELLS
    return dict(sv_sgridId=str(grid_id), sv_openedSlot=str(len(opened)), sv_unlockedSlotItem='0',
                sv_skillcubeHoldIds=[], sv_gridStatus='0',
                **{key: '0' if key in opened else '-1' for key in CELLS})


def progression(saved):
    return bool(saved and saved.get('skillGridProgression') is True)


def expansion_allowance(saved, grid_id=None):
    """Original mode consumes recovered reward rows, never a guessed per-level formula."""
    mode = saved.get('skillGridUnlockMode')
    # Schema-2 profiles are readable until the backed-up migration is run.
    legacy = mode == 'revival' or mode is None and saved.get('skillGridSchema') == 2
    if not legacy:
        import roi_grid_rewards
        allowance = roi_grid_rewards.earned_rights(saved.get('playerLevel', 1))
        preserved = saved.get('skillGridPreservedExpansions', {})
        if not isinstance(preserved, dict):
            raise ValueError('Invalid preserved grid expansions')
        retained = integer(preserved.get(str(grid_id), 0), 0, 12) if grid_id is not None else 0
        return max(allowance, retained)
    # Retained only as an explicitly selected, non-original compatibility mode.
    level = integer(saved.get('playerLevel', 1), 1, 49)
    levels = saved.get('skillGridExpansionLevels', list(range(6, 18)))
    if not isinstance(levels, list) or len(levels) > 12:
        raise ValueError('Invalid expansion-level schedule')
    normalized = [integer(v, 1, 49) for v in levels]
    if normalized != sorted(set(normalized)):
        raise ValueError('Expansion levels must be unique and increasing')
    return sum(level >= threshold for threshold in normalized)


def _metadata(grid, saved):
    opened = sum(integer(grid[key], -1, (1 << 64) - 1) not in (-1, (1 << 64) - 1) for key in CELLS)
    if progression(saved):
        if not BASE_CELLS <= {key for key in CELLS if grid[key] not in ('-1', str((1 << 64) - 1))}:
            raise ValueError('Base cells cannot be locked')
        allowance = expansion_allowance(saved, grid['sv_sgridId'])
        if opened > 4 + allowance:
            raise ValueError('Grid exceeds its earned expansion allowance')
        grid['sv_openedSlot'] = str(opened)
        grid['sv_unlockedSlotItem'] = str(4 + allowance - opened)
    return grid


def integer(value, minimum, maximum):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and (value.isascii() and value.isdigit() or value == '-1'):
        if len(value) > 20:
            raise ValueError('Grid number is too long')
        number = int(value)
    else:
        raise ValueError('Grid value is not an integer')
    if not minimum <= number <= maximum:
        raise ValueError('Grid value is outside its allowed range')
    return number


def validate_grids(value, saved=None):
    original_mode = bool(saved and saved.get('originalSkillCubes') is True)
    counts = {HOLD_ID: (2, 3)}
    if original_mode:
        import roi_skill_catalogue
        counts.update({hold: (count,) for hold, count in roi_skill_catalogue.block_counts().items()})
        if saved.get('diagnosticSkillCube') is not True:
            counts.pop(HOLD_ID)
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_GRIDS:
        raise ValueError('Invalid number of skill grids')
    expected = None
    if saved and 'skillGrids' in saved:
        expected = {integer(row['sv_sgridId'], 0, MAX_GRIDS - 1): row for row in saved['skillGrids']}
        if len(value) != len(expected):
            raise ValueError('Placement cannot create or delete loadouts')
    elif progression(saved):
        expected = {0: _metadata(empty_grid(progressive=True), saved)}
        if len(value) != 1:
            raise ValueError('Placement cannot create loadouts')
    result, ids = [], set()
    for source in value:
        if not isinstance(source, dict):
            raise ValueError('Invalid grid')
        grid_id = integer(source.get('sv_sgridId'), 0, MAX_GRIDS - 1)
        if grid_id in ids or expected is not None and grid_id not in expected:
            raise ValueError('Duplicate or unowned grid')
        ids.add(grid_id)
        result.append(_validate_grid(source, counts, original_mode, saved or {},
                                     expected.get(grid_id) if expected is not None else None))
    if ids != set(range(len(result))):
        raise ValueError('Loadout IDs must be contiguous')
    return sorted(result, key=lambda row: int(row['sv_sgridId']))


def _validate_grid(source, counts, original_mode, saved, expected):
    if not set(CELLS) <= source.keys():
        raise ValueError('Missing native 4x4 grid cells')
    result = empty_grid(integer(source['sv_sgridId'], 0, MAX_GRIDS - 1))
    holds = set()
    occupied = {}
    for key in CELLS:
        cell = integer(source[key], -1, (1 << 64) - 1)
        if cell == (1 << 64) - 1:
            cell = -1
        if expected is not None:
            old = integer(expected[key], -1, (1 << 64) - 1)
            if (old in (-1, (1 << 64) - 1)) != (cell == -1):
                raise ValueError('Placement cannot change locked cells')
        if cell > 0:
            hold, part = divmod(cell, 100)
            if hold not in counts or part >= 16:
                raise ValueError('Grid references an unowned cube or invalid part')
            holds.add(hold)
            parts = occupied.setdefault(hold, [])
            parts.append(part)
        result[key] = str(cell)
    for hold, parts in occupied.items():
        if len(parts) not in counts[hold]:
            raise ValueError('Incomplete or duplicated cube')
        # Reloaded original cubes can emit tag zero in every occupied cell.
        # Preserve that native encoding; nonzero legacy part tags remain unique.
        if original_mode and hold != HOLD_ID and any(parts) and len(set(parts)) != len(parts):
            raise ValueError('Duplicated cube part')
    sent_holds = source.get('sv_skillcubeHoldIds', [])
    if not isinstance(sent_holds, list) or len(sent_holds) > (16 if original_mode else 1):
        raise ValueError('Unexpected equipped-cube list')
    normalized = [integer(v, 1, max(counts)) for v in sent_holds]
    if len(set(normalized)) != len(normalized) or set(normalized) != holds:
        raise ValueError('Equipped-cube list does not match grid cells')
    result['sv_skillcubeHoldIds'] = [str(v) for v in sorted(holds)]
    if progression(saved):
        _metadata(result, saved)
    # Never grant expansion credit or change ownership from client-supplied metadata.
    for key in ('sv_openedSlot', 'sv_unlockedSlotItem', 'sv_gridStatus'):
        number = int(result[key])
        if integer(source.get(key, number), number, number) != number:
            raise ValueError('Expansion metadata cannot be changed')
    return result


def grids(saved):
    if not enabled(saved):
        return []
    value = deepcopy(saved.get('skillGrids', [empty_grid(progressive=progression(saved))]))
    # Migrate the first diagnostic schema only; original inventories are not involved.
    if len(value) == 1 and value[0].get('sv_sgridId') == '1' and value[0].get('sv_openedSlot') == '0':
        value[0].update(sv_sgridId='0', sv_openedSlot='16')
    for row in value:
        _metadata(row, saved)
    return deepcopy(validate_grids(value, dict(saved, skillGrids=value)))


def update_grids(value, saved):
    """Native placement sends only dirty grids; merge without dropping other loadouts."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_GRIDS:
        raise ValueError('Invalid grid update')
    current = grids(saved)
    merged = deepcopy(current)
    seen = set()
    for source in value:
        if not isinstance(source, dict):
            raise ValueError('Invalid grid')
        grid_id = integer(source.get('sv_sgridId'), 0, len(current) - 1)
        if grid_id in seen:
            raise ValueError('Duplicate grid update')
        seen.add(grid_id)
        merged[grid_id] = source
    return validate_grids(merged, dict(saved, skillGrids=current))


def extend(saved, requests):
    """Native extendSkillGrid: openGrids=[{sv_sgridId,sv_slotKeys:[sv_xNyN]}]."""
    if not progression(saved) or not isinstance(requests, list) or not 1 <= len(requests) <= MAX_GRIDS:
        raise ValueError('Invalid expansion request')
    value = grids(saved)
    seen = set()
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError('Invalid expansion')
        grid_id = integer(request.get('sv_sgridId'), 0, len(value) - 1)
        keys = request.get('sv_slotKeys')
        if grid_id in seen or not isinstance(keys, list) or not 1 <= len(keys) <= 12:
            raise ValueError('Invalid expansion cells')
        seen.add(grid_id)
        if any(type(key) is not str or key not in CELLS for key in keys) or len(set(keys)) != len(keys):
            raise ValueError('Unknown or duplicate cell')
        grid = value[grid_id]
        if len(keys) > int(grid['sv_unlockedSlotItem']):
            raise ValueError('No expansion credits remaining')
        for key in keys:
            if grid[key] != '-1':
                raise ValueError('Cell already open')
            x, y = int(key[4]), int(key[6])
            adjacent = [f'sv_x{nx}y{ny}' for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1))
                        if 0 <= nx < 4 and 0 <= ny < 4]
            if not any(grid[neighbor] != '-1' for neighbor in adjacent):
                raise ValueError('Expansion must connect to an open cell')
            grid[key] = '0'
        _metadata(grid, saved)
    return value


def add_grid(saved):
    value = grids(saved)
    if len(value) >= MAX_GRIDS:
        raise ValueError('All supported loadouts are owned')
    value.append(_metadata(empty_grid(len(value), progressive=progression(saved)), saved))
    return value


def migrate_progression(saved):
    """Archive the diagnostic board; unequip whole cubes instead of retaining partial shapes."""
    if progression(saved):
        return deepcopy(saved)
    result = deepcopy(saved)
    old = grids(saved)
    result.update(skillGridProgression=True, skillGridSchema=2)
    result['skillGridsBeforeProgression'] = deepcopy(old)
    result['skillGrids'] = []
    allowance = expansion_allowance(result)
    for row in old:
        new = empty_grid(int(row['sv_sgridId']), progressive=True)
        # Deterministic revival opening order, keeping the central four cells connected.
        order = ('sv_x0y1','sv_x0y2','sv_x3y1','sv_x3y2','sv_x1y0','sv_x2y0',
                 'sv_x1y3','sv_x2y3','sv_x0y0','sv_x3y0','sv_x0y3','sv_x3y3')
        for key in order[:allowance]:
            new[key] = '0'
        positions = {}
        for key in CELLS:
            cell = int(row[key])
            if cell > 0:
                positions.setdefault(cell // 100, []).append(key)
        for hold, keys in positions.items():
            if all(new[key] == '0' for key in keys):
                for key in keys:
                    new[key] = row[key]
                new['sv_skillcubeHoldIds'].append(str(hold))
        result['skillGrids'].append(_metadata(new, result))
    return result


def migrate_original_rewards(saved):
    """Stop invented future grants, retaining all already-open cells and placed cubes."""
    if saved.get('skillGridSchema') == 3 and saved.get('skillGridUnlockMode') == 'original_rewards':
        return deepcopy(saved)
    result = deepcopy(saved)
    current = grids(saved)
    result['skillGridLegacyUnlockPolicy'] = {
        'schema': saved.get('skillGridSchema'),
        'mode': saved.get('skillGridUnlockMode', 'revival'),
        'expansion_levels': saved.get('skillGridExpansionLevels', list(range(6, 18))),
        'grids': deepcopy(current),
    }
    # profile_store.update merges fields, so explicitly clear the superseded schedule.
    result['skillGridExpansionLevels'] = []
    result.update(skillGridSchema=3, skillGridUnlockMode='original_rewards',
                  skillGridPreservedExpansions={row['sv_sgridId']: max(0, sum(row[key] != '-1' for key in CELLS) - 4)
                                               for row in current})
    result['skillGrids'] = [_metadata(row, result) for row in current]
    grids(result)
    return result
