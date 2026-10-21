import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "client/tools/build_safety.py"
SPEC = importlib.util.spec_from_file_location("build_safety", MODULE_PATH)
build_safety = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_safety)


class BuildOutputSafetyTests(unittest.TestCase):
    def test_rejects_same_path_and_normalized_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "steam" / "roi.exe"
            source.parent.mkdir()
            source.write_bytes(b"fixture executable")

            aliases = (
                source,
                source.parent / "." / "roi.exe",
                source.parent / "unused" / ".." / "roi.exe",
            )
            for output in aliases:
                with self.subTest(output=output):
                    with self.assertRaises(ValueError):
                        build_safety.ensure_distinct_output(source, output)

    def test_rejects_existing_file_identity_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "steam.exe"
            source.write_bytes(b"fixture executable")
            alias = root / "same-file.exe"
            try:
                alias.hardlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this filesystem")

            with self.assertRaises(ValueError):
                build_safety.ensure_distinct_output(source, alias)

    def test_rejects_symlink_alias_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "steam.exe"
            source.write_bytes(b"fixture executable")
            alias = root / "linked.exe"
            try:
                alias.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("file symlinks are unavailable on this system")

            with self.assertRaises(ValueError):
                build_safety.ensure_distinct_output(source, alias)

    def test_accepts_a_distinct_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "steam.exe"
            output = root / "game" / "roi.exe"
            source.write_bytes(b"fixture executable")
            self.assertEqual(build_safety.ensure_distinct_output(source, output), output)

    def test_accepts_a_distinct_existing_output_without_modifying_either_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output = root / 'steam.exe', root / 'patched.exe'
            source.write_bytes(b'clean fixture')
            output.write_bytes(b'previous build fixture')
            self.assertEqual(build_safety.ensure_distinct_output(source, output), output)
            self.assertEqual(source.read_bytes(), b'clean fixture')
            self.assertEqual(output.read_bytes(), b'previous build fixture')

    def test_file_identity_permission_errors_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(build_safety.os.path, 'samefile', side_effect=PermissionError('fixture')):
                with self.assertRaises(PermissionError):
                    build_safety.ensure_distinct_output(root / 'source.exe', root / 'output.exe')


class BuildSafetyIntegrationTests(unittest.TestCase):
    def test_builder_checks_output_before_reading_source(self):
        tree = ast.parse(MODULE_PATH.with_name('build.py').read_text(encoding='utf-8'))
        build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build')
        first = build.body[0]
        self.assertIsInstance(first, ast.Assign)
        self.assertEqual(ast.dump(first.value, include_attributes=False),
                         ast.dump(ast.parse('ensure_distinct_output(SRC, out)', mode='eval').body,
                                  include_attributes=False))
        self.assertEqual(first.targets[0].id, 'out')

    def test_build_helper_is_in_the_client_component_inventory(self):
        manifest = json.loads((MODULE_PATH.parents[1] / 'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
        self.assertTrue('tools/build_safety.py' in manifest['sha256'],
                        'New build helper is missing from the client component manifest')


if __name__ == "__main__":
    unittest.main()
