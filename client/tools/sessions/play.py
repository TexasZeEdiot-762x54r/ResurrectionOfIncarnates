"""Session used by the launcher: scene changes, crash dumps, missing resources and C runtime errors only
(no per-frame hooks), written to logs/play.log."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sessions.observe import SCENES  # noqa: E402


def setup(d):
    from sessions import library_pages
    library_pages.setup(d)
    from sessions import tutorial_resources
    tutorial_resources.setup(d)
    from sessions import stage_ambience
    stage_ambience.setup(d)
    from sessions import audio_lifetime
    audio_lifetime.setup(d)
    from sessions import result_flow
    result_flow.setup(d)
    for addr, name in SCENES.items():
        d.bp(addr, lambda h, n=name: d.log(f"SCENE create {n}"))

    def res_missing(h):  # 0x140b69dea: rax = resource from 0x1407bb6d0, rbx = requested name
        if h.rax == 0:
            d.log(f"MISSING resource {h.str(h.rbx, 200)!r}")

    d.bp(0x140B69DEA, res_missing)

    def watson(h):
        d.log("INVALID PARAMETER (_invoke_watson); call chain:")
        for i, call, op in d.call_chain(h.rsp, 0x3000)[:20]:
            d.log(f"   stack+{i:x}: call at {d.describe(call)} -> {op}")

    for fn in ("_invoke_watson", "_invalid_parameter", "_invalid_parameter_noinfo"):
        d.bp_export("msvcr100.dll", fn, watson)
