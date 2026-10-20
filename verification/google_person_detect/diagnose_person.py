#!/usr/bin/env python3
"""Debug snapshots on the SAME model/ELF. No build, repair, or inference PASS."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE_SHA = "597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a"
BENCH_SHA = "78d1ea52f7ac63597fd8b48fce33d7b5c1919dd8bd4814a4b3de129aaf6fdc76"
MARKER = "[PERSON_DEBUG_SNAPSHOT] "


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def base_tools():
    if sha(HERE / "person_runner.py") != BASE_SHA or sha(HERE / "person_bench.py") != BENCH_SHA:
        raise ValueError("Original model-producing runner/bench changed; no reuse")
    import person_runner
    return person_runner


def functions(data):
    from elftools.elf.elffile import ELFFile
    elf = ELFFile(io.BytesIO(data))
    table = elf.get_section_by_name(".symtab")
    return sorted({(int(s["st_value"]), int(s["st_size"]), s.name) for s in table.iter_symbols()
                   if s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] != "SHN_UNDEF" and s.name})


def symbolize(table, address):
    contained = [(start, size, name) for start, size, name in table if start <= address < start + size]
    if contained:
        start, size, name = max(contained)
        return dict(address=address, symbol=name, offset=address - start, size=size, contains_address=True)
    before = [row for row in table if row[0] <= address]
    if not before:
        return dict(address=address, symbol=None, contains_address=False)
    start, size, name = max(before)
    return dict(address=address, nearest_symbol_NOT_containment=name,
                offset=address - start, size=size, contains_address=False)


def checked_build(base, common, bundle, env, state):
    record = json.loads((state / "current_build.json").read_text())
    model = Path(record["directory"]).resolve(strict=True)
    if (model.parent != (state / "builds").resolve() or record["identity"] != base.identity(bundle, env, common) or
            record["model_files"] != common.model_hashes(bundle, model) or
            record != json.loads((model / "build-record.json").read_text()) or
            record["timing"]["exit_code"] != 0 or record["timing"]["timed_out"] is not False):
        raise ValueError("Model/package/environment differs; no build or relabel performed")
    return record, model


def checked_capture(text, xml, bundle, cycles, samples):
    root = ET.parse(xml).getroot()
    tests = list(root.iter("testcase"))
    if (len(tests) != 1 or tests[0].get("name") != "person_diagnostic_test" or
            any(list(root.iter(n)) for n in ("failure", "error", "skipped"))):
        raise ValueError("Diagnostic test incomplete/failed; keep raw log")
    rows = [json.loads(line.split(MARKER, 1)[1]) for line in text.splitlines() if MARKER in line]
    if not 1 <= len(rows) <= samples:
        raise ValueError("Missing/extra debug snapshots")
    for i, row in enumerate(rows):
        if (row.get("schema") != 1 or row.get("sample") != i or row.get("initial_window_cycles") != cycles or
                row.get("elf_sha256") != bundle.manifest["elf_sha256"] or
                row.get("scope") != "intrusive_DM_debug_NOT_inference_or_performance" or
                row.get("firmware_changed") is not False or row.get("core_reset_before_capture") is not False or
                row.get("registers", {}).get("dpc") is None or
                row.get("dcsr_cause") not in (1, 2, 3, 4)):
            raise ValueError("Wrong/incomplete diagnostic identity")
    if len(rows) != samples and not rows[-1].get("natural_halt_before_pause") and not rows[-1].get("fault_before_pause"):
        raise ValueError("Unexpected early end of diagnostic capture")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=200000)
    parser.add_argument("--samples", type=int, default=3, choices=range(1, 5))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    if not 1000 <= args.cycles <= 2000000 or not 1 <= args.timeout <= 3600:
        parser.error("cycles=1000..2000000; timeout=1..3600 seconds")
    base = base_tools()
    common, bundle = base.helpers(), base.load_bundle(args.package)
    env = base.environment(common)
    if args.child:
        if os.environ.get("PERSON_DIAG_CHILD") != "1":
            raise ValueError("Diagnostic child must be launched by parent")
        from cocotb_tools.runner import get_runner
        get_runner("verilator").test(
            hdl_toplevel=bundle.manifest["hdl_top"], hdl_toplevel_lang="verilog",
            test_module="person_diag_bench", testcase="person_diagnostic_test", seed=137,
            build_dir=args.model, test_dir=args.directory, waves=False, gui=False,
            results_xml=str(args.directory / "results.xml"),
            extra_env=dict(PERSON_DIAG_CYCLES=str(args.cycles), PERSON_DIAG_SAMPLES=str(args.samples),
                           COCOTB_USE_FRONTDOOR="1", COCOTB_TRUST_INERTIAL_WRITES="0"))
        return
    state = common.state_directory(bundle.root)
    if not state.is_dir():
        raise ValueError("No existing model state; diagnostic never builds RTL")
    with common.state_lock(state):
        record, model = checked_build(base, common, bundle, env, state)
        (state / "diagnostics").mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="pc.", dir=state / "diagnostics"))
        base.write_json(run / "environment.json", env)
        base.write_json(run / "build-record.json", record)
        argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--package", str(bundle.root),
                "--child", "--directory", str(run), "--model", str(model), "--cycles", str(args.cycles),
                "--samples", str(args.samples), "--timeout", str(args.timeout)]
        base.write_json(run / "command.json", argv)
        child = base.child_environment(bundle, env)
        child["PERSON_DIAG_CHILD"] = "1"
        start, timed_out = time.monotonic(), False
        print("[PERSON_DIAGNOSTIC_DIRECTORY] " + str(run), flush=True)
        with (run / "diagnostic.log").open("xb") as stream:
            process = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT, env=child, start_new_session=True)
            try:
                code = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        timing = dict(exit_code=code, timed_out=timed_out, elapsed_seconds=time.monotonic() - start,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        base.write_json(run / "status.json", timing)
        if code or timed_out:
            raise ValueError("Diagnostic incomplete; preserved log: " + str(run / "diagnostic.log"))
        rows = checked_capture((run / "diagnostic.log").read_text(), run / "results.xml", bundle,
                               args.cycles, args.samples)
        # Demangling is display-only. Original symbol strings and raw log retained.
        demangler = shutil_which("c++filt")
        for row in rows:
            for field in ("pc_location", "ra_callsite_candidate"):
                name = row[field].get("symbol")
                if name and demangler:
                    result = subprocess.run([demangler, name], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        row[field]["demangled"] = result.stdout.strip()
        bundle.library.verify(bundle.root)
        checked_build(base, common, bundle, env, state)
        base.write_json(run / "capture.json", dict(schema=1, rows=rows, timing=timing,
                        diagnostic_sha256=sha(__file__), bench_sha256=sha(HERE / "person_diag_bench.py"),
                        original_runner_sha256=BASE_SHA, original_bench_sha256=BENCH_SHA,
                        raw_log_sha256=sha(run / "diagnostic.log"), xml_sha256=sha(run / "results.xml"),
                        model_identity=record["identity"], inference="NOT_ASSERTED"))
        for row in rows:
            print(MARKER + json.dumps(row, sort_keys=True))
        print("[PERSON_DIAGNOSTIC_CAPTURED] inference=NOT_ASSERTED no_rebuild=true results=" + str(run))


def shutil_which(name):
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[PERSON_DIAGNOSTIC_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
