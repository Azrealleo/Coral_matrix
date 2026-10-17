#!/usr/bin/env python3
"""External ANSI-safe acceptance/launcher for unchanged, fixed VCS packages."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
LIBRARY_SHA256 = "d5673e81b49c75a7630aa54f365f1dd9d5a606aa771b5b6021daa5e335fa864d"
RUNTIME_SHA256 = "6bbce3bb156405a0ee0720d55a17d1ff03109e43988684ab8905d023862816a1"
MARKER = "[GOOGLE_TCM_WORKSET] "
SGR = re.compile(r"\x1b\[[0-9;]*m")
LEADING = re.compile(r"^(?:[ \t]|\x1b\[[0-9;]*m)*")
TRAILING = re.compile(r"(?:[ \t]|\x1b\[[0-9;]*m)*$")
POLICY = "SGR_at_JSON_boundaries_only_raw_files_unchanged_v1"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def normalized_log(text):
    """Remove presentation colors, never truncate extra data or repair JSON."""
    result = []
    for line in text.splitlines(keepends=True):
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        body = line[:-len(ending)] if ending else line
        if MARKER in body:
            prefix, payload = body.split(MARKER, 1)
            left, right = LEADING.match(payload).end(), TRAILING.search(payload).start()
            if right < left:
                raise ValueError("empty structured JSON record")
            # Only colors outside the JSON object are removable. An escape inside
            # a value, unknown control, arbitrary suffix or second JSON still fails.
            body = (SGR.sub("", prefix) + MARKER + SGR.sub("", payload[:left]) +
                    payload[left:right] + SGR.sub("", payload[right:]))
        else:
            body = SGR.sub("", body)
            if MARKER in body:
                raise ValueError("color embedded in structured marker")
        if "\x1b" in body:
            raise ValueError("unsupported or in-JSON escape; raw log retained")
        result.append(body + ending)
    return "".join(result)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_package(root):
    root = Path(root).resolve(strict=True)
    # Authenticate code before importing from an external immutable package.
    if sha(root / "package_lib.py") != LIBRARY_SHA256 or sha(root / "runtime.py") != RUNTIME_SHA256:
        raise ValueError("unknown verifier/runtime; use a fixed svaext package, never edit hashes")
    library = load_module("package_lib", root / "package_lib.py")
    manifest = library.verify(root)
    for name in ("capacity_spec", "workset_spec", "workset_bench", "workset_axi_probe",
                 "prepare_workset", "prepare_control", "control_spec", "prepare"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(root))
    runtime = load_module("tcm_ansi_verified_runtime", root / "runtime.py")
    runtime.paths(root)
    import prepare_workset
    original_check = prepare_workset.checked_log

    def check_log(text, kib, tiles, delay):
        return original_check(normalized_log(text), kib, tiles, delay)

    prepare_workset.checked_log = check_log
    original_env = runtime.child_env

    def child_env(package):
        env = original_env(package)
        env.update(COCOTB_ANSI_OUTPUT="0", NO_COLOR="1")
        return env

    runtime.child_env = child_env
    original_write = runtime.write_json

    def write_json(path, value):
        if Path(path).name == "result.json":
            value = dict(value, acceptance_adapter_sha256=sha(__file__), log_presentation=POLICY)
        original_write(path, value)

    runtime.write_json = write_json
    return SimpleNamespace(root=root, library=library, manifest=manifest, runtime=runtime, checked_log=check_log)


def accept(bundle, requested_run, requested_state=None):
    """Finalize an existing complete T12 pilot, without simulator execution."""
    root, rt, manifest = bundle.root, bundle.runtime, bundle.manifest
    state = rt.state_directory(root, requested_state)
    run = Path(requested_run).resolve(strict=True)
    if run.parent != (state / "runs").resolve() or not re.fullmatch(r"t12_r0\.[A-Za-z0-9_]+", run.name):
        raise ValueError("accept requires an existing T12/0 run in this package's runtime/runs directory")
    if (run / "result.json").exists():
        raise ValueError("result.json exists; refusing overwrite")
    names = ("environment.json", "package-manifest.json", "_test.log", "results.xml",
             "_test-status.json", "_test-command.json")
    before = {name: sha(run / name) for name in names}
    package_sha = sha(root / "manifest.json")
    if (run / "package-manifest.json").read_bytes() != (root / "manifest.json").read_bytes():
        raise ValueError("run belongs to a different package manifest")
    env = rt.environment(root, manifest)
    identity = rt.build_identity(root, manifest, env)
    saved_env = json.loads((run / "environment.json").read_text())
    if rt.build_identity(root, manifest, saved_env) != identity:
        raise ValueError("run environment differs; retain the same compiler/Python isolation")
    record, build = rt.checked_build(state, identity)
    build_record = json.loads((build / "build-record.json").read_text())
    if build_record != record:
        raise ValueError("build record differs from current compiled model")
    command = [saved_env["python"], "-B", str(root / "runtime.py"), "_test", "--build-dir", str(run),
               "--model-dir", str(build), "--tiles", "12", "--delay", "0"]
    timing = json.loads((run / "_test-status.json").read_text())
    elapsed, timeout = timing.get("elapsed_seconds"), timing.get("timeout_seconds")
    if (type(timing.get("exit_code")) is not int or timing["exit_code"] != 0 or
            timing.get("timed_out") is not False or type(elapsed) not in (int, float) or
            not math.isfinite(elapsed) or elapsed <= 0 or type(timeout) is not int or not 1 <= timeout <= 86400 or
            timing.get("argv") != command or timing.get("log") != str(run / "_test.log") or
            json.loads((run / "_test-command.json").read_text()) != command):
        raise ValueError("nonzero/timed-out/incomplete phase or wrong simulation command")
    rt.check_xml(run / "results.xml")
    rows, log_identity = bundle.checked_log((run / "_test.log").read_text(), manifest["dtcm_kib"], 12, 0)
    expected_identity = (manifest["passed_workset_elf_sha256"], env["elf_entry"], env["elf_load_segments"], env["symbols"])
    if log_identity != expected_identity or any(row["vector_sha256"] != manifest["vector_sha256"]["12"] for row in rows):
        raise ValueError("logged ELF/layout/vectors do not match this package")
    bundle.library.verify(root)
    if (sha(root / "manifest.json") != package_sha or
            before != {name: sha(run / name) for name in names} or record["model_files"] != rt.model_hashes(build)):
        raise ValueError("run inputs or compiled model changed during acceptance")
    result = dict(schema=1, status="PASS", simulator="vcs", tiles=12, delay=0,
                  dtcm_kib=manifest["dtcm_kib"], package_manifest_sha256=package_sha,
                  build_identity=identity, model_files=record["model_files"], timing=timing, summaries=rows,
                  log_sha256=before["_test.log"], xml_sha256=before["results.xml"],
                  acceptance_adapter_sha256=sha(__file__), log_presentation=POLICY,
                  recovered_existing_run=True, simulation_rerun=False,
                  acceptance_input_sha256=before)
    # Exclusive create: never overwrite an earlier result or any original evidence.
    with (run / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    rt.checked_run(run, manifest, identity, record["model_files"])
    for row in rows:
        print("[TCM_WORKSET_SUMMARY] " + json.dumps(row, sort_keys=True))
    print("[TCM_VCS_ACCEPT_PASS] simulation_rerun=false raw_files_unchanged=true simulation_wall_seconds=" +
          str(round(elapsed, 3)) + " results=" + str(run))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("command", choices=("accept", "verify", "check", "build", "run"))
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--tiles", type=int, choices=(2, 12, 120, 192, 384, 768), default=12)
    parser.add_argument("--delay", type=int, choices=(0, 8), default=0)
    parser.add_argument("--timeout", type=int, default=21600)
    args = parser.parse_args()
    bundle = load_package(args.package)
    if args.command == "accept":
        if args.run_dir is None or args.tiles != 12 or args.delay != 0:
            parser.error("accept requires --run-dir and only accepts T12/delay0 pilots")
        accept(bundle, args.run_dir, args.state_dir)
    else:
        if args.run_dir is not None:
            parser.error("--run-dir is only for acceptance of an existing run")
        sys.argv = ["runtime.py", args.command, "--tiles", str(args.tiles), "--delay", str(args.delay),
                    "--timeout", str(args.timeout)]
        if args.state_dir is not None:
            sys.argv += ["--state-dir", str(args.state_dir)]
        bundle.runtime.main()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[TCM_VCS_ADAPTER_STOP] " + str(error), file=sys.stderr)
        sys.exit(1)
