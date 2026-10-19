#!/usr/bin/env python3
"""External Verilator entry point for unchanged, verified TCM RTL packages.

No Bazel/VCS/Java/RISC-V compiler. All outputs are in a distinct sibling state
directory. Original RTL, SRAM C++ DPI, firmware and Python checks stay untouched.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
LIBRARY_SHA256 = "d5673e81b49c75a7630aa54f365f1dd9d5a606aa771b5b6021daa5e335fa864d"
# Only this exact previous adapter may supply a reusable model after the
# runtime-only WAVES/GUI correction. Its actual build identity is retained.
PREVIOUS_ADAPTER_SHA256 = "f502f30e17d75e408418e89e408aa115c156d5ef4907f8c0e6701c41c7ca3d0d"
VERSIONS = {"cocotb": "2.0.0", "numpy": "1.26.4", "pyelftools": "0.32", "find-libpython": "0.5.1"}
TILES = (2, 12, 120, 192, 384, 768)
WARNINGS = ("WIDTH", "CASEINCOMPLETE", "LATCH", "SIDEEFFECT", "MULTIDRIVEN", "SPLITVAR",
            "BLKANDNBLK", "CASEX", "ASCRANGE", "WIDTHEXPAND", "WIDTHTRUNC", "UNSIGNED", "PINMISSING")
VISIBILITY = '''`verilator_config
// Same top-port visibility as the pinned upstream rules/default.vlt.tpl.
public -module "{top}" -var "io_*"
public -module "{top}" -var "clock"
public -module "{top}" -var "clk"
public -module "{top}" -var "reset"
public -module "{top}" -var "rst"
public -module "{top}" -var "rst_ni"
'''
MARKER = "[GOOGLE_TCM_WORKSET] "
SGR = re.compile(r"\x1b\[[0-9;]*m")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    # New evidence is never silently overwritten.
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def normalize(text):
    """Only remove SGR presentation outside structured JSON, never repair data."""
    lines = []
    for line in text.splitlines(keepends=True):
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        line = line[:-len(ending)] if ending else line
        if MARKER in line:
            prefix, payload = line.split(MARKER, 1)
            left = re.match(r"^(?:[ \t]|\x1b\[[0-9;]*m)*", payload).end()
            right = re.search(r"(?:[ \t]|\x1b\[[0-9;]*m)*$", payload).start()
            if right <= left:
                raise ValueError("empty structured record")
            clean = SGR.sub("", prefix) + MARKER + payload[left:right]
        else:
            clean = SGR.sub("", line)
            if MARKER in clean:
                raise ValueError("color embedded in structured marker")
        if "\x1b" in clean:
            raise ValueError("unsupported or embedded ANSI escape; raw log retained")
        lines.append(clean + ending)
    return "".join(lines)


def load_package(requested):
    root = Path(requested).resolve(strict=True)
    if sha(root / "package_lib.py") != LIBRARY_SHA256:
        raise ValueError("unknown package verifier; do not edit expected hashes")
    spec = importlib.util.spec_from_file_location("package_lib", root / "package_lib.py")
    library = importlib.util.module_from_spec(spec)
    sys.modules["package_lib"] = library
    spec.loader.exec_module(library)
    manifest = library.verify(root)
    # Only import packaged workload code AFTER checking every immutable file.
    for name in ("capacity_spec", "workset_spec", "workset_bench", "workset_axi_probe",
                 "prepare_workset", "prepare_control", "control_spec", "prepare"):
        sys.modules.pop(name, None)
    sys.path[:0] = [str(root / "support"), str(root / "python")]
    import prepare_workset
    return SimpleNamespace(root=root, library=library, manifest=manifest,
                           checked_log=prepare_workset.checked_log)


def command_output(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("command failed: " + shlex.join(argv) + "\n" + result.stdout + result.stderr)
    return result.stdout + result.stderr


def executable(name):
    value = shutil.which(name)
    if not value:
        raise ValueError("tool missing: " + name)
    return str(Path(value).absolute())


def environment(bundle):
    if platform.system() != "Linux" or platform.machine() != "x86_64" or sys.version_info[:2] != (3, 11):
        raise ValueError("requires Linux x86_64 and CPython3.11 in coral-verilator")
    if "COCOTB_ENABLE_PROFILING" in os.environ:
        raise ValueError("unset COCOTB_ENABLE_PROFILING for baseline speed testing")
    import importlib.metadata
    import find_libpython
    import cocotb_tools.config as config
    versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if versions != VERSIONS:
        raise ValueError("wrong Python dependency versions: " + repr(versions))
    tools = {"verilator": executable("verilator"), "make": executable("make"),
             "perl": executable("perl"), "cxx": executable(os.environ.get("CXX") or "g++"),
             "cc": executable(os.environ.get("CC") or "gcc"),
             "ar": executable(os.environ.get("AR") or "ar")}
    version = command_output([tools["verilator"], "--version"])
    if not re.search(r"\bVerilator 5\.052\b", version):
        raise ValueError("use the qualified Verilator5.052 baseline")
    macros = subprocess.run([tools["cxx"], "-std=c++17", "-dM", "-E", "-x", "c++", "-"],
                            input="", capture_output=True, text=True, timeout=30)
    if macros.returncode or "#define __cplusplus 201703L" not in macros.stdout:
        raise ValueError("original SRAM DPI requires working C++17; do not use system GCC4.8")
    libpython = find_libpython.find_libpython()
    if not libpython:
        raise ValueError("shared libpython3.11 missing")
    libs = Path(config.libs_dir).resolve()
    vpi = libs / "libcocotbvpi_verilator.so"
    cpp = Path(config.share_dir).resolve() / "lib/verilator/verilator.cpp"
    linked = {}
    for path in (vpi, Path(libpython)):
        linked[str(path)] = command_output(["ldd", str(path)])
        if "not found" in linked[str(path)]:
            raise ValueError("missing shared library dependencies: " + str(path))
    from workset_spec import vectors
    for tiles in TILES:
        if vectors(tiles)[3] != bundle.manifest["vector_sha256"][str(tiles)]:
            raise ValueError("NumPy vectors do not match packaged golden")
    from workset_bench import inspect_elf
    entry, segments, symbols, sizes = inspect_elf(bundle.root / "firmware/workset_program.elf")
    return dict(python=sys.executable, python_version=sys.version, versions=versions,
                libc=platform.libc_ver(), tools=tools, verilator_version=version,
                verilator_config=command_output([tools["verilator"], "-V"]),
                cxx_version=command_output([tools["cxx"], "--version"]),
                cc_version=command_output([tools["cc"], "--version"]),
                make_version=command_output([tools["make"], "--version"]),
                tool_sha256={k: sha(p) for k, p in tools.items()},
                cpp=str(cpp), cpp_sha256=sha(cpp), libs=str(libs), vpi_sha256=sha(vpi),
                libpython=str(Path(libpython).resolve()), libpython_sha256=sha(libpython), ldd=linked,
                compile_environment={name: os.environ.get(name) for name in
                                     ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "VERILATOR_ROOT", "PATH")},
                elf_entry=entry, elf_load_segments=[list(s) for s in segments], symbols=symbols,
                symbol_sizes=sizes)


def state_directory(root):
    state = root.with_name(root.name + "_verilator_runtime").resolve()
    if state == root or root in state.parents:
        raise ValueError("outputs must be outside the immutable package")
    return state


def build_identity(bundle, env, *, adapter_sha256=None):
    stable = {key: value for key, value in env.items() if key != "ldd"}
    return digest(dict(adapter_sha256=adapter_sha256 or sha(__file__), manifest_sha256=sha(bundle.root / "manifest.json"),
                       package=str(bundle.root), environment=stable, warnings=WARNINGS,
                       visibility=VISIBILITY, optimization="OPT_FAST=-O3", cxx_standard="c++17",
                       clock="original_python_clock_trust_inertial_0"))


def child_environment(bundle, env):
    child = dict(os.environ)
    for name in ("COCOTB_TESTCASE", "COCOTB_TEST_FILTER", "COCOTB_TEST_MODULES", "GPI_EXTRA",
                 "COCOTB_RESULTS_FILE", "PYTHONHOME", "MAKEFLAGS", "MFLAGS", "COCOTB_ENABLE_PROFILING",
                 "WAVES", "GUI"):
        child.pop(name, None)
    child.update(PYTHONPATH=os.pathsep.join(str(bundle.root / p) for p in ("support", "python")),
                 PYTHONDONTWRITEBYTECODE="1", TCM_VERILATOR_CHILD="1",
                 # Historical name is required by the unchanged packaged runfiles adapter.
                 TCM_VCS_PACKAGE=str(bundle.root), COCOTB_USE_FRONTDOOR="1", TEST_XLEN="32",
                 CLOCK_NS="1.25", COCOTB_TRUST_INERTIAL_WRITES="0", COCOTB_ANSI_OUTPUT="0",
                 # Runner2.0 treats even WAVES="0" / GUI="0" as True.
                 # Remove both variables and pass waves=False, gui=False.
                 NO_COLOR="1", LIBPYTHON_LOC=env["libpython"],
                 CC=env["tools"]["cc"], CXX=env["tools"]["cxx"])
    directories = [env["libs"], str(Path(env["libpython"]).parent)]
    if os.environ.get("LD_LIBRARY_PATH"):
        directories.append(os.environ["LD_LIBRARY_PATH"])
    child["LD_LIBRARY_PATH"] = os.pathsep.join(directories)
    return child


def build_commands(bundle, env, directory, jobs, *, write_visibility=True):
    root, top, tools = bundle.root, bundle.manifest["hdl_top"], env["tools"]
    # Same top-port-only visibility as the original Bazel model; no all-net access.
    visibility = directory / "visibility.vlt"
    if write_visibility:
        visibility.write_text(VISIBILITY.format(top=top), encoding="utf-8")
    ldflags = f"-Wl,-rpath,{env['libs']} -L{env['libs']} -lcocotbvpi_verilator -rdynamic"
    args = [tools["perl"], tools["verilator"], "-cc", "--exe", "-Mdir", str(directory),
            "--top-module", top, "--vpi", "--prefix", "Vtop", "-o", top,
            "-LDFLAGS", ldflags, "-CFLAGS", "-std=c++17 -I" + str(root / "dpi")]
    args += ["-Wno-" + w for w in WARNINGS]
    args += ['-DUSE_GENERIC=""' if name == "USE_GENERIC" else "-D" + name
             for name in bundle.manifest["defines"]]
    args += ["-I" + str(root / "rtl_dependencies" / p) for p in bundle.manifest["zip_include_dirs"]]
    # The monolithic original SV already contains all modules. Do NOT compile ZIP SV twice.
    args += [env["cpp"], str(visibility), str(root / "dpi/sram_backdoor.cc"),
             str(root / "rtl" / (top + ".sv"))]
    make = [tools["make"], "-j", str(jobs), "-C", str(directory), "-f", "Vtop.mk",
            "OPT_FAST=-O3", "CXX=" + tools["cxx"], "LINK=" + tools["cxx"], "AR=" + tools["ar"]]
    return [args, make]


def model_hashes(bundle, directory):
    names = (bundle.manifest["hdl_top"], "visibility.vlt", "compile-commands.json")
    return {name: sha(directory / name) for name in names}


def checked_build(bundle, state, identity, env=None):
    record = json.loads((state / "current_build.json").read_text())
    directory = Path(record["directory"]).resolve(strict=True)
    if directory.parent != (state / "builds").resolve():
        raise ValueError("model is outside this package's private build directory")
    if record["model_files"] != model_hashes(bundle, directory):
        raise ValueError("compiled Verilator model changed; old evidence preserved")
    if record["identity"] != identity:
        # A runtime-only fix must not silently relabel an old executable as a new
        # build. Accept the known old producer only when its FULL original
        # identity matches this package/environment, and its saved compiler
        # commands, visibility and successful build status still match exactly.
        if env is None or record["identity"] != build_identity(
                bundle, env, adapter_sha256=PREVIOUS_ADAPTER_SHA256):
            raise ValueError("model/environment changed: build a new Verilator model")
        commands = json.loads((directory / "compile-commands.json").read_text())
        try:
            jobs = int(commands[1][commands[1].index("-j") + 1])
        except (IndexError, TypeError, ValueError, AttributeError) as error:
            raise ValueError("invalid previous compile commands; model not reused") from error
        if (jobs not in range(1, 9) or
                commands != build_commands(bundle, env, directory, jobs, write_visibility=False) or
                (directory / "visibility.vlt").read_text() != VISIBILITY.format(top=bundle.manifest["hdl_top"])):
            raise ValueError("previous compile recipe differs; model not reused")
        timing = json.loads((directory / "_build-status.json").read_text())
        if (record != json.loads((directory / "build-record.json").read_text()) or
                timing != record["timing"] or timing["exit_code"] != 0 or timing["timed_out"] is not False):
            raise ValueError("previous build has no matching successful evidence")
    return record, directory


def execute(bundle, env, command, directory, timeout, extra=()):
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--package", str(bundle.root),
            command, "--directory", str(directory)] + list(extra)
    write_json(directory / (command + "-command.json"), argv)
    start = time.monotonic()
    timed_out = False
    logfile = directory / (command + ".log")
    with logfile.open("xb") as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                   env=child_environment(bundle, env), start_new_session=True)
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            status = process.wait()
    timing = dict(argv=argv, log=str(logfile), exit_code=status, timed_out=timed_out,
                  timeout_seconds=timeout, elapsed_seconds=time.monotonic() - start,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(directory / (command + "-status.json"), timing)
    if status or timed_out:
        raise ValueError("phase failed/incomplete; preserved log: " + str(logfile))
    return timing


def check_xml(path):
    root = ET.parse(path).getroot()
    tests = list(root.iter("testcase"))
    if (len(tests) != 1 or tests[0].get("name") != "tcm_workset_test" or
            any(list(root.iter(name)) for name in ("failure", "error", "skipped"))):
        raise ValueError("missing, extra, failed or skipped cocotb XML test")


def checked_results(bundle, env, path, tiles, delay):
    rows, identity = bundle.checked_log(normalize(Path(path).read_text()), bundle.manifest["dtcm_kib"], tiles, delay)
    expected = (bundle.manifest["passed_workset_elf_sha256"], env["elf_entry"],
                env["elf_load_segments"], env["symbols"])
    if identity != expected or any(row["vector_sha256"] != bundle.manifest["vector_sha256"][str(tiles)] for row in rows):
        raise ValueError("logged ELF/layout/vectors do not match this package")
    return rows


def checked_reference(bundle, env, reference, rows, tiles, delay):
    reference = Path(reference).resolve(strict=True)
    before = sha(reference)
    previous = checked_results(bundle, env, reference, tiles, delay)
    if previous != rows or sha(reference) != before:
        raise ValueError("reference differs: require exact cycles, counters, traffic, vectors and firmware")
    return dict(path=str(reference), sha256=before,
                policy="exact_original_strict_summaries_including_halt_cycles")


def check_pilot(bundle, env, state, build):
    for directory in (state / "runs").glob("t12_r0.*"):
        try:
            result = json.loads((directory / "result.json").read_text())
            timing = json.loads((directory / "_test-status.json").read_text())
            if (result["status"] != "PASS" or result["simulator"] != "verilator" or
                    result["build_identity"] != build["identity"] or result["model_files"] != build["model_files"] or
                    result["manifest_sha256"] != sha(bundle.root / "manifest.json") or
                    result["adapter_sha256"] != sha(__file__) or result["tiles"] != 12 or result["delay"] != 0 or
                    not result.get("reference") or result["timing"]["exit_code"] != 0 or
                    result["timing"]["timed_out"] is not False or result["timing"] != timing or
                    result["log_sha256"] != sha(directory / "_test.log") or
                    result["xml_sha256"] != sha(directory / "results.xml")):
                continue
            check_xml(directory / "results.xml")
            rows = checked_results(bundle, env, directory / "_test.log", 12, 0)
            reference = checked_reference(bundle, env, result["reference"]["path"], rows, 12, 0)
            if reference == result["reference"] and rows == result["summaries"]:
                return
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
            continue
    raise ValueError("first pass T12/delay0 with --reference-log on this same Verilator model")


@contextmanager
def state_lock(state):
    import fcntl
    with (state / "launcher.lock").open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another Verilator build/run holds this state lock")
        yield


def phase(args, bundle):
    if os.environ.get("TCM_VERILATOR_CHILD") != "1":
        raise ValueError("internal phase must be launched by this adapter")
    env = environment(bundle)
    if args.command == "_build":
        commands = build_commands(bundle, env, args.directory, args.jobs)
        write_json(args.directory / "compile-commands.json", commands)
        for argv in commands:
            print("[TCM_VERILATOR_COMMAND] " + shlex.join(argv), flush=True)
            subprocess.run(argv, cwd=args.directory, check=True)
        linked = command_output(["ldd", str(args.directory / bundle.manifest["hdl_top"])])
        (args.directory / "model-ldd.txt").write_text(linked, encoding="utf-8")
        if "not found" in linked:
            raise ValueError("compiled model has unresolved shared libraries")
    else:
        from cocotb_tools.runner import get_runner
        # Explicit 0 prevents runner2.0 auto-enabling inertial writes / GPI clock.
        runner = get_runner("verilator")
        runner.test(hdl_toplevel=bundle.manifest["hdl_top"], hdl_toplevel_lang="verilog",
                    test_module="workset_bench", testcase="tcm_workset_test", seed=137,
                    build_dir=args.model_dir, test_dir=args.directory, waves=False, gui=False,
                    results_xml=str(args.directory / "results.xml"),
                    extra_env=dict(TCM_DTCM_KIB=str(bundle.manifest["dtcm_kib"]),
                                   TCM_WS_TILES=str(args.tiles), TCM_WS_READ_DELAY=str(args.delay),
                                   COCOTB_USE_FRONTDOOR="1", COCOTB_TRUST_INERTIAL_WRITES="0"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("command", choices=("verify", "check", "build", "run", "_build", "_test"))
    p.add_argument("--tiles", type=int, choices=TILES, default=12)
    p.add_argument("--delay", type=int, choices=(0, 8), default=0)
    p.add_argument("--jobs", type=int, choices=range(1, 9), default=2)
    p.add_argument("--timeout", type=int, default=21600)
    p.add_argument("--reference-log", type=Path)
    p.add_argument("--directory", type=Path)
    p.add_argument("--model-dir", type=Path)
    a = p.parse_args()
    if not 1 <= a.timeout <= 86400:
        p.error("timeout must be 1..86400 seconds")
    bundle = load_package(a.package)
    if a.command == "verify":
        print("[TCM_VERILATOR_PACKAGE_VERIFIED] original_package_unchanged=true simulation=NOT_RUN")
        return
    if a.command in ("_build", "_test"):
        phase(a, bundle)
        return
    env = environment(bundle)
    if a.command == "check":
        print("[TCM_VERILATOR_ENV_CHECK] " + json.dumps(dict(python=env["python"], versions=env["versions"],
              libc=env["libc"], tools=env["tools"], verilator=env["verilator_version"].strip(),
              vectors_and_elf_checked=True, simulation="NOT_RUN"), sort_keys=True))
        return
    state = state_directory(bundle.root)
    state.mkdir(parents=True, exist_ok=True)
    identity = build_identity(bundle, env)
    with state_lock(state):
        if a.command == "build":
            try:
                _, build = checked_build(bundle, state, identity, env)
                print("[TCM_VERILATOR_BUILD_REUSED] " + str(build))
                return
            except (OSError, ValueError, KeyError):
                pass
            (state / "builds").mkdir(exist_ok=True)
            build = Path(tempfile.mkdtemp(prefix=identity[:12] + ".", dir=state / "builds"))
            write_json(build / "environment.json", env)
            print("[TCM_VERILATOR_BUILD_DIRECTORY] " + str(build), flush=True)
            timing = execute(bundle, env, "_build", build, a.timeout, ("--jobs", str(a.jobs)))
            bundle.library.verify(bundle.root)
            record = dict(identity=identity, directory=str(build), model_files=model_hashes(bundle, build), timing=timing)
            write_json(build / "build-record.json", record)
            # Only this private pointer is replaced; prior model/evidence is retained.
            pointer = state / "current_build.json"
            temporary = state / ("current_build." + str(os.getpid()) + ".json")
            write_json(temporary, record)
            os.replace(temporary, pointer)
            print("[TCM_VERILATOR_BUILD_PASS] compile_seconds=" + str(round(timing["elapsed_seconds"], 3)))
            return
        record, build = checked_build(bundle, state, identity, env)
        if record["identity"] != identity:
            print("[TCM_VERILATOR_BUILD_REUSED] " + str(build), flush=True)
            print("[TCM_VERILATOR_RUNTIME_FIX] waves_gui=unset model_and_build_records_unchanged=true", flush=True)
        if (a.tiles, a.delay) != (12, 0):
            check_pilot(bundle, env, state, record)
        elif a.reference_log is None:
            p.error("T12 baseline requires --reference-log from an existing complete same-capacity passing test")
        if a.reference_log:
            # Validate reference completeness/identity BEFORE spending time on simulation.
            checked_results(bundle, env, a.reference_log, a.tiles, a.delay)
        (state / "runs").mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix=f"t{a.tiles}_r{a.delay}.", dir=state / "runs"))
        write_json(run / "environment.json", env)
        write_json(run / "build-record.json", record)
        shutil.copy2(bundle.root / "manifest.json", run / "package-manifest.json")
        print("[TCM_VERILATOR_RUN_DIRECTORY] " + str(run), flush=True)
        timing = execute(bundle, env, "_test", run, a.timeout,
                         ("--model-dir", str(build), "--tiles", str(a.tiles), "--delay", str(a.delay)))
        check_xml(run / "results.xml")
        rows = checked_results(bundle, env, run / "_test.log", a.tiles, a.delay)
        reference = checked_reference(bundle, env, a.reference_log, rows, a.tiles, a.delay) if a.reference_log else None
        bundle.library.verify(bundle.root)
        if model_hashes(bundle, build) != record["model_files"]:
            raise ValueError("model changed during simulation")
        result = dict(schema=1, status="PASS", simulator="verilator", tiles=a.tiles, delay=a.delay,
                      dtcm_kib=bundle.manifest["dtcm_kib"], build_identity=record["identity"], model_files=record["model_files"],
                      manifest_sha256=sha(bundle.root / "manifest.json"), adapter_sha256=sha(__file__),
                      log_sha256=sha(run / "_test.log"), xml_sha256=sha(run / "results.xml"),
                      summaries=rows, reference=reference, timing=timing)
        write_json(run / "result.json", result)
        for row in rows:
            print("[TCM_WORKSET_SUMMARY] " + json.dumps(row, sort_keys=True))
        if reference:
            print("[TCM_VERILATOR_REFERENCE_MATCH] cycles_counters_axi_elf_vectors=EXACT")
        print("[TCM_VERILATOR_RUN_PASS] simulation_wall_seconds=" + str(round(timing["elapsed_seconds"], 3)) + " results=" + str(run))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[TCM_VERILATOR_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
