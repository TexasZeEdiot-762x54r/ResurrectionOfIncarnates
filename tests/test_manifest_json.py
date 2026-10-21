import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import audit_public
import refresh_manifests


def load_check_launch():
    path = ROOT / 'client/tools/check_launch.py'
    spec = importlib.util.spec_from_file_location('manifest_json_check_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StrictManifestJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_public_audit_rejects_duplicate_metadata_and_hash_entries(self):
        for manifest in (
            b'{"format":"a","format":"b","sha256":{}}',
            b'{"format":"a","sha256":{"file":"' + b'0' * 64 + b'","file":"' + b'0' * 64 + b'"}}',
        ):
            with self.subTest(manifest=manifest):
                (self.root / 'PUBLIC-MANIFEST.json').write_bytes(manifest)
                with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                    audit_public.audit(self.root)

    def test_package_validator_rejects_duplicate_metadata_and_file_entries(self):
        checker = load_check_launch()
        for manifest in (
            b'{"version":"v1","version":"v2","kind":"client","sha256":{"file.txt":"' + b'0' * 64 + b'"}}',
            b'{"version":"v1","kind":"client","sha256":{"file.txt":"' + b'0' * 64 + b'","file.txt":"' + b'0' * 64 + b'"}}',
        ):
            with self.subTest(manifest=manifest):
                (self.root / 'PACKAGE-MANIFEST.json').write_bytes(manifest)
                with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                    checker.validate_package(self.root)

    def test_refresh_rejects_duplicate_keys_before_any_manifest_write(self):
        (self.root / 'client').mkdir()
        (self.root / 'server').mkdir()
        public = self.root / 'PUBLIC-MANIFEST.json'
        client = self.root / 'client/PACKAGE-MANIFEST.json'
        server = self.root / 'server/PACKAGE-MANIFEST.json'
        original = b'{"version":"v1","version":"v2","sha256":{}}'
        public.write_bytes(original)
        client.write_bytes(b'client before')
        server.write_bytes(b'server before')
        before = {path: path.read_bytes() for path in (public, client, server)}
        with patch.object(refresh_manifests, 'ROOT', self.root):
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
                refresh_manifests.main()
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_duplicate_nested_map_keys_are_rejected(self):
        checker = load_check_launch()
        (self.root / 'PACKAGE-MANIFEST.json').write_bytes(
            b'{"version":"v1","kind":"client","sha256":{"outer":{"x":1,"x":2}}}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON object key'):
            checker.validate_package(self.root)


if __name__ == '__main__':
    unittest.main()
