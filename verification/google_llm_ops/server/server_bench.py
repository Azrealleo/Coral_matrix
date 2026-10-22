"""Standalone entry: execute the unchanged canonical per-case test body."""
import os
from pathlib import Path
import sys
import types
import cocotb
import packet

# Only a compatibility import, not a fake runfile success. All actual file
# requests below are allowlisted and must exist in the verified packet/model.
for name in ("bazel_tools","bazel_tools.tools","bazel_tools.tools.python","bazel_tools.tools.python.runfiles"):
    if name not in sys.modules:
        item=types.ModuleType(name);item.__path__=[];sys.modules[name]=item
shim=types.ModuleType("bazel_tools.tools.python.runfiles.runfiles");shim.Create=lambda:None
sys.modules[shim.__name__]=shim;sys.modules["bazel_tools.tools.python.runfiles"].runfiles=shim


def canonical(bundle,family,rtl_root):
    h=bundle.helpers
    path=bundle.root/("linear/linear_rtl_bench.py" if family=="int8" else "transformer/tx_bench.py")
    tree=packet.projected_bench(path.read_text(),{"runfile"} if family=="int8" else {"locate"})
    result=types.ModuleType("_llm_canonical_bench");result.__file__=str(path)
    with packet.isolated_modules(dict(spec=h.linear,audit=h.linear_audit,tx_spec=h.tx,tx_audit=h.tx_audit)):
        exec(compile(tree,str(path),"exec"),result.__dict__)

    def locate(package_name,name):
        allowed=h.linear.PACKAGE if name!="probe_program.elf" or family=="int8" else h.tx.PACKAGE
        if package_name!=allowed:raise ValueError("Unexpected canonical runfile package")
        files={"probe_program.elf":bundle.root/"firmware"/family/"probe_program.elf",
            "V"+packet.TOP+"_parameters.h":bundle.root/"parameters.h",
            packet.TOP+".sv":Path(rtl_root)/"rtl"/(packet.TOP+".sv")}
        if name not in files or not files[name].is_file():raise ValueError("Missing/unexpected canonical runfile")
        return files[name]
    if family=="int8":result.runfile=lambda name:locate(h.linear.PACKAGE,name)
    else:result.locate=locate
    return result


@cocotb.test()
async def server_operator_test(dut):
    if os.environ.get("LLM_SERVER_CHILD")!="1":raise ValueError("Needs qualified parent runner")
    bundle=packet.load(os.environ["LLM_PACKET"])
    family=os.environ["LLM_FAMILY"];index=int(os.environ["LLM_CASE"])
    if family not in ("int8","fp32") or not 0<=index<(4 if family=="int8" else 17):raise ValueError("Wrong case")
    bench=canonical(bundle,family,os.environ["LLM_RTL_PACKAGE"])
    await bench.run_case(dut,index)
