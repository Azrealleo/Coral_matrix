#!/usr/bin/env python3
"""Standalone VCS/cocotb entry point. No Bazel, Java, RISC-V compiler or Git."""
import argparse
import ctypes
from datetime import datetime, timezone
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
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
from package_lib import DEFINES, digest, sha, verify, write_json

ROOT = Path(__file__).resolve().parent
TILES = (2, 12, 120, 192, 384, 768)
BUILD_ARGS = ["-timescale=1ns/1ps", "-O3", "-assert", "svaext", "+define+VCS"] + ["+define+" + n for n in DEFINES]


def compiler_configuration():
    # Keep VCS2020's generated C/C++ on its original host compiler. The original
    # SRAM source needs C++17, so compile its C-ABI DPI SO separately.
    dpi_cxx = os.environ.get("TCM_DPI_CXX") or os.environ.get("CXX") or shutil.which("g++")
    if dpi_cxx:
        dpi_cxx = shutil.which(dpi_cxx) or dpi_cxx
    if not dpi_cxx or not Path(dpi_cxx).is_file():
        raise ValueError("set TCM_DPI_CXX to a C++17 compiler (Conda cxx-compiler); system GCC4.8 is insufficient")
    result = subprocess.run([dpi_cxx, "-std=c++17", "-dM", "-E", "-x", "c++", "-"],
                            input="", capture_output=True, text=True, timeout=30)
    if result.returncode or "#define __cplusplus 201703L" not in result.stdout:
        raise ValueError("SRAM DPI needs a working C++17 compiler; source was not rewritten")
    vcs = Path(shutil.which("vcs")).resolve()
    include = Path(os.environ.get("TCM_VCS_DPI_INCLUDE") or
                   str(Path(os.environ.get("VCS_HOME", str(vcs.parent.parent))) / "include")).resolve()
    if not (include / "svdpi.h").is_file():
        raise ValueError("VCS svdpi.h missing; set VCS_HOME or TCM_VCS_DPI_INCLUDE (not a Verilator header)")
    cc, cpp = (os.environ.get("TCM_VCS_CC", "/bin/gcc"), os.environ.get("TCM_VCS_CXX", "/bin/g++"))
    if not Path(cc).is_file() or not Path(cpp).is_file():
        raise ValueError("VCS host compiler missing; set TCM_VCS_CC/TCM_VCS_CXX to laboratory-supported compilers")
    version = subprocess.run([dpi_cxx, "--version"], capture_output=True, text=True, timeout=30)
    return dict(dpi_cxx=str(Path(dpi_cxx).resolve()), dpi_cxx_version=version.stdout,
                vcs_include=str(include), svdpi_sha256=sha(include / "svdpi.h"), vcs_cc=cc, vcs_cpp=cpp)


def dpi_selftest(path):
    # Original implementation, C ABI, no RTL simulator or Python backdoor loader.
    library = ctypes.CDLL(str(path))
    library.sram_init.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32]
    library.sram_init.restype = ctypes.c_void_p
    vector = ctypes.c_uint32 * 4
    library.sram_write.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
    library.sram_read.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    library.sram_cleanup.argtypes = [ctypes.c_void_p]
    handle = library.sram_init(0x01000000, 8192, 16)
    if not handle:
        raise ValueError("original SRAM DPI initialization failed")
    try:
        original = vector(0x03020100, 0x07060504, 0x0B0A0908, 0x0F0E0D0C)
        update = vector(0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        actual = vector()
        library.sram_write(handle, 511, original, 0xFFFF)
        library.sram_write(handle, 511, update, 0x0005)
        library.sram_read(handle, 511, actual)
        if list(actual) != [0x03FF01FF, 0x07060504, 0x0B0A0908, 0x0F0E0D0C]:
            raise ValueError("original SRAM DPI byte-mask selftest failed")
    finally:
        library.sram_cleanup(handle)


def build_dpi(root, build):
    config = compiler_configuration()
    library = build / "libsram_backdoor.so"
    argv = [config["dpi_cxx"], "-std=c++17", "-shared", "-fPIC", "-O2", "-fno-gnu-unique",
            "-Wl,-Bsymbolic", "-static-libstdc++", "-static-libgcc",
            "-I" + config["vcs_include"], "-I" + str(root / "dpi"),
            str(root / "dpi/sram_backdoor.cc"), "-o", str(library)]
    write_json(build / "dpi-compile-command.json", argv)
    subprocess.run(argv, check=True)
    result = subprocess.run(["ldd", str(library)], capture_output=True, text=True, timeout=30)
    (build / "dpi-ldd.txt").write_text(result.stdout + result.stderr)
    if result.returncode or any(s in result.stdout + result.stderr for s in ("not found", "libstdc++.so", "libgcc_s.so")):
        raise ValueError("DPI must be host-compatible and statically link its C++/GCC runtimes")
    dpi_selftest(library)
    print("[TCM_VCS_DPI_SELFTEST_PASS] original_C_ABI_byte_mask_checked_not_RTL_simulation", flush=True)
    return config


def paths(root):
    for name in ("support", "python"):
        sys.path.insert(0, str(root / name))
    os.environ["TCM_VCS_PACKAGE"] = str(root)


def state_directory(root, requested):
    state = (Path(requested) if requested else root.with_name(root.name + "_runtime")).resolve()
    try:
        state.relative_to(root)
    except ValueError:
        return state
    raise ValueError("runtime outputs must be outside the immutable package")


def environment(root, manifest):
    if sys.version_info[:2] != (3, 11) or platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("use CPython3.11 on Linux x86_64; do not use CentOS7 system Python3.6")
    import importlib.metadata
    versions = {n: importlib.metadata.version(n) for n in ("cocotb", "numpy", "pyelftools", "find-libpython")}
    if versions != {"cocotb": "2.0.0", "numpy": "1.26.4", "pyelftools": "0.32", "find-libpython": "0.5.1"}:
        raise ValueError("install the exact packaged requirements in a separate environment: " + repr(versions))
    vcs = shutil.which("vcs")
    if not vcs:
        raise ValueError("vcs is not in PATH; load the laboratory VCS environment first")
    version = subprocess.run([vcs, "-ID"], capture_output=True, text=True, timeout=30)
    if version.returncode:
        raise ValueError("vcs -ID failed: " + version.stdout + version.stderr)
    version_token = re.search(r"\b[A-Z]-\d{4}\.\d{2}[-_.A-Za-z0-9]*", version.stdout + version.stderr)
    if version_token is None:
        raise ValueError("cannot identify VCS release from vcs -ID; preserve output for inspection")
    from cocotb_tools.config import lib_name_path
    import find_libpython
    library = Path(lib_name_path("vpi", "vcs")).resolve(strict=True)
    python_library = find_libpython.find_libpython()
    if not python_library:
        raise ValueError("matching shared libpython3.11 not found")
    linked = {}
    for p in (library, Path(python_library)):
        result = subprocess.run(["ldd", str(p)], capture_output=True, text=True, timeout=30)
        linked[p.name] = result.stdout + result.stderr
        if result.returncode or "not found" in linked[p.name]:
            raise ValueError("incompatible/missing shared-library dependencies: " + str(p) + "\n" + linked[p.name])
    paths(root)
    from workset_spec import vectors
    for t in TILES:
        if vectors(t)[3] != manifest["vector_sha256"][str(t)]:
            raise ValueError("server NumPy generated different vectors/golden")
    from workset_bench import inspect_elf
    entry, segments, symbols, sizes = inspect_elf(root / "firmware/workset_program.elf")
    compiler = shutil.which("gcc")
    gcc_version = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=30).stdout if compiler else "not in PATH"
    return dict(python=sys.executable, python_version=sys.version, versions=versions,
                platform=platform.platform(), libc=platform.libc_ver(), vcs=str(Path(vcs).resolve()),
                vcs_version=version.stdout + version.stderr, vcs_release=version_token[0], gcc=gcc_version,
                vpi_library=str(library), libpython=str(python_library),
                vpi_sha256=sha(library), libpython_sha256=sha(python_library), ldd=linked,
                elf_entry=entry, elf_load_segments=segments, symbols=symbols, symbol_sizes=sizes,
                dpi_compiler=compiler_configuration(),
                license_environment_present=any(os.environ.get(n) for n in
                    ("LM_LICENSE_FILE", "SNPSLMD_LICENSE_FILE", "LICENSE_SERVER_VCSSIM")))


def build_identity(root, manifest, env):
    # Raw banners may contain today's time; ldd contains ASLR addresses. Keep
    # those diagnostics in environment.json, not in the reusable build key.
    stable = {k: env.get(k) for k in ("python", "python_version", "versions", "vcs", "vcs_release", "gcc",
                                    "libc", "vpi_library", "libpython", "vpi_sha256", "libpython_sha256", "dpi_compiler")}
    return digest(json.dumps(dict(package_path=str(root), top=manifest["hdl_top"],
        rtl_files={n: h for n, h in manifest["files"].items() if n.startswith(("rtl/", "rtl_dependencies/", "dpi/"))},
        arguments=BUILD_ARGS, environment=stable), sort_keys=True).encode())


def model_hashes(build):
    if (not (build / "simv").is_file() or not (build / "simv.daidir").is_dir() or
            not (build / "libsram_backdoor.so").is_file()):
        raise ValueError("VCS model missing simv, simv.daidir or the original SRAM DPI library")
    files = [build / "simv", build / "libsram_backdoor.so"] + [p for p in sorted((build / "simv.daidir").rglob("*")) if p.is_file()]
    return {p.relative_to(build).as_posix(): sha(p) for p in files}


def checked_build(state, identity):
    record = json.loads((state / "current_build.json").read_text())
    build = Path(record["directory"]).resolve(strict=True)
    build.relative_to((state / "builds").resolve(strict=True))
    if record["identity"] != identity or record["model_files"] != model_hashes(build):
        raise ValueError("compiled model/environment changed; run build again, never reuse stale simv")
    return record, build


def child_env(root):
    env = dict(os.environ)
    for name in ("COCOTB_TESTCASE", "COCOTB_TEST_FILTER", "COCOTB_TEST_MODULES", "GPI_EXTRA",
                 "COCOTB_RESULTS_FILE", "PYTHONHOME", "CLOCK_NS"):
        env.pop(name, None)
    env.update(PYTHONPATH=os.pathsep.join(str(root / n) for n in ("support", "python")),
               PYTHONDONTWRITEBYTECODE="1", TCM_VCS_PACKAGE=str(root), TCM_VCS_CHILD="1",
               COCOTB_USE_FRONTDOOR="1", TEST_XLEN="32", CLOCK_NS="1.25", WAVES="0", GUI="0")
    return env


def execute_phase(root, command, directory, timeout, extra=()):
    logfile = directory / (command + ".log")
    argv = [sys.executable, "-B", str(root / "runtime.py"), command,
            "--build-dir", str(directory)] + list(extra)
    write_json(directory / (command + "-command.json"), argv)
    started = time.monotonic()
    timed_out = False
    with logfile.open("wb") as stream:
        process = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                   env=child_env(root), start_new_session=True)
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
    result = dict(argv=argv, timeout_seconds=timeout, elapsed_seconds=time.monotonic() - started,
                  exit_code=status, timed_out=timed_out,
                  finished_utc=datetime.now(timezone.utc).isoformat(), log=str(logfile))
    write_json(directory / (command + "-status.json"), result)
    if status or timed_out:
        raise RuntimeError("phase failed/incomplete; preserved log: " + str(logfile))
    return result


def check_xml(path):
    root = ET.parse(path).getroot()
    tests = list(root.iter("testcase"))
    if (len(tests) != 1 or tests[0].get("name") != "tcm_workset_test" or
            any(list(root.iter(n)) for n in ("failure", "error", "skipped"))):
        raise ValueError("missing/failed/skipped/extra cocotb XML test")


def checked_run(directory, manifest, identity, model_files):
    from prepare_workset import checked_log
    record = json.loads((directory / "result.json").read_text())
    if (record["status"] != "PASS" or record["package_manifest_sha256"] != sha(ROOT / "manifest.json") or
            record["build_identity"] != identity or record["tiles"] != 12 or record["delay"] != 0 or
            record["model_files"] != model_files or
            record["log_sha256"] != sha(directory / "_test.log") or
            record["xml_sha256"] != sha(directory / "results.xml")):
        raise ValueError("not a matching complete small-workset pilot")
    check_xml(directory / "results.xml")
    checked_log((directory / "_test.log").read_text(), manifest["dtcm_kib"], 12, 0)


def phase(args, root, manifest):
    if os.environ.get("TCM_VCS_CHILD") != "1":
        raise ValueError("internal phase must be launched by runtime.py build/run")
    paths(root)
    from cocotb_tools.runner import get_runner
    runner = get_runner("vcs")
    if args.command == "_build":
        config = build_dpi(root, args.build_dir)
        runner.build(sources=[root / "rtl" / (manifest["hdl_top"] + ".sv")],
                     includes=[root / "rtl_dependencies" / n for n in manifest["zip_include_dirs"]],
                     hdl_toplevel=manifest["hdl_top"], build_args=BUILD_ARGS + ["-cc", config["vcs_cc"], "-cpp", config["vcs_cpp"]],
                     build_dir=args.build_dir, always=True, clean=False, waves=False)
    else:
        runner.test(hdl_toplevel=manifest["hdl_top"], hdl_toplevel_lang="verilog",
                    test_module="workset_bench", testcase="tcm_workset_test", seed=137,
                    build_dir=args.model_dir, test_dir=args.build_dir,
                    test_args=["-sv_lib", str(args.model_dir / "libsram_backdoor")],
                    results_xml=str(args.build_dir / "results.xml"), waves=False, gui=False,
                    extra_env=dict(TCM_DTCM_KIB=str(manifest["dtcm_kib"]), TCM_WS_TILES=str(args.tiles),
                                   TCM_WS_READ_DELAY=str(args.delay), COCOTB_USE_FRONTDOOR="1"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("verify", "check", "build", "run", "compare", "_build", "_test"))
    p.add_argument("--state-dir", type=Path)
    p.add_argument("--tiles", type=int, choices=TILES, default=12)
    p.add_argument("--delay", type=int, choices=(0, 8), default=0)
    p.add_argument("--timeout", type=int, default=21600)
    p.add_argument("--logs", type=Path, nargs="+")
    p.add_argument("--build-dir", type=Path)
    p.add_argument("--model-dir", type=Path)
    a = p.parse_args()
    manifest = verify(ROOT)
    if a.command == "verify":
        print("[TCM_VCS_PACKAGE_VERIFIED] top=" + manifest["hdl_top"] + " vcs_simulation=NOT_ASSERTED")
        return
    if a.command in ("_build", "_test"):
        phase(a, ROOT, manifest)
        return
    paths(ROOT)
    if a.command == "compare":
        if not a.logs:
            p.error("compare requires --logs")
        # Existing strict comparison, with no changes to measurements or acceptance.
        from prepare_workset import main as compare_main
        sys.argv = ["prepare_workset.py", "compare", "--logs"] + list(map(str, a.logs))
        compare_main()
        return
    if not 1 <= a.timeout <= 86400:
        p.error("--timeout must be 1..86400 seconds")
    env = environment(ROOT, manifest)
    if a.command == "check":
        print("[TCM_VCS_ENV_CHECK] " + json.dumps(dict(python=env["python"], versions=env["versions"],
              libc=env["libc"], vcs=env["vcs"], vectors_and_elf_checked=True, vcs_simulation="NOT_RUN")))
        return
    state = state_directory(ROOT, a.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    identity = build_identity(ROOT, manifest, env)
    if a.command == "build":
        if (state / "current_build.json").exists():
            try:
                _, build = checked_build(state, identity)
                print("[TCM_VCS_BUILD_REUSED] " + str(build))
                return
            except (OSError, ValueError, KeyError):
                pass  # Preserve old model; build a new unique attempt, never clean it.
        (state / "builds").mkdir(exist_ok=True)
        build = Path(tempfile.mkdtemp(prefix=identity[:12] + ".", dir=state / "builds"))
        write_json(build / "environment.json", env)
        print("[TCM_VCS_BUILD_DIRECTORY] " + str(build), flush=True)
        timing = execute_phase(ROOT, "_build", build, a.timeout)
        record = dict(identity=identity, directory=str(build), model_files=model_hashes(build), timing=timing)
        write_json(build / "build-record.json", record)
        write_json(state / "current_build.json", record)
        print("[TCM_VCS_BUILD_PASS] compile_seconds=" + str(round(timing["elapsed_seconds"], 3)))
        return
    build_record, build = checked_build(state, identity)
    if a.tiles > 12:
        qualified = False
        for previous in (state / "runs").glob("t12_r0.*"):
            try:
                checked_run(previous, manifest, identity, build_record["model_files"])
                qualified = True
                break
            except (OSError, ValueError, KeyError, ET.ParseError):
                continue
        if not qualified:
            raise ValueError("large run blocked: first complete run --tiles 12 --delay 0 on this same VCS model")
    (state / "runs").mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=f"t{a.tiles}_r{a.delay}.", dir=state / "runs"))
    write_json(run / "environment.json", env)
    shutil.copy2(ROOT / "manifest.json", run / "package-manifest.json")
    print("[TCM_VCS_RUN_DIRECTORY] " + str(run), flush=True)
    timing = execute_phase(ROOT, "_test", run, a.timeout,
                           ("--model-dir", str(build), "--tiles", str(a.tiles), "--delay", str(a.delay)))
    check_xml(run / "results.xml")
    from prepare_workset import checked_log
    rows, _ = checked_log((run / "_test.log").read_text(), manifest["dtcm_kib"], a.tiles, a.delay)
    record = dict(schema=1, status="PASS", simulator="vcs", tiles=a.tiles, delay=a.delay,
                  dtcm_kib=manifest["dtcm_kib"], package_manifest_sha256=sha(ROOT / "manifest.json"),
                  build_identity=identity, log_sha256=sha(run / "_test.log"),
                  model_files=build_record["model_files"],
                  xml_sha256=sha(run / "results.xml"), timing=timing, summaries=rows)
    write_json(run / "result.json", record)
    for row in rows:
        print("[TCM_WORKSET_SUMMARY] " + json.dumps(row, sort_keys=True))
    print("[TCM_VCS_RUN_PASS] simulation_wall_seconds=" + str(round(timing["elapsed_seconds"], 3)) + " results=" + str(run))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[TCM_VCS_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
