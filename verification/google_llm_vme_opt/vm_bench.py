"""Bazel VM entry. Shared exact test body; no implicit all-case execution."""
import os
from pathlib import Path
from types import SimpleNamespace
import cocotb
from bazel_tools.tools.python.runfiles import runfiles
import lv_spec as spec
import lv_audit as audit
from lv_bench import run_case


def locate(package,name):
    resolver=runfiles.Create()
    for workspace in (os.environ.get('TEST_WORKSPACE','_main'),'_main','coralnpu_hw'):
        value=resolver.Rlocation(workspace+'/'+package+'/'+name)
        if value and Path(value).is_file():return Path(value)
    raise ValueError('Missing actual VM runfile: '+package+'/'+name)


async def run_vm(dut,index):
    elf=locate(spec.PACKAGE,'probe_program.elf');report=audit.inspect(elf.read_bytes())
    rtl=locate(spec.BASE_RTL_PACKAGE,spec.TOP+'.sv')
    header=locate(spec.BASE_RTL_PACKAGE,'V'+spec.TOP+'_parameters.h')
    audit.checked_header(header.read_text())
    if spec.sha(rtl)!=spec.RTL_SHA:raise ValueError('VM RTL differs from qualified baseline')
    await run_case(dut,index,SimpleNamespace(root=elf.parent,report=report))


@cocotb.test()
async def candidate_probe_test(dut):await run_vm(dut,4)

@cocotb.test()
async def candidate_decode_tiny_test(dut):await run_vm(dut,0)

@cocotb.test()
async def candidate_prefill_tiny_test(dut):await run_vm(dut,1)

@cocotb.test()
async def candidate_decode_small_test(dut):await run_vm(dut,2)

@cocotb.test()
async def candidate_prefill_small_test(dut):await run_vm(dut,3)
