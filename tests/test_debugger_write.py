import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "client/tools/dbg.py"
ADDRESS = 0x12345000
PAYLOAD = b"\x90\x90"


class FakeKernel:
    def __init__(self, *, protect=True, write=True, count=None, restore=True,
                 flush=True, protect_exception=None, write_exception=None,
                 restore_exception=None, flush_exception=None):
        self.protect = protect
        self.write_ok = write
        self.count = count
        self.restore = restore
        self.flush = flush
        self.protect_exception = protect_exception
        self.write_exception = write_exception
        self.restore_exception = restore_exception
        self.flush_exception = flush_exception
        self.calls = []
        self.error = 0

    def VirtualProtectEx(self, process, address, size, protection, old):
        restoring = any(call[0] == "protect" for call in self.calls)
        self.calls.append(("restore" if restoring else "protect",
                           process, address.value, size, protection))
        if restoring:
            if self.restore_exception:
                raise self.restore_exception
            self.error = 87
            old._obj.value = 0x40
            return self.restore
        if self.protect_exception:
            raise self.protect_exception
        self.error = 5
        old._obj.value = 0x20
        return self.protect

    def WriteProcessMemory(self, process, address, data, size, got):
        self.calls.append(("write", process, address.value, size, bytes(data)))
        if self.write_exception:
            raise self.write_exception
        self.error = 299
        got._obj.value = size if self.count is None else self.count
        return self.write_ok

    def FlushInstructionCache(self, process, address, size):
        self.calls.append(("flush", process, address.value, size))
        if self.flush_exception:
            raise self.flush_exception
        self.error = 6
        return self.flush


def load_debugger(kernel):
    # Extract methods only: importing dbg would load native APIs and local paths.
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    source_class = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == "Debugger")
    methods = [node for node in source_class.body
               if isinstance(node, ast.FunctionDef) and node.name in ("write", "_arm")]
    isolated = ast.Module(body=[ast.ClassDef(name="Debugger", bases=[], keywords=[],
                                           body=methods, decorator_list=[])], type_ignores=[])
    safe_ctypes = SimpleNamespace(c_void_p=ctypes.c_void_p, c_size_t=ctypes.c_size_t,
                                  byref=ctypes.byref,
                                  get_last_error=lambda: kernel.error)
    namespace = {"ctypes": safe_ctypes, "wt": SimpleNamespace(DWORD=ctypes.c_uint32),
                 "k32": kernel}
    exec(compile(ast.fix_missing_locations(isolated), str(SOURCE), "exec"), namespace)
    debugger = namespace["Debugger"]()
    debugger.hproc = 101
    return debugger


class DebuggerWriteTests(unittest.TestCase):
    def invoke_failure(self, kernel, stage):
        with self.assertRaises(OSError) as caught:
            load_debugger(kernel).write(ADDRESS, PAYLOAD)
        self.assertIn(stage, str(caught.exception))
        self.assertIn(hex(ADDRESS), str(caught.exception))
        return caught.exception

    def stages(self, kernel):
        return [call[0] for call in kernel.calls]

    def test_success_requires_all_stages_and_restores_original_protection(self):
        kernel = FakeKernel()
        self.assertIs(load_debugger(kernel).write(ADDRESS, PAYLOAD), True)
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore", "flush"])
        self.assertEqual(kernel.calls[0], ("protect", 101, ADDRESS, 2, 0x40))
        self.assertEqual(kernel.calls[1], ("write", 101, ADDRESS, 2, PAYLOAD))
        self.assertEqual(kernel.calls[2], ("restore", 101, ADDRESS, 2, 0x20))
        self.assertEqual(kernel.calls[3], ("flush", 101, ADDRESS, 2))

    def test_initial_protection_failure_does_not_write_restore_or_flush(self):
        kernel = FakeKernel(protect=False)
        self.assertEqual(self.invoke_failure(kernel, "VirtualProtectEx").errno, 5)
        self.assertEqual(self.stages(kernel), ["protect"])

    def test_initial_protection_exception_does_not_write_restore_or_flush(self):
        kernel = FakeKernel(protect_exception=OSError("fixture protect failure"))
        self.invoke_failure(kernel, "VirtualProtectEx")
        self.assertEqual(self.stages(kernel), ["protect"])

    def test_failed_write_is_not_success_even_when_full_count_is_reported(self):
        kernel = FakeKernel(write=False)
        self.assertEqual(self.invoke_failure(kernel, "WriteProcessMemory").errno, 299)
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_failed_write_with_no_bytes_still_restores(self):
        kernel = FakeKernel(write=False, count=0)
        self.invoke_failure(kernel, "WriteProcessMemory")
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_short_and_excess_reported_writes_are_not_success(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                kernel = FakeKernel(count=count)
                self.invoke_failure(kernel, "WriteProcessMemory")
                self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_restoration_failure_is_not_success_and_does_not_flush(self):
        kernel = FakeKernel(restore=False)
        self.assertEqual(self.invoke_failure(kernel, "VirtualProtectEx").errno, 87)
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_restoration_exception_after_full_write_is_not_success(self):
        kernel = FakeKernel(restore_exception=OSError("fixture restore failure"))
        self.invoke_failure(kernel, "VirtualProtectEx")
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_both_write_and_restoration_failure_contexts_are_retained(self):
        kernel = FakeKernel(write=False, count=0, restore=False)
        error = self.invoke_failure(kernel, "WriteProcessMemory")
        self.assertIn("VirtualProtectEx", str(error))
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_write_exception_still_attempts_restoration(self):
        kernel = FakeKernel(write_exception=OSError("fixture write failure"))
        with self.assertRaises(OSError):
            load_debugger(kernel).write(ADDRESS, PAYLOAD)
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_restoration_exception_does_not_hide_write_failure(self):
        kernel = FakeKernel(write=False, count=0,
                            restore_exception=OSError("fixture restore failure"))
        error = self.invoke_failure(kernel, "WriteProcessMemory")
        self.assertIn("fixture restore failure", str(error))
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_flush_failure_is_not_success(self):
        kernel = FakeKernel(flush=False)
        self.assertEqual(self.invoke_failure(kernel, "FlushInstructionCache").errno, 6)
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore", "flush"])

    def test_flush_exception_is_not_success(self):
        kernel = FakeKernel(flush_exception=OSError("fixture flush failure"))
        self.invoke_failure(kernel, "FlushInstructionCache")
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore", "flush"])

    def test_write_and_restoration_exceptions_both_remain_visible(self):
        kernel = FakeKernel(write_exception=OSError("fixture write failure"),
                            restore_exception=OSError("fixture restore failure"))
        error = self.invoke_failure(kernel, "WriteProcessMemory")
        self.assertIn("fixture write failure", str(error))
        self.assertIn("fixture restore failure", str(error))
        self.assertEqual(self.stages(kernel), ["protect", "write", "restore"])

    def test_breakpoint_arm_does_not_swallow_write_failure(self):
        kernel = FakeKernel(protect=False)
        debugger = load_debugger(kernel)
        debugger.bps = {ADDRESS: [None, None]}
        debugger.read = lambda address, size: b"\x90"
        debugger.log = lambda *args: None
        with self.assertRaises(OSError):
            debugger._arm(ADDRESS)
        self.assertEqual(self.stages(kernel), ["protect"])


if __name__ == "__main__":
    unittest.main()
