import sys
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1] / 'client' / 'tools'
sys.path.insert(0, str(TOOLS))
import roi_skills
import roi_server_data


class SkillGridInvariantTests(unittest.TestCase):
    def make_grid(self, grid_id, x, y):
        grid = roi_skills.empty_grid(grid_id)
        grid[f'sv_x{x}y{y}'] = '100'
        grid[f'sv_x{x + 1}y{y}'] = '101'
        grid['sv_skillcubeHoldIds'] = ['1']
        return grid

    def test_five_layouts_are_independent_and_can_reuse_inventory_hold(self):
        grids = [self.make_grid(grid_id, 0, grid_id % 4) for grid_id in range(5)]
        saved = {'diagnosticSkillCube': True, 'skillGrids': grids}
        saved_snapshot = deepcopy(saved)
        before = roi_skills.grids(saved)

        changed = self.make_grid(2, 2, 2)
        changed_snapshot = deepcopy(changed)
        after = roi_skills.update_grids([changed], saved)
        validated = roi_skills.validate_grids(after, dict(saved, skillGrids=before))

        self.assertEqual([row['sv_sgridId'] for row in after], ['0', '1', '2', '3', '4'])
        self.assertEqual(after, validated)
        self.assertEqual(after[2]['sv_x2y2'], '100')
        self.assertEqual(after[2]['sv_x3y2'], '101')
        for grid_id in (0, 1, 3, 4):
            self.assertEqual(after[grid_id], before[grid_id])
        self.assertEqual([row['sv_skillcubeHoldIds'] for row in after], [['1']] * 5)
        self.assertEqual(saved, saved_snapshot)
        self.assertEqual(changed, changed_snapshot)

    def test_grid_validation_cannot_create_an_extra_layout(self):
        saved = {
            'diagnosticSkillCube': True,
            'skillGrids': [self.make_grid(grid_id, 0, 0) for grid_id in range(5)],
        }
        with self.assertRaisesRegex(ValueError, 'Invalid number of skill grids'):
            roi_skills.validate_grids(saved['skillGrids'] + [self.make_grid(5, 0, 0)], saved)

    def test_dirty_update_cannot_create_or_delete_layouts(self):
        saved = {
            'diagnosticSkillCube': True,
            'skillGrids': [self.make_grid(grid_id, 0, 0) for grid_id in range(5)],
        }
        with self.assertRaisesRegex(ValueError, 'Invalid grid update'):
            roi_skills.update_grids([], saved)
        with self.assertRaisesRegex(ValueError, 'Placement cannot create or delete loadouts'):
            roi_skills.validate_grids(saved['skillGrids'][:4], saved)

    def test_saving_grid_does_not_create_unverified_level_rights(self):
        saved = {
            'diagnosticSkillCube': True,
            'skillGridProgression': True,
            'skillGridSchema': 3,
            'skillGridUnlockMode': 'original_rewards',
            'playerLevel': 15,
        }
        grid = roi_skills.grids(saved)[0]
        with patch.object(roi_server_data, 'saved', return_value=saved), \
                patch.object(roi_server_data, 'save') as save, \
                patch.object(roi_server_data, 'publish_profile'), \
                patch.object(roi_server_data.time, 'time', return_value=1234):
            response = roi_server_data.update_skill_grid({'sv_grids': [grid]})

        self.assertEqual(response['result'], 'OK')
        stored = save.call_args.kwargs['skillGrids'][0]
        self.assertEqual(stored['sv_openedSlot'], '4')
        self.assertEqual(stored['sv_unlockedSlotItem'], '0')
        self.assertEqual(save.call_args.kwargs.keys(), {'skillGrids'})


if __name__ == '__main__':
    unittest.main()
