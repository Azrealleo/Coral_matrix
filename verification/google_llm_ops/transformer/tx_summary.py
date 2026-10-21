"""Collect only independently checked single-case RTL runs."""
import argparse
import json
from pathlib import Path
from tx_audit import inspect
from tx_spec import checked_log,CASES


def summarize(run,index,log_name="test.log"):
    report=inspect((run/"probe_program.elf").read_bytes())
    if report!=json.loads((run/"resources.json").read_text()):raise ValueError("ELF changed")
    row,result=checked_log((run/log_name).read_text(),index)
    rtl=json.loads((run/"rtl-identity.json").read_text())
    if row["elf_sha256"]!=report["elf_sha256"] or row["rtl_sha256"]!=rtl["rtl_sha256"]:
        raise ValueError("Test ELF/RTL differs from resource-audited build")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",type=Path,required=True);p.add_argument("--case",type=int,choices=range(len(CASES)),required=True)
    p.add_argument("--log-name",default="test.log")
    a=p.parse_args();print("[LLM_TX_SUMMARY] "+json.dumps(summarize(a.run,a.case,a.log_name),sort_keys=True))
