#!/usr/bin/env python3
"""External server Verilator launcher. Never modifies the exported package."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
COMMON_SHA = "9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855"
PACKAGE_TOOLS = {
    "portable.py": "2369f451e53ec704a538b08fae3b92f691f2cc9d9a432c0554441f16effff047",
    "firmware_report.py": "1e55ef1aad13a181ae07943accfce99c1e0cdda1aa7c21875418de912cd6e5fd",
    "spec.py": "a010b99273868f738daa7ce6abdabb0414227a7e4103baf6cdcf8f0b47b46520",
}
VERSIONS = {"cocotb": "2.0.0", "numpy": "1.26.4", "pyelftools": "0.32", "find-libpython": "0.5.1"}
MARKER = "[PERSON_RTL_OBSERVATION] "


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def module_at(name, path, digest):
    if sha(path) != digest:
        raise ValueError("Unknown/changed helper: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers():
    path = HERE / "verilator_common.py"
    if not path.exists():
        path = HERE.parent / "google_tcm_verilator/verilator_workset.py"
    return module_at("_person_qualified_verilator_helpers", path, COMMON_SHA)


def load_bundle(root):
    root = Path(root).resolve(strict=True)
    for name, digest in PACKAGE_TOOLS.items():
        if sha(root / name) != digest:
            raise ValueError("Unrecognized package utility: " + name)
    library = module_at("_person_package_verifier", root / "portable.py", PACKAGE_TOOLS["portable.py"])
    manifest = library.verify(root)
    sys.path.insert(0, str(root))
    spec = module_at("spec", root / "spec.py", PACKAGE_TOOLS["spec.py"])
    sys.modules["spec"] = spec
    audit = module_at("_person_elf_audit", root / "firmware_report.py", PACKAGE_TOOLS["firmware_report.py"])
    report = audit.inspect_elf((root / "firmware/person_program.elf").read_bytes())
    if report != json.loads((root / "evidence/resources.json").read_text()):
        raise ValueError("ELF resource audit differs from measured evidence")
    if (manifest["upstream"] != spec.UPSTREAM or manifest["model_sha256"] != spec.MODEL_SHA256 or
            manifest["elf_sha256"] != report["elf_sha256"] or
            manifest["memory_map"] != dict(itcm=0, dtcm=spec.DTCM_BASE, csr=0x02000000, external=0x20000000)):
        raise ValueError("Wrong model/ELF/memory map")
    for row in report["segments"]:
        start, size = row["address"], row["bytes"]
        if not (0 <= start < start + size <= 256 * 1024 or
                spec.DTCM_BASE <= start < start + size <= spec.DTCM_BASE + 512 * 1024):
            raise ValueError("ELF exceeds actual hardware capacity")
    for name in spec.ASSETS:
        spec.checked_asset(root / "assets", name)
    for case in ("person", "no_person"):
        if (root / "inputs" / (case + ".int8.bin")).stat().st_size != 9216:
            raise ValueError("Wrong input size")
    return SimpleNamespace(root=root, manifest=manifest, report=report, library=library)


def environment(common):
    import importlib.metadata
    import find_libpython
    import cocotb_tools.config as config
    if platform.system() != "Linux" or platform.machine() != "x86_64" or sys.version_info[:2] != (3, 11):
        raise ValueError("Requires Linux x86_64 CPython3.11 / coral-verilator")
    versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if versions != VERSIONS:
        raise ValueError("Dependency version mismatch: " + str(versions))
    tools = {"verilator": common.executable("verilator"), "make": common.executable("make"),
             "perl": common.executable("perl"), "cc": common.executable(os.environ.get("CC") or "gcc"),
             "cxx": common.executable(os.environ.get("CXX") or "g++"),
             "ar": common.executable(os.environ.get("AR") or "ar")}
    version = common.command_output([tools["verilator"], "--version"])
    if not re.search(r"\bVerilator 5\.052\b", version):
        raise ValueError("Requires qualified Verilator5.052")
    macros = subprocess.run([tools["cxx"], "-std=c++17", "-dM", "-E", "-x", "c++", "-"],
                            input="", text=True, capture_output=True, timeout=30)
    if macros.returncode or "#define __cplusplus 201703L" not in macros.stdout:
        raise ValueError("C++17 compiler required, not system GCC4.8")
    libpython = find_libpython.find_libpython()
    if not libpython:
        raise ValueError("Missing shared libpython")
    libs = Path(config.libs_dir).resolve()
    cpp = Path(config.share_dir).resolve() / "lib/verilator/verilator.cpp"
    for path in (libs / "libcocotbvpi_verilator.so", Path(libpython)):
        if "not found" in common.command_output(["ldd", str(path)]):
            raise ValueError("Unresolved dependency: " + str(path))
    return dict(python=sys.executable, versions=versions, tools=tools, libc=platform.libc_ver(),
                verilator_version=version, cpp=str(cpp), cpp_sha256=sha(cpp), libs=str(libs),
                vpi_sha256=sha(libs / "libcocotbvpi_verilator.so"), libpython=str(Path(libpython).resolve()),
                libpython_sha256=sha(libpython), tool_sha256={k: sha(p) for k, p in tools.items()},
                compile_environment={n: os.environ.get(n) for n in
                                     ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "VERILATOR_ROOT", "PATH")})


def identity(bundle, env, common):
    return common.digest(dict(manifest=sha(bundle.root / "manifest.json"), environment=env,
                              launcher=sha(__file__), bench=sha(HERE / "person_bench.py"),
                              helper=COMMON_SHA, warnings=common.WARNINGS, visibility=common.VISIBILITY))


def child_environment(bundle, env):
    child = dict(os.environ)
    for name in ("WAVES", "GUI", "COCOTB_ENABLE_PROFILING", "COCOTB_TESTCASE", "COCOTB_TEST_FILTER",
                 "COCOTB_TEST_MODULES", "COCOTB_RESULTS_FILE", "GPI_EXTRA", "PYTHONHOME", "MAKEFLAGS", "MFLAGS",
                 "COCOTB_TIMEOUT_CYCLES", "COCOTB_PLUSARGS"):
        child.pop(name, None)
    child.update(PYTHONPATH=os.pathsep.join((str(HERE), str(bundle.root), str(bundle.root / "python"))),
                 PYTHONDONTWRITEBYTECODE="1", PERSON_PACKAGE=str(bundle.root), PERSON_CHILD="1",
                 COCOTB_USE_FRONTDOOR="1", COCOTB_TRUST_INERTIAL_WRITES="0", TEST_XLEN="32",
                 CLOCK_NS="1.25", COCOTB_ANSI_OUTPUT="0", NO_COLOR="1", PYTHONUNBUFFERED="1",
                 LIBPYTHON_LOC=env["libpython"], CC=env["tools"]["cc"], CXX=env["tools"]["cxx"])
    child["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (
        env["libs"], str(Path(env["libpython"]).parent), os.environ.get("LD_LIBRARY_PATH"))))
    return child


def execute(bundle, env, phase, directory, timeout, extra):
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--package", str(bundle.root), phase,
            "--directory", str(directory)] + list(extra)
    write_json(directory / (phase + "-command.json"), argv)
    start, timed_out = time.monotonic(), False
    log = directory / (phase + ".log")
    with log.open("xb") as stream:
        process = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                   env=child_environment(bundle, env), start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
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
    timing = dict(argv=argv, log=str(log), exit_code=code, timed_out=timed_out,
                  elapsed_seconds=time.monotonic() - start, timeout_seconds=timeout,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(directory / (phase + "-status.json"), timing)
    if code or timed_out:
        raise ValueError("Phase failed/incomplete; preserved log: " + str(log))
    return timing


def checked_results(text, xml, bundle, case, mode, cycles):
    tests = ET.parse(xml).getroot()
    cases = list(tests.iter("testcase"))
    if (len(cases) != 1 or cases[0].get("name") != "person_model_test" or
            any(list(tests.iter(tag)) for tag in ("failure", "error", "skipped"))):
        raise ValueError("Missing/failed/skipped cocotb test")
    rows = [json.loads(line.split(MARKER, 1)[1]) for line in text.splitlines() if MARKER in line]
    if len(rows) != 1:
        raise ValueError("Missing/duplicate observation")
    row = rows[0]
    required = dict(schema=1, case=case, mode=mode, requested_cycles=cycles, fault=False,
                    itcm_kib=256, dtcm_kib=512, elf_sha256=bundle.manifest["elf_sha256"],
                    model_sha256=bundle.manifest["model_sha256"],
                    input_sha256=sha(bundle.root / "inputs" / (case + ".int8.bin")),
                    model_readback_equal=True, input_readback_equal=True, stack_low_canary_intact=True,
                    kernel_backend="pinned_TFLM_INT8_not_VME_offload")
    if any(row.get(k) != v for k, v in required.items()):
        raise ValueError("Wrong observation identity or failed memory/fault checks")
    status, used = row.get("firmware_status"), row.get("arena_used_bytes")
    if type(status) is not int or status not in (0, 1, 2, 3) or type(used) is not int or not 0 <= used <= 163840:
        raise ValueError("Invalid firmware status/arena")
    if status >= 2 and used == 0:
        raise ValueError("Allocated model has no arena measurement")
    if type(row.get("inference_complete")) is not bool or type(row.get("natural_halt")) is not bool:
        raise ValueError("Completion flags must be booleans")
    elapsed = row.get("observation_elapsed_cycles")
    if (type(elapsed) is not int or not 0 <= elapsed <= cycles + 1 or
            not row["natural_halt"] and abs(elapsed - cycles) > 1):
        raise ValueError("Observation window differs from requested cycle budget")
    if status == 3 and (row.get("scores_no_person_then_person") !=
                        bundle.manifest["reference_scores_no_person_then_person"][case] or
                        type(row.get("invoke_cycles")) is not int or row["invoke_cycles"] <= 0):
        raise ValueError("Reported completed Invoke differs from native output")
    if row.get("inference_complete"):
        if (status != 3 or not row.get("natural_halt") or
                row.get("scores_no_person_then_person") != bundle.manifest["reference_scores_no_person_then_person"][case] or
                type(row.get("invoke_cycles")) is not int or row["invoke_cycles"] <= 0):
            raise ValueError("Inference does not match complete native reference")
    elif mode == "infer" or row.get("natural_halt"):
        raise ValueError("Premature halt/incomplete inference")
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("command", choices=("verify", "check", "build", "smoke", "infer", "_build", "_test"))
    parser.add_argument("--case", choices=("person", "no_person"), default="person")
    parser.add_argument("--cycles", type=int, default=200000)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--mode", choices=("smoke", "infer"), default="smoke")
    args = parser.parse_args()
    if not 1000 <= args.cycles <= 2000000000 or not 1 <= args.timeout <= 86400:
        parser.error("cycles=1000..2000000000 and timeout=1..86400 seconds")
    common, bundle = helpers(), load_bundle(args.package)
    if args.command == "verify":
        print("[PERSON_SERVER_PACKAGE_VERIFIED] original_package_unchanged=true NPU_RTL=NOT_RUN")
        return
    env = environment(common)
    if args.command == "check":
        print("[PERSON_VERILATOR_ENV_CHECK] " + json.dumps(dict(python=env["python"], tools=env["tools"],
              versions=env["versions"], libc=env["libc"], ELF_resource_rechecked=True, NPU_RTL="NOT_RUN")))
        return
    if args.command in ("_build", "_test"):
        if os.environ.get("PERSON_CHILD") != "1":
            raise ValueError("Internal phase requires parent launcher")
        if args.command == "_build":
            commands = common.build_commands(bundle, env, args.directory, args.jobs)
            write_json(args.directory / "compile-commands.json", commands)
            for argv in commands:
                subprocess.run(argv, cwd=args.directory, check=True)
            if "not found" in common.command_output(["ldd", str(args.directory / bundle.manifest["hdl_top"])]):
                raise ValueError("Built model has unresolved libraries")
        else:
            from cocotb_tools.runner import get_runner
            get_runner("verilator").test(
                hdl_toplevel=bundle.manifest["hdl_top"], hdl_toplevel_lang="verilog",
                test_module="person_bench", testcase="person_model_test", seed=137,
                build_dir=args.model_dir, test_dir=args.directory, waves=False, gui=False,
                results_xml=str(args.directory / "results.xml"),
                extra_env=dict(PERSON_CASE=args.case, PERSON_MODE=args.mode, PERSON_CYCLES=str(args.cycles),
                               COCOTB_USE_FRONTDOOR="1", COCOTB_TRUST_INERTIAL_WRITES="0"))
        return
    state = common.state_directory(bundle.root)
    state.mkdir(parents=True, exist_ok=True)
    wanted = identity(bundle, env, common)

    def current_build():
        record = json.loads((state / "current_build.json").read_text())
        path = Path(record["directory"]).resolve(strict=True)
        if (path.parent != (state / "builds").resolve() or record["identity"] != wanted or
                record["model_files"] != common.model_hashes(bundle, path) or
                record["timing"]["exit_code"] != 0 or record["timing"]["timed_out"] is not False or
                record != json.loads((path / "build-record.json").read_text())):
            raise ValueError("Model/package/tools/environment changed; build a new model")
        return record, path

    with common.state_lock(state):
        if args.command == "build":
            try:
                _, path = current_build()
                print("[PERSON_VERILATOR_BUILD_REUSED] " + str(path))
                return
            except (OSError, ValueError, KeyError):
                pass
            (state / "builds").mkdir(exist_ok=True)
            path = Path(tempfile.mkdtemp(prefix=wanted[:12] + ".", dir=state / "builds"))
            write_json(path / "environment.json", env)
            print("[PERSON_VERILATOR_BUILD_DIRECTORY] " + str(path), flush=True)
            timing = execute(bundle, env, "_build", path, args.timeout, ("--jobs", str(args.jobs)))
            bundle.library.verify(bundle.root)
            record = dict(directory=str(path), identity=wanted, timing=timing,
                          model_files=common.model_hashes(bundle, path))
            write_json(path / "build-record.json", record)
            pointer = state / ("pointer." + str(os.getpid()) + ".json")
            write_json(pointer, record)
            os.replace(pointer, state / "current_build.json")
            print("[PERSON_VERILATOR_BUILD_PASS] compile_seconds=" + str(round(timing["elapsed_seconds"], 3)))
            return
        record, model = current_build()
        (state / "runs").mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix=args.command + "_" + args.case + ".", dir=state / "runs"))
        write_json(run / "environment.json", env)
        write_json(run / "build-record.json", record)
        print("[PERSON_VERILATOR_RUN_DIRECTORY] " + str(run), flush=True)
        timing = execute(bundle, env, "_test", run, args.timeout,
                         ("--model-dir", str(model), "--case", args.case, "--mode", args.command,
                          "--cycles", str(args.cycles)))
        row = checked_results((run / "_test.log").read_text(), run / "results.xml", bundle,
                              args.case, args.command, args.cycles)
        bundle.library.verify(bundle.root)
        if common.model_hashes(bundle, model) != record["model_files"]:
            raise ValueError("Compiled model changed")
        write_json(run / "result.json", dict(schema=1, observation=row, timing=timing, build=record,
                   manifest_sha256=sha(bundle.root / "manifest.json"), runner_sha256=sha(__file__),
                   bench_sha256=sha(HERE / "person_bench.py"),
                   raw_log_sha256=sha(run / "_test.log"), xml_sha256=sha(run / "results.xml")))
        print(MARKER + json.dumps(row, sort_keys=True))
        tag = "PERSON_NPU_INFERENCE_PASS" if row["inference_complete"] else "PERSON_SMOKE_OBSERVED_NOT_INFERENCE"
        print("[" + tag + "] wall_seconds=" + str(round(timing["elapsed_seconds"], 3)) + " results=" + str(run))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[PERSON_VERILATOR_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
