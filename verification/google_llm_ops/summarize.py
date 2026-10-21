"""Accept a completed RTL run; never convert host/reference evidence to RTL PASS."""
import argparse
import json
from pathlib import Path
from spec import checked_log
from audit import inspect


def summarize(run, index):
    report = inspect((run/"probe_program.elf").read_bytes())
    if report != json.loads((run/"resources.json").read_text()):
        raise ValueError("Measured ELF audit changed")
    raw = (run/"test.log").read_text()
    result = checked_log(raw,index)
    import re
    from spec import MARKER
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
    row = next(json.loads(s.split(MARKER,1)[1]) for s in clean.splitlines() if MARKER in s)
    rtl = json.loads((run/"rtl-identity.json").read_text())
    if row["elf_sha256"] != report["elf_sha256"] or row["rtl_sha256"] != rtl["rtl_sha256"]:
        raise ValueError("RTL test did not use the audited ELF/RTL")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",type=Path,required=True)
    p.add_argument("--case",type=int,choices=range(4),required=True)
    a = p.parse_args(); result = summarize(a.run,a.case)
    with (a.run/"comparison.json").open("x",encoding="utf-8") as stream:
        json.dump(result,stream,indent=2)
    print("[LLM_LINEAR_SUMMARY] "+json.dumps(result,sort_keys=True))
