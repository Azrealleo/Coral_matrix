#!/usr/bin/env python3
"""Export one immutable, tested-source TCM configuration; never run VCS here."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "google_tcm_capacity"
sys.path.insert(0, str(TOOLS))
import prepare_workset as workset
from prepare_control import checked_control_log, stage1_evidence
from package_lib import (CAPACITIES, DEFINES, UPSTREAM, checked_header, compilation_inputs,
                         seal, sha, verify, write_json, zip_contents)

SUPPORT = ("capacity_spec.py", "workset_spec.py", "workset_bench.py", "workset_axi_probe.py",
           "prepare_workset.py", "prepare_control.py", "control_spec.py", "prepare.py")
UPSTREAM_PY = ("coralnpu_test_utils/core_mini_axi_interface.py", "coralnpu_test_utils/backdoor.py",
               "coralnpu_test_utils/sim_backends/verilator_test_fixture.py",
               "coralnpu_test_utils/sim_backends/common_utils.py")
UPSTREAM_DPI = ("hdl/verilog/sram_backdoor.cc", "hdl/verilog/sram_backdoor.h")


def find_evidence(root, kib, rtl_sha, elf_sha):
    control_manifest = json.loads((root / "tcm_control_manifest.json").read_text())
    workset_manifest = json.loads((root / workset.MANIFEST).read_text())
    top = f"VmeCoreMini_ITCM8KB_DTCM{kib}KBAxi"
    control = None
    for run in sorted(root.parent.glob(f"control_d{kib}.*"), reverse=True):
        try:
            if json.loads((run / "manifest.json").read_text()) != control_manifest:
                continue
            checked_control_log((run / "test.log").read_text(), kib)
            checked_header((run / "parameters.h").read_text(), kib)
            matches = [line.split(None, 1) for line in (run / "artifacts.sha256").read_text().splitlines()
                       if line.split(None, 1)[-1].strip().endswith("/" + top + ".sv")]
            if len(matches) == 1 and matches[0][0] == rtl_sha:
                control = run
                break
        except (OSError, ValueError, KeyError):
            continue
    if control is None:
        raise ValueError("exported SV does not match a recorded passing control RTL hash; "
                         "no package written. Inspect generation differences, do not rebaseline hashes.")
    pilot = None
    for run in sorted(root.parent.glob("workset_d*_t12_r0.*"), reverse=True):
        try:
            if json.loads((run / "manifest.json").read_text()) != workset_manifest:
                continue
            pilot_kib = int(re.fullmatch(r"workset_d(\d+)_t12_r0\..+", run.name)[1])
            rows, _ = workset.checked_log((run / "test.log").read_text(), pilot_kib, 12, 0)
            if rows[0]["elf_sha256"] == elf_sha:
                pilot = run
                break
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if pilot is None:
        raise ValueError("firmware ELF has no complete passing T12 workset log; no package written")
    capacity = Path(stage1_evidence(root, kib)["directory"])
    return dict(capacity=capacity, control=control, workset_pilot=pilot)


def export(root, kib, elf, output, job):
    root, elf, output, job = (Path(p).resolve() for p in (root, elf, output, job))
    if kib not in CAPACITIES:
        raise ValueError("unsupported export capacity")
    workset.verify(root)
    top = f"VmeCoreMini_ITCM8KB_DTCM{kib}KBAxi"
    generated = root / f"bazel-bin/tests/cocotb/tcm_workset/d{kib}"
    inputs = {top + ".sv": generated / (top + ".sv"), top + ".zip": generated / (top + ".zip"),
              f"V{top}_parameters.h": generated / f"V{top}_parameters.h", "workset_program.elf": elf}
    before = {n: sha(p) for n, p in inputs.items()}
    parameters = checked_header(inputs[f"V{top}_parameters.h"].read_text(), kib)
    contents = zip_contents(inputs[top + ".zip"])
    includes = compilation_inputs(contents, top)
    evidence = find_evidence(root, kib, before[top + ".sv"], before["workset_program.elf"])
    archive = output.with_name(output.name + ".tar.gz")
    checksum = archive.with_name(archive.name + ".sha256")
    if output.exists() or archive.exists() or checksum.exists():
        raise ValueError("output exists; nothing overwritten")
    output.mkdir(parents=True)
    for directory in ("rtl", "rtl_dependencies", "original", "firmware", "support", "python", "evidence", "dpi"):
        (output / directory).mkdir()
    for n, source in inputs.items():
        folder = "original" if n.endswith(".zip") else "firmware" if n.endswith(".elf") else "rtl"
        shutil.copy2(source, output / folder / n)
    for name, data in contents.items():
        path = output / "rtl_dependencies" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in SUPPORT:
        shutil.copy2(TOOLS / name, output / "support" / name)
    for name in UPSTREAM_PY:
        path = output / "python" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(workset.git(root, "show", UPSTREAM + ":" + name))
    for name in UPSTREAM_DPI:
        (output / "dpi" / Path(name).name).write_bytes(workset.git(root, "show", UPSTREAM + ":" + name))
    # Namespace adapter only; the original fixture, workload and ELF are unchanged.
    adapter = output / "python/bazel_tools/tools/python/runfiles/runfiles.py"
    adapter.parent.mkdir(parents=True)
    shutil.copy2(HERE / "runfiles.py.template", adapter)
    for directory in ("bazel_tools", "bazel_tools/tools", "bazel_tools/tools/python",
                      "bazel_tools/tools/python/runfiles", "coralnpu_test_utils", "coralnpu_test_utils/sim_backends"):
        (output / "python" / directory / "__init__.py").write_bytes(b"")
    for name in ("runtime.py", "package_lib.py", "requirements.txt"):
        shutil.copy2(HERE / name, output / name)
    shutil.copy2(HERE / "PACKAGE-README.md", output / "README.md")
    (output / "LICENSE").write_bytes(workset.git(root, "show", UPSTREAM + ":LICENSE"))
    for name in ("tcm_capacity_manifest.json", "tcm_control_manifest.json", workset.MANIFEST):
        shutil.copy2(root / name, output / "evidence" / name)
    evidence_info = {}
    for label, run in evidence.items():
        target = output / "evidence" / label
        target.mkdir()
        for name in ("test.log", "manifest.json"):
            shutil.copy2(run / name, target / name)
        if label == "control":
            for name in ("artifacts.sha256", "parameters.h"):
                shutil.copy2(run / name, target / name)
        evidence_info[label] = dict(original_directory=str(run), log_sha256=sha(target / "test.log"))
    for name in ("build.log", "build-command.txt", "export.sh", "elf-outputs.txt", "execution-root.txt"):
        shutil.copy2(job / name, output / "evidence" / name)
    for name, path in inputs.items():
        if sha(path) != before[name]:
            raise ValueError("input changed during export; partial output retained, do not use")
    workset.verify(root)
    seal(output, dict(schema=1, upstream=UPSTREAM, dtcm_kib=kib, itcm_kib=8, hdl_top=top,
                      exported_utc=datetime.now(timezone.utc).isoformat(),
                      rtl_mode="original_monolithic_sv_no_rewrite", defines=list(DEFINES),
                      zip_include_dirs=includes, generated_parameters=parameters,
                      dpi_source_sha256={Path(n).name: sha(output / "dpi" / Path(n).name) for n in UPSTREAM_DPI},
                      passed_control_rtl_sha256=before[top + ".sv"],
                      passed_workset_elf_sha256=before["workset_program.elf"], evidence=evidence_info,
                      vector_sha256={str(t): workset.vectors(t)[3] for t in workset.TILE_CHOICES},
                      export_validation="bytes_equal_passed_control_rtl_not_vcs_simulated",
                      vcs_simulation="NOT_RUN", ram_model="original_generic_1cycle_512x128_16byte_mask",
                      memory_map=dict(itcm=0, dtcm=0x01000000, csr=0x02000000, external=0x20000000),
                      clock_ns="1.25", performance_scope="same_original_workset_cocotb_not_native_sv_tb"))
    verify(output)
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(output, arcname=output.name, recursive=True)
    checksum.write_bytes(f"{sha(archive)}  {archive.name}\n".encode())
    print("[TCM_VCS_EXPORT_VERIFIED] " + json.dumps(dict(dtcm_kib=kib, top=top,
          control_rtl_bytes_equal=True, firmware_bytes_equal=True, vcs_simulation="NOT_RUN")))
    print("[TCM_VCS_PACKAGE_DIRECTORY] " + str(output))
    print("[TCM_VCS_PACKAGE_ARCHIVE] " + str(archive))
    print("[TCM_VCS_PACKAGE_SHA256] " + sha(archive))
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", required=True, type=Path)
    p.add_argument("--kib", type=int, choices=CAPACITIES, required=True)
    p.add_argument("--elf", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--job", required=True, type=Path)
    a = p.parse_args()
    export(a.upstream, a.kib, a.elf, a.output, a.job)
