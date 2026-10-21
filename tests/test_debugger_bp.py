import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'client/tools/dbg.py'
ADDRESS = 0x12345000


def load_debugger():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    source_class = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == 'Debugger')
    methods = [node for node in source_class.body
               if isinstance(node, ast.FunctionDef) and node.name in ('bp', '_arm')]
    isolated = ast.Module(body=[ast.ClassDef(name='Debugger', bases=[], keywords=[],
                                           body=methods, decorator_list=[])], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(isolated), str(SOURCE), 'exec'), namespace)
    return namespace['Debugger']()


class MockDebuggerTests(unittest.TestCase):
    def setUp(self):
        self.debugger = load_debugger()
        self.debugger.hproc = 101
        self.debugger.bps = {}
        self.debugger.rearm = {}
        self.memory = {ADDRESS: b'\x90'}
        self.writes = []

        def read(address, size):
            return self.memory.get(address, b'')[:size]

        def write(address, data):
            self.writes.append((address, data))
            self.memory[address] = data
            return True

        self.debugger.read = read
        self.debugger.write = write

    def test_replacing_handler_preserves_original_byte_and_does_not_rearm(self):
        first = lambda _hit: None
        replacement = lambda _hit: None
        self.debugger.bp(ADDRESS, first)
        self.assertEqual(self.debugger.bps[ADDRESS], [b'\x90', first])
        self.assertEqual(self.memory[ADDRESS], b'\xcc')

        self.debugger.bp(ADDRESS, replacement)

        self.assertEqual(self.debugger.bps[ADDRESS], [b'\x90', replacement])
        self.assertEqual(self.memory[ADDRESS], b'\xcc')
        self.assertEqual(self.writes, [(ADDRESS, b'\xcc')])

    def test_replacing_handler_during_pending_single_step_keeps_rearm_state(self):
        first = lambda _hit: None
        replacement = lambda _hit: None
        self.debugger.bps[ADDRESS] = [b'\x90', first]
        self.debugger.rearm = {7: ADDRESS}

        self.debugger.bp(ADDRESS, replacement)

        self.assertEqual(self.debugger.bps[ADDRESS], [b'\x90', replacement])
        self.assertEqual(self.debugger.rearm, {7: ADDRESS})
        self.assertEqual(self.writes, [])

    def test_queued_registration_replacement_arms_original_byte_at_start(self):
        first = lambda _hit: None
        replacement = lambda _hit: None
        self.debugger.hproc = None
        self.debugger.bp(ADDRESS, first)
        self.debugger.bp(ADDRESS, replacement)
        self.assertEqual(self.debugger.bps[ADDRESS], [None, replacement])
        self.assertEqual(self.writes, [])

        self.debugger.hproc = 101
        self.debugger._arm(ADDRESS)

        self.assertEqual(self.debugger.bps[ADDRESS], [b'\x90', replacement])
        self.assertEqual(self.memory[ADDRESS], b'\xcc')
        self.assertEqual(self.writes, [(ADDRESS, b'\xcc')])


if __name__ == '__main__':
    unittest.main()
