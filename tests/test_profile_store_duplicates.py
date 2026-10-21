import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_store(path, index):
    spec = importlib.util.spec_from_file_location(f'isolated_profile_store_{index}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfileStoreDuplicateTests(unittest.TestCase):
    sources = (ROOT / 'client/tools/profile_store.py',)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_duplicate_keys_fail_before_any_update_write_and_preserve_bytes(self):
        fixtures = (
            b'{"gamePoint":10,"gamePoint":20}',
            b'{"circleCapacityPending":{"operation":"first","operation":"second"}}',
        )
        for index, source in enumerate(self.sources):
            store = load_store(source, index)
            for fixture_index, raw in enumerate(fixtures):
                path = self.root / f'profile-{index}-{fixture_index}.json'
                path.write_bytes(raw)
                with self.subTest(source=source, fixture=fixture_index):
                    with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                        store.read(path)
                    with patch.object(store.tempfile, 'mkstemp', wraps=store.tempfile.mkstemp) as mkstemp, \
                         patch.object(store.os, 'replace', wraps=store.os.replace) as replace:
                        with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                            store.update(path, {'unrelated': True})
                    mkstemp.assert_not_called()
                    replace.assert_not_called()
                    self.assertEqual(path.read_bytes(), raw)
                    self.assertEqual(list(self.root.glob('profile-*.tmp')), [])

    def test_nested_duplicate_keys_are_rejected_at_every_object_depth(self):
        for index, source in enumerate(self.sources):
            store = load_store(source, index)
            path = self.root / f'nested-{index}.json'
            path.write_text('{"outer":{"inner":{"same":1,"same":2}}}', encoding='utf-8')
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                store.read(path)

    def test_missing_and_valid_profiles_keep_existing_behavior(self):
        for index, source in enumerate(self.sources):
            store = load_store(source, index)
            path = self.root / f'valid-{index}.json'
            with self.subTest(source=source):
                self.assertEqual(store.read(path), {})
                store.update(path, {'gamePoint': 12})
                self.assertEqual(store.read(path), {'gamePoint': 12})


if __name__ == '__main__':
    unittest.main()
